#!/usr/bin/env bash
# Detects whether this repo follows strict Gitflow or GitHub flow, and its trunk branch.
# Prints `flow=gitflow|github` and `trunk=<branch>`.
set -euo pipefail

trunk="main"
git show-ref --verify --quiet refs/remotes/origin/master && trunk="master"

flow="github"
if git show-ref --verify --quiet refs/remotes/origin/develop \
   || git config --get-regexp '^gitflow\.' >/dev/null 2>&1 \
   || grep -riqE 'gitflow|git flow|release branch|hotfix branch' CONTRIBUTING.md CLAUDE.md AGENTS.md README.md 2>/dev/null \
   || git branch -a --format='%(refname:short)' | grep -qE '(release|hotfix)/'; then
  flow="gitflow"
  trunk="develop"
fi

echo "flow=$flow"
echo "trunk=$trunk"
