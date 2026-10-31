#!/usr/bin/env python3
"""Synchronize Codex skills and global instructions from a local release tag."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


releases = load('release_snapshot', 'prepare-release.py')
skills = load('codex_skills', 'sync-codex-skills.py')
instructions = load('global_instructions', 'install-instructions.py')
plugins = load('claude_plugin', 'sync-claude-plugin.py')


def plan_sources(sources, claude_home, codex_home, adopt_from=None, remove_sources=()):
    destination = codex_home / 'skills'
    desired, link_changes = skills.plan_sources(sources, destination, adopt_from, remove_sources=remove_sources)
    override = codex_home / 'AGENTS.override.md'
    if override.is_file() and override.read_text().strip():
        raise ValueError(f'Active override masks generated AGENTS.md: {override}')
    changes = []
    for agent, home in (('claude', claude_home), ('codex', codex_home)):
        changes.extend(instructions.prepare(home, instructions.render_sources(sources, agent)))
    if len({path for path, _, _ in changes}) != len(changes):
        raise ValueError('Agent home directories must be distinct')
    return desired, link_changes, changes


def synchronize_source(source, claude_home, codex_home, adopt_from=None):
    destination = codex_home / 'skills'
    desired, link_changes = skills.plan(source, destination, adopt_from)
    override = codex_home / 'AGENTS.override.md'
    if override.is_file() and override.read_text().strip():
        raise ValueError(f'Active override masks generated AGENTS.md: {override}')
    changes = []
    for agent, home in (('claude', claude_home), ('codex', codex_home)):
        changes.extend(instructions.prepare(home, instructions.render(source, agent)))
    if len({path for path, _, _ in changes}) != len(changes):
        raise ValueError('Agent home directories must be distinct')
    _apply_plan(destination, desired, link_changes, changes,
                lambda: plugins.install(source, claude_home, source.parent.parent / 'marketplaces'))
    return source


def synchronize_sources(sources, claude_home, codex_home, stages, adopt_from=None, remove_sources=()):
    desired, link_changes, changes = plan_sources(sources, claude_home, codex_home, adopt_from, remove_sources)
    prepared = plugins.prepare_sources(sources, stages)
    _apply_plan(codex_home / 'skills', desired, link_changes, changes,
                lambda: plugins.install_sources(prepared, claude_home))
    return sources


def _apply_plan(destination, desired, link_changes, changes, install_plugins):
    state_path = destination / skills.STATE
    old_state = instructions.snapshot(state_path)
    skills.apply(destination, desired, link_changes)
    instructions_applied = False
    try:
        instructions.apply(changes)
        instructions_applied = True
        install_plugins()
    except Exception as error:
        try:
            if instructions_applied:
                instructions.apply([(path, after, before) for path, before, after in reversed(changes)])
            for link, old, new in reversed(link_changes):
                if new is None:
                    if link.is_symlink() or link.exists():
                        raise ValueError(f'Cannot safely roll back changed link: {link}')
                elif not link.is_symlink() or os.readlink(link) != new:
                    raise ValueError(f'Cannot safely roll back changed link: {link}')
                skills.replace_link(link, old)
            instructions.write_snapshot(state_path, old_state)
        except Exception as rollback_error:
            raise RuntimeError(f'Synchronization failed ({error}); local rollback also failed: {rollback_error}') from error
        if instructions_applied:
            raise RuntimeError(f'Claude plugin installation failed; Codex and instructions restored. Claude may need recovery: {error}') from error
        raise


def synchronize(repo, tag, release_dir, claude_home, codex_home, adopt_from=None):
    source = releases.prepare(repo, tag, release_dir)
    return synchronize_source(source, claude_home, codex_home, adopt_from)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--releases', type=Path, default=Path.home() / '.local/share/agent-config/releases')
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')))
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    parser.add_argument('--adopt-from', type=Path)
    args = parser.parse_args()
    try:
        source = synchronize(args.repo.resolve(), args.tag, args.releases.expanduser().resolve(),
                             args.claude_home.expanduser().resolve(), args.codex_home.expanduser().resolve(),
                             args.adopt_from)
    except Exception as error:
        print(f'Synchronization failed: {error}', file=sys.stderr)
        return 1
    print(f'Installed Codex skills and global instructions from {source}')
    print('Restart Codex and reload Claude plugins to activate the release.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
