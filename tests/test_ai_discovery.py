import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from local_ai import LocalAI


class DiscoveryTests(unittest.TestCase):
    def test_clients_do_not_imply_local_api_and_connect_rechecks_models(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();root=base/'Applications';root.mkdir()
            for name,bid in [('ChatGPT','com.openai.chat'),('Claude','com.anthropic.claudefordesktop'),('豆包','com.example.doubao'),('Codex','com.openai.codex')]:
                p=root/(name+'.app')/'Contents';p.mkdir(parents=True)
                (p/'Info.plist').write_bytes(plistlib.dumps({'CFBundleName':name,'CFBundleIdentifier':bid}))
            ai=LocalAI(base/'state',base)
            def response(endpoint,route,data=None,timeout=4):
                if route=='/api/tags':return {'models':[{'name':'deepseek-r1:8b','size':4_000_000_000},{'name':'some:cloud','size':2_000_000_000}]}
                return {'data':[{'id':'qwen-small','type':'llm','compatibility_type':'gguf'}, {'id':'remote','type':'llm','compatibility_type':'remote'}, {'id':'embed','type':'embeddings','compatibility_type':'gguf'}]}
            ai.request=response
            found=ai.discover([root])
            self.assertEqual({c['name'] for c in found['clients'] if c['installed']},{'ChatGPT','Claude','豆包','Codex'})
            self.assertTrue(all(not c['local_engine'] for c in found['clients'] if c['installed']))
            ollama=next(s for s in found['services'] if s['provider']=='ollama')
            lm=next(s for s in found['services'] if s['provider']=='lmstudio')
            self.assertEqual([m['name'] for m in lm['models']],['qwen-small'])
            with self.assertRaises(ValueError):ai.connect(ollama['id'],'some:cloud')
            self.assertEqual(ai.settings['model'],'')
            settings=ai.connect(lm['id'],'qwen-small')
            self.assertEqual(settings['provider'],'lmstudio')
            self.assertEqual(LocalAI(base/'state',base).settings['provider'],'lmstudio')
            ai.request=lambda *args,**kwargs:{'data':[]}
            with self.assertRaises(ValueError):ai.connect(lm['id'],'qwen-small')

    def test_lmstudio_metadata_prompt_is_not_a_file_action(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();data=base/'private.txt';data.write_text('SECRET CONTENT')
            ai=LocalAI(base/'state',base);ai.configure('http://localhost:1234','local-model','lmstudio')
            captured=[]
            def response(endpoint,route,payload=None,timeout=4):
                if payload is None:return {'data':[{'id':'local-model','type':'llm','compatibility_type':'mlx'}]}
                captured.append(payload)
                return {'choices':[{'message':{'content':'请保留归属不明的数据，在 Finder 核对。'}}]}
            ai.request=response
            result=ai.explain({'path':str(data),'risk':'protected','basis':'shared evidence','name':'private.txt'})
            self.assertIn('保留',result['text']);self.assertTrue(data.exists())
            request=json.dumps(captured,ensure_ascii=False)
            self.assertNotIn('SECRET CONTENT',request);self.assertNotIn(str(base),request)
            self.assertIn('~/private.txt',request);self.assertIn('shared evidence',request)
            self.assertNotIn('tools',captured[0]);self.assertNotIn('tool_choice',captured[0])

    def test_wrong_provider_redirect_or_remote_cannot_be_auto_connected(self):
        with tempfile.TemporaryDirectory() as temp:
            ai=LocalAI(Path(temp),Path(temp))
            with self.assertRaises(ValueError):ai.configure('http://127.0.0.1:1234','x','claude-client')
            with self.assertRaises(ValueError):ai.configure('https://cloud.example.com','x','ollama')
            with self.assertRaises(ValueError):ai.connect('not-discovered','x')


if __name__=='__main__':unittest.main()
