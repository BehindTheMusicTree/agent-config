---
name: clean-repos
description: Scan every repo under ~/git/ for branches already merged into trunk (or develop under Gitflow) and worktrees pointing at them, then delete what's confirmed.
---

Resolve `SKILL_REPO_ROOT` from this SKILL.md’s actual location: follow any symlink for the skill directory, then take its grandparent directory. Set this environment variable before running the commands below; it must contain the shared `scripts/` directory.

Delete local/remote branches already merged into trunk, and worktrees on those branches, across every repo under `~/git/`. All discovery and deletion goes through `scripts/clean-repos.sh`, one call per phase. Always confirm before deleting.

Optional scope: **user-provided arguments** — e.g. "only <repo>", "exclude <repo>", "exclude branch <name>", "local only", "remote only". Map these to script flags: `--only-repo <name>`, `--exclude-repo <name>`, `--exclude <branch>` (all repeatable), `--local-only`, `--remote-only`. Pass them to both `scan` and `apply`; don't filter client-side.

**Every script call:** allow enough time and redirect to a file, then read the file. Scans across many repos exceed the default timeout, and the Bash tool's captured output has been seen to come back empty — even without backgrounding.

## Step 1 — Scan (read-only)

```bash
"$SKILL_REPO_ROOT/scripts/clean-repos.sh" scan "$HOME/git" [flags] > /tmp/clean-repos-scan.txt 2>&1; echo "exit:$?" >> /tmp/clean-repos-scan.txt
```

Prints one block per repo with candidates (clean repos are silent), then a `summary:` line. Two special candidate types:
- `local-squash-merged:` — merged per `gh`, but not a git ancestor of trunk. `apply` always skips these (`-d` can't delete them). The user can `git branch -D` them after checking the PR landed.
- `dirty-worktrees:` — branch looks merged but the worktree has uncommitted edits. Excluded from deletion; that diff is the only copy of the work.

## Step 2 — Confirm

Show the candidates grouped by repo and wait for explicit confirmation. Remote deletion is not reversible.

## Step 3 — Apply

```bash
"$SKILL_REPO_ROOT/scripts/clean-repos.sh" apply "$HOME/git" [same flags] > /tmp/clean-repos-apply.txt 2>&1; echo "exit:$?" >> /tmp/clean-repos-apply.txt
```

`apply` re-derives candidates fresh (new fetch, new merge check), removes worktrees before their branch, and never force-deletes. Skips are reported as `not-fully-merged`, `squash-merged-verify-manually`, or `uncommitted-changes` — relay them, don't override.

## Output format

1. **Scanned** — repos scanned / with candidates / clean / errored (with brief reason)
2. **Deleted** — per repo: local branches, remote branches, worktrees
3. **Skipped** — with reason
