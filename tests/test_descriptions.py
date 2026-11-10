import tempfile
import time
import unittest
from pathlib import Path
from storage import describe, Inventory


class ExplanationTests(unittest.TestCase):
    home = Path('/Users/fixture')

    def info(self, relative, directory=True):
        return describe(self.home / relative, directory, time.time(), self.home)

    def test_backup_is_not_generic_disposable_cache(self):
        d = self.info('Movies/JianyingPro/User Data/Projects/com.lveditor.draft/草稿/.backup')
        self.assertEqual(d['risk'], 'caution')
        self.assertIn('历史备份', d['kind'])
        self.assertIn('回退', d['impact'])
        self.assertIn('备份', d['advice'])

    def test_generated_thumbnail_and_source_image_differ(self):
        generated = self.info('Movies/JianyingPro/User Data/Cache/frameThumbnail/thumbnail.png', False)
        source = self.info('Movies/JianyingPro/User Data/Projects/com.lveditor.draft/草稿/Resources/photo.png', False)
        self.assertEqual(generated['risk'], 'review')
        self.assertIn('重新生成', generated['impact'])
        self.assertEqual(source['risk'], 'caution')
        self.assertIn('素材丢失', source['impact'])

    def test_cloud_draft_and_timeline_are_not_cache(self):
        cloud = self.info('Movies/JianyingPro/User Data/Projects/com.lveditor.draft/.cloud_cache_123/草稿')
        timeline = self.info('Movies/JianyingPro/User Data/Projects/com.lveditor.draft/草稿/Timelines')
        self.assertEqual(cloud['risk'], 'caution')
        self.assertIn('同步', cloud['advice'])
        self.assertEqual(timeline['risk'], 'caution')
        self.assertIn('工程打不开', timeline['impact'])

    def test_risk_boundaries_stay_protected(self):
        for path in ['.ssh/id_ed25519', 'Library/CloudStorage/Drive/JianyingPro/Cache/frameThumbnail']:
            d = self.info(path)
            self.assertEqual(d['risk'], 'protected')
            self.assertFalse(d['deletable'])
        model = self.info('.cache/huggingface/models/model.safetensors', False)
        self.assertNotEqual(model['risk'], 'recommended')
        self.assertIn('重新下载', model['advice'])

    def test_unknown_does_not_promise_safe_deletion(self):
        d = self.info('Documents/不认识的文件夹')
        self.assertEqual(d['risk'], 'caution')
        self.assertIn('不能仅凭名称', d['content'])
        self.assertIn('暂不建议', d['advice'])

    def test_davinci_database_and_generated_media(self):
        library = self.info('Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Disk Database')
        cache = self.info('Movies/DaVinci/CacheClip')
        self.assertEqual(library['risk'], 'caution')
        self.assertIn('数据库', library['advice'])
        self.assertEqual(cache['risk'], 'review')

    def test_index_removes_only_completed_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            home = root / 'home'
            home.mkdir()
            deleted = home/'a_%'
            deleted.mkdir()
            (deleted/'file').write_text('test')
            kept = home/'a_%other'
            kept.mkdir()
            inv = Inventory(root/'state', [home], home)
            inv.start()
            for _ in range(100):
                if not inv.progress['running']:
                    break
                time.sleep(.02)
            self.assertTrue(inv.progress['done'])
            inv.record_changes([str(deleted)])
            with inv.db() as db:
                self.assertIsNone(db.execute('SELECT path FROM nodes WHERE path=?',(str(deleted),)).fetchone())
                self.assertIsNotNone(db.execute('SELECT path FROM nodes WHERE path=?',(str(kept),)).fetchone())
            self.assertTrue(inv.progress['needs_rescan'])
            # record_changes edits the index, never the real files.
            self.assertTrue((deleted/'file').exists())
