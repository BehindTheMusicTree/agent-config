#!/usr/bin/env python3
"""Check the portable project adapter without changing project files."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


FORBIDDEN_FILES = {'copilot-instructions.md', '.cursorrules', '.windsurfrules', '.clinerules', 'GEMINI.md'}
FORBIDDEN_DIRS = (('.github', 'instructions'), ('.cursor', 'rules'), ('.windsurf', 'rules'))
SKIPPED = {'.git', 'node_modules'}


def project_files(root):
    """Tracked files when root is a git repository, otherwise every file outside .git and node_modules."""
    if (root / '.git').exists():
        result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return sorted(Path(name) for name in result.stdout.split('\0') if name and (root / name).exists())
    return sorted(p.relative_to(root) for p in root.rglob('*')
                  if not SKIPPED.intersection(p.relative_to(root).parts) and (p.is_file() or p.is_symlink()))


def check_nested(root):
    errors = []
    files = project_files(root)
    for relative in files:
        parent = relative.parent
        if parent == Path('.'):
            continue
        if relative.name == 'CLAUDE.md':
            claude, agents = root / relative, root / parent / 'AGENTS.md'
            if claude.is_symlink() or claude.read_text().strip() != '@AGENTS.md':
                errors.append(f'{relative}: CLAUDE.md must contain only @AGENTS.md')
            if not agents.is_file() or agents.is_symlink():
                errors.append(f'{parent / "AGENTS.md"}: AGENTS.md must be a regular file next to {relative}')
        elif relative.name == 'AGENTS.md':
            claude = root / parent / 'CLAUDE.md'
            if not claude.is_file() or claude.is_symlink():
                errors.append(f'{parent / "CLAUDE.md"}: CLAUDE.md must import {relative}')
    for relative in files:
        parts = relative.parts
        if relative.name in FORBIDDEN_FILES or any(
                parts[i:i + len(d)] == d and len(parts) > i + len(d) for d in FORBIDDEN_DIRS for i in range(len(parts))):
            errors.append(f'{relative}: client-specific instruction files are forbidden; use AGENTS.md and .agents/')
    return errors


def check(root):
    errors = check_nested(root)
    agents = root / 'AGENTS.md'
    claude = root / 'CLAUDE.md'
    if not agents.is_file() or agents.is_symlink():
        errors.append('AGENTS.md must be a regular file')
    if not claude.is_file() or claude.is_symlink():
        errors.append('CLAUDE.md must be a regular file importing AGENTS.md')
    elif claude.read_text().strip() != '@AGENTS.md':
        errors.append('CLAUDE.md must contain only @AGENTS.md')

    scopes = root / '.agents' / 'scopes.json'
    if scopes.exists():
        try:
            entries = json.loads(scopes.read_text())
            if not isinstance(entries, dict):
                raise ValueError('scopes must be an object')
            for name, entry in entries.items():
                if (not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name)
                        or not isinstance(entry, dict) or set(entry) != {'source', 'paths'}
                        or not isinstance(entry['source'], str) or not isinstance(entry['paths'], list)
                        or not entry['paths'] or not all(isinstance(p, str) and p for p in entry['paths'])):
                    raise ValueError(f'invalid scope: {name}')
                relative = Path(entry['source'])
                rule = root / relative
                if relative.is_absolute() or '..' in relative.parts or not rule.resolve().is_relative_to(root) or not rule.is_file():
                    raise ValueError(f'invalid rule source: {name}')
                routing = agents.read_text() if agents.is_file() else ''
                if not any(entry['source'] in line and all(
                        re.search(r'(?<![\w./*?\[\]-])' + re.escape(path) + r'(?![\w./*?\[\]-])', line)
                        for path in entry['paths'])
                           for line in routing.splitlines()):
                    errors.append(f'{name}: AGENTS.md must reference source and scope paths')
                adapter = root / '.claude' / 'rules' / f'{name}.md'
                expected = '---\npaths:\n' + ''.join(f'  - {json.dumps(path)}\n' for path in entry['paths']) + '---\n\n' + rule.read_text()
                if not adapter.is_file() or adapter.read_text() != expected:
                    errors.append(f'{name}: Claude scoped rule differs from source')
            for adapter in (root / '.claude' / 'rules').glob('*.md'):
                if adapter.stem not in entries:
                    errors.append(f'{adapter.name}: Claude scoped rule has no source')
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f'invalid scopes: {exc}')
    elif any((root / '.claude' / 'rules').glob('*.md')):
        errors.append('Claude scoped rules exist without .agents/scopes.json')

    source = root / '.agents' / 'skills'
    target = root / '.claude' / 'skills'
    if source.is_symlink() or target.is_symlink():
        errors.append('Skill roots must not be symlinks')
        return errors
    for directory in (source, target):
        if directory.exists() and not directory.is_dir():
            errors.append(f'{directory}: skill root must be a directory')
    skills = {p.name for p in source.iterdir() if p.is_dir()} if source.is_dir() else set()
    links = {p.name for p in target.iterdir()} if target.is_dir() else set()
    for name in sorted(skills | links):
        skill = source / name
        link = target / name
        if name not in skills or skill.is_symlink() or not (skill / 'SKILL.md').is_file():
            errors.append(f'{name}: missing regular skill source')
        if not link.is_symlink() or link.readlink() != Path('../../.agents/skills') / name:
            errors.append(f'{name}: expected relative Claude skill link')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    if not root.is_dir():
        parser.error('project must be a directory')
    errors = check(root)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Project agent adapters match their sources')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
