#!/usr/bin/env python3
"""Collect bounded, read-only Git facts for a PR; never infer validation success."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True, timeout=60)
    return result.stdout.decode('utf-8', errors='surrogateescape')


def changed_files(output):
    fields = iter(output.rstrip('\0').split('\0')) if output else iter(())
    files = []
    for status in fields:
        entry = {'status': status, 'path': next(fields)}
        if status.startswith(('R', 'C')):
            entry['previous_path'] = entry['path']
            entry['path'] = next(fields)
        files.append(entry)
    return files


def worktree_files(output):
    fields = iter(output.rstrip('\0').split('\0')) if output else iter(())
    files = []
    for item in fields:
        entry = {'status': item[:2], 'path': item[3:]}
        if 'R' in item[:2] or 'C' in item[:2]:
            entry['previous_path'] = next(fields)
        files.append(entry)
    return files


def bounded(items, limit):
    return {'total': len(items), 'omitted': max(0, len(items) - limit), 'items': items[:limit]}


def collect(root, base, limit, validation_logs, intent='change', depth='auto'):
    root = Path(git(root, 'rev-parse', '--show-toplevel').strip())
    result = subprocess.run(
        ['bash', str(Path(__file__).with_name('detect-branch-model.sh'))], cwd=root,
        capture_output=True, text=True, check=True, timeout=60,
    )
    detected = dict(line.split('=', 1) for line in result.stdout.splitlines())
    flow = detected['flow']
    if base is None:
        base = 'origin/' + detected['trunk']
    base_sha = git(root, 'rev-parse', '--verify', '--end-of-options', base + '^{commit}').strip()
    head = git(root, 'rev-parse', 'HEAD').strip()
    merge_base = git(root, 'merge-base', base_sha, head).strip()
    commits = []
    for line in git(root, 'log', '--format=%H%x00%s', base_sha + '..' + head).splitlines():
        sha, subject = line.split('\0', 1)
        commits.append({'sha': sha, 'subject': subject})
    files = changed_files(git(root, 'diff', '--name-status', '-z', '-M', merge_base, head, '--'))
    worktree = worktree_files(git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=normal'))
    logs = []
    for log in validation_logs:
        path = Path(log)
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file():
            raise ValueError(f'Validation log does not exist: {path}')
        logs.append({'path': str(path), 'validity': 'not_verified'})
    # Changes during collection would combine facts about different revisions.
    if git(root, 'rev-parse', 'HEAD').strip() != head or worktree_files(
        git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=normal')
    ) != worktree:
        raise ValueError('Repository changed during collection; retry on a stable worktree')
    return {
        'repository': str(root), 'branch': git(root, 'branch', '--show-current').strip() or None,
        'flow': flow, 'base_ref': base, 'base_sha': base_sha, 'merge_base': merge_base, 'head_sha': head,
        'review_request': {'intent': intent, 'depth': depth, 'classification': 'requires_hunk_review'},
        'commits': bounded(commits, limit), 'files': bounded(files, limit),
        'diff_stat': git(root, 'diff', '--shortstat', merge_base, head, '--').strip(),
        'worktree': {'dirty': bool(worktree), **bounded(worktree, limit)},
        'validation_logs': logs,
        'scope': 'Committed diff is merge-base..HEAD; worktree changes are listed separately. No tests are run or certified.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--base', help='Explicit base ref; otherwise use origin/<detected trunk>. No fetch is performed.')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--validation-log', action='append', default=[], help='Reference an existing log without reading it.')
    parser.add_argument('--intent', choices=('change', 'release', 'version-bump', 'dependency-bump', 'back-merge'),
                        default='change', help='PR purpose; does not classify risk automatically.')
    parser.add_argument('--depth', choices=('auto', 'light', 'standard', 'deep'), default='auto',
                        help='Requested review depth; apply the shared policy after inspecting hunks.')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('--limit must be between 1 and 100')
    try:
        sys.stdout.write(json.dumps(collect(args.repo, args.base, args.limit, args.validation_log,
                                          args.intent, args.depth), indent=2) + '\n')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f'pr-context: {exc}\n')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
