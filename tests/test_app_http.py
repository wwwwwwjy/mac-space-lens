import json
from pathlib import Path
import plistlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from actions import TrashManager
from app_management import AppManager
from local_ai import LocalAI
from server import LocalServer, make_handler
from storage import Inventory


class AppHTTPTests(unittest.TestCase):
    def test_http_uninstall_then_residual_confirmation_and_no_generic_bypass(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();home=base/'home';home.mkdir();root=base/'Applications';root.mkdir()
            app=root/'Fixture.app';(app/'Contents').mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'Fixture','CFBundleIdentifier':'org.fixture.editor'}))
            cache=home/'Library/Caches/org.fixture.editor/keep-until-confirmed';cache.parent.mkdir(parents=True);cache.write_text('temporary fixture')
            named=home/'Library/Application Support/Fixture/keep-until-ownership-confirmed';named.parent.mkdir(parents=True);named.write_text('temporary named fixture')
            inv=Inventory(state=base/'scan',roots=[home],home=home);actions=TrashManager(home,base/'state');apps=AppManager(actions,home,base/'state',roots=[root],process_reader=lambda:'')
            server=LocalServer(('127.0.0.1',0),make_handler(inv,actions,'test-token',ai=LocalAI(base/'state',home),apps=apps))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            endpoint='http://127.0.0.1:'+str(server.server_port)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(path,data=None,token='test-token'):
                body=None if data is None else json.dumps(data).encode()
                req=urllib.request.Request(endpoint+'/api/'+path,data=body,headers={'X-Local-Token':token,'Content-Type':'application/json'})
                try:
                    with opener.open(req,timeout=10) as result:return result.status,json.load(result)
                except urllib.error.HTTPError as err:return err.code,json.load(err)
            try:
                code,items=request('apps');self.assertEqual(code,200)
                ident=items['items'][0]['id']
                self.assertEqual(request('apps/preview',{'id':ident},token='wrong')[0],401)
                code,plan=request('apps/preview',{'id':ident});self.assertEqual(code,200)
                self.assertEqual(request('trash',{'ticket':plan['ticket'],'caution_ack':True})[0],400)
                self.assertTrue(app.exists());self.assertTrue(cache.exists())
                code,done=request('apps/uninstall',{'ticket':plan['ticket'],'confirm_name':'Fixture'})
                self.assertEqual(code,200);self.assertEqual(len(done['moved']),1);self.assertTrue(cache.exists())
                code,leftovers=request('apps/leftovers',{'id':done['target']['id']});self.assertEqual(code,200)
                residual=next(x for x in leftovers['items'] if x['path']==str(cache.parent))
                self.assertTrue(residual['deletable'])
                self.assertEqual(request('preview',{'ids':[residual['id']],'operation':'delete'})[0],400)
                self.assertEqual(request('preview',{'ids':[residual['id']],'operation':'trash'})[0],400)
                code,preview=request('apps/residual-preview',{'ids':[residual['id']]});self.assertEqual(code,200)
                self.assertEqual(request('trash',{'ticket':preview['ticket'],'caution_ack':False})[0],400)
                self.assertTrue(cache.exists())
                self.assertEqual(request('trash',{'ticket':preview['ticket'],'caution_ack':True})[0],400)
                code,moved=request('apps/residual-trash',{'ticket':preview['ticket'],'caution_ack':True});self.assertEqual(code,200);self.assertFalse(cache.exists())
                self.assertEqual(request('undo',{'id':moved['moved'][0]['id']})[0],200);self.assertTrue(cache.exists())
                candidate=next(x for x in leftovers['items'] if x['path']==str(named.parent))
                self.assertTrue(candidate['deletable']);self.assertTrue(candidate['needs_ownership_confirmation'])
                code,preview=request('apps/residual-preview',{'ids':[candidate['id']]});self.assertEqual(code,200)
                self.assertTrue(preview['needs_ownership_confirmation'])
                self.assertEqual(request('apps/residual-trash',{'ticket':preview['ticket'],'caution_ack':True})[0],400)
                self.assertTrue(named.exists())
                code,moved=request('apps/residual-trash',{'ticket':preview['ticket'],'caution_ack':True,'ownership_ack':True})
                self.assertEqual(code,200);self.assertFalse(named.exists())
                self.assertEqual(request('undo',{'id':moved['moved'][0]['id']})[0],200);self.assertTrue(named.exists())
                self.assertEqual(request('undo',{'id':done['moved'][0]['id']})[0],200);self.assertTrue(app.exists())
                self.assertEqual(request('apps/preview',{'id':[]})[0],400)
            finally:server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
