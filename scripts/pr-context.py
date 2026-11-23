#!/usr/bin/env python3
"""Collect bounded, read-only Git facts for a PR; never infer validation success."""
import argparse
import json
from pathlib import Path
import re
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

LOCAL_TEMPLATES = ('.github/pull_request_template.md', '.github/PULL_REQUEST_TEMPLATE.md',
                   'docs/pull_request_template.md')
ORG_TEMPLATES = ('.github/pull_request_template.md', '.github/PULL_REQUEST_TEMPLATE.md',
                 'pull_request_template.md', 'PULL_REQUEST_TEMPLATE.md', 'docs/pull_request_template.md')
GITFLOW_PREFIXES = ('feature/', 'release/', 'hotfix/')
MERGE_WORDS = {'squash': r'\bsquash', 'merge': r'\bmerge commit', 'rebase': r'\brebase and merge|\brebase merge'}


def gh_api(*args):
    """Return (status, text); 'missing' means HTTP 404, any other failure raises."""
    result = subprocess.run(['gh', 'api', *args], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode == 0:
        return 'ok', result.stdout
    if 'HTTP 404' in result.stderr:
        return 'missing', ''
    raise ValueError(f'gh api {args[-1]} failed: {result.stderr.strip()}')


def owner_repo(root):
    url = git(root, 'remote', 'get-url', 'origin').strip()
    match = re.search(r'[:/]([^/:]+)/([^/]+?)(?:\.git)?$', url)
    if not match:
        raise ValueError(f'Cannot read owner/repo from origin URL: {url}')
    return match.group(1), match.group(2)


def pr_template(root, github):
    candidates = [p for p in LOCAL_TEMPLATES if (root / p).is_file()]
    directory = root / '.github' / 'PULL_REQUEST_TEMPLATE'
    if directory.is_dir():
        candidates += sorted(str(p.relative_to(root)) for p in directory.glob('*.md'))
    if candidates:
        return {'source': 'local', 'path': candidates[0]}
    if not github:
        return {'source': 'unchecked', 'path': None}
    owner, _ = owner_repo(root)
    for path in ORG_TEMPLATES:
        status, _ = gh_api('-H', 'Accept: application/vnd.github.raw+json', f'repos/{owner}/.github/contents/{path}')
        if status == 'ok':
            return {'source': 'org', 'path': f'{owner}/.github:{path}'}
    status, listing = gh_api(f'repos/{owner}/.github/contents/.github/PULL_REQUEST_TEMPLATE')
    if status == 'ok':
        names = sorted(item['name'] for item in json.loads(listing) if item['name'].endswith('.md'))
        if names:
            return {'source': 'org', 'path': f'{owner}/.github:.github/PULL_REQUEST_TEMPLATE/{names[0]}'}
    return {'source': 'none', 'path': None}


def merge_method(root):
    owner, repo = owner_repo(root)
    _, text = gh_api(f'repos/{owner}/{repo}', '--jq',
                     '{squash: .allow_squash_merge, merge: .allow_merge_commit, rebase: .allow_rebase_merge}')
    allowed = [name for name, enabled in json.loads(text).items() if enabled]
    if len(allowed) == 1:
        return allowed[0]
    docs = ' '.join(p.read_text(errors='replace').lower() for p in root.glob('CONTRIBUTING*') if p.is_file())
    stated = [name for name in allowed if re.search(MERGE_WORDS[name], docs)]
    if len(stated) == 1:
        return stated[0]
    raise ValueError(f'Merge method is ambiguous (allowed: {", ".join(allowed) or "none"}); '
                     'state it in the contributing docs')


RELEASE_PLEASE_FILES = ('release-please-config.json', '.release-please-manifest.json')
# A job-level call of a reusable release-please workflow; such a job has no steps, so an
# auto-merge input in the same job block is that call's input.
RELEASE_PLEASE_USES = re.compile(r'^\s*uses:\s*["\']?[^\s"\'#]*/release-please\.ya?ml@', re.M)
AUTO_MERGE_TRUE = re.compile(r'(?:^\s*|[{,]\s*)auto-merge:\s*["\']?(?:true|True|TRUE)\b', re.M)


def job_blocks(text):
    """Split a workflow's `jobs:` mapping into per-job text by indentation (heuristic, no YAML parser)."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r'^jobs:\s*(?:#.*)?$', line)), None)
    if start is None:
        return []
    blocks, indent = [], None
    for line in lines[start + 1:]:
        if not line.strip() or line.lstrip().startswith('#'):
            if blocks:
                blocks[-1].append(line)
            continue
        width = len(line) - len(line.lstrip())
        if indent is None:
            indent = width
        if width < indent or width == 0:
            break
        if width == indent:
            blocks.append([])
        blocks[-1].append(line)
    return ['\n'.join(block) for block in blocks]


def release_please(root, base_sha):
    """Read release-please setup from the base commit: none, manual, or auto_merge."""
    present = git(root, 'ls-tree', '-z', '--name-only', base_sha, '--', *RELEASE_PLEASE_FILES).strip('\0')
    if not present:
        return 'none'
    workflows = [p for p in git(root, 'ls-tree', '-z', '--name-only', base_sha, '--', '.github/workflows/').split('\0')
                 if p.endswith(('.yml', '.yaml'))]
    for path in workflows:
        raw = git(root, 'show', f'{base_sha}:{path}')
        try:
            text = raw.encode('utf-8', 'surrogateescape').decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError(f'Cannot read workflow {path} at {base_sha[:12]}: {exc}') from exc
        if any(RELEASE_PLEASE_USES.search(job) and AUTO_MERGE_TRUE.search(job) for job in job_blocks(text)):
            return 'auto_merge'
    return 'manual'


def branch_prefix(flow, branch, intent):
    if flow != 'gitflow' or intent == 'back-merge':
        return 'n/a'
    return 'valid' if branch and branch.startswith(GITFLOW_PREFIXES) else 'invalid'


def collect(root, base, limit, validation_logs, intent='change', depth='auto', github=False):
    root = Path(git(root, 'rev-parse', '--show-toplevel').strip())
    result = subprocess.run(
        ['bash', str(Path(__file__).with_name('detect-branch-model.sh'))], cwd=root,
        capture_output=True, text=True, check=False, timeout=60,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Branch model detection failed')
    detected = dict(line.split('=', 1) for line in result.stdout.splitlines())
    flow = detected['flow']
    if base is None:
        base = 'origin/' + detected['trunk']
    base_sha = git(root, 'rev-parse', '--verify', '--end-of-options', base + '^{commit}').strip()
    head = git(root, 'rev-parse', 'HEAD').strip()
    merge_base = git(root, 'merge-base', base_sha, head).strip()
    release_mode = release_please(root, base_sha)
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
    branch = git(root, 'branch', '--show-current').strip() or None
    return {
        'repository': str(root), 'branch': branch,
        'branch_prefix': branch_prefix(flow, branch, intent),
        'pr_template': pr_template(root, github),
        'merge_method': merge_method(root) if github else None,
        'release_please': release_mode,
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
    parser.add_argument('--github', action='store_true',
                        help='Also query GitHub (read-only): organization PR template and allowed merge method.')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('--limit must be between 1 and 100')
    try:
        sys.stdout.write(json.dumps(collect(args.repo, args.base, args.limit, args.validation_log,
                                          args.intent, args.depth, args.github), indent=2) + '\n')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f'pr-context: {exc}\n')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
