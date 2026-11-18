#!/usr/bin/env python3
"""Merge managed Claude Code permission rules from release fragments into ~/.claude/settings.json.

A source may ship settings/permissions.json: {"allow": [], "ask": [], "deny": [], "retire": []}.
Managed rules are tracked in ~/.claude/agent-config-permissions.json so a rule removed from a
fragment disappears on the next synchronization, while rules the user added are never touched.
"retire" lists stale rules to delete from any list, whether or not they were ever managed.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
LISTS = ('allow', 'ask', 'deny')
FRAGMENT = 'settings/permissions.json'
STATE = 'agent-config-permissions.json'


def load_fragment(root):
    """Return the validated fragment of a source, or None when it ships none."""
    path = root / FRAGMENT
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) - {*LISTS, 'retire'}:
        raise ValueError(f'{path}: expected an object with only {", ".join((*LISTS, "retire"))}')
    fragment = {}
    for key in (*LISTS, 'retire'):
        rules = data.get(key, [])
        if not isinstance(rules, list) or not all(isinstance(r, str) and r.strip() and r == r.strip() for r in rules):
            raise ValueError(f'{path}: {key} must be a list of non-empty strings without surrounding whitespace')
        if len(set(rules)) != len(rules):
            raise ValueError(f'{path}: duplicate rule in {key}')
        fragment[key] = rules
    return fragment


def merge_fragments(roots):
    """Combine fragments, failing on a rule declared twice or in two lists, or retired while managed."""
    desired = {key: [] for key in LISTS}
    retire = []
    owner = {}
    for root in roots:
        fragment = load_fragment(root)
        if fragment is None:
            continue
        for key in LISTS:
            for rule in fragment[key]:
                if rule in owner:
                    raise ValueError(f'Rule {rule!r} is declared in {owner[rule]} and in {key} ({root})')
                owner[rule] = key
                desired[key].append(rule)
        retire.extend(r for r in fragment['retire'] if r not in retire)
    clash = sorted(set(retire) & set(owner))
    if clash:
        raise ValueError(f'Rules both managed and retired: {clash}')
    return desired, retire


def read_json(path, what):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ValueError(f'{path}: invalid JSON ({error})') from error
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected a JSON object for {what}')
    return data


def read_state(path):
    state = read_json(path, 'managed permissions')
    if state is None:
        return {key: [] for key in LISTS}
    if state.get('version') != 1 or any(
            not isinstance(state.get(key), list) or not all(isinstance(r, str) for r in state[key]) for key in LISTS):
        raise ValueError(f'{path}: unsupported managed permissions state')
    return {key: state[key] for key in LISTS}


def snapshot(path):
    if not path.exists():
        return None
    return {'text': path.read_text(encoding='utf-8'), 'mode': path.stat().st_mode & 0o777}


def dump(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def prepare(claude_home, roots):
    """Return (path, before, after) snapshots compatible with install-instructions.apply()."""
    desired, retire = merge_fragments(roots)
    settings_path = claude_home / 'settings.json'
    state_path = claude_home / STATE
    for path in (settings_path, state_path):
        if path.is_symlink():
            raise ValueError(f'Refusing to edit symlinked Claude file: {path}')
    previous = read_state(state_path)
    if not any(desired.values()) and not any(previous.values()) and not retire:
        return []
    settings = read_json(settings_path, 'Claude settings') or {}
    permissions = settings.get('permissions', {})
    if not isinstance(permissions, dict):
        raise ValueError(f'{settings_path}: "permissions" must be an object')
    for key in LISTS:
        current = permissions.get(key, [])
        if not isinstance(current, list) or not all(isinstance(r, str) for r in current):
            raise ValueError(f'{settings_path}: permissions.{key} must be a list of strings')
        kept = [r for r in current if r not in retire and (r not in previous[key] or r in desired[key])]
        merged = kept + [r for r in desired[key] if r not in kept]
        if merged != current:
            permissions[key] = merged
        elif key in permissions:
            permissions[key] = current
    new_settings = {**settings, 'permissions': permissions} if permissions else settings
    new_state = {'version': 1, **desired}
    changes = []
    before_settings = snapshot(settings_path)
    if before_settings is None or json.loads(before_settings['text']) != new_settings:
        changes.append((settings_path, before_settings,
                        {'text': dump(new_settings), 'mode': before_settings['mode'] if before_settings else 0o600}))
    before_state = snapshot(state_path)
    if before_state is None or json.loads(before_state['text']) != new_state:
        if before_state is not None or any(desired.values()):
            changes.append((state_path, before_state,
                            {'text': dump(new_state), 'mode': before_state['mode'] if before_state else 0o600}))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--claude-home', type=Path,
                        default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')))
    parser.add_argument('--source', type=Path, action='append', default=None, help='release root (default: this repo)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='write the merged permissions')
    mode.add_argument('--check', action='store_true', help='exit nonzero when settings differ')
    args = parser.parse_args()
    roots = [p.expanduser().resolve() for p in (args.source or [ROOT])]
    changes = prepare(args.claude_home.expanduser().resolve(), roots)
    if not changes:
        print('Up to date: managed Claude permissions')
        return 0
    if args.apply:
        import importlib.util
        spec = importlib.util.spec_from_file_location('global_instructions', ROOT / 'scripts/install-instructions.py')
        instructions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(instructions)
        instructions.apply(changes)
        print(f'Updated {", ".join(str(path) for path, _, _ in changes)}')
        return 0
    print(f'Out of date: {", ".join(str(path) for path, _, _ in changes)}')
    return 1 if args.check else 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
