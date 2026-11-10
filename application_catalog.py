"""Recognise installed applications from their public bundle metadata."""
from functools import lru_cache
from pathlib import Path
import plistlib
import re
import os
import time
from xml.parsers.expat import ExpatError


def normalized(value):
    return re.sub(r'[\W_]+', '', value.casefold())


class ApplicationCatalog:
    def __init__(self, roots, components=False):
        self.identifiers, self.names, self.apps, self.errors = {}, {}, [], []
        self.component_ids = set()
        for root in roots:
            self._visit(Path(root), 0)
        if components:
            deadline = time.monotonic() + 5
            for app in self.apps:
                self._components(Path(app['path'])/'Contents', deadline)

    def _components(self, contents, deadline):
        stack = [(contents, 0)]
        count = 0
        while stack:
            if time.monotonic() > deadline or count >= 15000:
                self.errors.append(str(contents))
                break
            folder, depth = stack.pop()
            if depth > 8 or folder.is_symlink():
                continue
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        count += 1
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            # App data doesn't belong in Resources for identity discovery.
                            if entry.name not in {'Resources', '_CodeSignature', 'node_modules'}:
                                stack.append((Path(entry.path), depth+1))
                        elif entry.name == 'Info.plist' and entry.stat().st_size < 2_000_000:
                            try:
                                with open(entry.path, 'rb') as handle:
                                    info = plistlib.load(handle)
                                bid = info.get('CFBundleIdentifier') if isinstance(info, dict) else None
                                if isinstance(bid, str):
                                    self.component_ids.add(bid.casefold())
                            except (OSError, ValueError, ExpatError):
                                pass
            except OSError:
                self.errors.append(str(folder))

    def _visit(self, root, depth):
        if depth > 2 or root.is_symlink():
            return
        try:
            for entry in root.iterdir():
                if entry.is_symlink() or not entry.is_dir():
                    continue
                if entry.suffix.lower() == '.app':
                    self._read(entry)
                elif not entry.name.startswith('.'):
                    self._visit(entry, depth + 1)
        except OSError as exc:
            if root.exists():
                self.errors.append(str(root))

    def _read(self, app):
        try:
            info_path = app / 'Contents' / 'Info.plist'
            if info_path.stat().st_size > 2_000_000:
                return
            with info_path.open('rb') as handle:
                info = plistlib.load(handle)
            if not isinstance(info, dict):
                return
            name = info.get('CFBundleDisplayName') or info.get('CFBundleName') or app.stem
            if not isinstance(name, str):
                return
            name = name[:100]
            identifier = info.get('CFBundleIdentifier', '')
            if isinstance(identifier, str) and identifier:
                self.identifiers[identifier.casefold()] = name
                self.apps.append({'path': str(app), 'name': name, 'identifier': identifier,
                                  'aliases': list(dict.fromkeys([app.stem, name])),
                                  'version': str(info.get('CFBundleShortVersionString', ''))[:80]})
            for alias in (app.stem, name):
                key = normalized(alias)
                if len(key) >= 3:
                    self.names[key] = name
        except (OSError, ValueError, plistlib.InvalidFileException, TypeError, ExpatError):
            self.errors.append(str(app))

    def owner(self, path, home):
        try:
            relative = path.relative_to(home)
        except ValueError:
            return None
        parts = relative.parts
        # Avoid claiming arbitrary user folders belong to an app with a similar name.
        if not parts or parts[0] != 'Library':
            return None
        for segment in parts[1:]:
            key = segment.casefold()
            if key in self.identifiers:
                return self.identifiers[key]
            if normalized(segment) in self.names:
                return self.names[normalized(segment)]
            candidate = key
            while candidate.count('.') >= 2:
                candidate = candidate.rsplit('.', 1)[0]
                if candidate in self.identifiers:
                    return self.identifiers[candidate]
        return None


@lru_cache(maxsize=8)
def catalog_for(home):
    return ApplicationCatalog((Path('/Applications'), home / 'Applications'))


def application_owner(path, home):
    return catalog_for(home).owner(path, home)
