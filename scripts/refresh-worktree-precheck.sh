#!/usr/bin/env bash
# Helper for the refresh-worktree command. Two subcommands:
#
#   refresh-worktree-precheck.sh precheck
#     Runs the non-destructive steps of a worktree refresh in order: detect
#     flow/trunk, stop this worktree's dev server(s), verify the current
#     branch, verify a clean tree, verify it's fully merged into trunk, then
#     fast-forward trunk. Stops at the first step that needs a human call and
#     reports why. Never deletes a branch, never touches uncommitted changes.
#     Prints key=value lines; final line is always `status=ok` or
#     `status=blocked reason=<reason>`.
#
#   refresh-worktree-precheck.sh check-port <port>
#     Reports whether a TCP port is free, held by a process in this worktree,
#     or held by something else. Prints key=value lines.
#
#   refresh-worktree-precheck.sh check-env-var <VARNAME> <project-dir>
#     Reports whether <project-dir>/.env already defines VARNAME. Use this
#     before prefixing an env var override (e.g. PORT=3001) onto a *combined*
#     multi-project command — dotenv doesn't override an already-set env var,
#     so a shell-level PORT=3001 leaks into every project the command launches,
#     silently hijacking any other project's own .env PORT instead of just the
#     one you meant to override. Prints `defines_<VARNAME>=true|false`.
#
# Run from inside the worktree to refresh.
set -uo pipefail

cmd="${1:?usage: refresh-worktree-precheck.sh <precheck|check-port> [args]}"
shift

case "$cmd" in
  precheck)
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

    wtdir="$(pwd)"
    killed=()
    while read -r pid; do
      [[ -z "$pid" ]] && continue
      cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)
      if [[ "$cwd" == "$wtdir"* ]]; then
        kill "$pid" 2>/dev/null && killed+=("$pid")
      fi
    done < <(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | sort -u)
    if [[ ${#killed[@]} -gt 0 ]]; then
      echo "killed_pids=${killed[*]}"
    else
      echo "killed_pids=none"
    fi

    old_branch="$(git branch --show-current)"
    if [[ -z "$old_branch" ]]; then
      echo "status=blocked reason=detached-head"
      exit 0
    fi
    echo "old_branch=$old_branch"

    dirty="$(git status --short)"
    if [[ -n "$dirty" ]]; then
      echo "status=blocked reason=dirty-tree"
      echo "$dirty" | sed 's/^/dirty_file=/'
      exit 0
    fi

    if ! git fetch origin >/dev/null 2>&1; then
      echo "status=blocked reason=fetch-failed"
      exit 0
    fi

    if ! git diff --exit-code "origin/$trunk" HEAD >/dev/null 2>&1; then
      echo "status=blocked reason=not-merged"
      exit 0
    fi
    echo "merged=true"

    if ! git switch "$trunk" >/dev/null 2>&1; then
      echo "status=blocked reason=switch-trunk-failed"
      exit 0
    fi
    if ! git pull --ff-only origin "$trunk" >/dev/null 2>&1; then
      echo "status=blocked reason=trunk-diverged"
      exit 0
    fi
    echo "trunk_updated=true"
    echo "status=ok"
    ;;

  check-port)
    port="${1:?usage: refresh-worktree-precheck.sh check-port <port>}"
    wtdir="$(pwd)"
    listener="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')"
    echo "port=$port"
    if [[ -z "$listener" ]]; then
      echo "status=free"
      exit 0
    fi
    cwd=$(lsof -a -p "$listener" -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)
    if [[ "$cwd" == "$wtdir"* ]]; then
      echo "status=occupied-in-worktree"
    else
      echo "status=occupied-other"
    fi
    echo "cwd=$cwd"
    ;;

  check-env-var)
    varname="${1:?usage: refresh-worktree-precheck.sh check-env-var <VARNAME> <project-dir>}"
    projdir="${2:?usage: refresh-worktree-precheck.sh check-env-var <VARNAME> <project-dir>}"
    echo "var=$varname"
    echo "dir=$projdir"
    if [[ -f "$projdir/.env" ]] && grep -qE "^${varname}=" "$projdir/.env"; then
      echo "defines_${varname}=true"
    else
      echo "defines_${varname}=false"
    fi
    ;;

  *)
    echo "Unknown subcommand: $cmd" >&2
    exit 1
    ;;
esac
