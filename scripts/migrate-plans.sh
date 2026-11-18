#!/usr/bin/env bash
# Move legacy <worktree>/.agent-plans/ contents into the central plan directory
# <git-common-dir>/agent-plans/<repo>-<branch>/ (keys as in clean-repos.sh).
# Dry run by default; --apply moves files. Existing destination files are never
# overwritten (the source is kept and reported). Commits nothing.
set -euo pipefail

apply=false
if [[ "${1:-}" == "--apply" ]]; then apply=true; shift; fi
root="${1:-}"
[[ $# -eq 1 && -d "$root" ]] || { echo "usage: migrate-plans.sh [--apply] <root>" >&2; exit 2; }

key() { printf '%s' "$1" | LC_ALL=C tr -c 'A-Za-z0-9._-' '-' | tr -s '-'; }

moved=0 kept=0 dirs=0
while IFS= read -r -d '' plans; do
  wt="${plans%/.agent-plans}"
  common="$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || { echo "skip $plans: not in a git worktree" >&2; continue; }
  repo="$(basename "$(dirname "$common")")"
  branch="$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null)" \
    || branch="detached-$(git -C "$wt" rev-parse --short HEAD)" \
      || { echo "skip $plans: no commit" >&2; continue; }
  dest="$common/agent-plans/$(key "$repo")-$(key "$branch")"
  dirs=$((dirs + 1))
  leftover=false
  while IFS= read -r -d '' src; do
    rel="${src#"$plans"/}"
    [[ "$rel" == ".gitignore" ]] && continue
    if [[ -e "$dest/$rel" ]]; then
      echo "keep   $src (exists: $dest/$rel)"; kept=$((kept + 1)); leftover=true; continue
    fi
    echo "move   $src -> $dest/$rel"
    if $apply; then
      mkdir -p "$(dirname "$dest/$rel")"
      mv "$src" "$dest/$rel"
    fi
    moved=$((moved + 1))
  done < <(find "$plans" -type f -print0 | sort -z)
  if $apply && ! $leftover; then
    rm -f "$plans/.gitignore"
    find "$plans" -depth -type d -empty -delete
  fi
done < <(find "$root" -maxdepth 6 -type d -name .agent-plans -not -path '*/node_modules/*' -print0 | sort -z)

mode=dry-run; $apply && mode=apply
echo "migrate-plans mode=$mode dirs=$dirs moved=$moved kept=$kept"
