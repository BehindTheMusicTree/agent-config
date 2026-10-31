#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/validate.py
python3 scripts/render-workflows.py
python3 -m unittest discover -s tests -v
for file in scripts/*.sh; do bash -n "$file"; done
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning scripts/*.sh
else
  echo 'shellcheck unavailable; skipped' >&2
fi
