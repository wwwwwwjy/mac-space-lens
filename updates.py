"""Check official GitHub releases and stage a verified macOS application."""
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

REPO = 'wwwwwwjy/mac-space-lens'
VERSION = '1.0.1'
APP_NAME = '空间磁盘管家.app'
BUNDLE_ID = 'local.spacelens.diskmanager'
MAX_ARCHIVE = 256 * 1024 * 1024


def version_parts(version):
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]{1,8}(\.[0-9]{1,8}){2}', version):
        raise ValueError('正式版本号无效。')
    return tuple(map(int, version.split('.')))


def github_download(url, limit, timeout, destination=None):
    command = ['/usr/bin/curl', '-q', '--fail', '--silent', '--show-error', '--location',
               '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '10',
               '--max-time', str(timeout), '--max-filesize', str(limit), '--user-agent', 'SpaceLens-Updater/1']
    if destination:
        command += ['--output', str(destination)]
    try:
        result = subprocess.run(command + [url], capture_output=True, check=True, timeout=timeout + 5)
    except subprocess.SubprocessError as exc:
        raise ValueError('无法从 GitHub 读取更新，请检查网络连接或稍后重试。') from exc
    if (destination.stat().st_size if destination else len(result.stdout)) > limit:
        raise ValueError('GitHub 更新文件超过大小限制。')
    return result.stdout


def validate_archive(package):
    """Reject paths and symlinks that could write outside the staging directory."""
    try:
        with zipfile.ZipFile(package) as archive:
            seen = set()
            links = set()
            size = 0
            for entry in archive.infolist():
                name = entry.filename if entry.flag_bits & 0x800 else entry.filename.encode('cp437').decode('utf-8')
                path = PurePosixPath(name)
                mode = stat.S_IFMT(entry.external_attr >> 16)
                size += entry.file_size
                if (not path.parts or path.parts[0] != APP_NAME or '..' in path.parts or '\\' in name
                        or path in seen or mode not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)
                        or size > 2 * MAX_ARCHIVE):
                    raise ValueError('更新包目录结构无效。')
                seen.add(path)
                if mode == stat.S_IFLNK:
                    if entry.file_size > 1024:
                        raise ValueError('更新包包含无效的符号链接。')
                    target = PurePosixPath(archive.read(entry).decode('utf-8'))
                    if not target.parts or target.is_absolute() or '..' in target.parts or len(path.parts) < 2:
                        raise ValueError('更新包包含无效的符号链接。')
                    links.add(path)
            if not seen or any(parent in links for path in seen for parent in path.parents):
                raise ValueError('更新包目录结构无效。')
    except zipfile.BadZipFile as exc:
        raise ValueError('更新包不是有效的 ZIP 文件。') from exc


class Updater:
    def __init__(self, bundle, runtime, data):
        self.bundle = bundle
        self.runtime = runtime
        self.preference = data / 'update-settings.json'
        self.install_lock = threading.Lock()
        self.current = VERSION
        if bundle:
            with (bundle / 'Contents/Info.plist').open('rb') as file:
                self.current = plistlib.load(file)['CFBundleShortVersionString']

    def settings(self):
        automatic = True
        try:
            automatic = json.loads(self.preference.read_text()).get('automatic') is not False
        except (OSError, ValueError, AttributeError):
            pass
        return {'automatic': bool(self.bundle and automatic), 'native': bool(self.bundle), 'current': self.current}

    def configure(self, automatic):
        if not self.bundle or type(automatic) is not bool:
            raise ValueError('请在 macOS App 中设置自动检查。')
        self.preference.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=self.preference.parent, delete=False) as file:
            temporary = Path(file.name)
            try:
                json.dump({'automatic': automatic}, file)
                file.close()
                temporary.replace(self.preference)
            finally:
                temporary.unlink(missing_ok=True)
        return self.settings()

    def check(self):
        url = f'https://api.github.com/repos/{REPO}/releases/latest'
        release = json.loads(github_download(url, 2 * 1024 * 1024, 20))
        tag = release.get('tag_name', '')
        if release.get('draft') or release.get('prerelease') or not tag.startswith('v'):
            raise ValueError('GitHub 返回的正式版本信息无效。')
        version = tag[1:]
        available = version_parts(version) > version_parts(self.current)
        assets = {asset.get('name') for asset in release.get('assets', []) if asset.get('state') == 'uploaded'}
        installable = {f'SpaceLens-{version}-universal.zip', 'SHA256SUMS.txt'} <= assets
        return {'current': self.current, 'version': version, 'update': available,
                'installable': bool(self.bundle and installable), 'notes': release.get('body') or ''}

    def prepare(self, version):
        if not self.bundle:
            raise ValueError('请在 macOS App 中安装更新。')
        if version_parts(version) <= version_parts(self.current):
            raise ValueError('只能安装比当前版本更新的正式版。')
        if not self.install_lock.acquire(blocking=False):
            raise ValueError('正在准备更新，请稍候。')
        try:
            release = self.check()
            if not release['installable'] or version != release['version']:
                raise ValueError('最新正式版或附件已变化，请重新检查更新。')
            candidate = self.runtime / 'update-ready.app'
            if candidate.exists():
                with (candidate / 'Contents/Info.plist').open('rb') as file:
                    if plistlib.load(file)['CFBundleShortVersionString'] == version:
                        return
                shutil.rmtree(candidate)
            self.stage(version)
        finally:
            self.install_lock.release()

    def stage(self, version):
        name = f'SpaceLens-{version}-universal.zip'
        url = f'https://github.com/{REPO}/releases/download/v{version}/'
        with tempfile.TemporaryDirectory(prefix='download-', dir=self.runtime) as directory:
            staging = Path(directory)
            package = staging / name
            sums = github_download(url + 'SHA256SUMS.txt', 65536, 20).decode('ascii')
            expected = re.findall(r'^([a-fA-F0-9]{64})[ \t]+\*?' + re.escape(name) + r'\r?$', sums, re.M)
            if len(expected) != 1:
                raise ValueError('正式版缺少有效的 SHA-256 校验值。')
            github_download(url + name, MAX_ARCHIVE, 180, package)
            with package.open('rb') as file:
                digest = hashlib.sha256()
                for chunk in iter(lambda: file.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected[0].lower():
                raise ValueError('安装包 SHA-256 校验失败。')
            validate_archive(package)
            candidate = staging / APP_NAME
            try:
                subprocess.run(['/usr/bin/ditto', '-x', '-k', str(package), str(staging)],
                               capture_output=True, check=True, timeout=60)
                with (candidate / 'Contents/Info.plist').open('rb') as file:
                    plist = plistlib.load(file)
                if (plist.get('CFBundleIdentifier') != BUNDLE_ID or
                        plist.get('CFBundleShortVersionString') != version or
                        plist.get('CFBundleExecutable') != 'SpaceLens'):
                    raise ValueError('更新包的应用身份或版本不匹配。')
                subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(candidate)],
                               capture_output=True, check=True, timeout=60)
            except (subprocess.SubprocessError, plistlib.InvalidFileException, OSError) as exc:
                raise ValueError('无法解包或验证更新 App。') from exc
            shutil.move(candidate, self.runtime / 'update-ready.app')
