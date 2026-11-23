---
description: Scan every repo under ~/git/ for branches already merged into trunk (or develop under Gitflow) and worktrees pointing at them, then delete what's confirmed.
---

Delete local/remote branches already merged into trunk, and worktrees on those branches, across every repo under `~/git/`. All discovery and deletion goes through `scripts/clean-repos.sh`, one call per phase. Always confirm before deleting.

Optional scope: **$ARGUMENTS** — e.g. "only <repo>", "exclude <repo>", "exclude branch <name>", "local only", "remote only". Map these to script flags: `--only-repo <name>`, `--exclude-repo <name>`, `--exclude <branch|absolute worktree path>` (all repeatable; a path also protects that worktree's branch and is the only way to exclude a detached HEAD; a handoff recap's absolute path protects that recap), `--local-only`, `--remote-only`, `--stale-empty-days <n>` ("stale after N days"), `--handoff-days <n>` ("keep trunk recaps N days"), `--keep-handoffs` ("keep handoff recaps"), `--remove-equivalent` (apply only; "also remove worktrees whose content is already on trunk"). Pass them to both `scan` and `apply` (`--remove-equivalent` to `apply` only); don't filter client-side.

**Every script call:** pass `timeout: 300000` and redirect to a file, then `Read` the file. Scans across many repos exceed the default timeout, and the Bash tool's captured output has been seen to come back empty — even without backgrounding.

## Step 1 — Scan (read-only)

Create a unique log directory outside the worktrees that apply may remove. Read the logs and delete this directory when finished, including on failure or when cleanup is cancelled; retain it only for diagnosis and report its path and reason.

```bash
cleanup_log_dir="$(mktemp -d "${TMPDIR:-/tmp}/agent-clean-repos.XXXXXX")"
printf '%s\n' "$cleanup_log_dir"
```

Use the printed absolute directory in subsequent tool calls; shell variables do not persist between calls. Replace `$cleanup_log_dir` below with that literal path.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/clean-repos.sh" scan "$HOME/git" [flags] > "$cleanup_log_dir/scan.txt" 2>&1; echo "exit:$?" >> "$cleanup_log_dir/scan.txt"
```

Prints one block per repo with candidates (clean repos are silent), then a `summary:` line. Besides plain `local:` and `remote:` branches and `worktrees:`, these candidate types need attention:
- `local-squash-merged-verified:` — merged per `gh`, and the branch's content is confirmed on trunk. `apply` deletes these with `git branch -D`.
- `local-squash-merged-unverified:` — merged per `gh`, but the branch's own patch differs from the merge commit. `apply` always skips these; the user can `git branch -D` them after checking the PR landed.
- `dirty-worktree:` — branch looks merged but the worktree has uncommitted edits, summarized as tracked/untracked counts (untracked files listed). Excluded from deletion; that diff is the only copy of the work. Never discard it without the user's explicit say-so.
- `unmerged-worktree:` — a worktree whose branch (or detached HEAD) is not proven merged: unmerged commits, an open PR or a detached HEAD. Reported with `ahead=`, `pushed=`, `pr=`, dirty counts, `content-on-trunk=yes` when its changes are already on trunk and, in `scan` only, `likely-superseded-by=#N` when its commit subjects match a trunk commit. These hints are context for a manual decision, never a deletion signal: `apply` never removes these worktrees or branches (`keep-worktree=… reason=unmerged-worktree`, counted in `kept-unmerged=`, not in `skipped=`).
- `worktree-equivalent:` — an unmerged worktree (branch or detached HEAD) whose content is proven on trunk (every commit cherry-picked, or the branch adds nothing to trunk; never judged by commit subject), clean, without open PR (unknown PR state keeps it) and idle. `apply` keeps it (`reason=equivalent-not-enabled`) unless `--remove-equivalent` is passed; then it removes the worktree and branch (`reason=content-on-trunk`). Ask the user before passing the flag.
- `worktrees-new-empty:` — branch created but never committed to, recently or with the worktree dirty or in use. Excluded from deletion.
- `worktrees-stale-empty:` — branch never committed to and created more than 1 day ago (`--stale-empty-days`), worktree clean, no process mentions its path and `lsof` shows nothing open in it. `apply` re-checks all of that, then removes the worktree and its branch; it never kills processes for these. Ignored files in the worktree (`.env`, `node_modules`, `.agent-tmp`) are lost on removal, as for merged worktrees.
- `stale-handoff:` — a handoff recap (`agent-handoff-*.md` in the repo's common git dir) or a plan directory (`agent-plans/<repo>-<branch>/` there) that no longer serves resuming a branch: its branch is gone (`branch-gone`) or deleted by this `apply` (`branch-deleted-on-apply`), or it is a trunk or detached-HEAD recap older than 7 days (`--handoff-days`, `older-than-<n>d`). `apply` re-derives them after its branch deletions, so a branch that fails to delete keeps its recap. `--exclude <branch>` or the recap's absolute path protects it; `--keep-handoffs` and `--remote-only` leave all recaps alone.
- `running-processes:` — non-agent leftover processes (`pid:comm`) started from a worktree that `apply` will kill before removing it.
- `agent-session:` — a claude/codex session runs in the worktree (by cwd or argv path, or as an ancestor of a process using it). Worktree, branches (local and remote) and processes are kept whole (`reason=agent-session`, counted in `skipped=`, also if the agent appears between scan and apply). `running-processes` never holds such a session. The caller and its ancestor chain are never signaled.
- `caller-worktree:` — the caller uses the worktree. The worktree and its branch are kept unless the user explicitly requests `--remove-caller-worktree`. Pass that flag to both scan and apply. The usual merge, clean-worktree, and agent-session checks still apply. After opting in, run subsequent commands from a surviving directory.
- `open-prs-unknown` — `gh` could not list open PRs, so remote deletion is skipped for that repo (deleting a PR's branch closes it).

## Step 2 — Confirm

Show the candidates grouped by repo and wait for explicit confirmation. Remote deletion is not reversible.

## Step 3 — Apply

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/clean-repos.sh" apply "$HOME/git" [same flags] > "$cleanup_log_dir/apply.txt" 2>&1; echo "exit:$?" >> "$cleanup_log_dir/apply.txt"
```

`apply` re-derives candidates fresh (new fetch, new merge check) and removes worktrees before their branch. It uses `git branch -D` only after confirming the branch is an ancestor of `origin/<trunk>` or that its content is already on trunk. Skips are reported as `not-fully-merged`, `squash-merged-verify-manually`, `uncommitted-changes`, `remove-failed`, `caller-worktree`, `agent-session`, `processes-changed`, `delete-failed`, `push-delete-failed`, `stale-empty-changed` or `open-prs-unknown` — relay them, don't override.

## Output format

1. **Scanned** — repos scanned / with candidates / clean / errored (with brief reason)
2. **Deleted** — per repo: local branches, remote branches, worktrees, handoff recaps
3. **Skipped** — with reason
4. **Kept (unmerged)** — per repo: unmerged worktrees with their `ahead/pushed/pr` state and any `likely-superseded-by` hint from the scan (`apply` does not compute it); the user decides each one
