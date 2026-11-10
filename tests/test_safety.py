import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from actions import TrashManager
from server import LocalServer, make_handler
from storage import Inventory, describe


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.state = self.base / 'state'
        self.manager = TrashManager(self.home, self.state)

    def tearDown(self):
        self.temp.cleanup()

    def expose(self, path):
        return self.manager.expose(dict(path=str(path), bytes=path.stat().st_blocks*512, incomplete=0))

    def file(self, name='sample.txt'):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture, not user data')
        return path

    def test_move_undo_no_overwrite_and_single_use_ticket(self):
        p = self.file()
        item = self.expose(p)
        plan = self.manager.preview([item['id']])
        with self.assertRaises(ValueError):
            self.manager.commit(plan['ticket'])
        result = self.manager.commit(plan['ticket'], True)
        self.assertEqual(len(result['moved']), 1)
        self.assertFalse(p.exists())
        ident = result['moved'][0]['id']
        p.write_text('new file')
        with self.assertRaises(FileExistsError):
            self.manager.undo(ident)
        self.assertEqual(p.read_text(), 'new file')
        p.unlink()  # Only this test-created fixture.
        self.manager.undo(ident)
        self.assertEqual(p.read_text(), 'fixture, not user data')
        with self.assertRaises(ValueError):
            self.manager.commit(plan['ticket'], True)

    def test_parent_child_deduplicated(self):
        p = self.file('folder/data')
        a, b = self.expose(p.parent), self.expose(p)
        plan = self.manager.preview([a['id'], b['id']])
        self.assertEqual(len(plan['items']), 1)
        self.assertEqual(plan['items'][0]['path'], str(p.parent))

    def test_permanent_delete_requires_own_ticket_and_exact_confirmation(self):
        p = self.file()
        item = self.expose(p)
        trash_plan = self.manager.preview([item['id']])
        with self.assertRaises(ValueError):
            self.manager.delete(trash_plan['ticket'], '永久删除', True)
        plan = self.manager.preview([item['id']], 'delete')
        with self.assertRaises(ValueError):
            self.manager.commit(plan['ticket'], True)
        for text in ['', '删除', '永久删除 ']:
            with self.assertRaises(ValueError):
                self.manager.delete(plan['ticket'], text, True)
        with self.assertRaises(ValueError):
            self.manager.delete(plan['ticket'], '永久删除', False)
        self.assertTrue(p.exists())
        result = self.manager.delete(plan['ticket'], '永久删除', True)
        self.assertEqual(len(result['deleted']), 1)
        self.assertFalse(p.exists())
        self.assertFalse(self.manager.trash.exists())
        self.assertEqual(self.manager.journal[-1]['status'], 'deleted')
        with self.assertRaises(ValueError):
            self.manager.undo(result['deleted'][0]['id'])
        with self.assertRaises(ValueError):
            self.manager.delete(plan['ticket'], '永久删除', True)

    def test_permanent_directory_delete_does_not_follow_symlink(self):
        p = self.file('selected/inside/data')
        kept = self.file('keep/data')
        (p.parent/'external-link').symlink_to(kept.parent)
        root = self.home/'selected'
        plan = self.manager.preview([self.expose(root)['id']], 'delete')
        result = self.manager.delete(plan['ticket'], '永久删除', True)
        self.assertEqual(len(result['deleted']), 1)
        self.assertFalse(root.exists())
        self.assertTrue(kept.exists())

    def test_permanent_delete_detects_changed_file(self):
        p = self.file()
        plan = self.manager.preview([self.expose(p)['id']], 'delete')
        p.write_text('content changed after confirmation preview')
        with self.assertRaises(ValueError):
            self.manager.delete(plan['ticket'], '永久删除', True)
        self.assertTrue(p.exists())

    def test_permanent_endpoint_confirmation(self):
        p = self.file()
        item = self.expose(p)
        inv = Inventory(self.state/'scan', [self.home], self.home)
        auth = 'test-confirmation'
        server = LocalServer(('127.0.0.1', 0), make_handler(inv, self.manager, auth))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:'+str(server.server_port)+'/api/'
        def post(endpoint, body):
            req = urllib.request.Request(base+endpoint, data=json.dumps(body).encode(),
                                         headers={'X-Local-Token': auth, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        try:
            plan = post('preview', {'ids':[item['id']], 'operation':'delete'})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                post('delete', {'ticket':plan['ticket'], 'caution_ack':True})
            self.assertEqual(cm.exception.code, 400)
            cm.exception.close()
            self.assertTrue(p.exists())
            result = post('delete', {'ticket':plan['ticket'], 'confirm_text':'永久删除', 'caution_ack':True})
            self.assertEqual(len(result['deleted']), 1)
            self.assertFalse(p.exists())
        finally:
            server.shutdown()
            server.server_close()

    def test_changed_file_rejected(self):
        p = self.file()
        item = self.expose(p)
        plan = self.manager.preview([item['id']])
        p.write_text('changed contents with another length')
        with self.assertRaises(ValueError):
            self.manager.commit(plan['ticket'], True)
        self.assertTrue(p.exists())

    def test_symlinks_and_protected_paths(self):
        p = self.file('folder/file')
        link = self.home / 'link'
        link.symlink_to(p.parent)
        self.assertIsNone(self.expose(link / 'file')['id'])
        self.assertIsNone(self.expose(self.home)['id'])
        key = self.file('.ssh/id_ed25519')
        self.assertIsNone(self.expose(key)['id'])
        cloud = self.file('Library/CloudStorage/Drive/item')
        self.assertIsNone(self.expose(cloud)['id'])
        self.assertNotEqual(describe(self.home/'.cache/codex-runtimes/python', True, time.time(), self.home)['risk'], 'recommended')

    def test_parent_replaced_by_symlink_after_preview(self):
        p = self.file('folder/file')
        item = self.expose(p)
        plan = self.manager.preview([item['id']])
        p.parent.rename(self.home/'original')
        (self.home/'folder').symlink_to(self.home/'original')
        with self.assertRaises(ValueError):
            self.manager.commit(plan['ticket'], True)
        self.assertTrue((self.home/'original/file').exists())

    def test_scan_skips_symlinks_and_counts_hardlink_once(self):
        p = self.file('a')
        os.link(p, self.home/'b')
        outside = self.base/'outside'
        outside.mkdir()
        (outside/'data').write_bytes(b'x'*8192)
        (self.home/'link').symlink_to(outside)
        inv = Inventory(self.state/'scan', [self.home], self.home)
        inv.start()
        for _ in range(100):
            if not inv.progress['running']:
                break
            time.sleep(.02)
        self.assertTrue(inv.progress['done'])
        self.assertEqual(inv.roots_data()[0]['bytes'], self.home.stat().st_blocks*512+p.stat().st_blocks*512)
        with self.assertRaises(ValueError):
            inv.browse(self.home/'link')
        with self.assertRaises(ValueError):
            inv.browse(self.base)

    def test_http_auth_and_cross_site_blocked(self):
        inv = Inventory(self.state/'scan', [self.home], self.home)
        auth = 'fixture-only'
        server = LocalServer(('127.0.0.1', 0), make_handler(inv, self.manager, auth))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:'+str(server.server_port)+'/api/status'
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(url)
            self.assertEqual(cm.exception.code, 401)
            cm.exception.close()
            req = urllib.request.Request(url, headers={'X-Local-Token':auth,'Origin':'https://untrusted.example'})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()
            req = urllib.request.Request(url, headers={'X-Local-Token':auth})
            with urllib.request.urlopen(req) as response:
                self.assertIn('disk', json.load(response))
            req = urllib.request.Request(url, headers={'X-Local-Token':auth,'Host':'untrusted.example'})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
