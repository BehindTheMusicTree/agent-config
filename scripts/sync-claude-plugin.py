#!/usr/bin/env python3
"""Install a Claude plugin from a specific prepared agent-config release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def run_claude(home, *args):
    env = os.environ.copy()
    env['CLAUDE_CONFIG_DIR'] = str(home)
    result = subprocess.run(['claude', 'plugin', *args], env=env, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Claude {' '.join(args)} failed: {(result.stderr or result.stdout)[-2000:]}")
    return result.stdout


def tree_digest(directory):
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink in managed marketplace: {path}')
        if path.is_file():
            digest.update(str(path.relative_to(directory)).encode())
            digest.update(b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()



def plugin_files(source):
    return [source / '.claude-plugin/plugin.json', *(source / 'commands').glob('*.md'),
            *(p for p in (source / 'scripts').glob('*') if p.is_file()),
            *(p for p in (source / 'references').rglob('*') if p.is_file())]


def prepare_sources(sources, stages):
    if not sources:
        raise ValueError('No Claude plugin sources specified')
    prepared = {}
    names = set()
    for owner, source in sources.items():
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', owner):
            raise ValueError(f'Invalid source name: {owner}')
        release = json.loads((source / '.agent-config-release.json').read_text())
        commit = release['commit']
        manifest = json.loads((source / '.claude-plugin/plugin.json').read_text())
        name = manifest['name']
        if (not re.fullmatch(r'[0-9a-f]{40,64}', commit) or source.name != commit
                or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name)
                or release['tag'] != 'v' + manifest['version']):
            raise ValueError(f'Invalid plugin identity or version: {owner}')
        if name in names:
            raise ValueError(f'Claude plugin name collision: {name}')
        names.add(name)
        marketplace = f'agent-config-{owner}-{commit}'
        prepared[owner] = {'source': source, 'commit': commit, 'name': name,
                           'version': manifest['version'], 'marketplace': marketplace,
                           'identifier': f'{name}@{marketplace}', 'stage': stages / owner / commit}
    return prepared


def stage_sources(prepared):
    for item in prepared.values():
        source, stage = item['source'], item['stage']
        stage.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.marketplace-', dir=stage.parent))
        try:
            for name in ('.claude-plugin', 'commands', 'scripts', 'references'):
                if (source / name).is_dir():
                    shutil.copytree(source / name, temporary / name)
            (temporary / '.claude-plugin/marketplace.json').write_text(json.dumps({
                'name': item['marketplace'], 'owner': {'name': item['name']},
                'plugins': [{'name': item['name'], 'source': './'}],
            }, indent=2) + '\n')
            if stage.exists() or stage.is_symlink():
                if stage.is_symlink() or not stage.is_dir() or tree_digest(stage) != tree_digest(temporary):
                    raise ValueError(f'Managed marketplace differs from release: {stage}')
            else:
                os.rename(temporary, stage)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def install_sources(prepared, home):
    state_path = home / '.agent-config-plugin.json'
    if state_path.is_symlink():
        raise ValueError(f'Refusing symlinked plugin state: {state_path}')
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    previous = state.get('managed_ids', [])
    if not isinstance(previous, list) or any(not isinstance(key, str) or not re.fullmatch(
            r'[a-z0-9-]+@(?:btmt-agent-config-[0-9a-f]{40,64}|agent-config-[a-z0-9-]+-[0-9a-f]{40,64})', key)
            for key in previous):
        raise ValueError('Invalid managed plugin state')
    expected = {item['identifier'] for item in prepared.values()}
    old = set(previous) | {'claude-config@btmt-claude-config', 'agent-config@btmt-claude-config'}
    journal = home / '.agent-config-plugin-pending.json'
    if journal.is_symlink():
        raise ValueError(f'Refusing symlinked plugin journal: {journal}')
    if journal.exists():
        pending = json.loads(journal.read_text())
        if (not isinstance(pending, dict) or set(pending) != {'version', 'expected', 'previous'}
                or pending['version'] != 1 or pending['expected'] != sorted(expected)
                or not isinstance(pending['previous'], list)
                or not all(isinstance(item, str) and (item in {'claude-config@btmt-claude-config',
                           'agent-config@btmt-claude-config'} or re.fullmatch(
                           r'[a-z0-9-]+@(?:btmt-agent-config-[0-9a-f]{40,64}|agent-config-[a-z0-9-]+-[0-9a-f]{40,64})', item))
                           for item in pending['previous'])):
            raise ValueError('Another plugin migration is incomplete; retry it first')
        old.update(pending['previous'])
    stage_sources(prepared)
    home.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.agent-plugin-pending-', dir=home)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'version': 1, 'expected': sorted(expected), 'previous': sorted(old)}, stream)
        os.replace(filename, journal)
    finally:
        Path(filename).unlink(missing_ok=True)
    for item in prepared.values():
        run_claude(home, 'install', item['name'], '--marketplace', str(item['stage']), '--scope', 'user', '--json')
    listing = json.loads(run_claude(home, 'list', '--json'))
    if not isinstance(listing, list):
        raise ValueError('Unexpected Claude plugin listing')
    installed = {}
    for entry in listing:
        if isinstance(entry, dict) and isinstance(entry.get('id'), str):
            installed.setdefault(entry['id'], []).append(entry)
    for item in prepared.values():
        entries = [entry for entry in installed.get(item['identifier'], []) if entry.get('scope') == 'user']
        if len(entries) != 1 or entries[0].get('version') != item['version'] or entries[0].get('enabled') is not True:
            raise RuntimeError(f"Claude did not record the requested plugin version for {item['identifier']}")
        cached = Path(entries[0]['installPath'])
        for file in plugin_files(item['source']):
            relative = file.relative_to(item['source'])
            if not (cached / relative).is_file() or (cached / relative).read_bytes() != file.read_bytes():
                raise RuntimeError(f'Claude plugin cache differs from release: {relative}')
    for identifier in sorted(old - expected):
        if any(entry.get('scope') == 'user' for entry in installed.get(identifier, [])):
            run_claude(home, 'uninstall', identifier, '--scope', 'user', '--keep-data', '--json')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.agent-plugin-state-', dir=state_path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'version': 2, 'managed_ids': sorted(expected),
                       'sources': {owner: {'commit': item['commit'], 'identifier': item['identifier']}
                                   for owner, item in prepared.items()}}, stream, indent=2)
            stream.write('\n')
        os.replace(filename, state_path)
    finally:
        Path(filename).unlink(missing_ok=True)
    journal.unlink()
    return expected


def verify_sources(prepared, home):
    journal = home / '.agent-config-plugin-pending.json'
    if journal.exists() or journal.is_symlink():
        raise ValueError('A Claude plugin synchronization is incomplete')
    state = json.loads((home / '.agent-config-plugin.json').read_text())
    expected = {owner: {'commit': item['commit'], 'identifier': item['identifier']}
                for owner, item in prepared.items()}
    if (state.get('version') != 2 or state.get('sources') != expected
            or state.get('managed_ids') != sorted(item['identifier'] for item in prepared.values())):
        raise ValueError('Claude plugin state does not match active sources')
    plugins_dir = Path(os.environ.get('CLAUDE_CODE_PLUGIN_CACHE_DIR', str(home / 'plugins'))).expanduser()
    installed = json.loads((plugins_dir / 'installed_plugins.json').read_text()).get('plugins', {})
    enabled = json.loads((home / 'settings.json').read_text()).get('enabledPlugins', {})
    for item in prepared.values():
        identifier = item['identifier']
        matches = [entry for entry in installed.get(identifier, []) if entry.get('scope') == 'user']
        if len(matches) != 1 or matches[0].get('version') != item['version'] or enabled.get(identifier) is not True:
            raise ValueError(f'Claude plugin is missing, disabled, or has the wrong version: {identifier}')
        cache = Path(matches[0]['installPath'])
        for file in plugin_files(item['source']):
            relative = file.relative_to(item['source'])
            if not (cache / relative).is_file() or (cache / relative).read_bytes() != file.read_bytes():
                raise ValueError(f'Claude plugin cache differs from release: {relative}')


def verify(source, home):
    release = json.loads((source / '.agent-config-release.json').read_text())
    commit = release['commit']
    identifier = 'agent-config@btmt-agent-config-' + commit
    state = json.loads((home / '.agent-config-plugin.json').read_text())
    if state.get('commit') != commit or state.get('managed_ids') != [identifier]:
        raise ValueError('Claude plugin state does not match active release')
    plugins_dir = Path(os.environ.get('CLAUDE_CODE_PLUGIN_CACHE_DIR', str(home / 'plugins'))).expanduser()
    installed = json.loads((plugins_dir / 'installed_plugins.json').read_text()).get('plugins', {})
    settings = json.loads((home / 'settings.json').read_text())
    matches = [entry for entry in installed.get(identifier, []) if entry.get('scope') == 'user']
    version = json.loads((source / '.claude-plugin/plugin.json').read_text())['version']
    if len(matches) != 1 or matches[0].get('version') != version or settings.get('enabledPlugins', {}).get(identifier) is not True:
        raise ValueError('Claude plugin is missing, disabled, or has the wrong version')
    cached = Path(matches[0]['installPath'])
    files = plugin_files(source)
    for file in files:
        target = cached / file.relative_to(source)
        if not target.is_file() or target.read_bytes() != file.read_bytes():
            raise ValueError(f'Claude plugin cache differs from release: {file.relative_to(source)}')
    return identifier

def install(source, home, stages):
    release = json.loads((source / '.agent-config-release.json').read_text())
    commit = release['commit']
    if not re.fullmatch(r'[0-9a-f]{40,64}', commit) or source.name != commit:
        raise ValueError('Invalid prepared release identity')
    manifest = json.loads((source / '.claude-plugin/plugin.json').read_text())
    if manifest['name'] != 'agent-config' or release['tag'] != 'v' + manifest['version']:
        raise ValueError('Plugin identity or version does not match release')
    marketplace = 'btmt-agent-config-' + commit
    stage = stages / commit
    stages.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.marketplace-', dir=stages))
    try:
        for name in ('.claude-plugin', 'commands', 'scripts'):
            shutil.copytree(source / name, temp / name)
        if (source / 'references').is_dir():
            shutil.copytree(source / 'references', temp / 'references')
        (temp / '.claude-plugin/marketplace.json').write_text(json.dumps({
            'name': marketplace, 'owner': {'name': 'BehindTheMusicTree'},
            'plugins': [{'name': 'agent-config', 'source': './'}],
        }, indent=2) + '\n')
        if stage.exists() or stage.is_symlink():
            if stage.is_symlink() or not stage.is_dir() or tree_digest(stage) != tree_digest(temp):
                raise ValueError(f'Managed marketplace differs from release: {stage}')
        else:
            os.rename(temp, stage)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    state_path = home / '.agent-config-plugin.json'
    if state_path.is_symlink():
        raise ValueError(f'Refusing symlinked plugin state: {state_path}')
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    ids = state.get('managed_ids', [])
    if not isinstance(ids, list) or any(not isinstance(key, str) or not re.fullmatch(r'agent-config@btmt-agent-config-[0-9a-f]{40,64}', key) for key in ids):
        raise ValueError('Invalid managed plugin state')
    previous = set(ids)
    previous.update(('claude-config@btmt-claude-config', 'agent-config@btmt-claude-config'))
    run_claude(home, 'install', 'agent-config', '--marketplace', str(stage), '--scope', 'user', '--json')
    listing = json.loads(run_claude(home, 'list', '--json'))
    if not isinstance(listing, list):
        raise ValueError('Unexpected Claude plugin listing')
    installed = {}
    for item in listing:
        if isinstance(item, dict) and isinstance(item.get('id'), str):
            installed.setdefault(item['id'], []).append(item)
    identifier = f'agent-config@{marketplace}'
    entries = [entry for entry in installed.get(identifier, []) if entry.get('scope') == 'user']
    if len(entries) != 1 or entries[0].get('version') != manifest['version'] or entries[0].get('enabled') is not True:
        raise RuntimeError(f'Claude did not record the requested plugin version for {identifier}')
    cached = Path(entries[0]['installPath'])
    for file in plugin_files(source):
        relative = file.relative_to(source)
        if not (cached / relative).is_file() or (cached / relative).read_bytes() != file.read_bytes():
            raise RuntimeError(f'Claude plugin cache differs from release: {relative}')

    previous.discard(identifier)
    for key in sorted(previous):
        values = installed.get(key, [])
        if any(entry.get('scope') == 'user' for entry in values):
            run_claude(home, 'uninstall', key, '--scope', 'user', '--keep-data', '--json')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.agent-plugin-state-', dir=state_path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'managed_ids': [identifier], 'commit': commit}, stream, indent=2)
            stream.write('\n')
        os.replace(filename, state_path)
    finally:
        Path(filename).unlink(missing_ok=True)
    return identifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')))
    parser.add_argument('--stages', type=Path, default=Path.home() / '.local/share/agent-config/marketplaces')
    args = parser.parse_args()
    try:
        result = install(args.source.resolve(), args.claude_home.expanduser().resolve(), args.stages.expanduser().resolve())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        sys.stderr.write(f'Claude plugin synchronization failed: {error}\n')
        return 1
    sys.stdout.write(f'Installed {result}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
