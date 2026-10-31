#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd -P)"
dest="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$dest"
for skill in "$repo_root"/skills/*; do
  [[ -f "$skill/SKILL.md" ]] || continue
  target="$dest/$(basename "$skill")"
  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -L "$target" && "$(readlink "$target")" == "$skill" ]]; then continue; fi
    printf 'Already exists; not replacing: %s\n' "$target" >&2
    exit 1
  fi
done
for skill in "$repo_root"/skills/*; do
  [[ -f "$skill/SKILL.md" ]] || continue
  target="$dest/$(basename "$skill")"
  [[ -L "$target" ]] || ln -s "$skill" "$target"
done
printf 'Installed skills in %s\n' "$dest"
