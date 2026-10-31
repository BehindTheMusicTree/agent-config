#!/usr/bin/env python3
"""Verify a release tag matches the plugin version."""
import argparse
import json
from pathlib import Path
import re
import sys


def check(tag, manifest):
    match = re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag)
    if not match:
        raise ValueError(f'Expected a stable tag in vX.Y.Z format: {tag}')
    version = json.loads(manifest.read_text(encoding='utf-8'))['version']
    if version != tag[1:]:
        raise ValueError(f'Tag {tag} does not match plugin version {version}')
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parent.parent / '.claude-plugin/plugin.json')
    args = parser.parse_args()
    try:
        version = check(args.tag, args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Invalid release: {error}', file=sys.stderr)
        return 1
    print(f'Release version {version} is valid')
    return 0


if __name__ == '__main__':
    sys.exit(main())
