"""Finder-supplied app icons and display names; cached in memory for this session."""
import base64
import json
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent


class AppPresentation:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def apply(self, apps):
        helper = ROOT/'bin/space-lens-app-info'
        if not helper.is_file():
            helper = ROOT/'.build/native/space-lens-app-info'
        if not helper.is_file():
            return [dict(a, icon=None) for a in apps]
        with self.lock:
            now = time.monotonic()
            known = {a['path'] for a in apps}
            self.cache = {k: v for k, v in self.cache.items() if k in known and now-v['time'] < 180}
            missing = [a['path'] for a in apps if a['path'] not in self.cache]
            # Bound each native request; returned paths must be from our catalogue.
            for offset in range(0, len(missing), 128):
                batch = missing[offset:offset+128]
                try:
                    result = subprocess.run([str(helper)], input=json.dumps(batch), capture_output=True,
                                            text=True, timeout=20, check=True)
                    data = json.loads(result.stdout)
                    if not isinstance(data, list):
                        continue
                    for value in data:
                        if not isinstance(value, dict) or value.get('path') not in batch:
                            continue
                        name, icon = value.get('name'), value.get('icon')
                        if not isinstance(name, str) or not name.strip() or len(name) > 200:
                            continue
                        if not isinstance(icon, str) or not icon.startswith('data:image/png;base64,') or len(icon) > 500000:
                            icon = None
                        elif not base64.b64decode(icon.partition(',')[2], validate=True).startswith(b'\x89PNG\r\n\x1a\n'):
                            icon = None
                        self.cache[value['path']] = {'name': name, 'icon': icon, 'time': now}
                except (OSError, subprocess.SubprocessError, ValueError):
                    continue
            rows = []
            for app in apps:
                presentation = self.cache.get(app['path'], {})
                name = presentation.get('name', app['name'])
                rows.append({**app, 'name': name, 'icon': presentation.get('icon'),
                             'aliases': list(dict.fromkeys(app.get('aliases', []) + [name]))})
            return rows
