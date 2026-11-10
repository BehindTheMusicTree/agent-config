#!/usr/bin/env bash
# PreToolUse hook: keep graphify graphs fresh at read time. Never blocks, always exits 0.
set -u
trap 'exit 0' ERR

input=$(cat)
command -v graphify >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

parsed=$(printf '%s' "$input" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("cwd") or "")
print(d.get("tool_name") or "")
' 2>/dev/null) || exit 0
cwd=$(printf '%s\n' "$parsed" | sed -n 1p)
tool=$(printf '%s\n' "$parsed" | sed -n 2p)
[ -n "$cwd" ] || exit 0

case "$tool" in
  Bash|Grep) kind=search ;;
  Read|Glob) kind="read" ;;
  *) exit 0 ;;
esac

top=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || exit 0
main=$(git -C "$top" worktree list --porcelain | sed -n 's/^worktree //p' | sed -n 1p)
# Opt-in: only repos whose main checkout already has a graph.
[ -f "$main/graphify-out/graph.json" ] || exit 0

out="$top/graphify-out"
if [ "$top" != "$main" ] && [ ! -d "$out" ]; then
  mkdir -p "$out"
  src="$main/graphify-out"
  for f in graph.json manifest.json GRAPH_REPORT.md .graphify_*; do
    [ -e "$src/$f" ] && cp -R "$src/$f" "$out/"
  done
  [ -d "$src/cache" ] && cp -R "$src/cache" "$out/"
fi
[ -d "$out" ] || exit 0

head_sha=$(git -C "$top" rev-parse HEAD)
diff_sum=$(git -C "$top" diff HEAD --no-ext-diff -- . ':!graphify-out' | shasum -a 256 | cut -d' ' -f1)
untracked_sum=$(git -C "$top" ls-files -o --exclude-standard | { grep -v '^graphify-out/' || true; } | shasum -a 256 | cut -d' ' -f1)
key="$head_sha:$(printf '%s%s' "$diff_sum" "$untracked_sum" | shasum -a 256 | cut -d' ' -f1)"

if [ -f "$out/.fresh-key" ] && [ "$(cat "$out/.fresh-key")" = "$key" ]; then
  cd "$top" && printf '%s' "$input" | graphify hook-guard "$kind"
  exit 0
fi

lock="$out/.refresh.lock"
if [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
  rmdir "$lock" 2>/dev/null || true
fi
if mkdir "$lock" 2>/dev/null; then
  (
    trap '' HUP
    cd "$top" || exit 0
    if GRAPHIFY_NO_BACKUP=1 graphify update . >"$out/refresh.log" 2>&1; then
      printf '%s' "$key" >"$out/.fresh-key"
    fi
    rmdir "$lock" 2>/dev/null || true
  ) >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

if [ "$(cat "$out/.notified-key" 2>/dev/null)" != "$key" ]; then
  printf '%s' "$key" >"$out/.notified-key"
  built=an\ older\ commit
  [ -f "$out/.fresh-key" ] && built=$(cut -c1-8 "$out/.fresh-key")
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"graphify graph is refreshing in the background (built for %s); use rg/Read for now."}}' "$built"
fi
exit 0
