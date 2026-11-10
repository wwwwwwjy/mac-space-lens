"""Application identity, explicit uninstall plans and conservative leftover discovery.

No broad name-globbing deletion; no sudo, launchctl, package scripts or content reads.
Only app bundles and bounded per-user candidates receive scoped trash capabilities.
Name-based candidates require an additional ownership confirmation at commit time.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import stat
import subprocess
import threading
import time

from actions import fingerprint
from application_catalog import ApplicationCatalog, normalized
from app_presentation import AppPresentation
from storage import APP_DIR, DATA_DIR, STATE, within

SELF_ID = 'local.spacelens.diskmanager'
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}\Z')
BUNDLE_ID = re.compile(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\Z')
# Only complete app-specific directories, never a vendor's shared parent.
NAMED_SUPPORT = {
    'com.google.Chrome': ['Google/Chrome'],
    'com.microsoft.edgemac': ['Microsoft Edge'],
    'org.mozilla.firefox': ['Firefox'],
    'com.microsoft.VSCode': ['Code'],
    'com.todesktop.230313mzl4w4u92': ['Cursor'],
    'com.openai.chat': ['com.openai.chat'],
    'com.anthropic.claudefordesktop': ['Claude'],
    'org.ryujinx.Ryujinx': ['Ryujinx'],
}
SHARED_NAMES = {normalized(name) for name in (
    'Shared', 'Common', 'Data', 'Cache', 'Caches', 'Logs', 'Application Support',
    'Applications', 'Google', 'Microsoft', 'Adobe', 'Apple', 'Autodesk',
    'Tencent', 'ByteDance', 'Valve', 'Unity', 'Epic Games', 'Electronic Arts',
)}
LOCATIONS = [
    ('Caches', '', '缓存', '重新安装后可能需要重新下载，首次启动变慢。'),
    ('Logs', '', '运行日志', '失去历史诊断记录，通常不影响个人文档。'),
    ('Preferences', '.plist', '个人偏好设置', '重装后设置、窗口偏好或登录状态可能重置。'),
    ('Saved Application State', '.savedState', '窗口恢复状态', '重装后不能恢复原来的窗口位置和会话。'),
    ('HTTPStorages', '', '网页存储', '可能移除登录状态、站点数据及离线内容。'),
    ('HTTPStorages', '.binarycookies', '网页登录数据', '网页登录状态可能丢失。'),
    ('WebKit', '', '内嵌网页数据', '可能清除内嵌网页的登录状态和离线数据。'),
    ('Application Support', '', '应用支持数据', '可能包含数据库、账号、本地历史、下载内容或唯一资料；必须先备份。'),
    ('Containers', '', '沙盒应用数据', '可能包含个人文档、项目和数据库。必须核对内容并保留备份。'),
]


def read_plist(path):
    try:
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            return {}
        data = plistlib.loads(path.read_bytes())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def measure(path, seconds=1.5, limit=40000):
    """Bounded, no-follow metadata walk. Partial sizes must not be shown as exact."""
    total = 0
    count = 0
    incomplete = False
    deadline = time.monotonic() + seconds
    seen = set()
    device = path.lstat().st_dev
    stack = [path]
    while stack:
        if time.monotonic() > deadline or count >= limit:
            incomplete = True
            break
        node = stack.pop()
        try:
            s = node.lstat()
            count += 1
            if s.st_dev != device:
                incomplete = True
                continue
            key = (s.st_dev, s.st_ino)
            if key not in seen:
                total += s.st_blocks * 512
                seen.add(key)
            if stat.S_ISDIR(s.st_mode):
                # Never open a symlink substituted between lstat and scandir.
                fd = os.open(node, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    if os.fstat(fd).st_ino != s.st_ino:
                        incomplete = True
                        continue
                    with os.scandir(fd) as children:
                        stack.extend(node / child.name for child in children)
                finally:
                    os.close(fd)
        except OSError:
            incomplete = True
    return total, incomplete


class AppManager:
    def __init__(self, actions, home, data_dir, roots=None, process_reader=None):
        self.actions, self.home = actions, Path(home).resolve()
        self.roots = tuple(Path(r).resolve() for r in (roots or ['/Applications', self.home/'Applications']))
        self.history_path = Path(data_dir)/'application-history.json'
        self.lock = threading.RLock()
        self.catalog = None
        self.presentation = AppPresentation()
        self.apps, self.targets, self.plans = {}, {}, {}
        self.process_reader = process_reader or self._processes
        self.records = {}
        try:
            saved = json.loads(self.history_path.read_text())
            if isinstance(saved, dict):
                self.records = {k: v for k, v in saved.items()
                                if BUNDLE_ID.fullmatch(k) and isinstance(v, dict) and v.get('identifier') == k
                                and isinstance(v.get('name'), str) and isinstance(v.get('aliases', []), list)}
        except (OSError, ValueError):
            pass
        actions.scope_validator = self.validate
        actions.restore_validator = self.validate_restore

    def _save(self):
        self.history_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.history_path.with_suffix('.tmp')
        with open(tmp, 'w') as handle:
            os.chmod(tmp, 0o600)
            json.dump(self.records, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.history_path)

    @staticmethod
    def _processes():
        try:
            return subprocess.check_output(['/bin/ps', '-ww', '-axo', 'command='], text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('无法核对正在运行的软件，暂不执行卸载。')

    def _running(self, identity):
        commands = self.process_reader()
        path = identity.get('path', '')
        if path and path+'/Contents/' in commands:
            return True
        identifier = identity.get('identifier', '')
        return bool(identifier and re.search(r'(?<![\w.])'+re.escape(identifier)+r'(?:\b|\.)', commands))

    def _app_root(self, path):
        return (path.suffix.lower() == '.app' and any(within(path, root) and path != root
                and len(path.relative_to(root).parts) <= 3 for root in self.roots)
                and not any(p.suffix.lower() == '.app' for p in path.parents))

    def _safe_identity(self, identity):
        bid = identity.get('identifier', '')
        return bool(BUNDLE_ID.fullmatch(bid) and not bid.casefold().startswith('com.apple.') and bid != SELF_ID)

    def _related(self, a, b):
        a, b = a.casefold(), b.casefold()
        return a == b or a.startswith(b+'.') or b.startswith(a+'.')

    def _active(self, identity, catalog):
        bid = identity['identifier']
        return ([a for a in catalog.apps if self._related(a['identifier'], bid)] +
                [{'identifier': value} for value in catalog.component_ids if self._related(value, bid)])

    def refresh(self, include_components=False):
        """Read public bundle metadata only. Store identity, not the user's app data."""
        with self.lock:
            self.catalog = ApplicationCatalog(self.roots, components=include_components)
            self.apps = {}
            for app in self.presentation.apply(self.catalog.apps):
                path = Path(app['path'])
                app = dict(app)
                app['id'] = hashlib.sha256(str(path).encode()).hexdigest()[:24]
                app['blocked'] = ''
                if (not self._safe_identity(app) or not self._app_root(path) or path.resolve() != path or
                        any(within(x, path) for x in (APP_DIR, STATE, DATA_DIR, self.history_path.parent))):
                    app['blocked'] = '系统应用、工具自身或路径不在支持的应用目录中，不能卸载。'
                elif not os.access(path.parent, os.W_OK):
                    app['blocked'] = '此位置需要管理员权限；请在 Finder 或官方卸载器中处理。'
                self.apps[app['id']] = app
                if self._safe_identity(app):
                    prior = self.records.get(app['identifier'], {})
                    self.records[app['identifier']] = {**prior, **{k: app[k] for k in ('name','path','identifier','aliases','version')},
                                                       'source': 'observed', 'last_seen': time.time()}
            self._save()
            return {'items': sorted(self.apps.values(), key=lambda x: x['name'].casefold()),
                    'warnings': ['有应用目录或元数据不可读取；没有把“未发现”当作已卸载。'] if self.catalog.errors else [],
                    'scope': '识别 /Applications 与当前用户 Applications 中的应用；系统应用和本工具不可卸载。'}

    def _issue(self, path, identity, scope, size, proof=None):
        item_id = secrets.token_urlsafe(18)
        item = {'path': str(path), 'stat': fingerprint(path.lstat()), 'bytes': size,
                'risk': 'caution', 'issued': time.time(), 'scope': scope,
                'app_identity': {k: identity.get(k) for k in ('identifier','name','aliases','path','source')},
                'proof': proof}
        self.actions.items[item_id] = item
        return item_id

    def explain_id(self, row):
        ident = secrets.token_urlsafe(18)
        with self.actions.lock:
            self.actions.explanations[ident] = {k: row.get(k) for k in
                ('path','name','bytes','kind','risk','content','advice','impact','owner','basis')}
        return ident

    def preview_uninstall(self, app_id):
        if not isinstance(app_id, str):
            raise ValueError('请选择应用列表中的软件。')
        self.refresh()
        app = self.apps.get(app_id)
        if not app or app['blocked']:
            raise ValueError(app.get('blocked') if app else '应用列表已变化，请刷新。')
        if self._running(app):
            raise ValueError('请先完全退出 '+app['name']+' 及其后台进程，再卸载；不会强制结束你的工作。')
        size, partial = measure(Path(app['path']), seconds=2)
        ident = self._issue(Path(app['path']), app, 'app_bundle', size)
        plan = self.actions.preview([ident])
        self.actions.tickets[plan['ticket']]['workflow'] = 'uninstall'
        self.plans[plan['ticket']] = dict(app)
        return {**plan, 'app': app, 'size_partial': partial,
                'impact': '将应用本体移入废纸篓，不能再直接启动；个人数据暂不处理。随后自动查找残留，由你另行勾选确认。'}

    def uninstall(self, ticket, confirm_name):
        if not isinstance(ticket, str) or not isinstance(confirm_name, str):
            raise ValueError('请先核对应用名称并确认卸载。')
        identity = self.plans.get(ticket)
        if not identity or confirm_name != identity['name']:
            raise ValueError('请输入完整应用名称确认卸载。')
        result = self.actions.commit(ticket, True, workflow='uninstall')
        self.plans.pop(ticket, None)
        # native Trash success is verified by the vanished original path; don't claim
        # completion on a permissions error or an interrupted move.
        if result['moved'] and not Path(identity['path']).exists():
            record = {**identity, 'source': 'uninstalled', 'uninstalled_at': time.time()}
            self.records[identity['identifier']] = record
            self._save()
            target = self._target(record)
            result['target'] = target
        return result

    def _target(self, identity):
        key = hashlib.sha256(identity['identifier'].encode()).hexdigest()[:24]
        self.targets[key] = dict(identity)
        return {'id': key, 'name': identity.get('name') or identity['identifier'],
                'identifier': identity['identifier'], 'source': identity.get('source','unknown'),
                'needs_confirmation': identity.get('source') not in {'uninstalled','confirmed'}}

    def orphan_targets(self):
        self.refresh(include_components=True)
        catalog = self.catalog
        candidates = {k: dict(v) for k, v in self.records.items() if not self._active(v, catalog)}
        skipped = 0
        for directory, suffix, *_ in LOCATIONS:
            folder = self.home/'Library'/directory
            if folder.is_symlink():
                continue
            try:
                entries = list(folder.iterdir())[:10000]
            except OSError:
                skipped += 1
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                name = entry.name
                if suffix:
                    if not name.endswith(suffix):
                        continue
                    name = name[:-len(suffix)]
                if not IDENTIFIER.fullmatch(name):
                    continue
                identity = {'identifier': name, 'name': name, 'aliases': [], 'source': 'unknown'}
                if self._safe_identity(identity) and name not in candidates and not self._active(identity, catalog):
                    candidates[name] = identity
        self.targets = {}
        result = [self._target(c) for c in candidates.values() if self._safe_identity(c)]
        return {'items': sorted(result, key=lambda x: (x['needs_confirmation'], x['name'].casefold())),
                'warnings': (['部分目录没有权限，结果可能不完整。'] if skipped or catalog.errors else []),
                'notice': '未发现对应应用只代表残留候选。可能属于外置磁盘上的软件、命令行工具或后台组件；旧记录之外的候选需要你确认软件已卸载。'}

    def _candidates(self, identity):
        bid = identity['identifier']
        result = []
        for directory, suffix, kind, impact in LOCATIONS:
            p = self.home/'Library'/directory/(bid+suffix)
            result.append((p, kind, impact, 'exact_id', '路径完整匹配应用标识 '+bid))
        for relative in NAMED_SUPPORT.get(bid, []):
            p = self.home/'Library/Application Support'/relative
            if not any(x[0] == p for x in result):
                result.append((p, '应用支持数据', '可能包含账号、书签、数据库、工作设置和唯一资料；请先备份。',
                               'recipe', '应用标识与已知专属数据目录同时匹配'))
        if bid.casefold() == 'org.ryujinx.ryujinx':
            for folder, kind, impact in (
                ('Logs', 'Ryujinx 运行日志', '删除历史运行和报错日志，不会删除游戏存档。'),
                ('Caches', 'Ryujinx 缓存', '再次使用时可能需要重新生成缓存。'),
            ):
                result.append((self.home/'Library'/folder/'Ryujinx', kind, impact,
                               'recipe', 'Ryujinx 应用标识与专属目录匹配'))
        # Exact app names are selectable, but never imply automatic ownership approval.
        for alias in identity.get('aliases', []):
            if not isinstance(alias, str) or '/' in alias or alias in {'.','..'} or len(alias) < 3:
                continue
            for folder in ('Application Support','Caches','Logs'):
                p = self.home/'Library'/folder/alias
                if not any(x[0] == p for x in result):
                    kind, impact = next((kind, impact) for directory, suffix, kind, impact in LOCATIONS
                                        if directory == folder and not suffix)
                    result.append((p, kind, impact, 'name_only',
                                   '目录名与该软件的完整名称一致；清理前还需你确认归属'))
        # Shared and privileged components are reported, never removed automatically.
        for base in (self.home/'Library/Group Containers', self.home/'Library/LaunchAgents',
                     Path('/Library/LaunchAgents'), Path('/Library/LaunchDaemons'), Path('/Library/PrivilegedHelperTools')):
            try:
                if base.is_symlink():
                    continue
                for p in list(base.iterdir())[:10000]:
                    stem = p.name.removesuffix('.plist')
                    if stem == bid or stem.startswith(bid+'.') or stem.endswith('.'+bid):
                        result.append((p, '共享数据 / 后台组件', '可能仍由其他应用使用或正在加载；请通过官方卸载器处理。',
                                       'shared', '应用标识相关，但属于共享或系统加载位置'))
            except OSError:
                continue
        return result

    def _residual_proof(self, path, identity):
        for candidate, _, _, proof, _ in self._candidates(identity):
            if path == candidate:
                return proof
        return None

    def _residual_allowed(self, path, identity, proof, catalog):
        if proof not in {'exact_id','recipe','name_only'} or not self._safe_identity(identity):
            return '这是共享数据或系统后台组件，请通过官方卸载器处理。'
        if identity.get('source') not in {'uninstalled','confirmed'}:
            return '需要先确认这个软件已经卸载。'
        if self._active(identity, catalog):
            return '仍发现该软件或相关版本，保留其数据。'
        if path.resolve() != path or not within(path, self.home/'Library'):
            return '路径含链接或不在当前用户的应用数据目录中。'
        if any(within(path, x) or within(x, path) for x in (APP_DIR, STATE, DATA_DIR, self.history_path.parent)):
            return '包含本工具或清理记录，不能处理。'
        if proof == 'name_only' and normalized(path.name) in SHARED_NAMES:
            return '这是通用或厂商共享目录，不能作为单个软件的残留清理。'
        if proof in {'recipe','name_only'}:
            for app in catalog.apps:
                aliases = [app.get('name',''), *app.get('aliases', [])]
                claims = [self.home/'Library/Application Support'/p
                          for p in NAMED_SUPPORT.get(app['identifier'], [])]
                if (normalized(path.name) in {normalized(a) for a in aliases} or
                        any(path == p or within(path, p) or within(p, path) for p in claims)):
                    return '仍安装着可能共用此目录的软件：'+app['name']+'。请先核对并卸载相关版本。'
        if not os.access(path.parent, os.W_OK | os.X_OK):
            return '当前账号没有移动此目录的权限，请在 Finder 中核对权限。'
        return ''

    def preview_residuals(self, ids):
        if (not isinstance(ids, list) or not ids or not all(isinstance(i, str) and
                self.actions.items.get(i, {}).get('scope') == 'app_residual' for i in ids)):
            raise ValueError('请从当前残留列表手动勾选。')
        plan = self.actions.preview(ids)
        self.actions.tickets[plan['ticket']]['workflow'] = 'residual'
        uncertain = [i['path'] for i in plan['items'] if i.get('proof') == 'name_only']
        return {**plan, 'needs_ownership_confirmation': bool(uncertain), 'ownership_paths': uncertain}

    def clean_residuals(self, ticket, caution_ack=False, ownership_ack=False):
        plan = self.actions.tickets.get(ticket) if isinstance(ticket, str) else None
        if not plan or plan.get('workflow') != 'residual':
            raise ValueError('请先核对所选残留，再确认清理。')
        if any(i.get('proof') == 'name_only' for i in plan['items']) and ownership_ack is not True:
            raise ValueError('请确认同名目录只属于这个已卸载软件，且没有其他软件使用。')
        return self.actions.commit(ticket, caution_ack, workflow='residual')

    def leftovers(self, target_id, confirm_absent=False):
        if not isinstance(target_id, str):
            raise ValueError('请从残留候选列表选择软件。')
        identity = dict(self.targets.get(target_id) or {})
        if not identity or not self._safe_identity(identity):
            raise ValueError('请选择残留列表中的软件，再重新检索。')
        catalog = ApplicationCatalog(self.roots, components=True)
        if self._active(identity, catalog):
            raise ValueError('检测到此应用或相关版本仍在安装目录中，不能当成卸载残留处理。')
        if confirm_absent is True:
            identity['source'] = 'confirmed'
            self.records[identity['identifier']] = identity
            self._save()
            self.targets[target_id] = identity
        running = self._running(identity)
        rows, warnings, seen = [], [], set()
        if catalog.errors:
            warnings.append('有应用元数据不可读取；请特别核对其他位置、其他版本及后台组件。')
        for path, kind, impact, proof, basis in self._candidates(identity):
            if str(path) in seen:
                continue
            seen.add(str(path))
            try:
                s = path.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                warnings.append('无权读取：'+str(path))
                continue
            reason = self._residual_allowed(path, identity, proof, catalog)
            if running:
                reason = '发现相关进程仍在运行，请先退出或使用官方卸载器。'
            size, incomplete = (0, True) if path.is_symlink() or path.resolve() != path else measure(path)
            # Measuring all children is optional: moving an approved directory to
            # Trash does not require a complete byte count. Native permission
            # failures are reported by the actual move, never as a false success.
            if identity['identifier'].casefold() == 'org.ryujinx.ryujinx' and path == self.home/'Library/Application Support/Ryujinx':
                kind = 'Ryujinx 存档、配置与缓存'
                impact = '可能包含游戏存档、模拟器设置、着色器缓存和已导入的固件。清理后重装不会自动找回这些资料；需要的存档请先备份。'
            ownership = proof == 'name_only' and not reason
            row = {'path': str(path), 'name': path.name, 'kind': kind, 'bytes': size,
                   'size_partial': incomplete, 'basis': basis, 'impact': impact,
                   'owner': identity.get('name', identity['identifier']), 'content': kind,
                   'risk': 'protected' if reason else 'caution', 'blocked': reason,
                   'advice': reason or ('可以勾选；确认窗口中需额外确认这个同名目录只属于已卸载软件。' if ownership else
                                       '可以勾选并移入废纸篓；将清理这个目录及其中全部内容，重要资料请先备份。'),
                   'needs_ownership_confirmation': ownership,
                   'size_note': '占用仅统计到部分内容，清理仍会移动整个目录及其中内容。' if incomplete else '',
                   'id': None, 'deletable': not bool(reason)}
            if not reason:
                row['id'] = self._issue(path, identity, 'app_residual', size, proof)
            row['explain_id'] = self.explain_id(row)
            rows.append(row)
        return {'items': rows, 'target': self._target(identity), 'warnings': warnings,
                'notice': '所有项目默认不勾选。不会处理个人文档目录、钥匙串、云端数据、其他用户、外置磁盘、通用厂商目录。未显示不等于绝无残留。'}

    def validate(self, item):
        path, identity = Path(item['path']), item.get('app_identity') or {}
        if not self._safe_identity(identity) or path.resolve() != path or fingerprint(path.lstat()) != tuple(item['stat']):
            raise ValueError('应用或残留路径已变化，请重新检索。')
        if self._running(identity):
            raise ValueError('相关应用或后台进程正在运行，请先退出再操作。')
        if item['scope'] == 'app_bundle':
            info = read_plist(path/'Contents/Info.plist')
            if (not self._app_root(path) or info.get('CFBundleIdentifier') != identity['identifier'] or
                    not stat.S_ISDIR(path.lstat().st_mode) or
                    any(within(x, path) for x in (APP_DIR, STATE, DATA_DIR, self.history_path.parent))):
                raise ValueError('应用身份已改变，未执行卸载。')
        elif item['scope'] == 'app_residual':
            proof = self._residual_proof(path, identity)
            reason = self._residual_allowed(path, identity, proof, ApplicationCatalog(self.roots, components=True))
            if reason or proof != item['proof']:
                raise ValueError(reason or '归属依据已变化，请重新检索。')
        else:
            raise ValueError('未知的应用操作。')
        if path.lstat().st_dev != self.home.stat().st_dev:
            raise ValueError('不处理其他挂载磁盘中的应用或数据。')
        return path

    def validate_restore(self, entry):
        src = Path(entry['source'])
        return bool(entry.get('scope') == 'app_bundle' and self._app_root(src)
                    and src.parent.resolve() == src.parent and self._safe_identity(entry.get('app_identity') or {}))
