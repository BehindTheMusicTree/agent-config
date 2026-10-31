#!/usr/bin/env python3
"""Prepare a snapshot from a published GitHub release without touching the checkout."""
import argparse
import contextlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('prepare_release', ROOT / 'scripts/prepare-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
TAG = re.compile(r'v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)')
REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*')


def published_tag(repo, version=None):
    if not REPOSITORY.fullmatch(repo):
        raise ValueError(f'Invalid GitHub repository: {repo}')
    if version is not None and not TAG.fullmatch(version):
        raise ValueError(f'Invalid stable release tag: {version}')
    command = ['gh', 'release', 'view']
    if version:
        command.append(version)
    command.extend(['--repo', repo, '--json', 'tagName,isDraft,isPrerelease'])
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    data = json.loads(output)
    tag = data.get('tagName')
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise ValueError('Release does not have a stable version tag')
    if data.get('isDraft') is not False or data.get('isPrerelease') is not False:
        raise ValueError(f'Release {tag} is a draft or prerelease')
    if version is not None and tag != version:
        raise ValueError(f'Release tag {tag} does not match requested version {version}')
    return tag


def fetch_tag(remote, tag, directory):
    if not TAG.fullmatch(tag):
        raise ValueError(f'Invalid stable release tag: {tag}')
    subprocess.run(['git', 'init', '--bare', '-q', str(directory)], check=True, capture_output=True)
    ref = f'refs/tags/{tag}'
    subprocess.run(['git', '-C', str(directory), 'fetch', '--no-tags', '--', remote, f'{ref}:{ref}'],
                   check=True, capture_output=True)


def prepare_remote(repo, version, releases):
    tag = published_tag(repo, version)
    with tempfile.TemporaryDirectory(prefix='agent-config-remote-') as temp:
        checkout = Path(temp) / 'repository.git'
        fetch_tag(f'https://github.com/{repo}.git', tag, checkout)
        return release.prepare(checkout, tag, releases)


def verify_repository(repo, expected_id):
    if not isinstance(expected_id, str) or not re.fullmatch(r'R_[A-Za-z0-9_-]+', expected_id):
        raise ValueError(f'Invalid immutable repository id: {repo}')
    result = subprocess.run(['gh', 'repo', 'view', repo, '--json', 'id,nameWithOwner'],
                            check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if data.get('id') != expected_id or data.get('nameWithOwner', '').lower() != repo.lower():
        raise ValueError(f'Repository identity changed; update the profile explicitly: {repo}')


def prepare_profile(profile, releases):
    if not isinstance(profile, dict) or set(profile) != {'version', 'public', 'private'} or profile['version'] != 1:
        raise ValueError('Invalid release profile')
    public = profile['public']
    private = profile['private']
    if (not isinstance(public, dict) or set(public) != {'repo', 'id'}
            or not isinstance(public['repo'], str) or not REPOSITORY.fullmatch(public['repo'])):
        raise ValueError('Invalid public repository')
    if (not isinstance(private, dict) or set(private) - {'repo', 'id', 'version'} or not {'repo', 'id'} <= set(private)
            or not isinstance(private['repo'], str) or not REPOSITORY.fullmatch(private['repo'])
            or (private.get('version') is not None and (not isinstance(private['version'], str)
                                                        or not TAG.fullmatch(private['version'])))):
        raise ValueError('Invalid private repository')
    if public['repo'].lower() == private['repo'].lower():
        raise ValueError('Public and private repositories must be distinct')
    verify_repository(public['repo'], public['id'])
    verify_repository(private['repo'], private['id'])
    private_source = prepare_remote(private['repo'], private.get('version'), releases / 'private')
    dependency = json.loads((private_source / 'agent-config-dependency.json').read_text())
    if (not isinstance(dependency, dict) or set(dependency) != {'repo', 'tag'}
            or dependency['repo'] != public['repo'] or not isinstance(dependency['tag'], str)
            or not TAG.fullmatch(dependency['tag'])):
        raise ValueError('Private release has an invalid public dependency')
    public_source = prepare_remote(public['repo'], dependency['tag'], releases / 'public')
    return {'public': public_source, 'private': private_source}


@contextlib.contextmanager
def synchronization_lock(releases):
    root = releases.parent
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.sync.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another synchronization is running') from error
        yield


def activate(path, releases):
    active = releases.parent / 'current'
    if active.exists() and not active.is_symlink():
        raise ValueError(f'Refusing to replace unmanaged path: {active}')
    if active.is_symlink() and active.resolve().parent != releases.resolve():
        raise ValueError(f'Refusing to replace unmanaged link: {active}')
    with tempfile.TemporaryDirectory(prefix='.active-', dir=releases.parent) as temporary:
        link = Path(temporary) / 'current'
        link.symlink_to(path, target_is_directory=True)
        os.replace(link, active)


def synchronize_remote(repo, version, releases, claude_home, codex_home, adopt_from):
    with synchronization_lock(releases):
        active = releases.parent / 'current'
        if (active.exists() and not active.is_symlink()) or (active.is_symlink() and active.resolve().parent != releases.resolve()):
            raise ValueError(f'Refusing to replace unmanaged active path: {active}')
        if active.is_symlink():
            try:
                return check_remote(repo, version, releases, claude_home, codex_home)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
                pass
        path = prepare_remote(repo, version, releases)
        sync_spec = importlib.util.spec_from_file_location('sync_local', ROOT / 'scripts/sync-local-release.py')
        sync = importlib.util.module_from_spec(sync_spec)
        sync_spec.loader.exec_module(sync)
        sync.synchronize_source(path, claude_home, codex_home, adopt_from)
        activate(path, releases)
        return path


def synchronize_profile(profile, releases, claude_home, codex_home, adopt_from=None):
    with synchronization_lock(releases):
        state = releases.parent / 'active-sources.json'
        if state.is_symlink() or (state.exists() and not state.is_file()):
            raise ValueError(f'Refusing unmanaged profile state: {state}')
        if state.exists():
            current = json.loads(state.read_text())
            if (not isinstance(current, dict) or current.get('version') != 1
                    or not isinstance(current.get('sources'), dict)):
                raise ValueError(f'Invalid active profile state: {state}')
        active = releases.parent / 'current-profile'
        if (active.exists() and not active.is_symlink()) or (active.is_symlink()
                and active.resolve().parent != (releases / 'sources/public').resolve()):
            raise ValueError(f'Refusing unmanaged active profile link: {active}')
        if state.exists() and active.is_symlink():
            try:
                return check_profile(profile, releases, claude_home, codex_home)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
                pass
        sources = prepare_profile(profile, releases / 'sources')
        sync_spec = importlib.util.spec_from_file_location('sync_profile', ROOT / 'scripts/sync-local-release.py')
        sync = importlib.util.module_from_spec(sync_spec)
        sync_spec.loader.exec_module(sync)
        sync.synchronize_sources(sources, claude_home, codex_home, releases.parent / 'marketplaces-v2', adopt_from)
        fd, filename = tempfile.mkstemp(prefix='.active-sources-', dir=releases.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'version': 1, 'sources': {name: str(path) for name, path in sources.items()}}, stream, indent=2)
                stream.write('\n')
            os.replace(filename, state)
            with tempfile.TemporaryDirectory(prefix='.profile-active-', dir=releases.parent) as temporary:
                link = Path(temporary) / 'current-profile'
                link.symlink_to(sources['public'], target_is_directory=True)
                os.replace(link, active)
        except OSError as error:
            raise RuntimeError(f'Sources installed but active profile could not be recorded: {error}') from error
        finally:
            Path(filename).unlink(missing_ok=True)
        return sources


def check_profile(profile, releases, claude_home, codex_home):
    state_path = releases.parent / 'active-sources.json'
    if state_path.is_symlink():
        raise ValueError(f'Refusing symlinked profile state: {state_path}')
    state = json.loads(state_path.read_text())
    if state.get('version') != 1 or set(state.get('sources', {})) != {'public', 'private'}:
        raise ValueError('Invalid active profile state')
    sources = {}
    for name, path in state['sources'].items():
        source = Path(path)
        expected_parent = (releases / 'sources' / name).resolve()
        if not source.is_absolute() or source.is_symlink() or source.resolve().parent != expected_parent:
            raise ValueError(f'Invalid active source: {name}')
        sources[name] = source.resolve()
    active = releases.parent / 'current-profile'
    if not active.is_symlink() or active.resolve() != sources['public']:
        raise ValueError('Active profile updater does not match the public release')
    with tempfile.TemporaryDirectory(prefix='agent-profile-check-') as temporary:
        expected = prepare_profile(profile, Path(temporary) / 'releases')
        for name, source in sources.items():
            if expected[name].name != source.name or release.tree_digest(expected[name]) != release.tree_digest(source):
                raise ValueError(f'Active snapshot does not match published release: {name}')
    sync_spec = importlib.util.spec_from_file_location('sync_profile_check', ROOT / 'scripts/sync-local-release.py')
    sync = importlib.util.module_from_spec(sync_spec)
    sync_spec.loader.exec_module(sync)
    prepared = sync.plugins.prepare_sources(sources, releases.parent / 'marketplaces-v2')
    sync.plugins.verify_sources(prepared, claude_home)
    _, links, changes = sync.plan_sources(sources, claude_home, codex_home)
    if links or changes:
        raise ValueError('Skills or instructions differ from active sources')
    return sources


def check_remote(repo, version, releases, claude_home, codex_home):
    tag = published_tag(repo, version)
    active = releases.parent / 'current'
    if not active.is_symlink() or active.resolve().parent != releases.resolve():
        raise ValueError('No managed active release')
    source = active.resolve()
    metadata = json.loads((source / '.agent-config-release.json').read_text())
    if metadata['tag'] != tag or source.name != metadata['commit']:
        raise ValueError(f'Active release does not match published release {tag}')
    with tempfile.TemporaryDirectory(prefix='agent-config-check-') as temporary:
        directory = Path(temporary)
        checkout = directory / 'remote.git'
        fetch_tag(f'https://github.com/{repo}.git', tag, checkout)
        expected = release.prepare(checkout, tag, directory / 'releases')
        if expected.name != metadata['commit'] or release.tree_digest(expected) != release.tree_digest(source):
            raise ValueError('Active snapshot does not match the published release')
    sync_spec = importlib.util.spec_from_file_location('sync_local_check', ROOT / 'scripts/sync-local-release.py')
    sync = importlib.util.module_from_spec(sync_spec)
    sync_spec.loader.exec_module(sync)
    sync.plugins.verify(source, claude_home)
    _, link_changes = sync.skills.plan(source, codex_home / 'skills')
    if link_changes:
        raise ValueError('Codex skills differ from active release')
    override = codex_home / 'AGENTS.override.md'
    if override.is_file() and override.read_text().strip():
        raise ValueError('Active Codex override masks generated instructions')
    for agent, home in (('claude', claude_home), ('codex', codex_home)):
        if sync.instructions.prepare(home, sync.instructions.render(source, agent)):
            raise ValueError(f'{agent} global instructions differ from active release')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='BehindTheMusicTree/agent-config')
    parser.add_argument('--version', help='stable release tag; defaults to GitHub latest')
    parser.add_argument('--profile', type=Path, help='JSON profile containing public and private repositories')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--sync-local', action='store_true', help='synchronize Claude, Codex and global instructions')
    mode.add_argument('--check', action='store_true', help='verify installation without making changes')
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')))
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    parser.add_argument('--adopt-from', type=Path, default=ROOT if (ROOT / '.git').exists() else None)
    parser.add_argument('--releases', type=Path, default=Path.home() / '.local/share/agent-config/releases')
    args = parser.parse_args()
    try:
        releases = args.releases.expanduser().resolve()
        if args.profile:
            if args.version or args.repo != 'BehindTheMusicTree/agent-config':
                raise ValueError('--profile cannot be combined with --repo or --version')
            profile = json.loads(args.profile.expanduser().read_text())
            if args.check:
                path = check_profile(profile, releases, args.claude_home.expanduser().resolve(),
                                     args.codex_home.expanduser().resolve())
            elif args.sync_local:
                path = synchronize_profile(profile, releases, args.claude_home.expanduser().resolve(),
                                           args.codex_home.expanduser().resolve(), args.adopt_from)
            else:
                path = prepare_profile(profile, releases / 'sources')
        elif args.check:
            path = check_remote(args.repo, args.version, releases, args.claude_home.expanduser().resolve(),
                                args.codex_home.expanduser().resolve())
        elif args.sync_local:
            path = synchronize_remote(args.repo, args.version, releases, args.claude_home.expanduser().resolve(),
                                      args.codex_home.expanduser().resolve(), args.adopt_from)
        else:
            path = prepare_remote(args.repo, args.version, releases)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        sys.stderr.write(f'Failed to prepare published release: {error}\n')
        return 1
    sys.stdout.write(f'{path}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
