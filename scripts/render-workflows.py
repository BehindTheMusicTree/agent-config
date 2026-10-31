#!/usr/bin/env python3
"""Render shared workflow blocks into Claude commands and Codex skills."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def render(root, apply):
    sources = root / 'workflows'
    if not sources.is_dir():
        raise ValueError('Missing workflows directory')
    files = sorted(sources.glob('*.json'))
    if not files:
        raise ValueError('No workflow sources')
    names = {file.stem for file in files}
    commands = {file.stem for file in (root / 'commands').glob('*.md')}
    skills = {file.parent.name for file in (root / 'skills').glob('*/SKILL.md')}
    if commands - names or skills - names:
        raise ValueError('Commands or skills have no workflow source')
    manifest = root / '.workflow-generated.json'
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError('Invalid workflow manifest')
    errors = []
    outputs = {}
    for file in files:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', file.stem):
            raise ValueError(f'Invalid workflow name: {file.name}')
        data = json.loads(file.read_text())
        if set(data) != {'blocks'} or not isinstance(data['blocks'], list) or not data['blocks']:
            raise ValueError(f'Invalid workflow source: {file}')
        claude, codex = [], []
        for block in data['blocks']:
            if not isinstance(block, dict):
                raise ValueError(f'Invalid block: {file}')
            if set(block) == {'shared'} and isinstance(block['shared'], str):
                claude.append(block['shared'])
                codex.append(block['shared'])
            elif set(block) == {'claude', 'codex'} and all(isinstance(x, str) for x in block.values()):
                claude.append(block['claude'])
                codex.append(block['codex'])
            else:
                raise ValueError(f'Invalid block: {file}')
        outputs[root / 'commands' / (file.stem + '.md')] = ''.join(claude)
        outputs[root / 'skills' / file.stem / 'SKILL.md'] = ''.join(codex)
    for path, content in outputs.items():
        if (path.is_symlink() or (path.exists() and not path.is_file())
                or any(parent.is_symlink() for parent in path.parents if parent != root.parent)):
            raise ValueError(f'Invalid output: {path}')
        if not path.is_file() or path.read_text() != content:
            errors.append(str(path))
    hashes = {str(path.relative_to(root)): hashlib.sha256(content.encode()).hexdigest()
              for path, content in outputs.items()}
    manifest_content = json.dumps(hashes, indent=2, sort_keys=True) + '\n'
    if manifest.is_symlink():
        raise ValueError(f'Invalid manifest: {manifest}')
    if not manifest.is_file() or manifest.read_text() != manifest_content:
        errors.append(str(manifest))
    if apply:
        for path in outputs:
            if str(path) in errors and path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if previous.get(str(path.relative_to(root))) != digest:
                    raise ValueError(f'Unmanaged or modified output: {path}')
        outputs[manifest] = manifest_content
        originals = {path: path.read_bytes() if path.exists() else None for path in outputs if str(path) in errors}
        written = []
        try:
            for path in originals:
                path.parent.mkdir(parents=True, exist_ok=True)
                written.append(path)
                path.write_text(outputs[path])
        except OSError as exc:
            failures = []
            for path in reversed(written):
                try:
                    if originals[path] is None:
                        path.unlink(missing_ok=True)
                    elif path.read_bytes() != originals[path]:
                        path.write_bytes(originals[path])
                except OSError as rollback_error:
                    failures.append(f'{path}: {rollback_error}')
            if failures:
                raise OSError(f'{exc}; rollback failed: {"; ".join(failures)}') from exc
            raise
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        changed = render(args.root.resolve(), args.apply)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if changed:
        print('\n'.join(changed))
    if changed and not args.apply:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
