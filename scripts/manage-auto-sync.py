#!/usr/bin/env python3
"""Manage the optional macOS launchd job for release synchronization."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

LABEL = 'org.behindthemusictree.agent-config.sync'


def build_plist(active, state, interval, path, profile=None):
    if interval < 300:
        raise ValueError('Sync interval must be at least 300 seconds')
    runner = active / 'scripts/prepare-remote-release.py'
    if not runner.is_file():
        raise ValueError(f'No active release updater: {runner}')
    python = shutil.which('python3')
    if not python:
        raise ValueError('python3 is required')
    environment = {'PATH': path}
    for key in ('HOME', 'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_PLUGIN_CACHE_DIR', 'CODEX_HOME', 'GH_CONFIG_DIR'):
        if os.environ.get(key):
            environment[key] = os.environ[key]
    arguments = [str(Path(python).resolve()), str(runner), '--sync-local', '--releases', str(state / 'releases')]
    if profile is not None:
        profile = profile.expanduser().resolve()
        if not profile.is_file():
            raise ValueError(f'Profile not found: {profile}')
        arguments.extend(['--profile', str(profile)])
    return {
        'Label': LABEL,
        'ProgramArguments': arguments,
        'StartInterval': interval,
        'RunAtLoad': True,
        'EnvironmentVariables': environment,
        'StandardOutPath': str(state / 'auto-sync.log'),
        'StandardErrorPath': str(state / 'auto-sync.log'),
    }


def install(active, state, agents, interval, path, profile=None):
    if sys.platform != 'darwin':
        raise ValueError('Automatic scheduling is supported on macOS only')
    config = build_plist(active, state, interval, path, profile)
    target = agents / (LABEL + '.plist')
    marker = state / 'launchd-installed.plist'
    data = plistlib.dumps(config)
    if target.is_symlink() or marker.is_symlink():
        raise ValueError('Refusing symlinked scheduler files')
    if target.exists() and (not marker.exists() or target.read_bytes() != marker.read_bytes()):
        raise ValueError(f'Refusing to overwrite modified or unmanaged job: {target}')
    if marker.exists() and not target.exists():
        raise ValueError(f'Managed scheduler file is missing: {target}')
    state.mkdir(parents=True, exist_ok=True)
    agents.mkdir(parents=True, exist_ok=True)
    previous = target.read_bytes() if target.exists() else None
    previous_marker = marker.read_bytes() if marker.exists() else None
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True, check=False)
    fd, name = tempfile.mkstemp(prefix='.agent-config-', dir=agents)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        try:
            os.replace(name, target)
            marker.write_bytes(data)
            result = subprocess.run(['launchctl', 'bootstrap', domain, str(target)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f'Failed to start scheduler: {result.stderr.strip()}')
        except (OSError, RuntimeError):
            subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True, check=False)
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
            if previous_marker is None:
                marker.unlink(missing_ok=True)
            else:
                marker.write_bytes(previous_marker)
            if previous is not None:
                subprocess.run(['launchctl', 'bootstrap', domain, str(target)], capture_output=True, check=False)
            raise
    finally:
        Path(name).unlink(missing_ok=True)
    return target


def uninstall(state, agents):
    target = agents / (LABEL + '.plist')
    marker = state / 'launchd-installed.plist'
    if target.is_symlink() or marker.is_symlink():
        raise ValueError('Refusing symlinked scheduler files')
    if target.exists() and (not marker.exists() or target.read_bytes() != marker.read_bytes()):
        raise ValueError(f'Refusing to remove modified or unmanaged job: {target}')
    subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True, check=False)
    target.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/share/agent-config')
    parser.add_argument('--agents', type=Path, default=Path.home() / 'Library/LaunchAgents')
    parser.add_argument('--interval', type=int, default=3600)
    parser.add_argument('--profile', type=Path, help='synchronize a public/private profile')
    args = parser.parse_args()
    try:
        if args.action == 'install':
            active = args.state / ('current-profile' if args.profile else 'current')
            target = install(active, args.state, args.agents, args.interval, os.environ.get('PATH', ''), args.profile)
            sys.stdout.write(f'Installed {target}\n')
        else:
            uninstall(args.state, args.agents)
            sys.stdout.write('Automatic synchronization removed\n')
    except (OSError, ValueError, RuntimeError) as error:
        sys.stderr.write(f'Scheduler error: {error}\n')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
