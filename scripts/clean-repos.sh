#!/usr/bin/env bash
# Scans (or cleans) merged branches and their worktrees across every git repo
# found directly under a root directory (e.g. ~/git/*). `scan` and `apply`
# share the exact same candidate-selection logic so what gets shown in `scan`
# is exactly what `apply` acts on — re-derived fresh at apply time (fresh
# fetch, fresh merge check) rather than passed back as a fragile branch list,
# since state can drift in the time it takes a human to read the plan.
# Every other worktree is still reported (unmerged-worktree) so the scan is a
# full inventory, but nothing in that category is removed unless it is proven
# equivalent to trunk (see --remove-equivalent).
#
# A worktree where a claude or codex session runs (the agent, or an ancestor of a
# process using the worktree, by argv path or cwd) is kept whole with its
# branches and processes (agent-session). Only without an agent are the other
# processes treated as leftovers and killed. The calling process chain is
# never signaled. Its worktree is kept unless explicitly opted in.
#
# Usage:
#   clean-repos.sh scan  [git-root] [options]
#   clean-repos.sh apply [git-root] [options]
#
# Options (repeatable where noted):
#   --exclude <branch|path>  never touch this branch name, in any repo, or the
#                             worktree at this absolute path (and its branch);
#                             a path is the only handle on a detached HEAD
#   --only-repo <name>       limit to this repo (repeatable)
#   --exclude-repo <name>    skip this repo (repeatable)
#   --local-only              skip remote branch deletion
#   --remote-only              skip local branch deletion
#   --stale-empty-days <n>    never-committed worktrees whose branch is older
#                             than n days (default 1) and that are clean and
#                             idle are removed with their branch on apply
#   --handoff-days <n>        trunk and detached-HEAD handoff recaps older than
#                             n days (default 7) are removed on apply; a
#                             branch's recap goes when the branch is gone
#   --keep-handoffs           never remove handoff recaps
#   --remove-caller-worktree  allow merged cleanup of the caller's worktree
#   --remove-equivalent       apply only: also remove worktrees whose content is
#                             already on trunk (every commit cherry-merged, or a
#                             merge into trunk changes nothing) when they are
#                             clean, idle and without an open PR; the branch is
#                             deleted with them, a detached HEAD has none.
#                             Without it they are only reported.
#
# An absolute --exclude path that names a handoff recap protects that file.
# A detached HEAD has no branch: protect it with its absolute path or with its
# commit SHA (4 or more hex digits, full or abbreviated) via --exclude.
#
# Plans live in <git-common-dir>/agent-plans/<repo>-<branch>/ next to the
# handoff recaps and follow the same lifecycle: the directory goes when its
# branch is gone (--exclude and --keep-handoffs protect it as they do a recap).
# Nothing about plans blocks or delays a worktree removal.
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
exclude_paths=()
only_repos=()
exclude_repos=()
stale_empty_days=1
handoff_days=7
keep_handoffs=false
remove_equivalent=false
remove_caller_worktree=false
entry_cwd="$(pwd -P)"

# Physical path when it exists (git and the user may spell symlinked parents
# differently, e.g. /var vs /private/var), without trailing slashes.
canonical_path() {
  local path="$1" tail="" dir
  while [[ "$path" == */ && "$path" != / ]]; do path="${path%/}"; done
  # A worktree directory deleted by hand (git lists it as prunable) no longer
  # exists: resolve its deepest existing ancestor and keep the missing tail.
  while [[ ! -d "$path" && "$path" == /?* ]]; do
    tail="/${path##*/}$tail"
    path="${path%/*}"
    [[ -n "$path" ]] || path=/
  done
  dir="$(cd "$path" 2>/dev/null && pwd -P)" || dir="$path"
  [[ "$dir" != / || -z "$tail" ]] || dir=""
  printf '%s\n' "$dir$tail"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    # Ref names never start with "/", so an absolute value is unambiguously a worktree path.
    --exclude)
      if [[ "$2" == /* ]]; then
        exclude_paths+=("$(canonical_path "$2")")
      else
        excludes+=("$2")
      fi
      shift 2 ;;
    --only-repo) only_repos+=("$2"); shift 2 ;;
    --exclude-repo) exclude_repos+=("$2"); shift 2 ;;
    --local-only) local_only=true; shift ;;
    --remote-only) remote_only=true; shift ;;
    --stale-empty-days) stale_empty_days="$2"; shift 2 ;;
    --handoff-days) handoff_days="$2"; shift 2 ;;
    --keep-handoffs) keep_handoffs=true; shift ;;
    --remove-equivalent) remove_equivalent=true; shift ;;
    --remove-caller-worktree) remove_caller_worktree=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ "$stale_empty_days" =~ ^[0-9]+$ ]] || { echo "--stale-empty-days needs a non-negative integer: $stale_empty_days" >&2; exit 1; }
[[ "$handoff_days" =~ ^[0-9]+$ ]] || { echo "--handoff-days needs a non-negative integer: $handoff_days" >&2; exit 1; }
# A leading zero would make Bash arithmetic read the value as octal.
stale_empty_days=$((10#$stale_empty_days))
handoff_days=$((10#$handoff_days))

contains() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
  return 1
}

path_excluded() {
  [[ ${#exclude_paths[@]} -gt 0 ]] && contains "$(canonical_path "$1")" "${exclude_paths[@]}"
}

# --exclude <sha> protects a detached HEAD, which has no branch name to match.
sha_excluded() {
  local sha="$1" x
  for x in ${excludes[@]+"${excludes[@]}"}; do
    [[ "$x" =~ ^[0-9a-fA-F]{4,40}$ && "$sha" == "${x,,}"* ]] && return 0
  done
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
  reflog="$(git reflog show "refs/heads/$br" 2>/dev/null)"
  [[ "$(wc -l <<<"$reflog" | tr -d ' ')" == "1" ]] && grep -q 'branch: Created from' <<<"$reflog"
}

# Unix time of the branch's creation, read from its single reflog entry.
branch_created_at() {
  local selector
  selector="$(git reflog show -n1 --date=unix --format=%gd "refs/heads/$1" 2>/dev/null)" || return 1
  selector="${selector##*@\{}"
  selector="${selector%\}}"
  [[ "$selector" =~ ^[0-9]+$ ]] || return 1
  echo "$selector"
}

# A never-committed worktree left alone for days is an abandoned setup, not a
# session about to start. Only call it stale when nothing uses it.
worktree_is_stale_empty() {
  local br="$1" path="$2" created
  created="$(branch_created_at "$br")" || return 1
  (( $(date +%s) - created > stale_empty_days * 86400 )) || return 1
  worktree_is_idle "$path" "$3"
}

# Nothing uses the worktree: no process mentions its path and none holds a file
# or cwd in it. Fail closed when lsof is unavailable or reports errors, since an
# in-use worktree would otherwise look idle.
worktree_is_idle() {
  local path="$1" state="$2"
  [[ -z "$state" ]] || return 1
  command -v lsof >/dev/null 2>&1 || return 1
  local out err
  err="$(mktemp)" || return 1
  local status=0
  out="$(lsof -t +D "$path" 2>"$err")" || status=$?
  # lsof exits 1 with no output when nothing is open; any stderr (unreadable
  # path, permission problem) means the answer is unknown, so fail closed.
  # An unprivileged lsof also cannot see other users' processes.
  if (( status > 1 )) || [[ -s "$err" ]]; then rm -f "$err"; return 1; fi
  rm -f "$err"
  [[ -z "$out" ]]
}

# Keep the original chain even if a caller exits and cleanup is reparented.
startup_chain() {
  local table
  table="$(ps -axo pid=,ppid= 2>/dev/null)" || return 1
  printf '%s\n' "$table" | awk -v self="$$" '
    $1 ~ /^[1-9][0-9]*$/ && $2 ~ /^[0-9]+$/ { parent[$1] = $2 }
    END {
      for (p = self; p != 0; p = parent[p]) {
        if (!(p in parent) || seen[p]++) exit 1
        print p
      }
    }'
}

read_cwd_records() {
  local output err status=0
  err="$(mktemp)" || return 1
  output="$(lsof -a -d cwd -Fpn "$@" 2>"$err")" || status=$?
  # A targeted query can find no cwd because a process just exited.
  if [[ -s "$err" ]] || (( status > 1 )); then rm -f "$err"; return 1; fi
  rm -f "$err"
  printf '%s\n' "$output"
}

process_table() {
  LC_ALL=C ps -ww -axo pid=,ppid=,stat=,lstart=,command= 2>/dev/null
}

classify_process_snapshot() {
  local path="$1" physical="$2" nested="$3" previous="$4" cwd_records="$5" targeted_cwds="$6" table
  # Read argv and process identity after the slower cwd query.
  table="$(process_table)" && [[ -n "$table" ]] || { echo unknown; return; }

  if ! printf '%s\n' "$previous" '@ps' "$table" '@cwd' "$cwd_records" "$targeted_cwds" | WT_PATH="$path" WT_REAL="$physical" \
    WT_ENTRY="$entry_cwd" WT_CHAIN="$original_chain" WT_NESTED="$nested" awk -v self="$$" -v q="'" '
    function inside(n, p,    i) {
      if (!(n == p || index(n, p "/") == 1)) return 0
      for (i in child) if (child[i] != "" && (n == child[i] || index(n, child[i] "/") == 1)) return 0
      return 1
    }
    function path_end(c) { return c == "" || index("/ \t\"" q, c) > 0 }
    function in_nested_arg(line,    i, p) {
      for (i in child) {
        p = child[i]
        if (p != "" && index(line, p) == 1 && path_end(substr(line, length(p) + 1, 1))) return 1
      }
      return 0
    }
    function mentions(line, p,    i, before, after) {
      before = ""
      while ((i = index(line, p)) > 0) {
        if (i > 1) before = substr(line, i - 1, 1)
        after = substr(line, i + length(p), 1)
        if ((before == "" || index(" =:\"" q, before) > 0) &&
            path_end(after) && !in_nested_arg(substr(line, i))) return 1
        before = substr(line, i, 1)
        line = substr(line, i + 1)
      }
      return 0
    }
    function agent(cmd,    n, a, i, b) {
      n = split(cmd, a, /[ \t]+/)
      for (i = 1; i <= 2 && i <= n; i++) {
        b = a[i]; sub(/.*\//, "", b)
        if (b == "claude" || b == "codex") return b
      }
      return ""
    }
    BEGIN {
      path = ENVIRON["WT_PATH"]; real = ENVIRON["WT_REAL"]
      n = split(ENVIRON["WT_CHAIN"], chain, "\n")
      for (i = 1; i <= n; i++) own[chain[i]] = 1
      split(ENVIRON["WT_NESTED"], child, "\n")
    }
    $0 == "@ps" { phase = 1; next }
    $0 == "@cwd" { phase = 2; next }
    $0 == "@targeted-identities" { phase = 3; pid = ""; next }
    $0 == "@targeted-cwd" { phase = 4; pid = ""; next }
    phase <= 1 {
      if (NF < 9 || $1 !~ /^[1-9][0-9]*$/ || $2 !~ /^[0-9]+$/ || $7 !~ /^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$/) {
        invalid = 1
        next
      }
      pid = $1
      start = $4 " " $5 " " $6 " " $7 " " $8
      line = $0
      for (i = 1; i <= 8; i++) sub(/^[ \t]*[^ \t]+/, "", line)
      sub(/^[ \t]+/, "", line)
      identity = $2 " " start " " line
      gsub(/[ \t]+$/, "", identity)
      gsub(/\t/, " ", identity)
      if (phase == 0) {
        previous[pid] = identity
        next
      }
      count++
      parent[pid] = $2; live[pid] = ($3 !~ /^Z/)
      started[pid] = start; current[pid] = identity
      command[pid] = line
      argv_match[pid] = mentions(line, path) || (path != real && mentions(line, real))
      next
    }
    phase == 3 {
      tab = index($0, "\t")
      if (tab) requested[substr($0, 1, tab - 1)] = substr($0, tab + 1)
      next
    }
    /^p[1-9][0-9]*$/ { pid = substr($0, 2); next }
    /^n/ && pid {
      cwd_seen = 1
      if (phase == 4) checked_cwd[pid] = requested[pid]
      dir = substr($0, 2)
      cwd_match[pid] = inside(dir, real) || (path != real && inside(dir, path))
    }
    END {
      if (invalid || !cwd_seen) exit 1
      for (p = self; p != 0; p = parent[p]) {
        if (!(p in parent) || seen[p]++) exit 1
        own[p] = 1
      }
      caller = inside(ENVIRON["WT_ENTRY"], real)
      for (pid in live) {
        if (!live[pid]) continue
        matches = argv_match[pid] || cwd_match[pid]
        if (pid in own) {
          if (pid != self && matches) caller = 1
          continue
        }
        if (!matches) {
          # Resample newly observed agents. Agent descendants need a cwd or
          # argv match before they count, so unrelated child churn is ignored.
          if (agent(command[pid]) != "" &&
              previous[pid] != current[pid] && checked_cwd[pid] != current[pid])
            print "unobserved\t" pid "\t" current[pid]
          continue
        }
        hops = 0
        for (p = pid; p != 0 && !(p in own); p = parent[p]) {
          if (!(p in parent) || ++hops > count) {
            exit 1
          }
          a = agent(command[p])
          if (a != "") {
            print "agent\t" pid ":" a
            break
          }
        }
        if (p == self || (!(p in own) && p != 0)) continue
        if (argv_match[pid]) print "leftover\t" pid "\t" started[pid]
        else print "busy\t" pid
      }
      if (caller) print "caller"
    }'; then
    echo unknown
  fi
}

# One classification for reporting, idle checks and signaling. Recheck cwd
# only for ambiguous new processes and then take a fresh argv/ancestry snapshot.
classify_worktree_processes() {
  local path="$1" physical previous cwd_records child nested=""
  local state attempt kind pid identity extra pid_list requested targeted_cwds=""
  local -a unobserved=()
  [[ -n "$original_chain" ]] && command -v lsof >/dev/null 2>&1 || { echo unknown; return; }
  physical="$(canonical_path "$path")"
  if [[ "$physical" == "$main_worktree" ]]; then
    for child in "${worktree_paths[@]}" "${detached_paths[@]}"; do
      if [[ "$child" == "$path/"* ]]; then
        nested+="$child"$'\n'"$physical${child#"$path"}"$'\n'
      elif [[ "$child" == "$physical/"* ]]; then
        nested+="$child"$'\n'"$path${child#"$physical"}"$'\n'
      fi
    done
  fi
  previous="$(process_table)" && [[ -n "$previous" ]] || { echo unknown; return; }
  cwd_records="$(read_cwd_records)" && [[ -n "$cwd_records" ]] || { echo unknown; return; }
  for attempt in 1 2 3; do
    state="$(classify_process_snapshot "$path" "$physical" "$nested" "$previous" "$cwd_records" "$targeted_cwds")"
    unobserved=()
    requested=""
    while IFS=$'\t' read -r kind pid identity; do
      case "$kind" in
        unobserved)
          unobserved+=("$pid")
          requested+="$pid"$'\t'"$identity"$'\n'
          ;;
        unknown|agent) printf '%s\n' "$state"; return ;;
      esac
    done <<< "$state"
    if [[ ${#unobserved[@]} -eq 0 ]]; then
      printf '%s\n' "$state"
      return
    fi
    if (( attempt < 3 )); then
      pid_list="$(IFS=,; printf '%s' "${unobserved[*]}")"
      extra="$(read_cwd_records -p "$pid_list")" || { echo unknown; return; }
      targeted_cwds+=$'\n@targeted-identities\n'"$requested"$'@targeted-cwd\n'"$extra"
    fi
  done
  echo unknown
}

process_keep_reason() {
  local state="$1" kind detail
  while IFS=$'\t' read -r kind detail; do
    case "$kind" in
      unknown) echo agent-session; return ;;
      agent) echo agent-session; return ;;
    esac
  done <<< "$state"
  if ! $remove_caller_worktree && [[ $'\n'"$state"$'\n' == *$'\ncaller\n'* ]]; then
    echo caller-worktree
  fi
}

show_processes() {
  local state="$1" kind pid rest
  while IFS=$'\t' read -r kind pid rest; do
    case "$kind" in
      leftover) printf '%s:%s ' "$pid" "$(ps -o comm= -p "$pid" 2>/dev/null | sed 's|.*/||')" ;;
    esac
  done <<< "$state"
}

show_agents() {
  local state="$1" kind detail
  while IFS=$'\t' read -r kind detail; do
    case "$kind" in
      agent) printf '%s ' "$detail" ;;
      unknown) printf '?:unknown ' ;;
    esac
  done <<< "$state"
}

stop_worktree_processes() {
  local path="$1" state kind pid started attempt
  local -a targets=()
  local -A term_start=()
  state="$(classify_worktree_processes "$path")"
  stop_reason="$(process_keep_reason "$state")"
  [[ -z "$stop_reason" ]] || return 1
  while IFS=$'\t' read -r kind pid started; do
    [[ "$kind" == leftover ]] || continue
    term_start["$pid"]="$started"
    targets+=("$pid")
  done <<< "$state"
  [[ ${#targets[@]} -gt 0 ]] || return 0

  kill -TERM -- "${targets[@]}" 2>/dev/null || true
  echo "repo=$name killed-processes=$path"
  for attempt in 0 1 2 3 4 5; do
    if (( attempt > 0 )); then sleep 1; fi
    state="$(classify_worktree_processes "$path")"
    stop_reason="$(process_keep_reason "$state")"
    [[ -z "$stop_reason" ]] || return 1
    targets=()
    while IFS=$'\t' read -r kind pid started; do
      [[ "$kind" == leftover ]] || continue
      if [[ "${term_start[$pid]:-}" != "$started" ]]; then
        stop_reason=processes-changed
        return 1
      fi
      targets+=("$pid")
    done <<< "$state"
    [[ ${#targets[@]} -gt 0 ]] || return 0
  done

  kill -KILL -- "${targets[@]}" 2>/dev/null || true
  state="$(classify_worktree_processes "$path")"
  stop_reason="$(process_keep_reason "$state")"
  [[ -z "$stop_reason" ]] || return 1
  if [[ $'\n'"$state" == *$'\nleftover\t'* ]]; then
    stop_reason=processes-changed
    return 1
  fi
  return 0
}

worktree_branch_proven_on_trunk() {
  branch_fully_cherry_merged "refs/heads/$1" || branch_adds_nothing_to_trunk "refs/heads/$1"
}

# Every proof that a worktree's content is already on trunk and nothing else
# needs it: the content is on origin/<trunk>, the tree is clean, no open PR
# (an unknown PR state fails closed) and no process uses it. br is empty for a
# detached HEAD.
worktree_is_equivalent() {
  local path="$1" ref="$2" br="$3"
  [[ -d "$path" ]] || return 1
  # Long-lived branches sit at or behind trunk, so they would always look
  # "merged"; and a detached HEAD already contained in trunk has no work of its own.
  if [[ -n "$br" ]]; then
    case "$br" in "$trunk"|main|master|develop|HEAD) return 1 ;; esac
    [[ "$br" != "${current_branch:-}" ]] || return 1
  fi
  if [[ -z "$br" ]] && git merge-base --is-ancestor "$ref" "origin/$trunk" 2>/dev/null; then
    return 1
  fi
  branch_fully_cherry_merged "$ref" || branch_adds_nothing_to_trunk "$ref" || return 1
  [[ -z "$(git -C "$path" status --porcelain 2>/dev/null)" ]] || return 1
  if [[ -n "$br" ]]; then
    $open_prs_known || return 1
    [[ -z "${open_pr_number[$br]:-}" ]] || return 1
  fi
  worktree_is_idle "$path" "${4-$(classify_worktree_processes "$path")}"
}

# One-line description of a worktree's uncommitted state, so the user can tell
# throwaway edits (tracked deletions of build output) from real work (new files).
worktree_dirty_summary() {
  local path="$1" line tracked=0 deletions=0 untracked=0 shown=0 listed="" summary
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if [[ "${line:0:2}" == "??" ]]; then
      untracked=$((untracked + 1))
      if [[ $shown -lt 5 ]]; then
        listed+="${listed:+, }${line:3}"
        shown=$((shown + 1))
      fi
    else
      tracked=$((tracked + 1))
      [[ "${line:0:2}" == *D* ]] && deletions=$((deletions + 1))
    fi
  done < <(git -C "$path" status --porcelain 2>/dev/null)
  summary="tracked=$tracked"
  [[ $tracked -gt 0 && $deletions -eq $tracked ]] && summary+=" (deletions only)"
  summary+=" untracked=$untracked"
  if [[ $untracked -gt 0 ]]; then
    summary+=": $listed"
    [[ $untracked -gt $shown ]] && summary+=" (+$((untracked - shown)) more)"
  fi
  echo "$summary"
}

# yes when the remote holds every local commit, no when there is no remote
# counterpart, partial:K when K local commits are not on it.
branch_push_state() {
  local br="$1" remote count
  # The branch's own remote counterpart, not its upstream: a branch cut from origin/main tracks that instead.
  remote="$(git rev-parse -q --verify "refs/remotes/origin/$br" 2>/dev/null)" \
    || { echo no; return; }
  count="$(git rev-list --count "$remote..refs/heads/$br" 2>/dev/null)" || { echo unknown; return; }
  if [[ "$count" == 0 ]]; then echo yes; else echo "partial:$count"; fi
}

# Hint only, never a deletion signal: a squash merged under another branch name
# keeps the commit subject (plus " (#N)"), but the PR may have changed the
# content, or a later PR reworked it, so a matching subject proves nothing about
# loss. Compares the subjects of the branch's commits (via `git cherry`) with
# trunk subjects since the merge-base, then with merged PR titles.
superseded_hint() {
  local ref="$1" mb sha subject key n total=0 matched=0 refs=""
  local -A trunk_subjects=()
  mb="$(git merge-base "$ref" "origin/$trunk" 2>/dev/null)" || return 0
  while IFS=$'\t' read -r sha subject; do
    if [[ "$subject" =~ ^(.*)\ \(#([0-9]+)\)$ ]]; then
      key="${BASH_REMATCH[1]}"; n="#${BASH_REMATCH[2]}"
    else
      key="$subject"; n="$sha"
    fi
    [[ -n "$key" && -z "${trunk_subjects[$key]:-}" ]] && trunk_subjects["$key"]="$n"
  done < <(git log --format='%h%x09%s' "$mb..origin/$trunk" 2>/dev/null)
  while read -r _ sha; do
    total=$((total + 1))
    subject="$(git log -1 --format=%s "$sha" 2>/dev/null)"
    [[ "$subject" =~ ^(.*)\ \(#([0-9]+)\)$ ]] && subject="${BASH_REMATCH[1]}"
    [[ -n "$subject" ]] || continue
    n="${trunk_subjects[$subject]:-${merged_pr_by_title[$subject]:-}}"
    [[ -n "$n" ]] || continue
    matched=$((matched + 1))
    [[ ",$refs," == *",$n,"* ]] || refs+="${refs:+,}$n"
  done < <(git cherry "origin/$trunk" "$ref" 2>/dev/null)
  if [[ $matched -gt 0 && $matched -eq $total ]]; then
    echo "likely-superseded-by=$refs"
  elif [[ $matched -gt 0 ]]; then
    echo "subject-matches=$matched/$total:$refs"
  fi
}

# Context for deciding a worktree's fate by hand. br is empty for a detached HEAD.
unmerged_worktree_summary() {
  local path="$1" ref="$2" br="$3" summary hint
  if [[ ! -d "$path" ]]; then
    echo missing
    return
  fi
  summary="ahead=$(git rev-list --count "origin/$trunk..$ref" 2>/dev/null || echo '?')"
  if [[ -n "$br" ]]; then
    summary+=" pushed=$(branch_push_state "$br")"
    if $open_prs_known; then
      summary+=" pr=${open_pr_number[$br]:-none}"
    else
      summary+=" pr=unknown"
    fi
  elif [[ -n "$(git for-each-ref --contains "$ref" refs/remotes/origin 2>/dev/null)" ]]; then
    summary+=" pushed=yes"
  else
    summary+=" pushed=no"
  fi
  summary+=" $(worktree_dirty_summary "$path")"
  if branch_fully_cherry_merged "$ref" || branch_adds_nothing_to_trunk "$ref"; then
    summary+=" content-on-trunk=yes"
  fi
  # The hint walks trunk history per worktree and only informs a decision made from the scan.
  if [[ "$mode" == scan ]]; then
    hint="$(superseded_hint "$ref")"
    [[ -z "$hint" ]] || summary+=" $hint"
  fi
  echo "$summary"
}

# The handoff workflow replaces characters; tr replaces bytes, so a multibyte
# character yields several dashes. Squeezing dashes makes both spellings agree.
handoff_key() { printf '%s' "$1" | LC_ALL=C tr -c 'A-Za-z0-9._-' '-' | tr -s '-'; }

# The handoff workflow writes one recap per branch to the common git dir as
# agent-handoff-<repo>-<branch>.md (earlier versions: agent-handoff-<branch>.md),
# with both names reduced to [A-Za-z0-9._-]. A recap only serves resuming its
# branch, so it is obsolete once the branch is gone. Plan directories
# (agent-plans/<repo>-<branch>/) follow the same rules. Trunk and detached-HEAD
# recaps have no branch lifecycle to follow, so age bounds them instead.
# Arguments: branches apply is about to delete, treated as gone (scan's
# prediction). Prints "<path>\t<reason>" per recap to remove.
stale_handoffs() {
  local common refs file stem rest c b is_protected is_live is_aged is_deleting
  local -a cands=()
  local -A live=() protected=() trunks=() deleting=() deleting_names=()
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 0
  # Without the branch list every recap would look orphaned.
  refs="$(git for-each-ref --format='%(refname:lstrip=2)' refs/heads)" \
    || { echo "repo=$name warning: cannot list branches, handoff recaps kept" >&2; return 0; }
  for b in "$@"; do
    [[ -n "$b" ]] || continue
    deleting_names["$b"]=1
    deleting["$(handoff_key "$b")"]=1
  done
  # Keys can collide (feature/x and feature-x): only the exact branches being
  # deleted leave the live set, so a surviving namesake keeps its recap.
  while IFS= read -r b; do
    [[ -n "$b" && -z "${deleting_names[$b]:-}" ]] && live["$(handoff_key "$b")"]=1
  done <<< "$refs"
  for b in ${repo_excludes[@]+"${repo_excludes[@]}"}; do protected["$(handoff_key "$b")"]=1; done
  for b in "$trunk" main master develop; do trunks["$(handoff_key "$b")"]=1; done
  while IFS= read -r -d '' file; do
    path_excluded "$file" && continue
    if [[ -d "$file" ]]; then
      stem="$(handoff_key "${file##*/}")"
    else
      stem="${file##*/agent-handoff-}"
      stem="$(handoff_key "${stem%.md}")"
    fi
    [[ -n "$stem" ]] || continue
    # The repo prefix is the directory name when the recap was written; a
    # renamed or symlinked repo leaves another prefix, and legacy names have
    # none. Every dash-separated suffix of the stem is a possible branch key.
    cands=("$stem")
    rest="$stem"
    while [[ "$rest" == *-* ]]; do
      rest="${rest#*-}"
      cands+=("$rest" "-$rest")
    done
    is_protected=false; is_live=false; is_aged=false; is_deleting=false
    for c in "${cands[@]}"; do
      [[ -n "$c" ]] || continue
      [[ -n "${protected[$c]:-}" ]] && is_protected=true
      # Trunks never count as live; a live branch named detached-<hex> does.
      if [[ -n "${trunks[$c]:-}" ]]; then
        is_aged=true
      elif [[ -n "${live[$c]:-}" ]]; then
        is_live=true
      elif [[ "$c" =~ ^detached-[0-9a-f]+$ ]]; then
        is_aged=true
      fi
      [[ -n "${deleting[$c]:-}" ]] && is_deleting=true
    done
    # A live branch's recap is never removed, even when a suffix also reads as
    # a trunk (feature-main); trunk and detached recaps expire by age.
    $is_protected && continue
    $is_live && continue
    if $is_aged; then
      # A directory's own mtime ignores in-place edits of the files inside.
      if [[ -d "$file" ]]; then
        [[ -z "$(find "$file" -mmin -"$((handoff_days * 1440))" -print -quit 2>/dev/null)" ]] \
          && printf '%s\t%s\n' "$file" "older-than-${handoff_days}d"
        continue
      fi
      [[ -n "$(find "$file" -mmin +"$((handoff_days * 1440))" 2>/dev/null)" ]] \
        && printf '%s\t%s\n' "$file" "older-than-${handoff_days}d"
      continue
    fi
    if $is_deleting; then
      printf '%s\t%s\n' "$file" branch-deleted-on-apply
    else
      printf '%s\t%s\n' "$file" branch-gone
    fi
  done < <({ find "$common" -maxdepth 1 -type f -name 'agent-handoff-*.md' -print0 2>/dev/null
             find "$common/agent-plans" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null; } | sort -z)
}

# Include the primary checkout when protecting refs. Only linked worktrees
# enter the worktree deletion lists.
read_worktrees() {
  local list line br current_path="" current_head=""
  list="$(git worktree list --porcelain 2>/dev/null)" && [[ -n "$list" ]] || return 1
  worktree_paths=()
  worktree_branches=()
  detached_paths=()
  detached_heads=()
  while IFS= read -r line; do
    if [[ "$line" == worktree\ * ]]; then
      current_path="${line#worktree }"
      current_head=""
    elif [[ "$line" == HEAD\ * ]]; then
      current_head="${line#HEAD }"
    elif [[ "$line" == detached ]]; then
      if [[ "$current_path" != "$main_worktree" ]]; then
        detached_paths+=("$current_path")
        detached_heads+=("$current_head")
      fi
    elif [[ "$line" == branch\ refs/heads/* ]]; then
      br="${line#branch refs/heads/}"
      worktree_paths+=("$current_path")
      worktree_branches+=("$br")
    fi
  done <<< "$list"

}

original_chain="$(startup_chain)" || original_chain=""

scanned=0; with_candidates=0; clean=0; errors=0; unmerged_total=0; kept_unmerged=0
deleted_local=0; deleted_remote=0; removed_worktrees=0; skipped=0; deleted_handoffs=0

for repo in "$git_root"/*/; do
  repo="${repo%/}"
  [[ -d "$repo/.git" ]] || continue
  name="$(basename "$repo")"
  main_worktree="$(canonical_path "$repo")"

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
  declare -A merged_pr_by_title=()
  if command -v gh >/dev/null 2>&1 && gh repo view >/dev/null 2>&1; then
    # A branch name can be reused across several merged PRs over time (e.g.
    # feature/x merged, then reopened and merged again later). Collect every
    # merge-commit oid gh reports for a given headRefName before deciding
    # verified/unverified, instead of classifying per PR row as they stream
    # in — otherwise the same branch can land in both buckets depending on
    # which merge commit happened to be checked last.
    declare -A branch_oids=()
    while IFS=$'\x1f' read -r b head_oid oid pr_number pr_title; do
      [[ -z "$b" ]] && continue
      [[ -n "$pr_title" && -z "${merged_pr_by_title[$pr_title]:-}" ]] && merged_pr_by_title["$pr_title"]="#$pr_number"
      branch_oids["$b"]="${branch_oids[$b]:-}${branch_oids[$b]:+ }$oid"
      # A branch name reused after its PR merged (e.g. a bot force-pushing one stable name) carries new, unmerged
      # commits: only treat the remote as merged when its tip is exactly what the PR merged.
      [[ "$(git rev-parse -q --verify "refs/remotes/origin/$b" 2>/dev/null)" == "$head_oid" ]] && remote_candidates+=("$b")
    done < <(gh pr list --state merged --base "$trunk" --json headRefName,mergeCommit,headRefOid,number,title \
      --jq '.[] | "\(.headRefName)\u001f\(.headRefOid)\u001f\(.mergeCommit.oid // "")\u001f\(.number)\u001f\(.title)"' --limit 100 2>/dev/null || true)

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
  # Fail closed: if the lookup fails we cannot know which remote branches back an
  # open PR, and deleting one closes that PR, so remote deletion is skipped.
  open_prs_known=true
  open_pr_branches=()
  declare -A open_pr_number=()
  if open_pr_out="$(gh pr list --state open --json headRefName,number --jq '.[] | "\(.headRefName)\t\(.number)"' --limit 200 2>/dev/null)"; then
    while IFS=$'\t' read -r b pr_number; do
      [[ -n "$b" ]] || continue
      open_pr_branches+=("$b")
      open_pr_number["$b"]="${pr_number:+#$pr_number}"
      open_pr_number["$b"]="${open_pr_number[$b]:-open}"
    done <<<"$open_pr_out"
  else
    open_prs_known=false
  fi
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
  remote_skipped_unknown=false
  if ! $open_prs_known && [[ ${#remote_candidates[@]} -gt 0 ]]; then
    remote_skipped_unknown=true
    remote_candidates=()
  fi

  if ! read_worktrees; then
    echo "repo=$name status=worktree-list-failed"
    errors=$((errors + 1))
    continue
  fi

  repo_excludes=("${excludes[@]}")
  for i in "${!worktree_paths[@]}"; do
    path_excluded "${worktree_paths[$i]}" && repo_excludes+=("${worktree_branches[$i]}")
  done

  kept_local=()
  for b in "${local_candidates[@]}"; do
    contains "$b" "${repo_excludes[@]}" || kept_local+=("$b")
  done
  kept_local_squash_verified=()
  for b in "${local_squash_verified[@]}"; do
    contains "$b" "${repo_excludes[@]}" || kept_local_squash_verified+=("$b")
  done
  kept_local_squash_unverified=()
  for b in "${local_squash_unverified[@]}"; do
    contains "$b" "${repo_excludes[@]}" || kept_local_squash_unverified+=("$b")
  done
  kept_remote=()
  for b in "${remote_candidates[@]}"; do
    contains "$b" "${repo_excludes[@]}" || kept_remote+=("$b")
  done

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
  dirty_details=()
  dirty_reasons=()
  new_empty_worktrees=()
  stale_empty_worktrees=()
  active_worktrees=()
  active_details=()
  active_reasons=()
  declare -A process_states=() late_protected=()
  active_branches=()
  protected_branches=()
  for i in "${!worktree_branches[@]}"; do
    br="${worktree_branches[$i]}"
    path="${worktree_paths[$i]}"
    local_candidate=false
    if contains "$br" "${kept_local[@]}" || contains "$br" "${kept_local_squash_verified[@]}" \
      || contains "$br" "${kept_local_squash_unverified[@]}"; then
      local_candidate=true
    fi
    if ! $local_candidate && ! contains "$br" "${kept_remote[@]}"; then continue; fi
    state="$(classify_worktree_processes "$path")"
    process_states["$path"]="$state"
    reason="$(process_keep_reason "$state")"
    if [[ -n "$reason" ]]; then
      active_worktrees+=("$path:$br")
      active_branches+=("$br")
      active_details+=("$(show_agents "$state")")
      active_reasons+=("$reason")
      protected_branches+=("$br")
    elif ! $local_candidate; then
      continue
    elif [[ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]]; then
      dirty_worktrees+=("$path:$br")
      dirty_details+=("$(worktree_dirty_summary "$path")")
      dirty_reasons+=(uncommitted-changes)
      protected_branches+=("$br")
    elif worktree_branch_is_new_empty "$br"; then
      if worktree_is_stale_empty "$br" "$path" "$state"; then
        stale_empty_worktrees+=("$path:$br")
      else
        new_empty_worktrees+=("$path:$br")
      fi
      protected_branches+=("$br")
    fi
  done
  if [[ ${#active_branches[@]} -gt 0 ]]; then
    # Deleting the remote branch of a live session would break its next push.
    tmp=()
    for b in "${kept_remote[@]}"; do contains "$b" "${active_branches[@]}" || tmp+=("$b"); done
    kept_remote=("${tmp[@]}")
  fi
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
    [[ "${worktree_paths[$i]}" != "$main_worktree" ]] || continue
    br="${worktree_branches[$i]}"
    (contains "$br" "${kept_local[@]}" || contains "$br" "${kept_local_squash_verified[@]}" \
     || contains "$br" "${kept_local_squash_unverified[@]}") \
      && worktree_removals+=("${worktree_paths[$i]}:$br")
  done

  # Everything else is only reported: not proven merged, so never removed.
  unmerged_worktrees=()
  unmerged_details=()
  unmerged_branches=()
  equivalent_worktrees=()
  equivalent_details=()
  equivalent_branches=()
  equivalent_refs=()
  if ! $remote_only; then
    for i in "${!worktree_branches[@]}"; do
      br="${worktree_branches[$i]}"
      path="${worktree_paths[$i]}"
      [[ "$path" != "$main_worktree" ]] || continue
      contains "$br" "${repo_excludes[@]}" && continue
      contains "$path:$br" "${worktree_removals[@]}" && continue
      contains "$path:$br" "${dirty_worktrees[@]}" && continue
      contains "$path:$br" "${new_empty_worktrees[@]}" && continue
      contains "$path:$br" "${stale_empty_worktrees[@]}" && continue
      contains "$path:$br" "${active_worktrees[@]}" && continue
      if worktree_is_equivalent "$path" "refs/heads/$br" "$br"; then
        equivalent_worktrees+=("$path:$br")
        equivalent_branches+=("$br")
        equivalent_refs+=("refs/heads/$br")
        equivalent_details+=("$(unmerged_worktree_summary "$path" "refs/heads/$br" "$br")")
        continue
      fi
      unmerged_worktrees+=("$path:$br")
      unmerged_branches+=("$br")
      unmerged_details+=("$(unmerged_worktree_summary "$path" "refs/heads/$br" "$br")")
    done
    for i in "${!detached_paths[@]}"; do
      path="${detached_paths[$i]}"
      sha="${detached_heads[$i]}"
      path_excluded "$path" && continue
      sha_excluded "$sha" && continue
      state="$(classify_worktree_processes "$path")"
      reason="$(process_keep_reason "$state")"
      if [[ -n "$reason" ]]; then
        active_worktrees+=("$path:(detached ${sha:0:7})")
        active_details+=("$(show_agents "$state")")
        active_reasons+=("$reason")
        continue
      fi
      if worktree_is_equivalent "$path" "$sha" "" "$state"; then
        equivalent_worktrees+=("$path:(detached ${sha:0:7})")
        equivalent_branches+=("")
        equivalent_refs+=("$sha")
        equivalent_details+=("$(unmerged_worktree_summary "$path" "$sha" "")")
        continue
      fi
      unmerged_worktrees+=("$path:(detached ${sha:0:7})")
      unmerged_branches+=("")
      unmerged_details+=("$(unmerged_worktree_summary "$path" "$sha" "")")
    done
  fi

  # Scan predicts the recaps of branches apply will delete; apply re-derives
  # them after its deletions, so a branch that fails to delete keeps its recap.
  handoff_removals=()
  handoff_reasons=()
  if ! $keep_handoffs && ! $remote_only; then
    apply_deletes=("${kept_local[@]}" "${kept_local_squash_verified[@]}")
    for wt in "${stale_empty_worktrees[@]}"; do apply_deletes+=("${wt##*:}"); done
    $remove_equivalent && for b in "${equivalent_branches[@]}"; do [[ -n "$b" ]] && apply_deletes+=("$b"); done
    while IFS=$'\t' read -r f r; do
      handoff_removals+=("$f")
      handoff_reasons+=("$r")
    done < <(stale_handoffs ${apply_deletes[@]+"${apply_deletes[@]}"})
  fi

  if [[ ${#kept_local[@]} -eq 0 && ${#kept_local_squash_verified[@]} -eq 0 \
        && ${#kept_local_squash_unverified[@]} -eq 0 && ${#kept_remote[@]} -eq 0 \
        && ${#worktree_removals[@]} -eq 0 && ${#dirty_worktrees[@]} -eq 0 \
        && ${#active_worktrees[@]} -eq 0 \
        && ${#new_empty_worktrees[@]} -eq 0 && ${#stale_empty_worktrees[@]} -eq 0 \
        && ${#unmerged_worktrees[@]} -eq 0 && ${#equivalent_worktrees[@]} -eq 0 \
        && ${#handoff_removals[@]} -eq 0 ]] \
        && ! $remote_skipped_unknown; then
    clean=$((clean + 1))
    continue
  fi
  with_candidates=$((with_candidates + 1))
  unmerged_total=$((unmerged_total + ${#unmerged_worktrees[@]}))

  if [[ "$mode" == "scan" ]]; then
    echo "repo=$name flow=$flow trunk=$trunk"
    [[ ${#kept_local[@]} -gt 0 ]] && echo "  local: ${kept_local[*]}"
    [[ ${#kept_local_squash_verified[@]} -gt 0 ]] && echo "  local-squash-merged-verified (branch's content confirmed on trunk, via merge-commit patch match, per-commit cherry match, or merge-tree no-op: will auto -D): ${kept_local_squash_verified[*]}"
    [[ ${#kept_local_squash_unverified[@]} -gt 0 ]] && echo "  local-squash-merged-unverified (confirmed via merged PR but branch's own patch differs from the merge commit or it's unavailable locally — git branch -d will safely refuse, needs manual -D after review): ${kept_local_squash_unverified[*]}"
    [[ ${#kept_remote[@]} -gt 0 ]] && echo "  remote: ${kept_remote[*]}"
    [[ ${#worktree_removals[@]} -gt 0 ]] && echo "  worktrees: ${worktree_removals[*]}"
    for wt in "${worktree_removals[@]}"; do
      path="${wt%:*}"
      pids="$(show_processes "${process_states[$path]}")"
      [[ -n "$pids" ]] && echo "  running-processes (will be killed on apply): ${wt%:*}: $pids"
    done
    for i in "${!active_worktrees[@]}"; do
      if [[ "${active_reasons[$i]}" == caller-worktree ]]; then
        echo "  caller-worktree (caller uses it, worktree and branch kept): ${active_worktrees[$i]}"
      else
        echo "  agent-session (worktree and branch kept): ${active_worktrees[$i]} [pid:agent=${active_details[$i]% }]"
      fi
    done
    for i in "${!dirty_worktrees[@]}"; do
      echo "  dirty-worktree (uncommitted changes, branch kept, not touched): ${dirty_worktrees[$i]} [${dirty_details[$i]}]"
    done
    for i in "${!equivalent_worktrees[@]}"; do
      echo "  worktree-equivalent (content on trunk, removable with --remove-equivalent): ${equivalent_worktrees[$i]} [${equivalent_details[$i]}]"
    done
    for i in "${!unmerged_worktrees[@]}"; do
      echo "  unmerged-worktree (not proven merged, never removed): ${unmerged_worktrees[$i]} [${unmerged_details[$i]}]"
    done
    $remote_skipped_unknown && echo "  open-prs-unknown (gh pr list failed, remote deletion skipped for this repo)"
    [[ ${#new_empty_worktrees[@]} -gt 0 ]] && echo "  worktrees-new-empty (branch created but never committed to, branch kept, not touched): ${new_empty_worktrees[*]}"
    [[ ${#stale_empty_worktrees[@]} -gt 0 ]] && echo "  worktrees-stale-empty (never committed to, branch older than ${stale_empty_days}d, clean and idle: worktree and branch removed on apply): ${stale_empty_worktrees[*]}"
    for i in "${!handoff_removals[@]}"; do
      echo "  stale-handoff (recap or plans of a gone branch, or trunk/detached ones older than ${handoff_days}d: removed on apply): ${handoff_removals[$i]} [${handoff_reasons[$i]}]"
    done
  else
    for wt in "${stale_empty_worktrees[@]}"; do
      path="${wt%:*}"
      br="${wt##*:}"
      # Re-check right before acting: the worktree may have been picked up
      # since the scan. Never kill anything here; an in-use one is skipped.
      if [[ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]] \
         || ! worktree_branch_is_new_empty "$br" \
         || ! worktree_is_stale_empty "$br" "$path" "$(classify_worktree_processes "$path")"; then
        late_protected["$br"]=1
        echo "repo=$name skip-worktree=$path branch=$br reason=stale-empty-changed"
        skipped=$((skipped + 1))
        continue
      fi
      if ! git worktree remove "$path" 2>/dev/null; then
        echo "repo=$name skip-worktree=$path reason=remove-failed"
        skipped=$((skipped + 1))
        continue
      fi
      echo "repo=$name removed-worktree=$path reason=stale-empty"
      removed_worktrees=$((removed_worktrees + 1))
      if git merge-base --is-ancestor "$br" "origin/$trunk" 2>/dev/null && git branch -D "$br" >/dev/null 2>&1; then
        echo "repo=$name deleted-local=$br reason=stale-empty"
        deleted_local=$((deleted_local + 1))
      else
        echo "repo=$name skip-local=$br reason=delete-failed"
        skipped=$((skipped + 1))
      fi
    done
    for wt in "${worktree_removals[@]}"; do
      path="${wt%:*}"
      br="${wt##*:}"
      if ! stop_worktree_processes "$path"; then
        late_protected["$br"]=1
        echo "repo=$name skip-worktree=$path branch=$br reason=$stop_reason"
        skipped=$((skipped + 1))
        continue
      fi
      if git worktree remove "$path" 2>/dev/null; then
        echo "repo=$name removed-worktree=$path"
        removed_worktrees=$((removed_worktrees + 1))
      else
        echo "repo=$name skip-worktree=$path reason=remove-failed"
        skipped=$((skipped + 1))
      fi
    done
    for i in "${!equivalent_worktrees[@]}"; do
      ew="${equivalent_worktrees[$i]}"
      path="${ew%:*}"
      br="${equivalent_branches[$i]}"
      if ! $remove_equivalent; then
        echo "repo=$name keep-worktree=$path branch=${ew##*:} reason=equivalent-not-enabled ${equivalent_details[$i]}"
        kept_unmerged=$((kept_unmerged + 1))
        continue
      fi
      # The bucket was derived moments ago in this run; re-prove right before acting.
      if ! worktree_is_equivalent "$path" "${equivalent_refs[$i]}" "$br"; then
        if [[ -n "$br" ]]; then late_protected["$br"]=1; fi
        echo "repo=$name skip-worktree=$path branch=${ew##*:} reason=equivalent-changed"
        skipped=$((skipped + 1))
        continue
      fi
      if ! git worktree remove "$path" 2>/dev/null; then
        echo "repo=$name skip-worktree=$path reason=remove-failed"
        skipped=$((skipped + 1))
        continue
      fi
      echo "repo=$name removed-worktree=$path reason=content-on-trunk"
      removed_worktrees=$((removed_worktrees + 1))
      [[ -n "$br" ]] || continue
      if worktree_branch_proven_on_trunk "$br" && git branch -D "$br" >/dev/null 2>&1; then
        echo "repo=$name deleted-local=$br reason=content-on-trunk"
        deleted_local=$((deleted_local + 1))
      else
        echo "repo=$name skip-local=$br reason=delete-failed"
        skipped=$((skipped + 1))
      fi
    done
    for i in "${!active_worktrees[@]}"; do
      aw="${active_worktrees[$i]}"
      details="${active_details[$i]% }"
      echo "repo=$name keep-worktree=${aw%:*} branch=${aw##*:} reason=${active_reasons[$i]}${details:+ [$details]}"
      skipped=$((skipped + 1))
    done
    for i in "${!dirty_worktrees[@]}"; do
      dw="${dirty_worktrees[$i]}"
      echo "repo=$name skip-worktree=${dw%:*} branch=${dw##*:} reason=${dirty_reasons[$i]}"
      skipped=$((skipped + 1))
    done
    for i in "${!unmerged_worktrees[@]}"; do
      uw="${unmerged_worktrees[$i]}"
      echo "repo=$name keep-worktree=${uw%:*} branch=${uw##*:} reason=unmerged-worktree ${unmerged_details[$i]}"
      kept_unmerged=$((kept_unmerged + 1))
    done
    for b in "${kept_local[@]}"; do
      [[ -z "${late_protected[$b]:-}" ]] || continue
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
      [[ -z "${late_protected[$b]:-}" ]] || continue
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
      [[ -z "${late_protected[$b]:-}" ]] || continue
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
    if $remote_skipped_unknown; then
      echo "repo=$name skip-remote-all reason=open-prs-unknown"
      skipped=$((skipped + 1))
    fi
    for b in "${kept_remote[@]}"; do
      [[ -z "${late_protected[$b]:-}" ]] || continue
      if ! read_worktrees; then
        echo "repo=$name skip-remote=$b reason=worktree-list-failed"
        skipped=$((skipped + 1))
        continue
      fi
      for i in "${!worktree_branches[@]}"; do
        [[ "${worktree_branches[$i]}" == "$b" ]] || continue
        path="${worktree_paths[$i]}"
        [[ -d "$path" ]] || continue
        reason="$(process_keep_reason "$(classify_worktree_processes "$path")")"
        if [[ -n "$reason" ]]; then
          echo "repo=$name skip-remote=$b reason=$reason"
          skipped=$((skipped + 1))
          continue 2
        fi
      done
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
    if ! $keep_handoffs && ! $remote_only; then
      while IFS=$'\t' read -r f r; do
        if { if [[ -d "$f" ]]; then rm -rf -- "$f"; else rm -f -- "$f"; fi; } 2>/dev/null; then
          echo "repo=$name deleted-handoff=$f reason=$r"
          deleted_handoffs=$((deleted_handoffs + 1))
        else
          echo "repo=$name skip-handoff=$f reason=remove-failed"
          skipped=$((skipped + 1))
        fi
      done < <(stale_handoffs)
    fi
  fi
done

if [[ "$mode" == "scan" ]]; then
  echo "summary: scanned=$scanned with-candidates=$with_candidates clean=$clean errors=$errors unmerged-worktrees=$unmerged_total"
else
  echo "summary: deleted-local=$deleted_local deleted-remote=$deleted_remote removed-worktrees=$removed_worktrees skipped=$skipped kept-unmerged=$kept_unmerged deleted-handoffs=$deleted_handoffs"
fi
