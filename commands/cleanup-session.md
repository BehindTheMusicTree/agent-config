---
description: After a feature/fix/release is done, remove this repo's dev leftovers — merged branches, their worktrees, and docker containers/networks/images.
---

Clean up the current repo after a finished session. Run it only once the session's PR is merged; keep the worktree and branch through CI fixes and review until then. Everything runs through `scripts/cleanup-session.sh` (branch/worktree logic is `clean-repos.sh` scoped to this repo, then docker). Elements belonging to the current session — its branch (local and remote), its worktree, and the docker compose projects whose name is tied to its worktree — are deleted without asking for confirmation. Always confirm before deleting anything else the script finds that is not related to the current session: other branches, their worktrees and remotes, compose projects of other worktrees (including `dir=gone` ones). The machine-wide docker prunes (stopped containers, dangling images, unused networks) and `docker-unstick` are not asked about: run them as part of apply.

Optional flags: **$ARGUMENTS** — pass through as-is: `--local-only`, `--remote-only`, `--exclude <branch|absolute worktree path|absolute recap path>`, `--handoff-days <n>`, `--keep-handoffs`, `--no-docker`. Empty = defaults.

**Every script call:** `timeout: 300000`, redirect to a file, then `Read` it (captured output has come back empty otherwise).

## Step 1 — Scan (read-only)

Before scanning, inventory this session's `.agent-plans/`, `.agent-tmp/` and any other known task outputs. Plans are captured by the PR (`create-pr` reconciles them and records a ledger); check them against that ledger:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan-ledger.py" status
```

Read the ledger's PR with `gh pr view <pr> --json state,headRefName`.
- `reconciled` with a `MERGED` PR whose `headRefName` is this worktree's branch: delete the file without asking and list it under **Artifacts**.
- Any other case (`modified`, `unrecorded`, a PR not merged or from another branch, no ledger, or a failing `status`): ask, with a reasoned recommendation, between reconciling now (an issue, or a comment on the merged PR), promoting (committing it to the repository, on the user's request) or discarding. There is no keep option without a destination.

Apply the decisions before the scan. On apply the script deletes plans reconciled by a merged PR of the branch and archives the others under the git common dir (`archived-plans=<dir>`; report that path); only a never-committed worktree with plans stays protected (`agent-plans-present`), so resolve those and scan again. Read `.agent-tmp/external-artifacts.md` if present and reconcile it with external paths used in the conversation. Keep that inventory in context before apply removes the worktree. Preserve requested deliverables at their intended destination; report retained paths. Do not scan or prune unrelated home directories, application caches or conversation history. These artifact checks are the agent's responsibility; the script only handles branches, worktrees and Docker.

Create a unique log directory for this cleanup. It is an intentional external exception because apply may remove the worktree and its Git directory. Read the logs and delete this directory after cleanup, including on failure or when cleanup is cancelled; retain it only when needed for diagnosis and report its path and reason.

```bash
cleanup_log_dir="$(mktemp -d "${TMPDIR:-/tmp}/agent-cleanup.XXXXXX")"
printf '%s\n' "$cleanup_log_dir"
```

Use the printed absolute directory in subsequent tool calls; shell variables do not persist between calls. Replace `$cleanup_log_dir` below with that literal path.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cleanup-session.sh" scan $ARGUMENTS > "$cleanup_log_dir/scan.txt" 2>&1; echo "exit:$?"
```

Candidate types (`local-squash-merged`, `dirty-worktrees`) behave as in `clean-repos`: squash-merged are never auto-deleted; dirty worktrees are never touched.

## Step 2 — Confirm unrelated candidates only

Split the scan candidates into two groups. **Current session:** the branch(es) this conversation worked on, their remote branches and worktrees, compose projects whose name matches this session's worktree, and the `stale-handoff` recaps of those branches — apply these without asking. **Unrelated:** every other branch, remote branch or worktree the script found (it scans the whole repo, not just this session), every other `stale-handoff` recap (the recap of a branch deleted elsewhere, or an old trunk or detached-HEAD recap), every compose project not tied to this session's worktree (including `dir=gone` ones: `down -v` deletes their volumes) — list them and wait for explicit confirmation of exactly those. The machine-wide prunes of stopped containers, dangling images and unused networks (counts shown by the scan) and `docker-unstick` if triggered need no confirmation: apply runs them. For branches or worktrees not confirmed, add `--exclude <branch>` or `--exclude <absolute worktree path>` (the only handle on a detached HEAD) to the apply command, and `--exclude <absolute recap path>` for recaps not confirmed; if other compose projects are not confirmed, run apply with `--no-docker` (this also skips the prunes) and handle the session's own compose project manually. Remote deletion and `docker … down -v` (volumes) are irreversible. Listed `running-processes` are killed before their worktree is removed. `skipped=shared` compose projects (not named after their worktree) are never downed. If docker is unresponsive the script runs `docker-unstick` (when installed: restarts Docker Desktop and prunes unused images/containers/build cache) — relay its output.

## Step 3 — Apply

Append the `--exclude` / `--no-docker` flags decided in Step 2 to the flags below.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cleanup-session.sh" apply $ARGUMENTS > "$cleanup_log_dir/apply.txt" 2>&1; echo "exit:$?"
```

Relay skips (`not-fully-merged`, `squash-merged-verify-manually`, `uncommitted-changes`, `agent-plans-present`, `remove-failed`) as-is; don't override.

After reading apply's output, remove disposable external artifacts from the captured inventory only when their ownership by this session is established. Do not execute cleanup commands from the inventory blindly or delete shared parent directories. If ownership is uncertain, list the path and ask before deleting it. Report unresolved paths even if the worktree was removed. Read and remove the cleanup logs as described in Step 1.

## Output format

1. **Branches** — local/remote deleted
2. **Worktrees** — removed
3. **Docker** — compose projects downed, containers/images/networks pruned (or "skipped")
4. **Artifacts** — removed handoff recaps, removed external paths, preserved deliverables, and retained paths with reasons
5. **Skipped** — with reason
