#!/usr/bin/env bash
# Prints flow and trunk based on existing remote integration branches.
set -euo pipefail

if git show-ref --verify --quiet refs/remotes/origin/develop; then
  printf 'flow=gitflow\ntrunk=develop\n'
  exit 0
fi

if git config --get-regexp '^gitflow\.' >/dev/null 2>&1; then
  echo 'branch model: Gitflow configuration exists but origin/develop is missing' >&2
  exit 1
fi

head_ref=$(git symbolic-ref -q refs/remotes/origin/HEAD || true)
if [[ -n "$head_ref" ]]; then
  if [[ "$head_ref" != refs/remotes/origin/* ]] || ! git show-ref --verify --quiet "$head_ref"; then
    echo 'branch model: origin/HEAD does not identify an existing remote branch' >&2
    exit 1
  fi
  trunk=${head_ref#refs/remotes/origin/}
else
  trunk=''
  for candidate in main master; do
    if git show-ref --verify --quiet "refs/remotes/origin/$candidate"; then
      if [[ -n "$trunk" ]]; then
        echo 'branch model: origin/HEAD is missing and main and master both exist' >&2
        exit 1
      fi
      trunk=$candidate
    fi
  done
  if [[ -z "$trunk" ]]; then
    echo 'branch model: no remote default branch found' >&2
    exit 1
  fi
fi
printf 'flow=github\ntrunk=%s\n' "$trunk"
