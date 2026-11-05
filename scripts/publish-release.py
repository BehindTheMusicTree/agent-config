#!/usr/bin/env python3
"""Publish the validated tag's changelog; fail closed on API errors."""

import json
import logging
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class APIError(ValueError):
    def __init__(self, status):
        super().__init__(f'GitHub API request failed (HTTP {status})')
        self.status = status


class GitHub:
    def __init__(self, repository, token, api_url):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise ValueError('Repository and GitHub token are required')
        if not api_url.startswith('https://'):
            raise ValueError('GitHub API URL must use HTTPS')
        self.base = f'{api_url.rstrip("/")}/repos/{repository}'
        self.token = token

    def request(self, method, path, data=None):
        request = Request(self.base + path, method=method,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={'Authorization': f'Bearer {self.token}',
                                   'Accept': 'application/vnd.github+json',
                                   'Content-Type': 'application/json',
                                   'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            raise APIError(error.code) from None


def release_notes(changelog, tag):
    if not re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag):
        raise ValueError('Expected a stable vX.Y.Z tag')
    lines = changelog.splitlines()
    headings = []
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if marker:
            run, tail = marker.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not tail.strip():
                fence = None
        elif fence is None and line.startswith('## '):
            headings.append(index)
    starts = [i for i in headings if re.fullmatch(r'## \[' + re.escape(tag[1:]) + r'\](?: - \d{4}-\d{2}-\d{2})?', lines[i])]
    if len(starts) != 1:
        raise ValueError('Expected one version changelog section')
    end = next((i for i in headings if i > starts[0]), len(lines))
    body = '\n'.join(lines[starts[0] + 1:end]).strip()
    if not re.sub(r'^#{1,6}\s.*$', '', re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL), flags=re.MULTILINE).strip():
        raise ValueError('Version changelog section is empty')
    return body


def verify_release(release, tag):
    if (release['tag_name'] != tag or release['draft'] is not False or
            release['prerelease'] is not False or not release['published_at']):
        raise ValueError('Existing release is not the expected published stable release')


def publish(api, tag, commit, notes):
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or commit == '0' * 40:
        raise ValueError('Expected the exact tag commit SHA')
    path = '/releases/tags/' + quote(tag, safe='')
    try:
        release = api.request('GET', path)
    except APIError as error:
        if error.status != 404:
            raise
    else:
        verify_release(release, tag)
        return 'existing'
    try:
        release = api.request('POST', '/releases', {
            'tag_name': tag, 'target_commitish': commit, 'name': tag, 'body': notes,
            'draft': False, 'prerelease': False, 'make_latest': 'legacy',
        })
    except APIError as error:
        if error.status != 422:
            raise
        # A concurrent successful publisher is the only acceptable collision.
        release = api.request('GET', path)
        verify_release(release, tag)
        return 'existing'
    verify_release(release, tag)
    return 'created'


def main():
    tag = os.environ['GITHUB_REF_NAME']
    notes = release_notes(Path('CHANGELOG.md').read_text(encoding='utf-8'), tag)
    api = GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GH_TOKEN'], os.environ['GITHUB_API_URL'])
    logging.info('%s release %s', publish(api, tag, os.environ['RELEASE_COMMIT'], notes), tag)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        logging.error('Release publication failed: %s', error)
        sys.exit(1)
