import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from actions import TrashManager
from app_management import AppManager


class AppManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name).resolve()
        self.home=self.base/'home';self.home.mkdir()
        self.root=self.base/'Applications';self.root.mkdir()
        self.actions=TrashManager(self.home,self.base/'state')
        self.commands=''
        self.manager=AppManager(self.actions,self.home,self.base/'state',roots=[self.root],process_reader=lambda:self.commands)
        self.app=self.make_app('Example Editor','org.example.editor')
        self.cache=self.data('Caches/org.example.editor/data')
        self.prefs=self.data('Preferences/org.example.editor.plist')
        self.keep=self.data('Application Support/Example Editor/user-work')
        self.similar=self.data('Caches/org.example.editor2/data')

    def tearDown(self):
        self.temp.cleanup()

    def make_app(self,name,bid,parent=None):
        p=(parent or self.root)/(name+'.app')
        (p/'Contents').mkdir(parents=True)
        (p/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':name,'CFBundleIdentifier':bid}))
        (p/'Contents/executable').write_text('owned fixture, not executable')
        return p

    def data(self,path):
        p=self.home/'Library'/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('owned fixture');return p

    def preview(self):
        row=next(x for x in self.manager.refresh()['items'] if x['path']==str(self.app))
        return self.manager.preview_uninstall(row['id'])

    def uninstall(self):
        plan=self.preview()
        return self.manager.uninstall(plan['ticket'], 'Example Editor')

    def test_two_stage_uninstall_residual_manual_selection_restore(self):
        plan=self.preview()
        self.assertTrue(self.app.exists())
        with self.assertRaises(ValueError):self.manager.uninstall(plan['ticket'],'wrong name')
        with self.assertRaises(ValueError):self.actions.commit(plan['ticket'], True)
        result=self.manager.uninstall(plan['ticket'],'Example Editor')
        self.assertFalse(self.app.exists());self.assertTrue(self.cache.exists());self.assertTrue(self.prefs.exists())
        found=self.manager.leftovers(result['target']['id'])
        rows={x['path']:x for x in found['items']}
        self.assertTrue(rows[str(self.cache.parent)]['deletable'])
        self.assertTrue(rows[str(self.prefs)]['deletable'])
        self.assertTrue(rows[str(self.keep.parent)]['deletable'])
        self.assertTrue(rows[str(self.keep.parent)]['needs_ownership_confirmation'])
        self.assertNotIn(str(self.similar.parent),rows)
        selected=rows[str(self.cache.parent)]['id']
        with self.assertRaises(ValueError):self.actions.preview([selected], 'delete')
        ticket=self.actions.preview([selected])
        moved=self.actions.commit(ticket['ticket'],True)
        self.assertFalse(self.cache.exists());self.assertTrue(self.prefs.exists());self.assertTrue(self.keep.exists());self.assertTrue(self.similar.exists())
        self.actions.undo(moved['moved'][0]['id']);self.assertTrue(self.cache.exists())
        self.actions.undo(result['moved'][0]['id']);self.assertTrue(self.app.exists())
        self.assertNotIn('org.example.editor', {x['identifier'] for x in self.manager.orphan_targets()['items']})

    def test_uninstall_and_reinstall_or_duplicate_blocks_residual_delete(self):
        result=self.uninstall()
        found=self.manager.leftovers(result['target']['id'])
        candidate=next(x for x in found['items'] if x['path']==str(self.cache.parent))
        ticket=self.actions.preview([candidate['id']])
        self.make_app('Other Version','org.example.editor')
        with self.assertRaises(ValueError):self.actions.commit(ticket['ticket'],True)
        self.assertTrue(self.cache.exists())

    def test_app_identity_and_running_process_revalidated_at_confirmation(self):
        plan=self.preview();self.commands=str(self.app)+'/Contents/executable'
        with self.assertRaises(ValueError):self.manager.uninstall(plan['ticket'],'Example Editor')
        self.commands=''
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.somebody.else'}))
        with self.assertRaises(ValueError):self.manager.uninstall(plan['ticket'],'Example Editor')
        self.assertTrue(self.app.exists())

    def test_orphan_candidate_needs_manual_identity_confirmation(self):
        orphan=self.data('Caches/org.former.tool/data')
        target=next(x for x in self.manager.orphan_targets()['items'] if x['identifier']=='org.former.tool')
        before=self.manager.leftovers(target['id'])
        self.assertTrue(before['target']['needs_confirmation'])
        self.assertTrue(all(not x['deletable'] for x in before['items']))
        after=self.manager.leftovers(target['id'], True)
        row=next(x for x in after['items'] if x['path']==str(orphan.parent))
        self.assertTrue(row['deletable']);self.assertTrue(orphan.exists())
        self.assertTrue(self.cache.exists())
        self.assertNotIn('org.example.editor',{x['identifier'] for x in self.manager.orphan_targets()['items']})

    def test_symlink_shared_directory_and_user_projects_not_deleted(self):
        project=self.home/'Documents/Example Editor/valuable.txt';project.parent.mkdir(parents=True);project.write_text('keep')
        link=self.home/'Library/Application Support/org.example.editor';link.symlink_to(project.parent,target_is_directory=True)
        group=self.data('Group Containers/TEAM.org.example.editor/database')
        result=self.uninstall();found=self.manager.leftovers(result['target']['id'])
        bypath={x['path']:x for x in found['items']}
        self.assertFalse(bypath[str(link)]['deletable'])
        self.assertFalse(bypath[str(group.parent)]['deletable'])
        self.assertNotIn(str(project.parent),bypath)
        self.assertTrue(project.exists());self.assertTrue(group.exists())

    def test_embedded_helper_does_not_become_orphan_and_general_actions_stay_protected(self):
        self.make_app('Helper','org.unrelated.helper', self.app/'Contents/Library/LoginItems')
        self.data('Caches/org.unrelated.helper/data')
        self.assertNotIn('org.unrelated.helper',{x['identifier'] for x in self.manager.orphan_targets()['items']})
        general=self.actions.expose({'path':str(self.app),'bytes':100,'incomplete':0})
        self.assertFalse(general['deletable'])
        general_prefs=self.actions.expose({'path':str(self.prefs),'bytes':100,'incomplete':0})
        self.assertFalse(general_prefs['deletable'])

    def test_scoped_preview_cannot_override_changed_path(self):
        result=self.uninstall();found=self.manager.leftovers(result['target']['id'])
        row=next(x for x in found['items'] if x['path']==str(self.cache.parent))
        ticket=self.actions.preview([row['id']])
        original=self.cache.parent;original.rename(original.with_name('moved'))
        original.symlink_to(self.keep.parent,target_is_directory=True)
        with self.assertRaises(ValueError):self.actions.commit(ticket['ticket'],True)
        self.assertTrue(self.keep.exists())

    def test_software_inventory_does_not_scan_disk_or_residuals(self):
        with patch('app_management.ApplicationCatalog._components', side_effect=AssertionError('No helper walk for app list')), \
             patch.object(self.manager, '_candidates', side_effect=AssertionError('No residue search for app list')), \
             patch('storage.Inventory.start', side_effect=AssertionError('No full scan')):
            rows = self.manager.refresh()['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['path'], str(self.app))

    def test_named_residual_needs_ownership_ack_and_trashes_full_directory(self):
        result=self.uninstall();found=self.manager.leftovers(result['target']['id'])
        row=next(x for x in found['items'] if x['path']==str(self.keep.parent))
        plan=self.manager.preview_residuals([row['id']])
        self.assertTrue(plan['needs_ownership_confirmation'])
        self.assertEqual(plan['ownership_paths'],[str(self.keep.parent)])
        with self.assertRaises(ValueError):self.actions.commit(plan['ticket'],True)
        with self.assertRaises(ValueError):self.manager.clean_residuals(plan['ticket'],True)
        self.assertTrue(self.keep.exists())
        moved=self.manager.clean_residuals(plan['ticket'],True,True)
        self.assertEqual(len(moved['moved']),1);self.assertFalse(self.keep.parent.exists())
        self.assertTrue(self.cache.exists());self.assertTrue(self.similar.exists())
        self.actions.undo(moved['moved'][0]['id']);self.assertTrue(self.keep.exists())

    def test_ryujinx_support_and_logs_are_selectable_and_all_removed_after_confirmation(self):
        app=self.make_app('Ryujinx','org.ryujinx.Ryujinx')
        save=self.data('Application Support/Ryujinx/bis/save/owned-fixture')
        log=self.data('Logs/Ryujinx/owned.log')
        row=next(x for x in self.manager.refresh()['items'] if x['path']==str(app))
        plan=self.manager.preview_uninstall(row['id'])
        result=self.manager.uninstall(plan['ticket'],'Ryujinx')
        found=self.manager.leftovers(result['target']['id'])
        self.assertEqual(len(found['items']),2)
        self.assertTrue(all(x['deletable'] and not x['needs_ownership_confirmation'] for x in found['items']))
        support=next(x for x in found['items'] if 'Application Support' in x['path'])
        self.assertIn('存档',support['impact'])
        plan=self.manager.preview_residuals([x['id'] for x in found['items']])
        with self.assertRaises(ValueError):self.manager.clean_residuals(plan['ticket'])
        self.assertTrue(save.exists());self.assertTrue(log.exists())
        moved=self.manager.clean_residuals(plan['ticket'],True)
        self.assertEqual(len(moved['moved']),2);self.assertFalse(save.exists());self.assertFalse(log.exists())
        self.assertEqual(self.manager.leftovers(result['target']['id'])['items'],[])
        for entry in moved['moved']:self.actions.undo(entry['id'])
        self.assertTrue(save.exists());self.assertTrue(log.exists())

    def test_name_collision_blocks_old_ticket_if_another_app_is_installed(self):
        result=self.uninstall();found=self.manager.leftovers(result['target']['id'])
        row=next(x for x in found['items'] if x['path']==str(self.keep.parent))
        plan=self.manager.preview_residuals([row['id']])
        self.make_app('Example Editor','org.different.app')
        with self.assertRaisesRegex(ValueError,'共用'):self.manager.clean_residuals(plan['ticket'],True,True)
        self.assertTrue(self.keep.exists())
        fresh=self.manager.leftovers(result['target']['id'])
        self.assertFalse(next(x for x in fresh['items'] if x['path']==str(self.keep.parent))['deletable'])

    def test_vendor_directory_cannot_be_unlocked_by_name_confirmation(self):
        vendor=self.data('Application Support/Adobe/keep')
        result=self.uninstall()
        self.manager.targets[result['target']['id']]['aliases'].append('Adobe')
        found=self.manager.leftovers(result['target']['id'])
        row=next(x for x in found['items'] if x['path']==str(vendor.parent))
        self.assertFalse(row['deletable']);self.assertIsNone(row['id'])
        self.assertTrue(vendor.exists())

    def test_partial_size_does_not_block_whole_directory_trash(self):
        result=self.uninstall()
        with patch('app_management.measure',return_value=(1,True)):
            found=self.manager.leftovers(result['target']['id'])
        row=next(x for x in found['items'] if x['path']==str(self.cache.parent))
        self.assertTrue(row['deletable']);self.assertTrue(row['size_partial']);self.assertIn('整个目录',row['size_note'])
        plan=self.manager.preview_residuals([row['id']])
        moved=self.manager.clean_residuals(plan['ticket'],True)
        self.assertFalse(self.cache.exists());self.assertEqual(len(moved['moved']),1)
        self.actions.undo(moved['moved'][0]['id']);self.assertTrue(self.cache.exists())

    def test_no_system_self_or_invalid_bundle_uninstall(self):
        self.make_app('System','com.apple.fake')
        self.make_app('Space Lens','local.spacelens.diskmanager')
        self.make_app('Bad','../invalid')
        rows=self.manager.refresh()['items']
        for row in rows:
            if row['path']!=str(self.app):
                self.assertTrue(row['blocked'])
                with self.assertRaises(ValueError):self.manager.preview_uninstall(row['id'])


if __name__=='__main__':unittest.main()
