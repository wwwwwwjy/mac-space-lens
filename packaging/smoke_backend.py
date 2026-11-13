"""Exercise the distributed backend with owned fixtures, never existing user files."""
import json
import hashlib
import os
from pathlib import Path
import platform
import socket
import subprocess
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT/'dist/空间磁盘管家.app/Contents/Resources/backend/space-lens-server'


def check(architecture, file_actions=False):
    runtime = Path(tempfile.mkdtemp(prefix='space-lens-')).resolve()
    data = Path(tempfile.mkdtemp(prefix='space-lens-smoke-data-')).resolve()
    fixture_parent = ROOT/'.build'
    fixture = Path(tempfile.mkdtemp(prefix='owned-smoke-fixture-', dir=fixture_parent)).resolve()
    env = dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME'):
        env.pop(key, None)
    env.update(SPACE_LENS_STATE=str(runtime), SPACE_LENS_DATA=str(data), PATH='/usr/bin:/bin')
    command = ['/usr/bin/arch', '-'+architecture, str(BINARY), '--desktop', '--no-browser', '--port', '0', '--parent-pid', str(os.getpid())]
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    port = None
    try:
        line = process.stdout.readline()
        assert line, process.stderr.read()
        url = urllib.parse.urlsplit(json.loads(line)['ready'])
        port = url.port
        base = 'http://'+url.netloc
        def api(route, body=None):
            request = urllib.request.Request(base+'/api/'+route, headers={'X-Local-Token':url.fragment,'Content-Type':'application/json'},
                                             data=None if body is None else json.dumps(body).encode())
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        status = api('status')
        assert status['home'] == str(Path.home())
        assert not status['scan']['running'] and not status['scan']['started'], 'Unexpected startup scan'
        manifest = json.loads((BINARY.parent.parent/'author-support-integrity.json').read_text())
        assert manifest['github'] == 'wwwwwwjy'
        assert set(manifest['assets']) == {'author-alipay.png', 'author-wechat.png'}
        for filename, digest in manifest['assets'].items():
            with urllib.request.urlopen(base+'/assets/'+filename, timeout=10) as response:
                assert response.headers['Content-Type'] == 'image/png'
                assert hashlib.sha256(response.read()).hexdigest() == digest, 'Packaged receipt differs'
        apps = api('apps')
        assert apps['items'], 'Missing software inventory'
        assert any(x.get('icon', '').startswith('data:image/png;base64,') for x in apps['items'] if x.get('icon')), 'No native app icons'
        after_apps = api('status')
        assert not after_apps['scan']['running'] and not after_apps['scan']['started'], 'App list triggered a disk scan'
        assert api('ai/settings')['endpoint'] == 'http://127.0.0.1:11434'
        if file_actions:
            first, second = fixture/'trash-and-restore.txt', fixture/'permanent-fixture.txt'
            first.write_text('Owned fixture: only this file may be moved.')
            second.write_text('Owned fixture: only this file may be deleted.')
            rows = api('browse?path='+urllib.parse.quote(str(fixture)))['items']
            by_name = {r['name']:r for r in rows}
            plan = api('preview', {'ids':[by_name[first.name]['id']], 'operation':'trash'})
            moved = api('trash', {'ticket':plan['ticket'], 'caution_ack':True})
            assert len(moved['moved'])==1, moved
            assert not first.exists()
            api('undo', {'id':moved['moved'][0]['id']})
            assert first.read_text().startswith('Owned fixture')
            plan = api('preview', {'ids':[by_name[second.name]['id']], 'operation':'delete'})
            deleted = api('delete', {'ticket':plan['ticket'],'confirm_text':'永久删除','caution_ack':True})
            assert len(deleted['deleted'])==1, deleted
            assert not second.exists()
            rows = api('browse?path='+urllib.parse.quote(str(fixture)))['items']
            assert all(r['name']!=second.name for r in rows)
            first.unlink()
        api('quit', {})
        process.wait(timeout=10)
        assert process.returncode==0, process.stderr.read()
        assert not runtime.exists(), 'Runtime directory remains'
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1',port)) != 0, 'Listener remains'
        print(architecture+': packaged runtime, API, quit, listener and temp cleanup PASS'+('; native trash, restore and permanent delete PASS' if file_actions else ''))
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        # Only owned, explicitly named fixture/state trees are removed.
        import shutil
        for directory in (runtime, data, fixture):
            shutil.rmtree(directory, ignore_errors=True)


if __name__=='__main__':
    check(platform.machine())
    if platform.machine() == 'arm64':
        check('x86_64')
