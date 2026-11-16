#!/usr/bin/env python3
"""Manage Claude Code's project-relative plan directory without overwriting user choices."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
KEY = 'plansDirectory'
VALUE = '.agent-plans'


def prepare(claude_home):
    """Return snapshots compatible with install-instructions.apply()."""
    path = claude_home / 'settings.json'
    if path.is_symlink() or not path.resolve().is_relative_to(claude_home.resolve()):
        raise ValueError(f'Refusing to edit symlinked or external Claude settings: {path}')
    before = {'text': path.read_text(encoding='utf-8'), 'mode': path.stat().st_mode & 0o777} if path.exists() else None
    settings = json.loads(before['text']) if before else {}
    if not isinstance(settings, dict):
        raise ValueError(f'{path}: expected a JSON object')
    if KEY in settings:
        if settings[KEY] != VALUE:
            raise ValueError(f'{path}: {KEY} is {settings[KEY]!r}; refusing to overwrite the user value')
        return []
    settings[KEY] = VALUE
    after = {'text': json.dumps(settings, indent=2, ensure_ascii=False) + '\n',
             'mode': before['mode'] if before else 0o600}
    return [(path, before, after)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changes = prepare(args.claude_home.expanduser().resolve())
    if args.apply and changes:
        spec = importlib.util.spec_from_file_location('global_instructions', ROOT / 'scripts/install-instructions.py')
        instructions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(instructions)
        instructions.apply(changes)
    print(f'{KEY}={VALUE}: ' + ('out of date' if changes and not args.apply else 'up to date'))
    return 1 if changes and args.check else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
