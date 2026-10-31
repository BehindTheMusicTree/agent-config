#!/usr/bin/env bash
# Cleans dev leftovers for the current repo: merged branches + their worktrees
# (delegated to clean-repos.sh, scoped to this repo), then docker leftovers.
#
# Usage:
#   cleanup-session.sh scan  [clean-repos flags] [--no-docker]
#   cleanup-session.sh apply [clean-repos flags] [--no-docker]
set -euo pipefail

mode="${1:?usage: cleanup-session.sh <scan|apply> [flags]}"
shift
docker_on=true
flags=()
for a in "$@"; do
  [[ "$a" == "--no-docker" ]] && docker_on=false || flags+=("$a")
done

common="$(git rev-parse --path-format=absolute --git-common-dir)"
repo="$(dirname "$common")"
[[ -d "$common" && "$(basename "$common")" == ".git" ]] || { echo "status=blocked reason=not-a-standard-repo" >&2; exit 1; }
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== branches/worktrees: $(basename "$repo")"
"$here/clean-repos.sh" "$mode" "$(dirname "$repo")" --only-repo "$(basename "$repo")" ${flags[@]+"${flags[@]}"}

echo "== docker"
if ! $docker_on; then echo "skipped: --no-docker"; exit 0; fi
if ! command -v docker >/dev/null 2>&1 ; then echo "skipped: docker unavailable"; exit 0; fi
# macOS has no `timeout` and docker (Go) ignores SIGALRM: background it, SIGKILL on deadline.
deadline() {
  local secs=$1; shift
  "$@" & local pid=$!
  for ((i = 0; i < secs; i++)); do kill -0 "$pid" 2>/dev/null || { wait "$pid"; return; }; sleep 1; done
  kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124
}
if ! deadline 15 docker info >/dev/null 2>&1; then
  if command -v docker-unstick >/dev/null 2>&1; then
    echo "docker unresponsive: running docker-unstick"
    docker-unstick 2>&1 | tail -3 || true
  fi
  deadline 15 docker info >/dev/null 2>&1 || { echo "skipped: docker unresponsive"; exit 0; }
fi

wt_root="$repo/.claude/worktrees/"
projects=()
ps_out="$(mktemp)"; trap 'rm -f "$ps_out"' EXIT
deadline 30 docker ps -a --format '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}' > "$ps_out" \
  || { echo "skipped: docker unresponsive"; exit 0; }
while IFS=$'\t' read -r proj dir; do
  [[ -n "$proj" && "$dir" == "$wt_root"* ]] || continue
  # Machine-wide stacks (e.g. a shared S3) can be started from a worktree; only down those named after it.
  slug="${dir#"$wt_root"}"; slug="${slug%%/*}"
  if [[ "$proj" != *"$slug"* ]]; then
    echo "compose-project=$proj skipped=shared (name not tied to worktree $slug)"
    continue
  fi
  [[ "$mode" == apply && -d "$dir" ]] && continue
  projects+=("$proj")
  echo "compose-project=$proj dir=$([[ -d "$dir" ]] && echo exists || echo gone)"
done < <(sort -u "$ps_out")

if [[ "$mode" == scan ]]; then
  echo "stopped-containers=$(docker ps -aq -f status=exited -f status=created | wc -l | tr -d ' ')"
  echo "dangling-images=$(docker images -q -f dangling=true | wc -l | tr -d ' ')"
  echo "note: apply also prunes unused networks; compose projects with dir=exists are downed only once their worktree is removed"
  exit 0
fi

for p in ${projects[@]+"${projects[@]}"}; do
  docker compose -p "$p" down -v --remove-orphans 2>&1 | tail -3
done
docker container prune -f | tail -1
docker image prune -f | tail -1
docker network prune -f | tail -1
