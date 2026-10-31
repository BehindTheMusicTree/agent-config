#!/usr/bin/env python3
"""Prepare an immutable local release snapshot from a Git tag."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def git(repo, *args, binary=False):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=not binary).stdout


def tree_digest(directory):
    result = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink in existing snapshot: {path}')
        if path.is_file():
            result.update(str(path.relative_to(directory)).encode())
            result.update(b'\0')
            result.update(hashlib.sha256(path.read_bytes()).digest())
            result.update(str(path.stat().st_mode & 0o777).encode())
    return result.hexdigest()


def prepare(repo, tag, releases):
    if not re.fullmatch(r'v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)', tag):
        raise ValueError(f'Invalid stable release tag: {tag}')
    commit = git(repo, 'rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}').strip()
    version = json.loads(git(repo, 'show', f'{commit}:.claude-plugin/plugin.json'))['version']
    if version != tag[1:]:
        raise ValueError(f'Tag {tag} does not match manifest version {version}')
    target = releases / commit
    archive = git(repo, 'archive', '--format=tar', commit, binary=True)
    releases.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.release-', dir=releases))
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as tar:
            for member in tar.getmembers():
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError(f'Unsupported archive entry: {member.name}')
                destination = temporary / path
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    stream = tar.extractfile(member)
                    if stream is None:
                        raise ValueError(f'Cannot read archive entry: {member.name}')
                    with destination.open('wb') as output:
                        shutil.copyfileobj(stream, output)
                    destination.chmod(member.mode & 0o777)
        (temporary / '.agent-config-release.json').write_text(json.dumps({'tag': tag, 'commit': commit}) + '\n')
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir() or tree_digest(target) != tree_digest(temporary):
                raise ValueError(f'Existing snapshot does not match release: {target}')
        else:
            os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--releases', type=Path, default=Path.home() / '.local/share/agent-config/releases')
    args = parser.parse_args()
    try:
        print(prepare(args.repo.resolve(), args.tag, args.releases.expanduser().resolve()))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f'Error preparing release: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
