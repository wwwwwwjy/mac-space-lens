"""Build a self-contained universal2 .app; no private .state data is included."""
from pathlib import Path
import importlib.metadata
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build'
DIST = ROOT / 'dist'
APP = DIST / '空间磁盘管家.app'
MINIMUM = '12.0'
VERSION = '1.0.0'


def run(args):
    environment = dict(os.environ)
    environment['PYINSTALLER_CONFIG_DIR'] = str(BUILD / 'pyinstaller-cache')
    subprocess.run([str(x) for x in args], check=True, cwd=ROOT, env=environment)


def universal(source, output, frameworks=()):
    parts = []
    for arch in ('arm64', 'x86_64'):
        target = BUILD / 'native' / (output.name + '-' + arch)
        run(['xcrun', 'swiftc', '-O', '-swift-version', '5', '-target', arch+'-apple-macos'+MINIMUM,
             '-module-cache-path', BUILD/'swift-cache', source, '-o', target] +
            [flag for framework in frameworks for flag in ('-framework', framework)])
        parts.append(target)
    run(['lipo', '-create', *parts, '-output', output])
    run(['codesign', '--force', '--sign', '-', '--timestamp=none', output])


def main():
    if sys.platform != 'darwin':
        raise SystemExit('在 Mac 上构建。')
    sys.path.insert(0, str(ROOT))
    from support_assets import verify_support_assets
    support_hashes = verify_support_assets()
    (BUILD / 'native').mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)
    executable = BUILD/'native'/'SpaceLens'
    helper = BUILD/'native'/'space-lens-trash'
    app_info = BUILD/'native'/'space-lens-app-info'
    universal(ROOT/'native'/'SpaceLens.swift', executable, ('Cocoa', 'WebKit'))
    universal(ROOT/'trash-helper.swift', helper, ('Foundation',))
    universal(ROOT/'native'/'AppPresentation.swift', app_info, ('AppKit',))
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
         '--target-arch', 'universal2', '--name', 'space-lens-server',
         '--distpath', BUILD/'frozen', '--workpath', BUILD/'pyinstaller', '--specpath', BUILD,
         '--add-data', str(ROOT/'web')+':web', '--add-binary', str(helper)+':bin',
         '--add-binary', str(app_info)+':bin',
         '--exclude-module', 'tkinter', '--exclude-module', 'unittest', ROOT/'server.py'])
    if APP.exists():
        shutil.rmtree(APP)
    contents = APP/'Contents'
    resources = contents/'Resources'
    (contents/'MacOS').mkdir(parents=True)
    resources.mkdir()
    shutil.copy2(executable, contents/'MacOS'/'SpaceLens')
    shutil.copytree(BUILD/'frozen'/'space-lens-server', resources/'backend', symlinks=True)
    plist = {'CFBundleName': '空间磁盘管家', 'CFBundleDisplayName': '空间磁盘管家',
             'CFBundleIdentifier': 'local.spacelens.diskmanager', 'CFBundleExecutable': 'SpaceLens',
             'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': VERSION, 'CFBundleVersion': '1',
             'LSMinimumSystemVersion': MINIMUM, 'NSHighResolutionCapable': True,
             'CFBundleIconFile': 'SpaceLens', 'NSSupportsAutomaticGraphicsSwitching': True,
             'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True, 'NSAllowsArbitraryLoadsInWebContent': True},
             'NSDesktopFolderUsageDescription': '扫描你选择清理的桌面文件，显示占用与用途；只在确认后处理文件。',
             'NSDocumentsFolderUsageDescription': '读取文件大小和目录信息，帮助你核对可以清理的资料。',
             'NSDownloadsFolderUsageDescription': '查看下载文件占用，并在你确认后移到废纸篓或删除。',
             'NSHumanReadableCopyright': '© 2026 汪同学（wwwwwwjy）。第三方许可见 Resources/Licenses。'}
    with (contents/'Info.plist').open('wb') as handle:
        plistlib.dump(plist, handle)
    (contents/'PkgInfo').write_bytes(b'APPL????')
    iconset = BUILD/'SpaceLens.iconset'
    if iconset.exists():
        shutil.rmtree(iconset)
    run(['xcrun', 'swiftc', '-O', '-module-cache-path', BUILD/'swift-cache', ROOT/'native'/'Icon.swift', '-o', BUILD/'native'/'make-icon'])
    run([BUILD/'native'/'make-icon', iconset])
    run(['iconutil', '-c', 'icns', iconset, '-o', resources/'SpaceLens.icns'])
    licenses = resources/'Licenses'
    licenses.mkdir()
    distribution = importlib.metadata.distribution('pyinstaller')
    for entry in distribution.files or []:
        if entry.name in ('COPYING.txt', 'LICENSE', 'LICENSE.txt'):
            shutil.copy2(distribution.locate_file(entry), licenses/('PyInstaller-'+entry.name))
    stdlib_license = Path(sys.base_prefix)/'Resources/English.lproj/Documentation/_sources/license.rst.txt'
    if stdlib_license.exists():
        shutil.copy2(stdlib_license, licenses/'Python-LICENSE.txt')
    (licenses/'说明.txt').write_text('内置 Python 3.14 与 PyInstaller bootloader。PyInstaller 的分发例外允许随应用分发。SQLite 为公有领域。macOS 系统框架由系统提供。Ollama 与 AI 模型不包含在 App 中。\n', encoding='utf-8')
    shutil.copy2(ROOT/'使用说明.md', resources/'使用说明.md')
    (resources/'author-support-integrity.json').write_text(json.dumps({'author': '汪同学', 'github': 'wwwwwwjy', 'assets': support_hashes}, ensure_ascii=False, indent=2)+'\n')
    run(['codesign', '--force', '--sign', '-', '--timestamp=none', APP])
    run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', APP])
    # Check every Mach-O payload: no ARM-only dependency may hide in a universal app.
    binaries = []
    for candidate in APP.rglob('*'):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        with candidate.open('rb') as handle:
            magic = handle.read(4)
        if magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
            architectures = subprocess.check_output(['lipo', '-archs', str(candidate)], text=True).split()
            if not {'arm64', 'x86_64'} <= set(architectures):
                raise RuntimeError('非通用组件：'+str(candidate))
            binaries.append(str(candidate.relative_to(APP)))
    archive = DIST/('SpaceLens-'+VERSION+'-universal.zip')
    if archive.exists():
        archive.unlink()
    run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', APP, archive])
    report = {'app': APP.name, 'version': VERSION, 'minimum_macos': MINIMUM,
              'architectures': ['arm64','x86_64'], 'universal_binaries_checked': len(binaries),
              'pyinstaller': importlib.metadata.version('pyinstaller'), 'python': platform.python_version(),
              'signing': 'ad-hoc; not notarized', 'archive_bytes': archive.stat().st_size}
    (DIST/'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
