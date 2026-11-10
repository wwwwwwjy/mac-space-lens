"""Metadata-only disk inventory. No file contents, symlinks or mounted disks are followed."""
from __future__ import annotations

import os
import contextlib
import sqlite3
import stat
import threading
import time
from pathlib import Path
from descriptions import explain
from application_catalog import application_owner

APP_DIR = Path(__file__).resolve().parent
HOME = Path.home()
STATE = Path(os.environ.get('SPACE_LENS_STATE', APP_DIR / '.state')).resolve()
DATA_DIR = Path(os.environ.get('SPACE_LENS_DATA', STATE)).resolve()
LARGE = 20 * 1024**2
RISK_LABELS = {'recommended': '建议清理', 'review': '确认后可清理', 'caution': '慎重清理', 'protected': '仅查看'}


class ScanCancelled(Exception):
    pass


def within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _base_description(path: Path, is_dir: bool, mtime: float, home: Path = HOME) -> dict:
    """Suggestions are based on location/type, never a claim that contents are disposable."""
    p, h = str(path), str(home)
    lower = p.lower()
    name = path.name.lower()
    age = max(0, (time.time() - mtime) / 86400)
    risk, kind, note = 'caution', '个人文件', '用途仅按路径和扩展名判断。请先查看，确认不再使用并有备份。'
    protected = (not within(path, home) or path == home or
                 any(within(path, root) or within(root, path) for root in (APP_DIR, STATE, DATA_DIR)))
    fixed = ['Library', 'Library/Application Support', 'Library/Containers', 'Library/Group Containers',
             'Library/Preferences', 'Library/Keychains', 'Library/Caches', 'Library/Logs',
             'Desktop', 'Documents', 'Downloads', 'Movies', 'Music', 'Pictures', 'Applications',
             '.cache', '.config', '.local']
    if any(path == home / x for x in fixed):
        protected = True
    if any(within(path, home / x) for x in ['.ssh', '.gnupg', '.aws', 'Library/Keychains',
           'Library/Preferences', 'Library/Mail', 'Library/Messages', '.Trash']):
        protected = True
        note = '包含系统设置、账号凭据、邮件/消息或废纸篓内容，本工具不清理。'
    cloud = any(within(path, home / x) for x in ['Library/Mobile Documents', 'Library/CloudStorage'])
    if cloud:
        protected = True
        note = '云盘同步目录：删除可能同步到其他设备。请在对应云盘中使用“移除下载”。'
    if '/caches/' in lower or within(path, home / '.cache') or '/.npm/_cacache' in lower:
        risk, kind, note = 'recommended', '应用缓存', '通常可重新生成；请先退出所属应用。再次使用可能需要下载或重新渲染。'
    if '/library/logs/' in lower:
        risk, kind, note = ('recommended' if age > 30 else 'review'), '运行日志', '主要用于诊断问题；先退出所属应用。若正在排查故障，建议保留近期日志。'
    if '/deriveddata/' in lower:
        risk, kind, note = 'recommended', 'Xcode 编译缓存', '可重新编译生成；先关闭 Xcode，之后第一次编译会变慢。'
    if name in {'cache', 'code cache', 'gpucache'} and '/library/application support/' in lower:
        risk, kind, note = 'review', '应用缓存候选', '目录名像缓存，但不同应用用途不同；先退出应用并核对内容。'
    if within(path, home / 'Downloads'):
        risk, kind, note = 'review', '下载文件', '请确认已安装、已解压或另有备份；下载目录也可能存放唯一的工作素材。'
        if path.suffix.lower() in {'.dmg', '.pkg', '.zip', '.7z', '.rar', '.tar', '.gz', '.iso'}:
            kind, note = '安装包 / 压缩包', '安装或解压完成后通常可移除；先确认不需要重装、离线安装或保留压缩原件。'
    if name == 'node_modules' or '/node_modules/' in lower or name in {'.venv', 'venv'}:
        risk, kind, note = 'review', '开发依赖', '有依赖清单且能重新下载时可重建；删除会让对应项目暂时不能运行。'
    if any(x in lower for x in ['huggingface', '/.lmstudio/models', '/.ollama/models']) or path.suffix.lower() in {'.gguf', '.safetensors', '.ckpt'}:
        risk, kind, note = 'review', 'AI 模型 / 模型缓存', '不是普通临时文件。删除后本地 AI 可能无法运行，需要重新下载大文件。'
    if any(x in lower for x in ['jianying', 'capcut', 'davinci', 'blackmagic', 'com.lveditor']):
        if risk != 'recommended':
            risk, kind, note = 'caution', '剪辑应用数据', '可能包含草稿、工程、素材、代理或渲染缓存；优先在剪映 / 达芬奇内清理，不能仅凭大小删除。'
        else:
            kind = '剪辑应用缓存'
    if path.suffix.lower() in {'.mp4', '.mov', '.mkv', '.mxf', '.braw', '.r3d', '.wav'}:
        risk, kind, note = 'caution', '视频 / 音频素材', '可能仍被剪辑工程引用；移走会导致媒体离线。请先备份或在剪辑软件中归档。'
    if any(x in lower for x in ['wechat', 'weixin', 'com.tencent.xin']):
        risk, kind, note = 'caution', '微信数据', '可能包含聊天附件与记录。建议优先使用微信自带的存储空间管理。'
    if '/steamapps' in lower or path.suffix.lower() in {'.app', '.pvm', '.qcow2', '.vmdk', '.photoslibrary'}:
        risk, kind, note = 'caution', '应用 / 游戏 / 资料库', '请优先在 Steam、虚拟机或照片应用内管理；不建议手动删除内部文件。'
    if '/mobileSync/backup'.lower() in lower:
        risk, kind, note = 'caution', 'iPhone / iPad 备份', '可能是唯一的设备备份。请在 Finder 的设备备份管理中确认后移除。'
    if '/library/application support/' in lower and kind == '个人文件':
        kind, note = '应用数据', '可能同时保存设置、账号、素材与数据库；不等同于缓存，请先核对所属应用。'
    if '/.codex/' in lower or '/.claude/' in lower:
        risk, kind, note = 'caution', 'AI 工具工作数据', '可能包含会话、配置、插件和工作文件；请勿整目录清理。'
    if 'codex-runtimes' in lower or '/.npm-global/' in lower:
        risk, kind, note = 'caution', '工具运行环境', '这是已安装的运行时或命令行工具，不是普通缓存。删除可能使 Codex / 开发工具无法工作。'
    if risk == 'recommended' and ('com.apple.' in lower or name == 'geoservices'):
        risk, kind, note = 'caution', 'macOS 服务缓存', '系统服务可能正在使用，通常由 macOS 管理。不建议为少量空间手动清理。'
    if '/application support/steam' in lower:
        risk, kind, note = 'caution', 'Steam 游戏与客户端数据', '可能包含已安装游戏、存档及客户端数据。优先在 Steam 的“存储空间”中卸载不玩的游戏。'
    if '/parallels/downloads' in lower and path.suffix.lower() == '.iso':
        risk, kind, note = 'review', '虚拟机系统安装镜像', '安装 Windows 后可能不再需要；请确认虚拟机没有挂载此镜像，并且不需要离线重装。'
    if '/group containers/' in lower and kind == '个人文件':
        kind, note = '应用共享数据', '应用组共享目录，可能含离线下载、资料库或账号数据；请进入目录核对，不按名称猜测是否可删除。'
    if path == home / '.Trash':
        kind, note = '废纸篓', '仍占用磁盘空间。确认无误后可在 Finder 中清空；本工具不永久删除。'
    if not within(path, home):
        kind, note = '应用 / 系统 / 共享数据', '用于解释空间占用。此区域只读，请通过应用卸载器或 macOS 存储管理处理。'
    if protected:
        risk = 'protected'
    return {'risk': risk, 'risk_label': RISK_LABELS[risk], 'kind': kind, 'note': note,
            'deletable': not protected}


def describe(path: Path, is_dir: bool, mtime: float, home: Path = HOME) -> dict:
    base = _base_description(path, is_dir, mtime, home)
    details = explain(path, is_dir, home, base)
    if details['owner'] == '用途待核对':
        detected_owner = application_owner(path, home)
        if detected_owner:
            details['owner'] = detected_owner
            details['basis'] += '；所属应用根据本机已安装应用信息匹配'
    result = {**base, **details, 'note': base['note']}
    result['risk_label'] = RISK_LABELS[result['risk']]
    return result


class Inventory:
    def __init__(self, state: Path = STATE, roots=None, home: Path = HOME):
        self.state, self.home = state, home
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = state / 'inventory.sqlite3'
        self.roots = roots or [home, Path('/Applications'), Path('/Library'), Path('/private/var'), Path('/Users/Shared')]
        self.progress = {'running': False, 'done': False, 'files': 0, 'dirs': 0, 'errors': 0, 'current': '', 'started': 0, 'finished': 0}
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.worker = None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS nodes(path TEXT PRIMARY KEY,parent TEXT,name TEXT,dir INTEGER,bytes INTEGER,logical INTEGER,mtime REAL,files INTEGER,incomplete INTEGER,risk TEXT,kind TEXT,note TEXT,deletable INTEGER)')
            db.execute('CREATE INDEX IF NOT EXISTS parent_idx ON nodes(parent)')
            db.execute('CREATE INDEX IF NOT EXISTS size_idx ON nodes(bytes DESC)')
            db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)')
            row = db.execute("SELECT value FROM meta WHERE key='finished'").fetchone()
            if row:
                self.progress.update(done=True, finished=float(row[0]))
                totals = [db.execute('SELECT files,incomplete FROM nodes WHERE path=?', (str(root),)).fetchone() for root in self.roots]
                self.progress.update(files=sum(x['files'] for x in totals if x),
                                     errors=sum(x['incomplete'] for x in totals if x),
                                     dirs=db.execute('SELECT COUNT(*) FROM nodes WHERE dir=1').fetchone()[0])
            self.progress['needs_rescan'] = bool(db.execute("SELECT value FROM meta WHERE key='needs_rescan'").fetchone())
            version = db.execute("SELECT value FROM meta WHERE key='description_version'").fetchone()
            if not version or version[0] != '2':
                # Only candidate rows need reclassification; browsing describes small items live.
                for row in db.execute('SELECT path,dir,mtime FROM nodes WHERE bytes>=?', (LARGE,)).fetchall():
                    d = describe(Path(row['path']), row['dir'], row['mtime'], home)
                    db.execute('UPDATE nodes SET risk=?,kind=?,deletable=? WHERE path=?',
                               (d['risk'], d['kind'], int(d['deletable']), row['path']))
                db.execute("INSERT OR REPLACE INTO meta VALUES('description_version','2')")

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    @contextlib.contextmanager
    def db(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def start(self):
        if not self.operation_lock.acquire(blocking=False):
            raise ValueError('正在扫描或处理文件，请稍后再试。')
        with self.lock:
            self.cancel_event.clear()
            self.progress = {'running': True, 'done': False, 'files': 0, 'dirs': 0, 'errors': 0, 'current': '', 'started': time.time(), 'finished': 0}
        self.worker = threading.Thread(target=self._scan, daemon=True)
        self.worker.start()

    def cancel(self):
        self.cancel_event.set()

    def _scan(self):
        db = self._connect()
        db.execute('DELETE FROM nodes')
        db.execute('DELETE FROM meta')
        db.commit()
        seen_links = set()
        commits = [0]
        last_progress = [0.0]

        def visit(path, device):
            if self.cancel_event.is_set():
                raise ScanCancelled()
            try:
                s = path.lstat()
            except OSError:
                self.progress['errors'] += 1
                return 0, 0, 0, 1
            if stat.S_ISLNK(s.st_mode) or s.st_dev != device:
                return 0, 0, 0, 0
            if within(path, self.state):
                return 0, 0, 0, 0
            allocated, logical, count, incomplete = s.st_blocks * 512, s.st_size, 0, 0
            directory = stat.S_ISDIR(s.st_mode)
            if not directory and not stat.S_ISREG(s.st_mode):
                return 0, 0, 0, 0
            if not directory:
                count = 1
                self.progress['files'] += 1
                if s.st_nlink > 1:
                    identity = (s.st_dev, s.st_ino)
                    if identity in seen_links:
                        allocated = logical = 0
                    seen_links.add(identity)
            else:
                self.progress['dirs'] += 1
                logical = 0
                now = time.monotonic()
                if now - last_progress[0] > .3:
                    self.progress['current'] = str(path)
                    last_progress[0] = now
                try:
                    with os.scandir(path) as entries:
                        for entry in entries:
                            a, l, n, e = visit(Path(entry.path), device)
                            allocated += a
                            logical += l
                            count += n
                            incomplete += e
                except OSError:
                    incomplete += 1
                    self.progress['errors'] += 1
            if directory or allocated >= LARGE or logical >= LARGE:
                info = describe(path, directory, s.st_mtime, self.home)
                db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (str(path), str(path.parent), path.name, int(directory), allocated, logical,
                            s.st_mtime, count, incomplete, info['risk'], info['kind'], info['note'], int(info['deletable'])))
                commits[0] += 1
                if commits[0] % 1500 == 0:
                    db.commit()
            return allocated, logical, count, incomplete

        try:
            for root in self.roots:
                try:
                    device = root.lstat().st_dev
                except OSError:
                    continue
                visit(root, device)
                db.commit()
            finished = time.time()
            db.execute("INSERT OR REPLACE INTO meta VALUES('finished',?)", (str(finished),))
            db.execute("INSERT OR REPLACE INTO meta VALUES('description_version','2')")
            db.commit()
            self.progress.update(done=True, finished=finished)
        except ScanCancelled:
            self.progress.update(done=False, cancelled=True)
        except Exception as exc:
            self.progress['error'] = str(exc)
        finally:
            db.close()
            self.progress['running'] = False
            self.operation_lock.release()

    def roots_data(self):
        with self.db() as db:
            return [dict(row) for root in self.roots for row in db.execute('SELECT * FROM nodes WHERE path=?', (str(root),))]

    def with_context(self, rows):
        with self.db() as db:
            result = []
            for row in rows:
                item = dict(row)
                item['children'] = []
                if item.get('dir'):
                    item['children'] = [dict(r) for r in db.execute(
                        'SELECT name,path,bytes,dir FROM nodes WHERE parent=? AND bytes>0 ORDER BY bytes DESC LIMIT 3',
                        (item['path'],))]
                result.append(item)
            return result

    def record_changes(self, paths):
        """Remove vanished entries, without pretending stale ancestor totals were re-scanned."""
        with self.db() as db:
            for path in paths:
                db.execute('DELETE FROM nodes WHERE path=? OR (path>=? AND path<?)',
                           (path, path+'/', path+'0'))
            db.execute("INSERT OR REPLACE INTO meta VALUES('needs_rescan','1')")
        self.progress['needs_rescan'] = True

    def candidates(self, risk='all', query='', limit=120):
        clauses = ['bytes >= ?']
        args = [LARGE]
        if risk in RISK_LABELS:
            clauses.append('risk=?')
            args.append(risk)
        if query:
            clauses.append('instr(lower(path),lower(?)) > 0')
            args.append(query[:200])
        # Keep suggested aggregate folders, suppress their descendants to avoid double-counting rows.
        with self.db() as db:
            rows = db.execute('SELECT * FROM nodes WHERE '+' AND '.join(clauses)+' ORDER BY bytes DESC LIMIT 6000', args).fetchall()
        result, selected_dirs = [], set()
        root_set = {str(x) for x in self.roots}
        # Visit parents first, using a set lookup for ancestors. Avoid quadratic
        # pairwise comparisons on dependency trees with thousands of directories.
        for row in sorted(rows, key=lambda r: r['path'].count('/')):
            d = dict(row)
            path = Path(d['path'])
            if d['path'] in root_set or not d['deletable']:
                continue
            if any(parent in selected_dirs for parent in path.parents):
                continue
            result.append(d)
            if d['dir']:
                selected_dirs.add(path)
        return sorted(result, key=lambda x: x['bytes'], reverse=True)[:limit]

    def browse(self, path: Path, offset=0):
        if not any(within(path, r) for r in self.roots) or within(path, self.home / '.Trash'):
            raise ValueError('该目录不在可浏览范围。')
        # Do not follow a symlink in any path component.
        if path.resolve() != path or within(path, self.state):
            raise ValueError('不进入符号链接或工具运行目录。')
        with self.db() as db:
            known = {r['path']: dict(r) for r in db.execute('SELECT * FROM nodes WHERE parent=?', (str(path),))}
        rows, errors = [], 0
        with os.scandir(path) as entries:
            for entry in entries:
                p = Path(entry.path)
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    errors += 1
                    continue
                directory = stat.S_ISDIR(st.st_mode)
                item = known.get(str(p)) or dict(path=str(p), parent=str(path), name=p.name, dir=directory,
                                               bytes=st.st_blocks*512 if not directory else 0,
                                               logical=st.st_size if not directory else 0, mtime=st.st_mtime,
                                               files=0 if directory else 1, incomplete=1 if directory else 0)
                item.update(describe(p, directory, st.st_mtime, self.home))
                if stat.S_ISLNK(st.st_mode) or within(p, self.state):
                    item.update(deletable=False, risk='protected', kind='链接 / 受保护目录', note='不会跟随符号链接或清理工具自身。', dir=False)
                rows.append(item)
        rows.sort(key=lambda x: x['bytes'], reverse=True)
        return {'items': rows[offset:offset+150], 'total': len(rows), 'errors': errors}
