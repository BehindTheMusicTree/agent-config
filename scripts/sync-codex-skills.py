#!/usr/bin/env python3
"""Reconcile managed Codex skill links with a versioned agent-config checkout."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

STATE = '.agent-config-skills.json'


class DesiredSkills(dict):
    def __init__(self, links, owners, sources):
        super().__init__(links)
        self.owners = owners
        self.sources = sorted(sources)


def plan(source, destination, adopt_from=None):
    return plan_sources({'default': source}, destination, adopt_from, legacy=True)


def plan_sources(sources, destination, adopt_from=None, *, legacy=False, remove_sources=()):
    destination = destination.resolve()
    desired = {}
    owners = {}
    if not sources:
        raise ValueError('No skill sources specified')
    for owner, source in sources.items():
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', owner):
            raise ValueError(f'Invalid source name: {owner}')
        skills = source.resolve() / 'skills'
        if not skills.is_dir():
            raise ValueError(f'Missing skills directory: {skills}')
        for item in sorted(skills.iterdir()):
            if item.is_dir() and (item / 'SKILL.md').is_file():
                if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', item.name):
                    raise ValueError(f'Invalid skill name: {item.name}')
                if item.name in desired:
                    raise ValueError(f'Skill collision: {item.name} in {owners[item.name]} and {owner}')
                desired[item.name] = str(item.resolve())
                owners[item.name] = owner
    if not desired:
        raise ValueError('Refusing to synchronize an empty skills directory')
    state_file = destination / STATE
    if state_file.is_symlink():
        raise ValueError(f'Refusing symlinked state file: {state_file}')
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding='utf-8'))
        if state.get('version') not in (1, 2) or not isinstance(state.get('links'), dict):
            raise ValueError('Invalid managed skill state')
        previous = state['links']
        if state['version'] == 1 and remove_sources:
            raise ValueError('Migrate legacy skill state before removing sources')
        if state['version'] == 2:
            old_owners = state.get('owners')
            old_sources = state.get('sources')
            if (not isinstance(old_owners, dict) or set(old_owners) != set(previous)
                    or not isinstance(old_sources, list) or len(old_sources) != len(set(old_sources))
                    or any(not isinstance(owner, str) or owner not in old_sources for owner in old_owners.values())):
                raise ValueError('Invalid managed skill ownership state')
            if legacy:
                raise ValueError('Multi-source skills require the multi-source synchronizer')
            removed = set(remove_sources)
            if removed & set(sources) or removed - set(old_sources):
                raise ValueError('Invalid sources selected for removal')
            missing = set(old_sources) - set(sources) - removed
            if missing:
                raise ValueError(f'Missing managed sources; explicitly remove them: {sorted(missing)}')
            for skill in set(old_owners) & set(owners):
                if old_owners[skill] != owners[skill] and old_owners[skill] not in removed:
                    raise ValueError(f'Skill ownership changed without removing source: {skill}')
    else:
        previous = {}
        if remove_sources:
            raise ValueError('Cannot remove sources without managed state')
    if adopt_from is not None:
        legacy_checkout = Path(adopt_from).resolve()
        if not (legacy_checkout / '.git').exists() or not (legacy_checkout / 'skills').is_dir():
            raise ValueError(f'Not an agent-config checkout: {legacy_checkout}')
        if destination.is_dir():
            for entry in destination.iterdir():
                if not entry.is_symlink() or entry.name in previous:
                    continue
                if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', entry.name):
                    continue
                target = os.readlink(entry)
                if not os.path.isabs(target):
                    continue
                if Path(target).resolve() == (legacy_checkout / 'skills' / entry.name).resolve():
                    previous[entry.name] = target
    changes = []
    for name in sorted(set(previous) | set(desired)):

        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            raise ValueError(f'Invalid managed skill name: {name}')
        link = destination / name
        current = os.readlink(link) if link.is_symlink() else None
        if link.exists() and current is None:
            raise ValueError(f'Refusing to replace existing entry: {link}')
        recorded = previous.get(name)
        if recorded is not None and current != recorded:
            raise ValueError(f'Managed link was modified or removed: {link}')
        target = desired.get(name)
        if recorded is None and current is not None and current != target:
            raise ValueError(f'Refusing to replace unmanaged link: {link}')
        if current != target:
            changes.append((link, current, target))
    return (desired if legacy else DesiredSkills(desired, owners, sources)), changes


def replace_link(link, target):
    if target is None:
        link.unlink(missing_ok=True)
        return
    fd, temporary = tempfile.mkstemp(prefix='.agent-skill-', dir=link.parent)
    os.close(fd)
    Path(temporary).unlink()
    try:
        os.symlink(target, temporary)
        os.replace(temporary, link)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply(destination, desired, changes):
    destination.mkdir(parents=True, exist_ok=True)
    applied = []
    try:
        for link, old, new in changes:
            actual = os.readlink(link) if link.is_symlink() else None
            if actual != old or (link.exists() and not link.is_symlink()):
                raise ValueError(f'Entry changed since preflight: {link}')
            replace_link(link, new)
            applied.append((link, old))
        fd, temporary = tempfile.mkstemp(prefix='.agent-state-', dir=destination)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                state = {'version': 1, 'links': desired}
                if isinstance(desired, DesiredSkills):
                    state = {'version': 2, 'links': desired, 'owners': desired.owners, 'sources': desired.sources}
                json.dump(state, stream, indent=2)
                stream.write('\n')
            os.replace(temporary, destination / STATE)
        finally:
            Path(temporary).unlink(missing_ok=True)
    except (OSError, ValueError):
        for link, old in reversed(applied):
            replace_link(link, old)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-name', help='stable identifier for the primary source')
    parser.add_argument('--extra-source', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--remove-source', action='append', default=[], metavar='NAME')
    parser.add_argument('--destination', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'skills')
    parser.add_argument('--adopt-from', type=Path, help='migrate links created from this legacy checkout')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    try:
        if args.source_name:
            sources = {args.source_name: args.source.expanduser()}
            for item in args.extra_source:
                if '=' not in item:
                    raise ValueError('Expected --extra-source NAME=PATH')
                name, path = item.split('=', 1)
                if not name or not path or name in sources:
                    raise ValueError(f'Invalid or duplicate source: {name}')
                sources[name] = Path(path).expanduser()
            desired, changes = plan_sources(sources, destination, args.adopt_from, remove_sources=args.remove_source)
        elif args.extra_source or args.remove_source:
            raise ValueError('--source-name is required when managing multiple sources')
        else:
            desired, changes = plan(args.source, destination, args.adopt_from)
        for link, old, new in changes:
            print(f'{link}: {old or "(absent)"} -> {new or "(remove)"}')
        if args.apply:
            apply(destination, desired, changes)
            print(f'Synchronized {len(desired)} skills')
        elif not changes:
            print('No link changes')
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
