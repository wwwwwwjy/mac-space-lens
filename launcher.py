"""Double-click entry: reuse the local session or start a detached service."""
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from storage import APP_DIR, STATE

os.umask(0o077)
STATE.mkdir(exist_ok=True, mode=0o700)


def live_url():
    try:
        session = json.loads((STATE / 'session.json').read_text())
        u = urllib.parse.urlsplit(session['url'])
        if u.scheme != 'http' or u.hostname != '127.0.0.1' or not u.fragment or not u.port:
            return None
        req = urllib.request.Request('http://'+u.netloc+'/api/status', headers={'X-Local-Token': u.fragment})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.load(response)
        if 'scan' in data and 'disk' in data:
            return session['url']
    except (OSError, ValueError, KeyError):
        return None


def main():
    with open(STATE / 'launcher.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        url = live_url()
        if not url:
            with open(STATE / 'server.log', 'a') as log:
                subprocess.Popen([sys.executable, str(APP_DIR / 'server.py'), '--no-browser']+
                                 (['--resume-session'] if '--resume-session' in sys.argv else []),
                                 cwd=APP_DIR, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=log, start_new_session=True)
            for _ in range(40):
                time.sleep(.3)
                url = live_url()
                if url:
                    break
        if not url:
            print('启动失败，请检查 '+str(STATE / 'server.log'))
            return 1
        if '--no-browser' not in sys.argv:
            webbrowser.open(url)
        print('本地服务已就绪。关闭网页不等于退出；请用页面左下角的“退出本地服务”。')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
