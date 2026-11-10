#!/usr/bin/env bash
# PreToolUse hook: keep graphify graphs fresh at read time. Never blocks, always exits 0.
# Usage: graphify-fresh.sh [--client claude|codex]. The codex client only seeds and refreshes
# the graph, in silence: Codex Desktop rejects additionalContext on PreToolUse, so its agent is
# steered by the graphify skill and the Codex instructions instead.
set -u
trap 'exit 0' ERR

client=claude
if [ $# -gt 0 ]; then
  [ "$1" = "--client" ] || exit 0
  client=${2:-}
fi
case "$client" in
  claude|codex) ;;
  *) exit 0 ;;
esac

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
# Opt-in: only repos that gitignore graphify-out/ (versioned signal; a graph is built if absent).
git -C "$top" check-ignore -q graphify-out/graph.json || exit 0

out="$top/graphify-out"
if [ "$top" != "$main" ] && [ ! -d "$out" ] && [ -f "$main/graphify-out/graph.json" ]; then
  mkdir -p "$out"
  src="$main/graphify-out"
  for f in graph.json manifest.json GRAPH_REPORT.md .graphify_*; do
    [ -e "$src/$f" ] && cp -R "$src/$f" "$out/"
  done
  [ -d "$src/cache" ] && cp -R "$src/cache" "$out/"
fi
mkdir -p "$out"

head_sha=$(git -C "$top" rev-parse HEAD)
diff_sum=$(git -C "$top" diff HEAD --no-ext-diff -- . ':!graphify-out' | shasum -a 256 | cut -d' ' -f1)
untracked_sum=$(cd "$top" && git ls-files -o --exclude-standard | { grep -v '^graphify-out/' || true; } | tr '\n' '\0' | { xargs -0 shasum -a 256 2>/dev/null || true; } | shasum -a 256 | cut -d' ' -f1)
key="$head_sha:$(printf '%s%s' "$diff_sum" "$untracked_sum" | shasum -a 256 | cut -d' ' -f1)"

if [ -f "$out/.fresh-key" ] && [ "$(cat "$out/.fresh-key")" = "$key" ]; then
  [ "$client" = claude ] && cd "$top" && printf '%s' "$input" | graphify hook-guard "$kind"
  exit 0
fi

lock="$out/.refresh.lock"
if [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
  rmdir "$lock" 2>/dev/null || true
fi
if [ "$(cat "$out/.failed-key" 2>/dev/null)" != "$key" ] && mkdir "$lock" 2>/dev/null; then
  (
    trap '' HUP
    cd "$top" || exit 0
    if GRAPHIFY_NO_BACKUP=1 graphify update . >"$out/refresh.log" 2>&1; then
      printf '%s' "$key" >"$out/.fresh-key"
    else
      printf '%s' "$key" >"$out/.failed-key"
    fi
    rmdir "$lock" 2>/dev/null || true
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

[ "$client" = claude ] || exit 0

if [ "$(cat "$out/.notified-key" 2>/dev/null)" != "$key" ]; then
  printf '%s' "$key" >"$out/.notified-key"
  if [ ! -f "$out/graph.json" ]; then
    msg="graphify graph is being built for the first time; use rg/Read for now."
  else
    built=an\ older\ commit
    [ -f "$out/.fresh-key" ] && built=$(cut -c1-8 "$out/.fresh-key")
    msg="graphify graph is refreshing in the background (built for $built); use rg/Read for now."
  fi
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"%s"}}' "$msg"
fi
exit 0
