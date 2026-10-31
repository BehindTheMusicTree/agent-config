#!/usr/bin/env python3
"""Collect failed PR check logs and bounded evidence; never modify GitHub resources."""
import argparse
from collections import deque
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse


FAILURES = {'FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'ERROR'}
ERROR = re.compile(r'::error|##\[error\]|\berror\b|\bfail(?:ed|ure)?\b|exception|traceback|fatal|assertionerror', re.I)
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
TIMESTAMP = re.compile(r'\b\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z\s*')


def gh_json(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError(f'gh exited {result.returncode}: {result.stderr[-1500:]}')
    return json.loads(result.stdout)


def clip(line):
    return {'text': line.rstrip('\n')[:500], 'truncated': len(line.rstrip('\n')) > 500}


def index_log(path, max_groups):
    groups = {}
    tail = deque(maxlen=20)
    with path.open(errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            tail.append({'line': number, **clip(line)})
            clean = ANSI.sub('', line)
            if ERROR.search(clean):
                key = TIMESTAMP.sub('', clean).strip()
                group = groups.setdefault(key, {'count': 0, 'first_line': number, 'lines': []})
                group['count'] += 1
                group['lines'].append(number)
    index = path.with_suffix('.index.json')
    index.write_text(json.dumps([
        {'message': message, **value} for message, value in groups.items()
    ], indent=2) + '\n')
    selected = list(groups.values())[:max_groups]
    ranges = [(max(1, group['first_line'] - 2), group['first_line'] + 2) for group in selected]
    excerpts = []
    with path.open(errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            if any(start <= number <= end for start, end in ranges):
                excerpts.append({'line': number, **clip(line)})
    return {
        'log': str(path), 'index': str(index), 'candidate_groups': len(groups),
        'omitted_groups': max(0, len(groups) - max_groups), 'excerpts': excerpts if groups else list(tail),
        'selection': 'Heuristic error candidates with context; inspect the full log for diagnosis.' if groups
        else 'No error pattern matched; showing the last 20 lines. This does not establish success.',
    }


def collect(pr, repo, output_root, max_groups):
    metadata = gh_json('pr', 'view', pr, '--repo', repo, '--json', 'number,url,headRefOid,statusCheckRollup')
    directory = Path(tempfile.mkdtemp(prefix=f'pr-{metadata["number"]}-', dir=output_root))
    result = {'repository': repo, 'pr': metadata['url'], 'head_sha': metadata['headRefOid'],
              'artifacts': str(directory), 'failed_checks': [], 'status': 'ok',
              'check_count': len(metadata['statusCheckRollup'] or []),
              'scope': 'Fresh check snapshot; no checks are rerun and no resources are modified.'}
    for check in metadata['statusCheckRollup'] or []:
        conclusion = check.get('conclusion') or check.get('state', '')
        if conclusion not in FAILURES:
            continue
        entry = {'name': check.get('name') or check.get('context'), 'conclusion': conclusion,
                 'url': check.get('detailsUrl') or check.get('targetUrl')}
        result['failed_checks'].append(entry)
        url = urlparse(entry['url'] or '')
        match = re.fullmatch(r'/' + re.escape(repo) + r'/actions/runs/(\d+)/(?:attempts/\d+/)?job/(\d+)/?', url.path)
        if url.hostname != 'github.com' or not match:
            entry['status'] = 'external_or_unresolved'
            entry['next_step'] = 'Inspect the linked provider diagnostics; no GitHub job ID was inferred.'
            result['status'] = 'partial'
            continue
        run_id, job_id = match.groups()
        try:
            run = gh_json('run', 'view', run_id, '--repo', repo, '--json', 'attempt,headSha,jobs')
            if run['headSha'] != metadata['headRefOid']:
                raise ValueError('Run SHA differs from PR head; refresh checks before collecting logs')
            job = next((job for job in run['jobs'] if str(job['databaseId']) == job_id), None)
            if job is None:
                raise ValueError('Job is not in the current run attempt; refresh checks')
            entry.update({'run_id': run_id, 'attempt': run['attempt'], 'job_id': job_id})
            log = directory / f'{metadata["headRefOid"]}-{run_id}-{run["attempt"]}-{job_id}.log'
            with log.open('wb') as stream:
                completed = subprocess.run([
                    'gh', 'run', 'view', run_id, '--repo', repo, '--attempt', str(run['attempt']),
                    '--job', job_id, '--log',
                ], stdout=stream, stderr=subprocess.PIPE, timeout=120)
            if completed.returncode or log.stat().st_size == 0:
                log.unlink()
                raise ValueError(f'Log unavailable (exit {completed.returncode}): '
                                 + completed.stderr.decode(errors='replace')[-1500:])
            entry.update({'status': 'collected', **index_log(log, max_groups)})
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
            entry.update({'status': 'collection_failed', 'error': str(exc)})
            result['status'] = 'partial'
    # Catch a push or rerun while downloading. A stale snapshot is not current CI status.
    try:
        current = gh_json('pr', 'view', pr, '--repo', repo, '--json', 'headRefOid,statusCheckRollup')
        if any(current[key] != metadata[key] for key in ('headRefOid', 'statusCheckRollup')):
            result['status'] = 'stale'
            result['error'] = 'PR head or checks changed during collection; refresh before acting.'
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        result['status'] = 'partial'
        result['error'] = f'Final freshness check failed; current CI state is unverified: {exc}'
    manifest = directory / 'manifest.json'
    result['manifest'] = str(manifest)
    manifest.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pr', help='PR number')
    parser.add_argument('--repo', required=True, help='GitHub owner/repository')
    parser.add_argument('--output-dir', help='Existing, gitignored or external artifact directory; default: system temp.')
    parser.add_argument('--max-groups', type=int, default=4, help='Maximum excerpt groups per job (1–20).')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo) or not args.pr.isdecimal():
        parser.error('Expected --repo owner/repository and a numeric PR number')
    if not 1 <= args.max_groups <= 20:
        parser.error('--max-groups must be between 1 and 20')
    try:
        output_root = Path(args.output_dir).resolve() if args.output_dir else Path(tempfile.gettempdir())
        if not output_root.is_dir():
            raise ValueError('Output directory must already exist')
        if args.output_dir:
            tracked = subprocess.run(['git', '-C', str(output_root), 'rev-parse', '--show-toplevel'],
                                     capture_output=True, text=True)
            if tracked.returncode == 0:
                ignored = subprocess.run(['git', '-C', tracked.stdout.strip(), 'check-ignore', '-q', str(output_root)],
                                         capture_output=True)
                if ignored.returncode:
                    raise ValueError('Output directory inside a repository must be gitignored')
        result = collect(args.pr, args.repo, output_root, args.max_groups)
        preview = {**result, 'failed_checks': result['failed_checks'][:5],
                   'omitted_checks': max(0, len(result['failed_checks']) - 5)}
        sys.stdout.write(json.dumps(preview, indent=2) + '\n')
        return 0 if result['status'] == 'ok' else 1
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f'ci-failure-context: {exc}\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
