#!/usr/bin/env bash
# PreToolUse hook: keep graphify graphs fresh at read time. Never blocks, always exits 0.
# Usage: graphify-fresh.sh [--client claude|codex]. The codex client only seeds and refreshes
# the graph, in silence: Codex Desktop rejects additionalContext on PreToolUse, so its agent is
# steered by the graphify skill and the Codex instructions instead.
# The claude client also tells each session once how to use the graph. It does not delegate to
# `graphify hook-guard`, whose per-call nudge is ignored after the first few calls and contradicts
# the refresh notice while the agent edits.
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
import json, os, sys
d = json.load(sys.stdin)
cwd = d.get("cwd") or ""
tool = d.get("tool_name") or ""
ti = d.get("tool_input") or {}
# Read/Grep/Glob name their target in structured fields; Bash commands are not parsed.
p = ti.get("file_path") if tool == "Read" else ti.get("path") if tool in ("Grep", "Glob") else None
target = cwd
if isinstance(p, str) and p:
    p = p if os.path.isabs(p) else os.path.join(cwd, p)
    target = p if os.path.isdir(p) else os.path.dirname(p)
    while target and not os.path.isdir(target) and os.path.dirname(target) != target:
        target = os.path.dirname(target)
print(cwd)
print(tool)
print(d.get("session_id") or "")
print(target)
' 2>/dev/null) || exit 0
cwd=$(printf '%s\n' "$parsed" | sed -n 1p)
tool=$(printf '%s\n' "$parsed" | sed -n 2p)
session=$(printf '%s\n' "$parsed" | sed -n 3p)
target=$(printf '%s\n' "$parsed" | sed -n 4p)
[ -n "$cwd" ] || exit 0

case "$tool" in
  Bash|Grep|Read|Glob) ;;
  *) exit 0 ;;
esac

top=$(git -C "$target" rev-parse --show-toplevel 2>/dev/null) || exit 0
main=$(git -C "$top" worktree list --porcelain | sed -n 's/^worktree //p' | sed -n 1p)
# Opt-in: only repos that gitignore graphify-out/ (versioned signal; a graph is built if absent).
git -C "$top" check-ignore -q graphify-out/graph.json || exit 0

out="$top/graphify-out"
seed_from=
if [ "$top" != "$main" ] && [ ! -d "$out" ] && [ -f "$main/graphify-out/graph.json" ]; then
  seed_from="$main/graphify-out"
fi
mkdir -p "$out"

head_sha=$(git -C "$top" rev-parse HEAD)
diff_sum=$(git -C "$top" diff HEAD --no-ext-diff -- . ':!graphify-out' | shasum -a 256 | cut -d' ' -f1)
untracked_sum=$(cd "$top" && git ls-files -o --exclude-standard | { grep -v '^graphify-out/' || true; } | tr '\n' '\0' | { xargs -0 shasum -a 256 2>/dev/null || true; } | shasum -a 256 | cut -d' ' -f1)
key="$head_sha:$(printf '%s%s' "$diff_sum" "$untracked_sum" | shasum -a 256 | cut -d' ' -f1)"

if [ -n "$seed_from" ] || [ "$(cat "$out/.fresh-key" 2>/dev/null)" != "$key" ]; then
  lock="$out/.refresh.lock"
  if [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
    rmdir "$lock" 2>/dev/null || true
  fi
  if { [ -n "$seed_from" ] || [ "$(cat "$out/.failed-key" 2>/dev/null)" != "$key" ]; } && mkdir "$lock" 2>/dev/null; then
    (
      trap '' HUP
      cd "$top" || exit 0
      if [ -n "$seed_from" ]; then
        for f in graph.json manifest.json GRAPH_REPORT.md .graphify_*; do
          [ -e "$seed_from/$f" ] && cp -R "$seed_from/$f" "$out/"
        done
        [ -d "$seed_from/cache" ] && cp -R "$seed_from/cache" "$out/"
      fi
      if GRAPHIFY_NO_BACKUP=1 graphify update . >"$out/refresh.log" 2>&1; then
        printf '%s' "$key" >"$out/.fresh-key"
      else
        printf '%s' "$key" >"$out/.failed-key"
      fi
      rmdir "$lock" 2>/dev/null || true
    ) </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
  fi
fi

[ "$client" = claude ] || exit 0
[ -n "$session" ] || exit 0

# One notice per session and graph state: a session that starts during the first build is told
# again once the graph exists.
state=ready
[ -f "$out/graph.json" ] || state=building
marker="$session:$state"
[ "$(cat "$out/.notified-session" 2>/dev/null)" = "$marker" ] && exit 0
printf '%s' "$marker" >"$out/.notified-session"

if [ "$state" = building ]; then
  msg="The repository at $top has its graphify graph built for the first time (or seeded from the main checkout) in the background; use rg/Read for now."
else
  msg="The repository at $top has a graphify knowledge graph in graphify-out/, refreshed in the background after edits; run graphify from that directory. Use it for structure questions (modules, dependencies, how concepts connect): graphify query '<specific question>' --budget 800, graphify explain '<path>::<symbol>', graphify path '<A>' '<B>'. Use rg/Read for function bodies, exact call sites and line-level work: the graph is static and misses calls resolved at runtime. This note is shown once per session."
fi
MSG="$msg" python3 -c '
import json, os
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": os.environ["MSG"]}}), end="")
'
exit 0
