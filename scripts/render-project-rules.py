#!/usr/bin/env python3
"""Generate project Claude rules from scoped sources, protecting local edits."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def render(root, apply):
    manifest = root / '.agents' / 'generated-rules.json'
    scope_file = root / '.agents' / 'scopes.json'
    if manifest.is_symlink() or scope_file.is_symlink():
        raise ValueError('Manifest and scope file must be regular files')
    entries = json.loads(scope_file.read_text())
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    if not isinstance(entries, dict) or not isinstance(previous, dict):
        raise ValueError('Scopes and manifest must be objects')
    directory = root / '.claude' / 'rules'
    if any(path.is_symlink() for path in (root / '.agents', root / '.claude', directory)):
        raise ValueError('Project adapter directories must not be symlinks')
    outputs = {}
    for name, entry in entries.items():
        if (not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name)
                or not isinstance(entry, dict) or set(entry) != {'source', 'paths'}
                or not isinstance(entry['source'], str) or not isinstance(entry['paths'], list)
                or not entry['paths'] or not all(isinstance(p, str) and p for p in entry['paths'])):
            raise ValueError(f'Invalid scope: {name}')
        relative = Path(entry['source'])
        source = root / relative
        if relative.is_absolute() or '..' in relative.parts or not source.resolve().is_relative_to(root) or not source.is_file():
            raise ValueError(f'Invalid source: {name}')
        content = '---\npaths:\n' + ''.join(f'  - {json.dumps(p)}\n' for p in entry['paths']) + '---\n\n' + source.read_text()
        outputs[name] = content.encode()
    if set(previous) - set(outputs):
        raise ValueError('Removed scopes have managed outputs; remove them and update the manifest explicitly')
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in outputs.items()}
    changed = []
    for name, content in outputs.items():
        path = directory / f'{name}.md'
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f'Invalid output: {path}')
        current = path.read_bytes() if path.exists() else None
        if current != content:
            changed.append(path)
            if apply and current is not None and hashlib.sha256(current).hexdigest() != previous.get(name):
                raise ValueError(f'Unmanaged or modified output: {path}')
    manifest_content = (json.dumps(hashes, indent=2, sort_keys=True) + '\n').encode()
    if not manifest.exists() or manifest.read_bytes() != manifest_content:
        changed.append(manifest)
    if apply:
        originals = {path: path.read_bytes() if path.exists() else None for path in changed}
        written = []
        try:
            for path in changed:
                path.parent.mkdir(parents=True, exist_ok=True)
                written.append(path)
                path.write_bytes(manifest_content if path == manifest else outputs[path.stem])
        except OSError as exc:
            failures = []
            for path in reversed(written):
                try:
                    if originals[path] is None:
                        path.unlink(missing_ok=True)
                    elif path.read_bytes() != originals[path]:
                        path.write_bytes(originals[path])
                except OSError as error:
                    failures.append(f'{path}: {error}')
            if failures:
                raise OSError(f'{exc}; rollback failed: {"; ".join(failures)}') from exc
            raise
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        changed = render(args.project.resolve(strict=True), args.apply)
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if changed:
        print('\n'.join(str(path) for path in changed))
    return int(bool(changed) and not args.apply)


if __name__ == '__main__':
    raise SystemExit(main())
