#!/usr/bin/env python3
"""Derive the Codex auto-compaction threshold from the Claude Code compaction window.

Claude Code compacts at CLAUDE_CODE_AUTO_COMPACT_WINDOW minus an internal reserve, while
Codex compacts when the active context reaches model_auto_compact_token_limit. The reserve
is undocumented, so it lives in settings/compact.json; re-measure it with Claude's /context
("Autocompact buffer") after a Claude Code upgrade.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_KEY = 'CLAUDE_CODE_AUTO_COMPACT_WINDOW'
CODEX_KEY = 'model_auto_compact_token_limit'
CODEX_LINE = re.compile(rf'^{CODEX_KEY}\s*=\s*(\S+)[ \t]*(#.*)?$', re.MULTILINE)
TABLE = re.compile(r'^\s*\[', re.MULTILINE)


def load_reserve(root=ROOT):
    data = json.loads((root / 'settings/compact.json').read_text())
    reserve = data.get('claudeCompactReserveTokens')
    if not isinstance(reserve, int) or isinstance(reserve, bool) or reserve <= 0:
        raise ValueError('settings/compact.json: claudeCompactReserveTokens must be a positive integer')
    return reserve


def claude_window(claude_home):
    """Return the configured Claude compaction window, or None when it is not set."""
    path = claude_home / 'settings.json'
    if not path.is_file():
        return None
    value = json.loads(path.read_text()).get('env', {}).get(CLAUDE_KEY)
    if value is None:
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).isdigit():
        raise ValueError(f'{path}: env.{CLAUDE_KEY} must be a positive integer, got {value!r}')
    return int(value)


def codex_limit(window, reserve):
    limit = window - reserve
    if limit <= 0:
        raise ValueError(f'{CLAUDE_KEY}={window} is not larger than the Claude reserve ({reserve})')
    return limit


def render_codex(text, limit):
    """Set the top-level Codex key in config.toml text, leaving every other line untouched."""
    first_table = TABLE.search(text)
    top_level_end = first_table.start() if first_table else len(text)
    line = f'{CODEX_KEY} = {limit}'
    matches = [m for m in CODEX_LINE.finditer(text) if m.start() < top_level_end]
    if len(matches) > 1:
        raise ValueError(f'Duplicate top-level {CODEX_KEY} in Codex config')
    if matches:
        match = matches[0]
        comment = f' {match.group(2)}' if match.group(2) else ''
        return text[:match.start()] + line + comment + text[match.end():]
    return line + '\n' + text


def prepare(claude_home, codex_home, root=ROOT):
    """Return (path, before, after) snapshots compatible with install-instructions.apply()."""
    window = claude_window(claude_home)
    if window is None:
        return []
    limit = codex_limit(window, load_reserve(root))
    path = codex_home / 'config.toml'
    if path.is_symlink() or not path.resolve().is_relative_to(codex_home.resolve()):
        raise ValueError(f'Refusing to edit symlinked or external Codex config: {path}')
    before = {'text': path.read_text(encoding='utf-8'), 'mode': path.stat().st_mode & 0o777} if path.exists() else None
    after = {'text': render_codex(before['text'] if before else '', limit),
             'mode': before['mode'] if before else 0o600}
    try:
        import tomllib
    except ModuleNotFoundError:
        tomllib = None
    if tomllib and tomllib.loads(after['text']).get(CODEX_KEY) != limit:
        raise ValueError(f'Could not set {CODEX_KEY} in {path}')
    return [] if before == after else [(path, before, after)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')))
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='write the derived Codex threshold')
    mode.add_argument('--check', action='store_true', help='exit nonzero if Codex differs from Claude')
    args = parser.parse_args()
    claude_home = args.claude_home.expanduser().resolve()
    codex_home = args.codex_home.expanduser().resolve()
    window = claude_window(claude_home)
    if window is None:
        print(f'{CLAUDE_KEY} is not set in {claude_home / "settings.json"}; Codex is left unchanged')
        return 0
    reserve = load_reserve()
    summary = f'Claude window {window} - reserve {reserve} = Codex {CODEX_KEY} {codex_limit(window, reserve)}'
    changes = prepare(claude_home, codex_home)
    if not changes:
        print(f'Up to date: {summary}')
        return 0
    path = changes[0][0]
    if args.apply:
        spec = importlib.util.spec_from_file_location('global_instructions', ROOT / 'scripts/install-instructions.py')
        instructions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(instructions)
        instructions.apply(changes)
        print(f'Updated {path}: {summary}. Restart Codex to apply.')
        return 0
    print(f'Out of date: {path} ({summary})')
    return 1 if args.check else 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
