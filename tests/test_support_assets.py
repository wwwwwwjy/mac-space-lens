import hashlib
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from actions import TrashManager
from server import LocalServer, make_handler
from storage import Inventory
from support_assets import ASSET_ROOT, SUPPORT_ASSETS, read_support_asset, verify_support_assets


class SupportAssetsTests(unittest.TestCase):
    def test_author_images_have_same_square_size_and_verified_bytes(self):
        self.assertEqual(set(SUPPORT_ASSETS), {'/assets/author-alipay.png', '/assets/author-wechat.png'})
        self.assertEqual(len(verify_support_assets()), 2)
        for route, item in SUPPORT_ASSETS.items():
            data, mime = read_support_asset(route)
            self.assertEqual(mime, 'image/png')
            self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(struct.unpack('>II', data[16:24]), (640, 640))
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
        self.assertEqual({p.name for p in ASSET_ROOT.iterdir()}, {a['file'] for a in SUPPORT_ASSETS.values()})

    def test_modified_or_linked_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root/'author-alipay.png'
            file.write_bytes(b'unrelated payment code')
            with patch('support_assets.ASSET_ROOT', root):
                with self.assertRaisesRegex(ValueError, '校验失败'):
                    read_support_asset('/assets/author-alipay.png')
                file.unlink()
                file.symlink_to(ASSET_ROOT/'author-alipay.png')
                with self.assertRaisesRegex(ValueError, '校验失败'):
                    read_support_asset('/assets/author-alipay.png')

    def test_no_arbitrary_asset_path(self):
        for path in ['/assets/../support_assets.py', '/assets/other.png', 'https://untrusted.example/code.png']:
            with self.assertRaises(KeyError):
                read_support_asset(path)

    def test_http_images_are_fixed_and_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            home = base/'home'; home.mkdir()
            inv = Inventory(state=base/'scan', roots=[home], home=home)
            actions = TrashManager(home, base/'state')
            server = LocalServer(('127.0.0.1', 0), make_handler(inv, actions, 'fixture-token'))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            url = 'http://127.0.0.1:'+str(server.server_port)
            try:
                for route in SUPPORT_ASSETS:
                    with opener.open(url+route) as response:
                        self.assertEqual(response.headers['Content-Type'], 'image/png')
                        self.assertEqual(response.read(), read_support_asset(route)[0])
                for route in ['/assets/other.png', '/assets/%2e%2e/server.py']:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        opener.open(url+route)
                    self.assertEqual(caught.exception.code, 404)
                    caught.exception.close()
                request = urllib.request.Request(url+'/api/support', data=b'{"alipay":"https://untrusted.example"}',
                    headers={'Content-Type':'application/json','X-Local-Token':'fixture-'+'token'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    opener.open(request)
                self.assertEqual(caught.exception.code, 404)
                caught.exception.close()
                self.assertFalse(inv.progress['running'])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
