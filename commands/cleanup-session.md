---
description: After a feature/fix/release is done, remove this repo's dev leftovers — merged branches, their worktrees, and docker containers/networks/images.
model: sonnet
---

Clean up the current repo after a finished session. Everything runs through `scripts/cleanup-session.sh` (branch/worktree logic is `clean-repos.sh` scoped to this repo, then docker). Always confirm before deleting.

Optional flags: **$ARGUMENTS** — pass through as-is: `--local-only`, `--remote-only`, `--exclude <branch>`, `--no-docker`. Empty = defaults.

**Every script call:** `timeout: 300000`, redirect to a file, then `Read` it (captured output has come back empty otherwise).

## Step 1 — Scan (read-only)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cleanup-session.sh" scan $ARGUMENTS > /tmp/cleanup-session-scan.txt 2>&1; echo "exit:$?"
```

Candidate types (`local-squash-merged`, `dirty-worktrees`) behave as in `clean-repos`: squash-merged are never auto-deleted; dirty worktrees are never touched.

## Step 2 — Confirm

Show the candidates and wait for explicit confirmation. Remote deletion and `docker … down -v` (volumes) are irreversible. Listed `running-processes` are killed before their worktree is removed. `skipped=shared` compose projects (not named after their worktree) are never downed. If docker is unresponsive the script runs `docker-unstick` (when installed: restarts Docker Desktop and prunes unused images/containers/build cache) — relay its output.

## Step 3 — Apply

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cleanup-session.sh" apply $ARGUMENTS > /tmp/cleanup-session-apply.txt 2>&1; echo "exit:$?"
```

Relay skips (`not-fully-merged`, `squash-merged-verify-manually`, `uncommitted-changes`) as-is; don't override.

## Output format

1. **Branches** — local/remote deleted
2. **Worktrees** — removed
3. **Docker** — compose projects downed, containers/images/networks pruned (or "skipped")
4. **Skipped** — with reason
