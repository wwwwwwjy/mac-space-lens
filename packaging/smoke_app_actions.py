"""Native Trash smoke for a fabricated application inside this project's build tree."""
import json
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import actions
from app_management import AppManager
from storage import HOME


def main():
    fixture=Path(tempfile.mkdtemp(prefix='.space-lens-owned-app-smoke-',dir=ROOT.parent)).resolve()
    manager=None
    try:
        # All inputs live under our newly-created fixture, not real application/data paths.
        app=fixture/'Applications/Smoke Fixture.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'Smoke Fixture','CFBundleIdentifier':'org.spacelens.smokefixture'}))
        (app/'Contents/payload').write_text('Only an owned fixture; not a real app')
        home=fixture/'fixture-home';home.mkdir()
        cache=home/'Library/Caches/org.spacelens.smokefixture/data';cache.parent.mkdir(parents=True);cache.write_text('Owned fixture residual')
        prefs=home/'Library/Preferences/org.spacelens.smokefixture.plist';prefs.parent.mkdir(parents=True);prefs.write_bytes(plistlib.dumps({'fixture':True}))
        actions.NATIVE_HELPER=ROOT/'dist/空间磁盘管家.app/Contents/Resources/backend/_internal/bin/space-lens-trash'
        assert actions.NATIVE_HELPER.exists()
        manager=actions.TrashManager(HOME, fixture/'state')
        apps=AppManager(manager,home,fixture/'state',roots=[fixture/'Applications'],process_reader=lambda:'')
        chosen=apps.refresh()['items'][0]
        plan=apps.preview_uninstall(chosen['id'])
        result=apps.uninstall(plan['ticket'],'Smoke Fixture')
        assert len(result['moved'])==1,result
        assert not app.exists() and cache.exists() and prefs.exists()
        residuals=apps.leftovers(result['target']['id'])['items']
        ids=[x['id'] for x in residuals if x['deletable']]
        assert len(ids)==2,residuals
        plan=manager.preview(ids)
        cleaned=manager.commit(plan['ticket'],True)
        assert len(cleaned['moved'])==2,cleaned
        assert not cache.exists() and not prefs.exists()
        for move in cleaned['moved']:manager.undo(move['id'])
        manager.undo(result['moved'][0]['id'])
        assert cache.exists() and prefs.exists() and app.exists()
        assert all(entry['status']=='restored' for entry in manager.journal)
        print('PASS: fabricated app native Trash, automatic residual discovery, selected cache/preferences Trash, all three items restored; no real apps touched.')
    finally:
        if manager:
            for entry in manager.journal:
                if entry['status'] in {'trashed','pending'}:
                    manager.undo(entry['id'])
        shutil.rmtree(fixture)


if __name__=='__main__':main()
