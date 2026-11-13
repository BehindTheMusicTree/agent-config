---
name: cleanup-session
description: After a feature/fix/release is done, remove this repo's dev leftovers — merged branches, their worktrees, and docker containers/networks/images.
---

Resolve `SKILL_REPO_ROOT` from this SKILL.md’s actual location: follow any symlink for the skill directory, then take its grandparent directory. Set this environment variable before running the commands below; it must contain the shared `scripts/` directory.

Clean up the current repo after a finished session. Run it only once the session's PR is merged; keep the worktree and branch through CI fixes and review until then. Everything runs through `scripts/cleanup-session.sh` (branch/worktree logic is `clean-repos.sh` scoped to this repo, then docker). Elements belonging to the current session — its branch (local and remote), its worktree, and the docker compose projects whose name is tied to its worktree — are deleted without asking for confirmation. Always confirm before deleting anything else the script finds that is not related to the current session: other branches, their worktrees and remotes, compose projects of other worktrees (including `dir=gone` ones). The machine-wide docker prunes (stopped containers, dangling images, unused networks) and `docker-unstick` are not asked about: run them as part of apply.

Optional flags: **user-provided arguments** — pass through as-is: `--local-only`, `--remote-only`, `--exclude <branch>`, `--no-docker`. Empty = defaults.

**Every script call:** allow enough time, redirect to a file, then read it (captured output has come back empty otherwise).

## Step 1 — Scan (read-only)

```bash
"$SKILL_REPO_ROOT/scripts/cleanup-session.sh" scan [flags] > /tmp/cleanup-session-scan.txt 2>&1; echo "exit:$?"
```

Candidate types (`local-squash-merged`, `dirty-worktrees`) behave as in `clean-repos`: squash-merged are never auto-deleted; dirty worktrees are never touched.

## Step 2 — Confirm unrelated candidates only

Split the scan candidates into two groups. **Current session:** the branch(es) this conversation worked on, their remote branches and worktrees, and compose projects whose name matches this session's worktree — apply these without asking. **Unrelated:** every other branch, remote branch or worktree the script found (it scans the whole repo, not just this session), every compose project not tied to this session's worktree (including `dir=gone` ones: `down -v` deletes their volumes), — list them and wait for explicit confirmation of exactly those. The machine-wide prunes of stopped containers, dangling images and unused networks (counts shown by the scan) and `docker-unstick` if triggered need no confirmation: apply runs them. For branches not confirmed, add `--exclude <branch>` to the apply command; if other compose projects are not confirmed, run apply with `--no-docker` and handle the session's own compose project manually. Remote deletion and `docker … down -v` (volumes) are irreversible. Listed `running-processes` are killed before their worktree is removed. `skipped=shared` compose projects (not named after their worktree) are never downed. If docker is unresponsive the script runs `docker-unstick` (when installed: restarts Docker Desktop and prunes unused images/containers/build cache) — relay its output.

## Step 3 — Apply

Append the `--exclude` / `--no-docker` flags decided in Step 2 to the flags below.

```bash
"$SKILL_REPO_ROOT/scripts/cleanup-session.sh" apply [flags] > /tmp/cleanup-session-apply.txt 2>&1; echo "exit:$?"
```

Relay skips (`not-fully-merged`, `squash-merged-verify-manually`, `uncommitted-changes`) as-is; don't override.

## Output format

1. **Branches** — local/remote deleted
2. **Worktrees** — removed
3. **Docker** — compose projects downed, containers/images/networks pruned (or "skipped")
4. **Skipped** — with reason
