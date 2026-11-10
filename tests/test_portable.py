import json
import plistlib
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from application_catalog import ApplicationCatalog
from lifecycle import Lifecycle
from local_ai import LocalAI, local_endpoint
from storage import Inventory, describe


class PortableTests(unittest.TestCase):
    def test_other_home_and_installed_bundle_identification(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)/'another-person'
            contents = home/'Applications'/'Unknown Editor.app'/'Contents'
            contents.mkdir(parents=True)
            (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.example.editor', 'CFBundleName':'未知剪辑软件'}))
            broken = home/'Applications/Broken.app/Contents'
            broken.mkdir(parents=True)
            (broken/'Info.plist').write_bytes(b'<?xml version="1.0"?><plist>\x00not valid</plist>')
            catalog = ApplicationCatalog([home/'Applications'])
            self.assertEqual(catalog.owner(home/'Library'/'Caches'/'org.example.editor', home), '未知剪辑软件')
            self.assertIsNone(catalog.owner(home/'Documents'/'Unknown Editor', home))
            project = home/'Movies/JianyingPro/User Data/Projects/demo/.backup'
            info = describe(project, True, time.time(), home)
            self.assertEqual(info['risk'], 'caution')
            self.assertIn('历史备份', info['kind'])
            self.assertTrue(info['deletable'])

    def test_scan_cancellation_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root/'home'
            home.mkdir()
            (home/'file').write_text('fixture')
            inv = Inventory(state=root/'state', roots=[home], home=home)
            inv.operation_lock.acquire()
            inv.cancel()
            inv._scan()
            self.assertTrue(inv.progress['cancelled'])
            self.assertFalse(inv.progress['done'])
            self.assertFalse(inv.operation_lock.locked())

    def test_exit_waits_for_file_operation_then_shuts_down(self):
        class FakeInventory:
            operation_lock = threading.Lock()
            cancelled = False
            def cancel(self):
                self.cancelled = True
        class FakeServer:
            stopped = threading.Event()
            def shutdown(self):
                self.stopped.set()
        inv, server = FakeInventory(), FakeServer()
        inv.operation_lock.acquire()
        lifecycle = Lifecycle(inv)
        lifecycle.attach(server)
        lifecycle.request_exit()
        self.assertTrue(inv.cancelled)
        self.assertFalse(server.stopped.wait(.03))
        inv.operation_lock.release()
        self.assertTrue(server.stopped.wait(1))

    def test_ai_endpoint_is_local_and_cannot_redirect_to_cloud(self):
        for bad in ['https://example.com', 'http://192.168.1.8:11434', 'http://127.0.0.1.evil.com',
                    'http://localhost@evil.com', 'http://localhost:11434/a', 'file:///etc/passwd', 'http://localhost:99999']:
            with self.assertRaises(ValueError, msg=bad):
                local_endpoint(bad)
        self.assertEqual(local_endpoint('http://localhost:11434/'), 'http://127.0.0.1:11434')

    def test_exit_does_not_hang_on_read_only_permission_prompt(self):
        class StalledScanner:
            def is_alive(self):
                return True
            def join(self, timeout):
                assert timeout == 2
        class FakeInventory:
            operation_lock = threading.Lock()
            worker = StalledScanner()
            progress = {'running': True}
            def cancel(self):
                pass
        class FakeServer:
            stopped = threading.Event()
            def shutdown(self):
                self.stopped.set()
        inv, server = FakeInventory(), FakeServer()
        inv.operation_lock.acquire()
        try:
            lifecycle = Lifecycle(inv)
            lifecycle.attach(server)
            lifecycle.request_exit()
            self.assertTrue(server.stopped.wait(1))
        finally:
            inv.operation_lock.release()

    def test_ai_metadata_only_local_model_and_no_action(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                response = {'models':[{'name':'fixture:small', 'size':20_000_000}, {'name':'fixture:cloud','size':20_000_000}]}
                raw = json.dumps(response).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(raw)
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'message':{'content':'这是备份，删除会失去恢复能力。'}}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp)/'private-user'
                home.mkdir()
                file = home/'secret.txt'
                file.write_text('PRIVATE CONTENT SHOULD NEVER BE SENT')
                ai = LocalAI(Path(temp)/'settings', home)
                ai.configure('http://127.0.0.1:'+str(server.server_port), 'fixture:small')
                self.assertEqual([x['name'] for x in ai.models()], ['fixture:small'])
                result = ai.explain({'path':str(file), 'kind':'文件', 'bytes':100, 'risk':'caution'})
                self.assertIn('恢复', result['text'])
                payload = json.dumps(captured, ensure_ascii=False)
                self.assertNotIn('PRIVATE CONTENT', payload)
                self.assertNotIn(str(home), payload)
                self.assertIn('~/secret.txt', payload)
                self.assertEqual(captured[0]['keep_alive'], 0)
                self.assertTrue(file.exists())
                self.assertEqual(LocalAI(Path(temp)/'settings', home).settings['model'], 'fixture:small')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
