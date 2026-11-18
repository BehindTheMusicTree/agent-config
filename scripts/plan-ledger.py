#!/usr/bin/env python3
"""Record which .agent-plans/ files a PR reconciled, and report whether they changed since."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

LEDGER = 'plan-ledger.json'


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True, timeout=60)
    return result.stdout.decode('utf-8', errors='surrogateescape').strip()


def ledger_path(root):
    return Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', LEDGER))


def inventory(root):
    """Hash every file under any .agent-plans/ of this worktree, except each directory's .gitignore."""
    plans = {}
    for directory, subdirectories, files in os.walk(root):
        current = Path(directory)
        in_plans = '.agent-plans' in current.relative_to(root).parts
        for name in subdirectories:
            # os.walk does not follow directory links, so they would hide plans from the ledger.
            if (in_plans or name == '.agent-plans') and (current / name).is_symlink():
                relative = (current / name).relative_to(root).as_posix()
                raise ValueError(f'cannot inventory plan entry {relative}: symlinked directory')
        # Nested repositories and linked worktrees (a .git file) own their plans.
        subdirectories[:] = sorted(name for name in subdirectories
                                   if name != '.git' and not (current / name / '.git').exists())
        if not in_plans:
            continue
        for name in sorted(files):
            if name == '.gitignore' and current.name == '.agent-plans':
                continue
            path = current / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'cannot inventory plan entry {relative}: not a regular file')
            plans[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return plans


def read_ledger(path):
    try:
        ledger = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{path}: unreadable ledger ({exc})') from exc
    if not isinstance(ledger, dict) or not isinstance(ledger.get('plans'), dict):
        raise ValueError(f'{path}: ledger has no plans mapping')
    pr = ledger.get('pr')
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 0:
        raise ValueError(f'{path}: ledger has no valid PR number')
    return ledger


def record(repo, pr, exclude=()):
    root = Path(git(repo, 'rev-parse', '--show-toplevel'))
    path = ledger_path(root)
    plans = inventory(root)
    unknown = sorted(set(exclude) - set(plans))
    if unknown:
        raise ValueError(f'excluded paths are not plans of this worktree: {", ".join(unknown)}')
    ledger = {'pr': pr, 'head': git(root, 'rev-parse', 'HEAD'),
              'plans': {relative: digest for relative, digest in plans.items() if relative not in exclude}}
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)
    return {'ledger': str(path), **ledger}


def status(repo):
    root = Path(git(repo, 'rev-parse', '--show-toplevel'))
    path = ledger_path(root)
    ledger = read_ledger(path) if path.exists() else None
    recorded = ledger['plans'] if ledger else {}
    plans = []
    for relative, digest in inventory(root).items():
        if relative not in recorded:
            state = 'unrecorded'
        elif recorded[relative] == digest:
            state = 'reconciled'
        else:
            state = 'modified'
        plans.append({'path': relative, 'state': state})
    return {'ledger': str(path) if ledger else None, 'pr': ledger['pr'] if ledger else None,
            'head': ledger['head'] if ledger else None, 'plans': plans}


def pr_merged_from_branch(root, ledger, branch):
    """True when the ledger's PR is merged and was opened from this branch; any doubt is False."""
    if not ledger or not branch or ledger['pr'] == 0:
        return False
    try:
        result = subprocess.run(['gh', 'pr', 'view', str(ledger['pr']), '--json', 'state,headRefName'], cwd=root,
                                capture_output=True, check=True, timeout=60)
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return isinstance(data, dict) and data.get('state') == 'MERGED' and data.get('headRefName') == branch


def archive(repo, dest, branch):
    """Move the plans a merged PR did not reconcile out of the worktree, before it is removed.

    Plans recorded in the ledger and unchanged are disposable only when the ledger's PR is merged and
    came from `branch`. Everything else (modified, unrecorded, unreadable ledger, unknown PR state)
    is copied to dest, verified by hash, then removed from the worktree.
    """
    root = Path(git(repo, 'rev-parse', '--show-toplevel'))
    plans = inventory(root)
    path = ledger_path(root)
    try:
        ledger = read_ledger(path) if path.exists() else None
    except ValueError:
        ledger = None
    recorded = ledger['plans'] if ledger else {}
    drop = pr_merged_from_branch(root, ledger, branch)
    discarded = sorted(relative for relative, digest in plans.items() if drop and recorded.get(relative) == digest)
    archived = sorted(set(plans) - set(discarded))
    if archived and Path(dest).exists():
        raise ValueError(f'{dest}: archive destination already exists')
    for relative in archived:
        source = root / relative
        target = Path(dest) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != plans[relative]:
            raise ValueError(f'{relative}: archived copy differs from the plan')
        source.unlink()
    return {'dest': str(dest), 'archived': archived, 'discarded': discarded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    commands = parser.add_subparsers(dest='command', required=True)
    record_parser = commands.add_parser('record', help='Hash the current plans against a PR number.')
    record_parser.add_argument('--pr', type=int, required=True)
    record_parser.add_argument('--exclude', action='append', default=[], metavar='PATH',
                               help='Worktree-relative plan unrelated to this PR; it stays unrecorded.')
    commands.add_parser('status', help='Compare current plans with the ledger; merge state is not queried.')
    archive_parser = commands.add_parser('archive', help='Move plans a merged PR did not reconcile to a directory.')
    archive_parser.add_argument('--dest', required=True, help='Directory that receives the archived plans; must not exist.')
    archive_parser.add_argument('--branch', default='', help='Branch of this worktree; empty for a detached HEAD.')
    args = parser.parse_args()
    if args.command == 'record' and args.pr < 0:
        parser.error('--pr must be a non-negative PR number')
    try:
        if args.command == 'record':
            result = record(args.repo, args.pr, args.exclude)
        elif args.command == 'archive':
            result = archive(args.repo, args.dest, args.branch)
        else:
            result = status(args.repo)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f'plan-ledger: {exc}\n')
        return 1
    sys.stdout.write(json.dumps(result, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
