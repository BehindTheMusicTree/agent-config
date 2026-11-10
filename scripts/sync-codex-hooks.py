#!/usr/bin/env python3
"""Install the graphify freshness hook into the Codex hooks file.

Codex has no plugin hooks, so the hook shipped for Claude (scripts/graphify-fresh.sh) is registered in
$CODEX_HOME/hooks.json with --client codex. Exactly one managed PreToolUse entry is maintained and found
again through the script name; every other hook is left untouched.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SCRIPT = 'scripts/graphify-fresh.sh'
EVENT = 'PreToolUse'
MATCHER = 'Bash'
TIMEOUT = 5


def command_for(root):
    return f'{shlex.quote(str((root / SCRIPT).resolve()))} --client codex'


def is_managed(handler):
    if not isinstance(handler, dict) or not isinstance(handler.get('command'), str):
        return False
    try:
        words = shlex.split(handler['command'])
    except ValueError:
        return False
    return bool(words) and words[0].endswith('/' + SCRIPT)


def managed_entry(root):
    return {'matcher': MATCHER, 'hooks': [{'type': 'command', 'command': command_for(root), 'timeout': TIMEOUT}]}


def merge(data, root, path='hooks.json'):
    """Return data with a single managed entry, replacing an existing one in place."""
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected a JSON object')
    hooks = data.get('hooks', {})
    entries = hooks.get(EVENT, []) if isinstance(hooks, dict) else None
    if not isinstance(hooks, dict) or not isinstance(entries, list):
        raise ValueError(f'{path}: "hooks" must be an object whose {EVENT} value is a list')
    merged = []
    placed = False
    for entry in entries:
        handlers = entry.get('hooks') if isinstance(entry, dict) else None
        if not isinstance(handlers, list):
            merged.append(entry)
            continue
        kept = [handler for handler in handlers if not is_managed(handler)]
        if len(kept) == len(handlers):
            merged.append(entry)
            continue
        if not placed:
            merged.append(managed_entry(root))
            placed = True
        if kept:
            merged.append({**entry, 'hooks': kept})
    if not placed:
        merged.append(managed_entry(root))
    return {**data, 'hooks': {**hooks, EVENT: merged}}


def prepare(codex_home, root=ROOT):
    """Return (path, before, after) snapshots compatible with install-instructions.apply()."""
    if not (root / SCRIPT).is_file():
        raise ValueError(f'Missing graphify freshness hook: {root / SCRIPT}')
    path = codex_home / 'hooks.json'
    if path.is_symlink() or not path.resolve().is_relative_to(codex_home.resolve()):
        raise ValueError(f'Refusing to edit symlinked or external Codex hooks file: {path}')
    before = {'text': path.read_text(encoding='utf-8'), 'mode': path.stat().st_mode & 0o777} if path.exists() else None
    try:
        current = json.loads(before['text']) if before else {}
    except json.JSONDecodeError as error:
        raise ValueError(f'{path}: invalid JSON, fix it by hand ({error})') from error
    merged = merge(current, root, path)
    if merged == current:
        return []
    after = {'text': json.dumps(merged, indent=2) + '\n', 'mode': before['mode'] if before else 0o600}
    return [(path, before, after)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='write the managed hook entry')
    mode.add_argument('--check', action='store_true', help='exit nonzero if the managed hook entry is missing or stale')
    args = parser.parse_args()
    changes = prepare(args.codex_home.expanduser().resolve())
    if not changes:
        print('Up to date: graphify freshness hook is installed for Codex')
        return 0
    path = changes[0][0]
    if args.apply:
        spec = importlib.util.spec_from_file_location('global_instructions', ROOT / 'scripts/install-instructions.py')
        instructions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(instructions)
        instructions.apply(changes)
        print(f'Updated {path}. Restart Codex, then trust the hook once in /hooks.')
        return 0
    print(f'Out of date: {path}')
    return 1 if args.check else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
