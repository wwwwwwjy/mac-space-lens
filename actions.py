"""Explicit selection -> action-bound confirmation -> Trash or permanent deletion."""
from __future__ import annotations

import contextlib
import ctypes
import errno
import json
import os
import secrets
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

from storage import APP_DIR, HOME, STATE, describe, within

NATIVE_HELPER = APP_DIR / 'bin' / 'space-lens-trash'


def fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)


@contextlib.contextmanager
def directory_fd(path):
    """Open each component without following symlinks, so a parent swap cannot escape."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


def move_exclusive(src_fd, src, dst_fd, dst):
    # macOS atomic no-overwrite rename. Same-volume moves preserve resource forks/xattrs.
    if sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameatx_np
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(src_fd, os.fsencode(src), dst_fd, os.fsencode(dst), 4) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    else:
        raise OSError('清理功能仅支持 macOS；其他平台只读。')


def erase_entry(parent_fd, name, expected, device):
    """Delete through directory descriptors; never follow links or cross a mount."""
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if fingerprint(current) != fingerprint(expected):
        raise ValueError('文件正在变化，已停止；请退出相关应用后重新扫描。')
    if current.st_dev != device:
        raise ValueError('遇到其他磁盘挂载，已停止；不会清理挂载的磁盘。')
    if stat.S_ISDIR(current.st_mode):
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError('目录已经改变，停止删除。')
            with os.scandir(fd) as entries:
                for entry in entries:
                    child = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                    erase_entry(fd, entry.name, child, device)
            present = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (present.st_dev, present.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError('目录已经改变，停止删除。')
            os.rmdir(name, dir_fd=parent_fd)
        finally:
            os.close(fd)
    elif stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode):
        # unlink removes the link itself, not its target.
        os.unlink(name, dir_fd=parent_fd)
    else:
        raise ValueError('遇到正在使用的特殊文件，停止删除。请先退出相关应用。')


class TrashManager:
    def __init__(self, home=HOME, state=STATE):
        self.home, self.state = Path(home), Path(state)
        self.trash = self.home / '.Trash'
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.journal_path = state / 'trash-history.json'
        self.lock = threading.RLock()
        self.items, self.tickets, self.explanations = {}, {}, {}
        self.scope_validator = None
        self.restore_validator = None
        self.use_native = self.home == HOME
        try:
            self.journal = json.loads(self.journal_path.read_text())
        except FileNotFoundError:
            self.journal = []

    def save(self):
        tmp = self.journal_path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            os.chmod(tmp, 0o600)
            json.dump(self.journal, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.journal_path)

    def expose(self, row):
        row = dict(row)
        p = Path(row['path'])
        row['id'] = None
        try:
            s = p.lstat()
            details = describe(p, stat.S_ISDIR(s.st_mode), s.st_mtime, self.home)
            row.update(details)
            explain_id = secrets.token_urlsafe(18)
            with self.lock:
                self.explanations[explain_id] = {k: row.get(k) for k in
                    ('path', 'dir', 'bytes', 'kind', 'risk', 'content', 'advice', 'impact', 'owner')}
                if len(self.explanations) > 5000:
                    self.explanations = dict(list(self.explanations.items())[-2500:])
            row['explain_id'] = explain_id
            # Only regular files/directories, complete inventories and unchanged parent paths.
            if (not details['deletable'] or row.get('incomplete') or
                    not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)) or p.resolve() != p):
                row['deletable'] = False
                return row
            item_id = secrets.token_urlsafe(18)
            with self.lock:
                self.items[item_id] = {'path': str(p), 'stat': fingerprint(s), 'bytes': row['bytes'],
                                       'risk': details['risk'], 'issued': time.time()}
                if len(self.items) > 15000:
                    cutoff = time.time() - 1800
                    self.items = {k: v for k, v in self.items.items() if v['issued'] > cutoff}
                    if len(self.items) > 15000:
                        self.items = dict(list(self.items.items())[-10000:])
            row['id'] = item_id
        except FileNotFoundError:
            return None
        except OSError:
            row['deletable'] = False
        return row

    def validate(self, item):
        if item.get('scope'):
            if not self.scope_validator:
                raise ValueError('专用操作未初始化，请重新打开应用。')
            return self.scope_validator(item)
        path = Path(item['path'])
        if not within(path, self.home) or path == self.home or path.resolve() != path:
            raise ValueError('文件路径已改变或不允许清理。请重新扫描。')
        s = path.lstat()
        if fingerprint(s) != tuple(item['stat']):
            raise ValueError('文件在扫描后发生变化，请刷新列表再选择：'+path.name)
        if not describe(path, stat.S_ISDIR(s.st_mode), s.st_mtime, self.home)['deletable']:
            raise ValueError('此文件受保护，不能清理。')
        return path

    def preview(self, ids, operation='trash'):
        if operation not in {'trash', 'delete'}:
            raise ValueError('不支持的清理方式。')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 200 or not all(isinstance(x, str) for x in ids):
            raise ValueError('请勾选 1–200 项。')
        with self.lock:
            chosen = []
            for item_id in set(ids):
                item = self.items.get(item_id)
                if not item or time.time() - item['issued'] > 1800:
                    raise ValueError('列表已过期，请刷新后重新选择。')
                if item.get('scope') and operation != 'trash':
                    raise ValueError('应用卸载与残留清理只允许移入废纸篓，保留撤回机会。')
                self.validate(item)
                chosen.append(item.copy())
            chosen.sort(key=lambda x: len(Path(x['path']).parts))
            unique = []
            for item in chosen:
                if not any(within(Path(item['path']), Path(p['path'])) for p in unique):
                    unique.append(item)
            ticket = secrets.token_urlsafe(24)
            self.tickets = {k: v for k, v in self.tickets.items() if time.time() - v['time'] < 600}
            self.tickets[ticket] = {'items': unique, 'time': time.time(), 'operation': operation}
            return {'ticket': ticket, 'items': unique, 'bytes': sum(i['bytes'] for i in unique),
                    'caution': any(i['risk'] == 'caution' for i in unique), 'operation': operation}

    def commit(self, ticket, caution_ack=False, workflow=None):
        with self.lock:
            plan = self.tickets.get(ticket)
            if not plan or time.time() - plan['time'] > 600:
                raise ValueError('确认已过期，请重新选择。')
            if plan['operation'] != 'trash':
                raise ValueError('清理方式不匹配，请重新预览。')
            if plan.get('workflow') and workflow != plan['workflow']:
                raise ValueError('请通过应用卸载确认窗口操作。')
            if any(i['risk'] == 'caution' for i in plan['items']) and caution_ack is not True:
                raise ValueError('请确认已备份慎重清理的文件。')
            for item in plan['items']:
                self.validate(item)
            self.tickets.pop(ticket)
            if self.use_native:
                return self.native_commit(plan['items'])
            if not self.trash.exists():
                self.trash.mkdir(mode=0o700)
            successes, failures = [], []
            with directory_fd(self.trash) as dest_fd:
                trash_stat = os.fstat(dest_fd)
                if trash_stat.st_uid != os.getuid():
                    raise ValueError('废纸篓不属于当前用户，停止操作。')
                for item in plan['items']:
                    entry = None
                    try:
                        path = self.validate(item)
                        with directory_fd(path.parent) as src_fd:
                            s = os.stat(path.name, dir_fd=src_fd, follow_symlinks=False)
                            if fingerprint(s) != tuple(item['stat']):
                                raise ValueError('文件已经变化，请重新扫描。')
                            if s.st_dev != trash_stat.st_dev:
                                raise ValueError('不移动跨磁盘文件。')
                            ident = secrets.token_hex(8)
                            # Leave room for NAME_MAX even with long Chinese filenames.
                            short = path.name.encode('utf-8')[:150].decode('utf-8', errors='ignore')
                            name = short+'.space-lens-'+ident
                            entry = {'id': ident, 'source': str(path), 'destination': str(self.trash / name),
                                     'time': time.time(), 'bytes': item['bytes'], 'status': 'pending',
                                     'inode': s.st_ino, 'device': s.st_dev, 'scope': item.get('scope'),
                                     'app_identity': item.get('app_identity')}
                            self.journal.append(entry)
                            self.save()  # durable recovery record BEFORE changing any user file
                            move_exclusive(src_fd, path.name, dest_fd, name)
                            entry['status'] = 'trashed'
                            self.save()
                            successes.append({'path': str(path), 'id': ident})
                    except (OSError, ValueError) as exc:
                        if entry:
                            # A completed move is recoverable even if the final journal write failed.
                            if not Path(entry['source']).exists() and Path(entry['destination']).exists():
                                entry['status'] = 'trashed'
                            else:
                                entry['status'] = 'failed'
                            try:
                                self.save()
                            except OSError:
                                pass
                        failures.append({'path': item['path'], 'error': str(exc)})
            return {'moved': successes, 'failed': failures}

    def delete(self, ticket, confirm_text, caution_ack=False):
        with self.lock:
            plan = self.tickets.get(ticket)
            if not plan or time.time() - plan['time'] > 600:
                raise ValueError('确认已过期，请重新选择。')
            if plan['operation'] != 'delete':
                raise ValueError('必须单独预览“直接删除”，不能使用移入废纸篓的确认。')
            if confirm_text != '永久删除':
                raise ValueError('请输入“永久删除”确认。这项操作不经过废纸篓，不能撤回。')
            if any(i['risk'] == 'caution' for i in plan['items']) and caution_ack is not True:
                raise ValueError('请确认已核对慎重清理项。')
            for item in plan['items']:
                self.validate(item)
            self.tickets.pop(ticket)
            successes, failures = [], []
            for item in plan['items']:
                entry = None
                try:
                    path = self.validate(item)
                    with directory_fd(path.parent) as fd:
                        s = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
                        if fingerprint(s) != tuple(item['stat']):
                            raise ValueError('文件已经变化，请重新扫描。')
                        if s.st_dev != self.home.stat().st_dev:
                            raise ValueError('不删除跨磁盘文件。')
                        entry = {'id': secrets.token_hex(8), 'source': str(path),
                                 'time': time.time(), 'bytes': item['bytes'],
                                 'operation': 'delete', 'status': 'deleting'}
                        self.journal.append(entry)
                        self.save()  # If interrupted, the record explicitly shows an uncertain partial delete.
                        erase_entry(fd, path.name, s, s.st_dev)
                        entry['status'] = 'deleted'
                        self.save()
                        successes.append({'path': str(path), 'id': entry['id']})
                except (OSError, ValueError) as exc:
                    if entry and entry['status'] == 'deleted':
                        # Data deletion succeeded even if recording the result failed.
                        successes.append({'path': item['path'], 'id': entry['id']})
                        failures.append({'path': item['path'], 'error': '文件已永久删除，但记录写入失败：'+str(exc)})
                        continue
                    if entry:
                        entry['status'] = 'delete_failed'
                        try:
                            self.save()
                        except OSError:
                            pass
                    failures.append({'path': item['path'], 'error': str(exc)+('；可能已删除部分子项，不能撤回。' if entry else '')})
            return {'deleted': successes, 'failed': failures}

    def native(self, operation, source, inode, device, destination=None):
        if not NATIVE_HELPER.exists():
            raise ValueError('缺少 macOS 废纸篓接口，请保留完整工具文件夹。')
        args = [str(NATIVE_HELPER), operation, str(source), str(inode), str(device)]
        if destination is not None:
            args.append(str(destination))
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            raise ValueError('系统接口未完成操作，请在 Finder 中核对。')
        if result.returncode:
            raise ValueError(data.get('error', '系统拒绝操作。'))
        return data

    def native_commit(self, items):
        successes, failures = [], []
        for item in items:
            entry = None
            try:
                path = self.validate(item)
                with directory_fd(path.parent) as source_fd:
                    s = os.stat(path.name, dir_fd=source_fd, follow_symlinks=False)
                    if fingerprint(s) != tuple(item['stat']):
                        raise ValueError('文件在确认后发生变化。')
                    if s.st_dev != self.home.stat().st_dev:
                        raise ValueError('不移动跨磁盘文件。')
                    ident = secrets.token_hex(8)
                    short = path.name.encode('utf-8')[:150].decode('utf-8', errors='ignore')
                    name = short+'.space-lens-'+ident
                    staged = path.parent / name
                    entry = {'id': ident, 'source': str(path), 'staging': str(staged),
                             'destination': str(self.trash / name), 'time': time.time(),
                             'bytes': item['bytes'], 'status': 'pending', 'native': True,
                             'inode': s.st_ino, 'device': s.st_dev, 'scope': item.get('scope'),
                             'app_identity': item.get('app_identity')}
                    self.journal.append(entry)
                    self.save()
                    # Unique name makes the durable recovery path deterministic.
                    move_exclusive(source_fd, path.name, source_fd, name)
                    try:
                        data = self.native('trash', staged, s.st_ino, s.st_dev)
                    except Exception:
                        # Never leave a merely-renamed source behind on a normal failure.
                        if staged.exists():
                            move_exclusive(source_fd, name, source_fd, path.name)
                        raise
                    entry['destination'] = data['destination']
                    entry['status'] = 'trashed'
                    self.save()
                    successes.append({'path': str(path), 'id': ident})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                if entry:
                    if Path(entry['source']).exists():
                        entry['status'] = 'failed'
                    try:
                        self.save()
                    except OSError:
                        pass
                failures.append({'path': item['path'], 'error': str(exc)})
        return {'moved': successes, 'failed': failures}

    def undo(self, ident):
        with self.lock:
            entry = next((e for e in self.journal if e['id'] == ident), None)
            if not entry or entry['status'] not in {'trashed', 'pending'}:
                raise ValueError('此记录不可撤回。')
            src, dst = Path(entry['source']), Path(entry['destination'])
            app_restore = bool(entry.get('scope') == 'app_bundle' and self.restore_validator
                               and self.restore_validator(entry))
            if (not within(src, self.home) and not app_restore) or within(src, self.trash) or dst.parent != self.trash:
                raise ValueError('撤回路径不合法。')
            if entry.get('native'):
                with directory_fd(src.parent):
                    if entry.get('staging') and Path(entry['staging']).exists():
                        recovery_source = Path(entry['staging'])
                    else:
                        recovery_source = dst
                    self.native('restore', recovery_source, entry['inode'], entry['device'], src)
                entry['status'] = 'restored'
                self.save()
                return {'restored': str(src)}
            with directory_fd(self.trash) as trash_fd, directory_fd(src.parent) as restore_fd:
                s = os.stat(dst.name, dir_fd=trash_fd, follow_symlinks=False)
                if s.st_ino != entry['inode'] or s.st_dev != entry['device']:
                    raise ValueError('废纸篓文件已变化，不能自动撤回。')
                move_exclusive(trash_fd, dst.name, restore_fd, src.name)
            entry['status'] = 'restored'
            self.save()
            return {'restored': str(src)}
