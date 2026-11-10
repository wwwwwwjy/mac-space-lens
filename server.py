#!/usr/bin/env python3
"""Loopback-only local utility. No uploads, telemetry, external assets or shell commands."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import signal
import sqlite3
import shutil
import subprocess
import threading
import time
import tempfile
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from actions import TrashManager
from storage import APP_DIR, HOME, STATE, DATA_DIR, Inventory
from lifecycle import Lifecycle
from local_ai import LocalAI
from app_management import AppManager


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(inv, actions, token, lifecycle=None, ai=None, apps=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log tokens, private paths or file names.

        def send(self, status, value, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def guard(self, auth=True):
            expected = '127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host') != expected:
                self.send(403, {'error': '仅允许本机地址访问。'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://'+expected:
                self.send(403, {'error': '拒绝跨站请求。'})
                return False
            if auth and not hmac.compare_digest(self.headers.get('X-Local-Token', ''), token):
                self.send(401, {'error': '请从启动器重新打开页面。'})
                return False
            return True

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if not self.guard(url.path.startswith('/api/')):
                return
            try:
                if url.path == '/api/status':
                    disk = shutil.disk_usage('/System/Volumes/Data' if Path('/System/Volumes/Data').exists() else HOME)
                    self.send(200, {'scan': dict(inv.progress), 'disk': dict(total=disk.total, used=disk.used, free=disk.free),
                                    'roots': inv.roots_data(), 'home': str(HOME)})
                elif url.path == '/api/items':
                    q = urllib.parse.parse_qs(url.query)
                    rows = inv.candidates(q.get('risk', ['all'])[0], q.get('q', [''])[0])
                    self.send(200, {'items': [item for x in inv.with_context(rows) if (item := actions.expose(x)) is not None]})
                elif url.path == '/api/browse':
                    q = urllib.parse.parse_qs(url.query)
                    data = inv.browse(Path(q.get('path', [str(HOME)])[0]), max(0, int(q.get('offset', ['0'])[0])))
                    data['items'] = [item for x in inv.with_context(data['items']) if (item := actions.expose(x)) is not None]
                    self.send(200, data)
                elif url.path == '/api/history':
                    self.send(200, {'items': list(reversed(actions.journal))[:200]})
                elif url.path == '/api/ai/settings' and ai:
                    self.send(200, ai.settings)
                elif url.path == '/api/apps' and apps:
                    self.send(200, apps.refresh())
                elif url.path == '/api/apps/orphans' and apps:
                    self.send(200, apps.orphan_targets())
                elif url.path in {'/', '/style.css', '/app.js', '/applications.js'}:
                    name = {'/': 'index.html', '/style.css': 'style.css', '/app.js': 'app.js', '/applications.js': 'applications.js'}[url.path]
                    mime = {'/': 'text/html', '/style.css': 'text/css', '/app.js': 'text/javascript', '/applications.js': 'text/javascript'}[url.path]
                    self.send(200, (APP_DIR / 'web' / name).read_bytes(), mime+'; charset=utf-8')
                else:
                    self.send(404, {'error': '未找到。'})
            except (OSError, ValueError) as exc:
                self.send(400, {'error': friendly_error(exc)})

        def do_POST(self):
            if not self.guard():
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 64000 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('请求格式不正确。')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('请求格式不正确。')
                if lifecycle and lifecycle.closing.is_set():
                    raise ValueError('程序正在退出，当前文件操作完成后会自动关闭。')
                if self.path.startswith('/api/ai/') and ai:
                    if self.path == '/api/ai/settings':
                        result = ai.configure(data.get('endpoint'), data.get('model'), data.get('provider','ollama'))
                    elif self.path == '/api/ai/models':
                        result = {'models': ai.models(data.get('endpoint'), data.get('provider'))}
                    elif self.path == '/api/ai/discover':
                        result = ai.discover()
                    elif self.path == '/api/ai/connect':
                        result = ai.connect(data.get('id'), data.get('model'))
                    elif self.path == '/api/ai/explain':
                        item = actions.explanations.get(data.get('id'))
                        if not item:
                            raise ValueError('文件列表已更新，请重新选择要解释的项目。')
                        result = ai.explain(item)
                    else:
                        raise ValueError('不支持的 AI 操作。')
                    self.send(200, result)
                    return
                if self.path == '/api/scan':
                    inv.start()
                    self.send(200, {'started': True})
                    return
                if self.path == '/api/quit':
                    if lifecycle:
                        self.send(200, {'stopped': True})
                        lifecycle.request_exit()
                        return
                    if inv.progress['running'] or inv.operation_lock.locked():
                        raise ValueError('正在扫描或处理文件，请等待完成后退出。')
                    self.send(200, {'stopped': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                if not inv.operation_lock.acquire(blocking=False):
                    raise ValueError('扫描或清理正在进行，请完成后再操作。')
                try:
                    # Recheck after acquiring the lock: shutdown may have begun
                    # while this request was waiting for the scanner to finish.
                    if lifecycle and lifecycle.closing.is_set():
                        raise ValueError('程序正在退出，未开始新的文件操作。')
                    if self.path == '/api/preview':
                        ids = data.get('ids')
                        if isinstance(ids, list) and any(isinstance(i, str) and actions.items.get(i, {}).get('scope') for i in ids):
                            raise ValueError('软件和残留请通过专用确认窗口清理。')
                        result = actions.preview(data.get('ids'), data.get('operation', 'trash'))
                    elif self.path == '/api/apps/preview' and apps:
                        result = apps.preview_uninstall(data.get('id'))
                    elif self.path == '/api/apps/uninstall' and apps:
                        result = apps.uninstall(data.get('ticket'), data.get('confirm_name'))
                    elif self.path == '/api/apps/leftovers' and apps:
                        result = apps.leftovers(data.get('id'), data.get('confirm_absent') is True)
                    elif self.path == '/api/apps/residual-preview' and apps:
                        result = apps.preview_residuals(data.get('ids'))
                    elif self.path == '/api/apps/residual-trash' and apps:
                        result = apps.clean_residuals(data.get('ticket'), data.get('caution_ack'), data.get('ownership_ack'))
                    elif self.path == '/api/apps/reveal' and apps:
                        item = actions.explanations.get(data.get('id'))
                        if not item or not Path(item['path']).exists():
                            raise ValueError('该项目已不存在，请刷新列表。')
                        subprocess.run(['/usr/bin/open', '-R', item['path']], check=True, timeout=10)
                        result = {'opened': True}
                    elif self.path == '/api/trash':
                        if not isinstance(data.get('ticket'), str):
                            raise ValueError('请先预览并确认。')
                        result = actions.commit(data['ticket'], data.get('caution_ack'))
                    elif self.path == '/api/delete':
                        if not isinstance(data.get('ticket'), str):
                            raise ValueError('请先单独预览并确认直接删除。')
                        result = actions.delete(data['ticket'], data.get('confirm_text'), data.get('caution_ack'))
                    elif self.path == '/api/undo':
                        result = actions.undo(data.get('id'))
                    elif self.path == '/api/reveal':
                        # Only paths from the authorized inventory may be passed to Finder.
                        item = actions.items.get(data.get('id'))
                        if not item:
                            raise ValueError('请刷新列表后重试。')
                        path = actions.validate(item)
                        subprocess.run(['/usr/bin/open', '-R', str(path)], check=True, timeout=10)
                        result = {'opened': True}
                    else:
                        self.send(404, {'error': '未找到。'})
                        return
                    if self.path in {'/api/trash', '/api/delete', '/api/apps/uninstall', '/api/apps/residual-trash'}:
                        completed = result.get('deleted', result.get('moved', []))
                        if completed or result.get('failed'):
                            try:
                                inv.record_changes([item['path'] for item in completed])
                            except (sqlite3.Error, OSError):
                                inv.progress['needs_rescan'] = True
                                result['refresh_warning'] = '文件操作已完成，但列表索引更新失败。请重新扫描。'
                    self.send(200, result)
                finally:
                    inv.operation_lock.release()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.send(400, {'error': friendly_error(exc)})

    return Handler


def friendly_error(exc):
    if isinstance(exc, PermissionError):
        return 'macOS 未允许访问此位置。可在系统设置 → 隐私与安全性 → 文件与文件夹 / 完全磁盘访问权限中检查“空间磁盘管家”（网页版则检查终端），再重启应用。'
    if isinstance(exc, FileExistsError):
        return '原位置已有同名文件，为避免覆盖，未执行撤回。请在 Finder 中手动核对。'
    if isinstance(exc, FileNotFoundError):
        return '文件已移动、已删除，或原文件夹已不存在。请刷新列表 / 在 Finder 中核对。'
    return str(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--resume-session', action='store_true', help='Keep the existing local browser session during an update.')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--parent-pid', type=int, default=0)
    parser.add_argument('--no-auto-scan', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    inv, actions = Inventory(), TrashManager(state=DATA_DIR)
    lifecycle = Lifecycle(inv, args.parent_pid) if args.desktop else None
    ai = LocalAI(DATA_DIR, HOME)
    apps = AppManager(actions, HOME, DATA_DIR)
    token = secrets.token_urlsafe(32)
    if args.resume_session:
        try:
            previous = json.loads((STATE / 'session.json').read_text())
            old_url = urllib.parse.urlsplit(previous['url'])
            if old_url.scheme == 'http' and old_url.hostname == '127.0.0.1' and old_url.port == args.port and 32 <= len(old_url.fragment) <= 128:
                token = old_url.fragment
        except (OSError, ValueError, KeyError, TypeError):
            pass
    handler = make_handler(inv, actions, token, lifecycle, ai, apps)
    try:
        server = LocalServer(('127.0.0.1', args.port), handler)
    except OSError:
        server = LocalServer(('127.0.0.1', 0), handler)
    url = 'http://127.0.0.1:'+str(server.server_port)+'/#'+token
    (STATE / 'session.json').write_text(json.dumps({'url': url, 'pid': os.getpid()}))
    if lifecycle:
        lifecycle.attach(server)
        signal.signal(signal.SIGTERM, lambda *_: lifecycle.request_exit())
        signal.signal(signal.SIGINT, lambda *_: lifecycle.request_exit())
    print(json.dumps({'ready': url}) if args.desktop else '本地磁盘管家已启动：'+url, flush=True)
    # Scanning is started only by an explicit POST /api/scan from the scan button.
    # Keep --no-auto-scan accepted for older launchers; startup is always idle now.
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args.desktop:
            # Only remove a session directory created under this user's temporary directory.
            temp_root = Path(tempfile.gettempdir()).resolve()
            if STATE.parent == temp_root and STATE.name.startswith('space-lens-') and STATE != DATA_DIR:
                shutil.rmtree(STATE, ignore_errors=True)


if __name__ == '__main__':
    main()
