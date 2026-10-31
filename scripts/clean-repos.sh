#!/usr/bin/env bash
# Scans (or cleans) merged branches and their worktrees across every git repo
# found directly under a root directory (e.g. ~/git/*). `scan` and `apply`
# share the exact same candidate-selection logic so what gets shown in `scan`
# is exactly what `apply` acts on — re-derived fresh at apply time (fresh
# fetch, fresh merge check) rather than passed back as a fragile branch list,
# since state can drift in the time it takes a human to read the plan.
#
# Usage:
#   clean-repos.sh scan  [git-root] [options]
#   clean-repos.sh apply [git-root] [options]
#
# Options (repeatable where noted):
#   --exclude <branch>       never touch this branch name, in any repo
#   --only-repo <name>       limit to this repo (repeatable)
#   --exclude-repo <name>    skip this repo (repeatable)
#   --local-only              skip remote branch deletion
#   --remote-only              skip local branch deletion
#
# git-root defaults to ~/git.
set -euo pipefail

mode="${1:?usage: clean-repos.sh <scan|apply> [git-root] [options]}"
shift
git_root="$HOME/git"
if [[ $# -gt 0 && "$1" != --* ]]; then
  git_root="$1"
  shift
fi
[[ -d "$git_root" ]] || { echo "git-root not found: $git_root" >&2; exit 1; }

local_only=false
remote_only=false
excludes=()
only_repos=()
exclude_repos=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --exclude) excludes+=("$2"); shift 2 ;;
    --only-repo) only_repos+=("$2"); shift 2 ;;
    --exclude-repo) exclude_repos+=("$2"); shift 2 ;;
    --local-only) local_only=true; shift ;;
    --remote-only) remote_only=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

contains() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
  return 1
}

# Direct tree comparison (tree(branch) vs tree(mergeCommit)) produces false
# negatives once trunk has had other PRs merged after this squash-merge
# landed: mergeCommit's tree then carries that later content too, so it no
# longer matches the branch's tree even though the branch's own change is
# still fully represented on trunk. Isolate each side's own patch instead —
# diff the branch against its own merge-base with trunk, and diff the merge
# commit against its parent (a squash commit has one parent) or between its
# two parents (a real, non-squash merge commit has two — comparing it to a
# single "parent" would just show trunk's own history, not the PR's diff).
# Matching patch-ids mean the branch's own change is fully represented on
# trunk, independent of anything unrelated merged afterward.
patch_id_equivalent() {
  local b="$1" oid="$2" mb pid_a pid_b parents
  mb="$(git merge-base "$b" "origin/$trunk" 2>/dev/null)" || return 1
  [[ -n "$mb" ]] || return 1
  pid_a="$(git diff "$mb" "$b" -- 2>/dev/null | git patch-id --stable 2>/dev/null | awk '{print $1}')"
  parents="$(git cat-file -p "$oid" 2>/dev/null | grep -c '^parent ' || true)"
  if [[ "$parents" -gt 1 ]]; then
    pid_b="$(git diff "${oid}^1" "${oid}^2" -- 2>/dev/null | git patch-id --stable 2>/dev/null | awk '{print $1}')"
  else
    pid_b="$(git diff "${oid}^" "$oid" -- 2>/dev/null | git patch-id --stable 2>/dev/null | awk '{print $1}')"
  fi
  [[ -n "$pid_a" && "$pid_a" == "$pid_b" ]]
}

# patch_id_equivalent only tests one hypothesis: the branch's *entire*
# merge-base..tip diff matches *one* PR's merge commit. That misses branches
# whose tip carries commits from several separate merges (e.g. a squashed fix
# plus a later chore commit that itself landed on trunk as a different,
# non-identical commit) — the aggregate diff then matches no single merge
# commit even though every individual change is on trunk. `git cherry` already
# does per-commit patch-id matching walking the branch's unique history, so
# fall back to it: every commit unique to the branch (vs trunk) is marked '-'
# (equivalent patch found upstream) rather than '+' (not found) only when the
# branch's full contents are represented on trunk, regardless of how many
# separate commits/PRs they arrived as.
branch_fully_cherry_merged() {
  local b="$1" out
  out="$(git cherry "origin/$trunk" "$b" 2>/dev/null)" || return 1
  [[ -n "$out" ]] || return 1
  ! grep -q '^+' <<<"$out"
}

# Last-resort tree-level check: simulate merging the branch into trunk. If the
# result is identical to trunk's tree, the branch adds nothing trunk lacks —
# covers squash merges with edited messages/fixups that patch-id can't match.
# Conflicts (non-zero exit) or a differing tree stay unverified.
branch_adds_nothing_to_trunk() {
  local b="$1" merged trunk_tree
  merged="$(git merge-tree --write-tree "origin/$trunk" "$b" 2>/dev/null)" || return 1
  trunk_tree="$(git rev-parse "origin/$trunk^{tree}" 2>/dev/null)" || return 1
  [[ "$(head -1 <<<"$merged")" == "$trunk_tree" ]]
}

# A worktree branch with zero commits ahead of trunk is ambiguous: it could be
# a brand-new worktree whose branch was created but never worked in, or a
# branch whose real work is fully merged/squashed back into trunk. Both look
# identical by ancestry alone. The branch's own reflog disambiguates: a branch
# that was only ever created (never committed to) has exactly one reflog
# entry, "branch: Created from ...". Anything else means it had commits at
# some point, so its removal is "real" work being cleaned up, not a no-op.
worktree_branch_is_new_empty() {
  local br="$1" reflog
  reflog="$(git reflog show "$br" 2>/dev/null)"
  [[ "$(wc -l <<<"$reflog" | tr -d ' ')" == "1" ]] && grep -q 'branch: Created from' <<<"$reflog"
}

scanned=0; with_candidates=0; clean=0; errors=0
deleted_local=0; deleted_remote=0; removed_worktrees=0; skipped=0

for repo in "$git_root"/*/; do
  repo="${repo%/}"
  [[ -d "$repo/.git" ]] || continue
  name="$(basename "$repo")"

  [[ ${#only_repos[@]} -gt 0 ]] && ! contains "$name" "${only_repos[@]}" && continue
  [[ ${#exclude_repos[@]} -gt 0 ]] && contains "$name" "${exclude_repos[@]}" && continue

  scanned=$((scanned + 1))
  cd "$repo"

  if ! git fetch --prune origin >/dev/null 2>&1; then
    echo "repo=$name status=fetch-failed"
    errors=$((errors + 1))
    continue
  fi

  # Trust actual remote refs over naming heuristics — a repo can adopt
  # git-flow-style branch names (docs, feature/* prefixes) without ever
  # having pushed a develop branch, which would otherwise misfire "gitflow"
  # and point at a trunk ref that doesn't exist.
  flow="github"
  trunk="main"
  git show-ref --verify --quiet refs/remotes/origin/master && trunk="master"
  if git show-ref --verify --quiet refs/remotes/origin/develop; then
    flow="gitflow"
    trunk="develop"
  fi

  if ! git show-ref --verify --quiet "refs/remotes/origin/$trunk"; then
    echo "repo=$name status=no-trunk"
    errors=$((errors + 1))
    continue
  fi

  current_branch="$(git branch --show-current)"

  # Use the full refname and strip refs/heads/ ourselves rather than
  # %(refname:short): a local branch whose name collides with a remote name
  # (e.g. a stray branch literally called "origin") gets disambiguated by
  # :short into "heads/origin", which git branch -d then rejects outright.
  mapfile -t local_candidates < <(git branch --merged "origin/$trunk" --format='%(refname)' \
    | sed -n 's#^refs/heads/##p' | grep -vE "^($trunk|main|master|develop|HEAD|$current_branch)$" || true)

  mapfile -t remote_candidates < <(git branch -r --merged "origin/$trunk" --format='%(refname:short)' \
    | sed -n 's#^origin/##p' | grep -vE "^($trunk|main|master|develop|HEAD)$" || true)

  # Squash-merged PRs never land as an ancestor of trunk, so --merged above
  # misses them (common under GitHub flow). Cross-check via gh, best-effort —
  # but keep these in separate buckets (local_squash_verified/unverified) rather than
  # folding them into local_candidates: `git branch -d` verifies ancestry
  # against trunk, and a squash-merged branch structurally never satisfies
  # that (the squash creates a new commit trunk-side), so -d will always
  # refuse it. Reporting it identically to a real --merged candidate in scan
  # promised a deletion apply could never deliver, and the resulting "skip
  # ... not-fully-merged" read as a false claim when gh had just said the PR
  # *was* merged. Keeping the bucket distinct lets both modes describe it
  # accurately instead of retrying a check that's guaranteed to fail.
  local_squash_verified=()
  local_squash_unverified=()
  if command -v gh >/dev/null 2>&1 && gh repo view >/dev/null 2>&1; then
    # A branch name can be reused across several merged PRs over time (e.g.
    # feature/x merged, then reopened and merged again later). Collect every
    # merge-commit oid gh reports for a given headRefName before deciding
    # verified/unverified, instead of classifying per PR row as they stream
    # in — otherwise the same branch can land in both buckets depending on
    # which merge commit happened to be checked last.
    declare -A branch_oids=()
    while IFS=$'\t' read -r b head_oid oid; do
      [[ -z "$b" ]] && continue
      branch_oids["$b"]="${branch_oids[$b]:-}${branch_oids[$b]:+ }$oid"
      # A branch name reused after its PR merged (e.g. a bot force-pushing one stable name) carries new, unmerged
      # commits: only treat the remote as merged when its tip is exactly what the PR merged.
      [[ "$(git rev-parse -q --verify "refs/remotes/origin/$b" 2>/dev/null)" == "$head_oid" ]] && remote_candidates+=("$b")
    done < <(gh pr list --state merged --base "$trunk" --json headRefName,mergeCommit,headRefOid \
      --jq '.[] | "\(.headRefName)\t\(.headRefOid)\t\(.mergeCommit.oid // "")"' --limit 100 2>/dev/null || true)

    for b in "${!branch_oids[@]}"; do
      git show-ref --verify --quiet "refs/heads/$b" || continue
      [[ "$b" != "$current_branch" ]] || continue
      contains "$b" "${local_candidates[@]}" && continue
      # A squash merge lands as a new commit on trunk, so this branch is
      # never a git ancestor of trunk and --merged above can't see it.
      # `gh` confirming the PR merged only proves headRefName matched at
      # merge time — it says nothing about whether the local branch has
      # since picked up extra commits. Compare each side's own patch (see
      # patch_id_equivalent above): a match on any of the branch's merge
      # commits means nothing would be lost, so it's safe to auto -D;
      # otherwise fall back to manual review.
      verified=false
      for oid in ${branch_oids[$b]}; do
        if [[ -n "$oid" ]] && git cat-file -e "$oid" 2>/dev/null \
           && patch_id_equivalent "$b" "$oid"; then
          verified=true
          break
        fi
      done
      if [[ "$verified" == true ]] || branch_fully_cherry_merged "$b" \
         || branch_adds_nothing_to_trunk "$b"; then
        local_squash_verified+=("$b")
      else
        local_squash_unverified+=("$b")
      fi
    done
  fi

  # Re-apply the trunk/main/master/develop/HEAD safety exclusion here, not just
  # to the --merged-based list above: the gh cross-check below appends branch
  # names from PR headRefName unfiltered, and a real "sync main back into
  # develop" PR has headRefName=main — without this, that would let the
  # protected trunk names back into the candidate list.
  mapfile -t local_candidates < <(printf '%s\n' "${local_candidates[@]}" \
    | grep -vE "^($trunk|main|master|develop|HEAD|$current_branch)$" | grep -v '^$' | sort -u || true)
  mapfile -t local_squash_verified < <(printf '%s\n' "${local_squash_verified[@]}" \
    | grep -vE "^($trunk|main|master|develop|HEAD|$current_branch)$" | grep -v '^$' | sort -u || true)
  mapfile -t local_squash_unverified < <(printf '%s\n' "${local_squash_unverified[@]}" \
    | grep -vE "^($trunk|main|master|develop|HEAD|$current_branch)$" | grep -v '^$' | sort -u || true)
  mapfile -t remote_candidates < <(printf '%s\n' "${remote_candidates[@]}" \
    | grep -vE "^($trunk|main|master|develop|HEAD)$" | grep -v '^$' | sort -u || true)

  # A branch with an open PR is never cleanup material, even if an earlier PR under the same name merged.
  mapfile -t open_pr_branches < <(gh pr list --state open --json headRefName --jq '.[].headRefName' --limit 200 2>/dev/null || true)
  drop_open_pr_branches() {
    local b
    for b in "$@"; do
      contains "$b" "${open_pr_branches[@]}" || echo "$b"
    done
  }
  mapfile -t local_candidates < <(drop_open_pr_branches "${local_candidates[@]}")
  mapfile -t local_squash_verified < <(drop_open_pr_branches "${local_squash_verified[@]}")
  mapfile -t local_squash_unverified < <(drop_open_pr_branches "${local_squash_unverified[@]}")
  mapfile -t remote_candidates < <(drop_open_pr_branches "${remote_candidates[@]}")

  $local_only && remote_candidates=()
  $remote_only && local_candidates=() && local_squash_verified=() && local_squash_unverified=()

  kept_local=()
  for b in "${local_candidates[@]}"; do
    contains "$b" "${excludes[@]}" || kept_local+=("$b")
  done
  kept_local_squash_verified=()
  for b in "${local_squash_verified[@]}"; do
    contains "$b" "${excludes[@]}" || kept_local_squash_verified+=("$b")
  done
  kept_local_squash_unverified=()
  for b in "${local_squash_unverified[@]}"; do
    contains "$b" "${excludes[@]}" || kept_local_squash_unverified+=("$b")
  done
  kept_remote=()
  for b in "${remote_candidates[@]}"; do
    contains "$b" "${excludes[@]}" || kept_remote+=("$b")
  done

  # Worktrees tied to a now-merged local branch (skip the main worktree, i.e. $repo itself).
  worktree_paths=()
  worktree_branches=()
  current_path=""
  while IFS= read -r line; do
    if [[ "$line" == worktree\ * ]]; then
      current_path="${line#worktree }"
    elif [[ "$line" == branch\ refs/heads/* ]]; then
      br="${line#branch refs/heads/}"
      if [[ "$current_path" != "$repo" ]]; then
        worktree_paths+=("$current_path")
        worktree_branches+=("$br")
      fi
    fi
  done < <(git worktree list --porcelain)

  # A branch can look fully merged (zero commits ahead of trunk — e.g. it was
  # created off trunk and trunk simply moved past it) while its worktree still
  # holds real, uncommitted edits. Deleting the branch/worktree in that case
  # would discard work that was never merged, just never committed. Detect
  # that before deciding what to remove, and pull the branch out of the
  # deletion candidates entirely — the worktree is the only ref holding it.
  # A branch that was only ever created, never committed to, isn't "merged"
  # work — it just trivially satisfies the ancestry check because it has zero
  # commits. Deleting it could throw away a workspace someone set up to start
  # on, not a completed task. Protect it the same way as a dirty worktree:
  # pull it out of every deletion candidate list, report it separately.
  dirty_worktrees=()
  new_empty_worktrees=()
  protected_branches=()
  for i in "${!worktree_branches[@]}"; do
    br="${worktree_branches[$i]}"
    path="${worktree_paths[$i]}"
    (contains "$br" "${kept_local[@]}" || contains "$br" "${kept_local_squash_verified[@]}" \
      || contains "$br" "${kept_local_squash_unverified[@]}") || continue
    if [[ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]]; then
      dirty_worktrees+=("$path:$br")
      protected_branches+=("$br")
    elif worktree_branch_is_new_empty "$br"; then
      new_empty_worktrees+=("$path:$br")
      protected_branches+=("$br")
    fi
  done
  if [[ ${#protected_branches[@]} -gt 0 ]]; then
    tmp=()
    for b in "${kept_local[@]}"; do contains "$b" "${protected_branches[@]}" || tmp+=("$b"); done
    kept_local=("${tmp[@]}")
    tmp=()
    for b in "${kept_local_squash_verified[@]}"; do contains "$b" "${protected_branches[@]}" || tmp+=("$b"); done
    kept_local_squash_verified=("${tmp[@]}")
    tmp=()
    for b in "${kept_local_squash_unverified[@]}"; do contains "$b" "${protected_branches[@]}" || tmp+=("$b"); done
    kept_local_squash_unverified=("${tmp[@]}")
  fi

  worktree_removals=()
  for i in "${!worktree_branches[@]}"; do
    br="${worktree_branches[$i]}"
    (contains "$br" "${kept_local[@]}" || contains "$br" "${kept_local_squash_verified[@]}" \
     || contains "$br" "${kept_local_squash_unverified[@]}") \
      && worktree_removals+=("${worktree_paths[$i]}:$br")
  done

  if [[ ${#kept_local[@]} -eq 0 && ${#kept_local_squash_verified[@]} -eq 0 \
        && ${#kept_local_squash_unverified[@]} -eq 0 && ${#kept_remote[@]} -eq 0 \
        && ${#worktree_removals[@]} -eq 0 && ${#dirty_worktrees[@]} -eq 0 \
        && ${#new_empty_worktrees[@]} -eq 0 ]]; then
    clean=$((clean + 1))
    continue
  fi
  with_candidates=$((with_candidates + 1))

  if [[ "$mode" == "scan" ]]; then
    echo "repo=$name flow=$flow trunk=$trunk"
    [[ ${#kept_local[@]} -gt 0 ]] && echo "  local: ${kept_local[*]}"
    [[ ${#kept_local_squash_verified[@]} -gt 0 ]] && echo "  local-squash-merged-verified (branch's content confirmed on trunk, via merge-commit patch match, per-commit cherry match, or merge-tree no-op: will auto -D): ${kept_local_squash_verified[*]}"
    [[ ${#kept_local_squash_unverified[@]} -gt 0 ]] && echo "  local-squash-merged-unverified (confirmed via merged PR but branch's own patch differs from the merge commit or it's unavailable locally — git branch -d will safely refuse, needs manual -D after review): ${kept_local_squash_unverified[*]}"
    [[ ${#kept_remote[@]} -gt 0 ]] && echo "  remote: ${kept_remote[*]}"
    [[ ${#worktree_removals[@]} -gt 0 ]] && echo "  worktrees: ${worktree_removals[*]}"
    for wt in "${worktree_removals[@]}"; do
      pids="$(pgrep -f "${wt%%:*}" | tr '\n' ' ' || true)"
      [[ -n "$pids" ]] && echo "  running-processes (will be killed on apply): ${wt%%:*}: $pids"
    done
    [[ ${#dirty_worktrees[@]} -gt 0 ]] && echo "  dirty-worktrees (uncommitted changes, branch kept, not touched): ${dirty_worktrees[*]}"
    [[ ${#new_empty_worktrees[@]} -gt 0 ]] && echo "  worktrees-new-empty (branch created but never committed to, branch kept, not touched): ${new_empty_worktrees[*]}"
  else
    for wt in "${worktree_removals[@]}"; do
      path="${wt%%:*}"
      if pkill -f "$path"; then
        for _ in 1 2 3 4 5; do pgrep -f "$path" >/dev/null || break; sleep 1; done
        pkill -9 -f "$path" || true
        echo "repo=$name killed-processes=$path"
      fi
      if git worktree remove "$path" 2>/dev/null; then
        echo "repo=$name removed-worktree=$path"
        removed_worktrees=$((removed_worktrees + 1))
      else
        echo "repo=$name skip-worktree=$path reason=remove-failed"
        skipped=$((skipped + 1))
      fi
    done
    for dw in "${dirty_worktrees[@]}"; do
      echo "repo=$name skip-worktree=${dw%%:*} branch=${dw#*:} reason=uncommitted-changes"
      skipped=$((skipped + 1))
    done
    for b in "${kept_local[@]}"; do
      # Ancestry vs origin/$trunk, not `git branch -d`'s HEAD/upstream check: a stale local trunk would refuse merged branches.
      if git merge-base --is-ancestor "$b" "origin/$trunk" 2>/dev/null \
         && git branch -D "$b" >/dev/null 2>&1; then
        echo "repo=$name deleted-local=$b"
        deleted_local=$((deleted_local + 1))
      else
        echo "repo=$name skip-local=$b reason=not-fully-merged"
        skipped=$((skipped + 1))
      fi
    done
    for b in "${kept_local_squash_verified[@]}"; do
      # Safe to force-delete: verified above that this branch's own patch
      # matches the PR's merge commit, so -D can't lose anything that -d's
      # ancestry check would have caught.
      if git branch -D "$b" >/dev/null 2>&1; then
        echo "repo=$name deleted-local=$b reason=squash-merged-verified"
        deleted_local=$((deleted_local + 1))
      else
        echo "repo=$name skip-local=$b reason=delete-failed"
        skipped=$((skipped + 1))
      fi
    done
    for b in "${kept_local_squash_unverified[@]}"; do
      # Never attempt `git branch -d` here: by construction, membership in
      # this bucket means the branch failed both plain --merged (not a real
      # ancestor of trunk) and the squash patch-id/cherry checks above, so it
      # is NOT safely mergeable. `git branch -d`'s ancestry check compares
      # against the branch's own @{upstream} when one is configured, not
      # against trunk — if the branch's upstream is its own identical remote
      # counterpart, that check trivially passes regardless of whether the
      # branch is actually merged into trunk, silently deleting unmerged
      # work. Explicitly gate on ancestry-to-trunk first so this bucket can
      # never be deleted through that loophole; it always requires manual -D.
      if git merge-base --is-ancestor "$b" "origin/$trunk" 2>/dev/null \
         && git branch -d "$b" >/dev/null 2>&1; then
        echo "repo=$name deleted-local=$b"
        deleted_local=$((deleted_local + 1))
      else
        echo "repo=$name skip-local=$b reason=squash-merged-verify-manually"
        skipped=$((skipped + 1))
      fi
    done
    for b in "${kept_remote[@]}"; do
      if git push origin --delete "$b" >/dev/null 2>&1; then
        echo "repo=$name deleted-remote=$b"
        deleted_remote=$((deleted_remote + 1))
      elif ! git ls-remote --exit-code --heads origin "$b" >/dev/null 2>&1; then
        echo "repo=$name already-deleted-remote=$b"
      else
        echo "repo=$name skip-remote=$b reason=push-delete-failed"
        skipped=$((skipped + 1))
      fi
    done
  fi
done

if [[ "$mode" == "scan" ]]; then
  echo "summary: scanned=$scanned with-candidates=$with_candidates clean=$clean errors=$errors"
else
  echo "summary: deleted-local=$deleted_local deleted-remote=$deleted_remote removed-worktrees=$removed_worktrees skipped=$skipped"
fi
