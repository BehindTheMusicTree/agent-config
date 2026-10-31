---
name: new-worktree
description: Create a git worktree and branch for a new task, then copy gitignored env files into it so the worktree is immediately runnable.
---

Resolve `SKILL_REPO_ROOT` from this SKILL.md’s actual location: follow any symlink for the skill directory, then take its grandparent directory. Set this environment variable before running the commands below; it must contain the shared `scripts/` directory.

Create a new git worktree with its own branch, then populate it with the same gitignored env files (`.env`, `.env.local`, etc.) the main worktree already has, so it's runnable without a manual setup pass.

The branch name is: **user-provided arguments**

If no branch name was given, ask for one before proceeding. Optionally the user may also specify a base ref (e.g. "off develop") — if so, pass it as a second argument below; otherwise let the script auto-detect the trunk.

## Step 1 — Run the setup script

```bash
"$SKILL_REPO_ROOT/scripts/new-worktree-setup.sh" <branch-name> [<base-ref>]
```

Allow enough time for the command to finish — the dependency install can exceed the 120s default, and output printed before an auto-move to the background is lost.

This does everything in one pass: detects the flow/trunk (Gitflow `develop` vs. GitHub `main`/`master`) unless a base ref was given, creates the worktree and branch at `.claude/worktrees/<slug>` (same location Claude Code's own `EnterWorktree` tool uses), discovers and copies every gitignored `.env`-style file, offsets any `PORT`-style variable by a deterministic per-branch amount (skipping `_REMOTE_PORT` variables, which point at a fixed port on another machine), rewrites any cross-file `localhost:<port>` reference so it stays in sync with the offset (e.g. one app's `BACKEND_URL` pointing at another app's port), and installs dependencies with the detected package manager (or a `.venv` for a bare `pyproject.toml`).

It prints `key=value` lines, ending in `status=ok` or `status=blocked reason=<reason>`. Trust its output — it re-derives everything fresh each run, so there's no need to re-run individual git/perl commands by hand to double-check it.

If `status=blocked`, stop and report the reason to the user rather than trying to work around it manually.

## Step 2 — Check for extra CLAUDE.md setup steps

The script installs dependencies via the detected package manager, but can't know about repo-specific setup steps documented in prose. When it prints `check_claude_md_setup=true`, check the repo root's `CLAUDE.md` for a documented Setup section and follow any additional commands it lists beyond a plain package install — things like installing a CLI's plugin collections, or registering pre-commit hooks (this has come up in practice: a repo whose `CLAUDE.md` Setup section required a venv install *and* `ansible-galaxy collection install` *and* `pre-commit install`, none of which a lockfile install alone would have caught). Run these from inside the new worktree, not the main one. Keep this generic — don't special-case any particular tool by name, just follow what the repo's own `CLAUDE.md` documents. If there's no Setup section, skip this and say so.

## Step 3 — Output format

Keep this terse, built from the script's `key=value` output:
1. Worktree path and branch name
2. Base ref it branched from
3. Count of env files copied (or "no gitignored env files found")
4. Port variables reassigned and their new values, plus any cross-file references rewritten (or "no port variables found"). If the script printed any `stale_ref=` lines, list each one and say the copied value points at a dead port that differs from `.env.example` — offer to fix it, don't rewrite it yourself
5. Whether dependencies were installed (with which package manager, or venv) — if `install_status=fail`, show the tail of `install_log` — and whether any extra `CLAUDE.md`-documented setup steps were run
6. If the script printed `dev_up_script=<path>` (not `none`), mention it as the next step to start dev servers, e.g. "To start dev servers: `<path>`" — don't run it yourself, this command only sets up the worktree. (Use `new-worktree-and-serve` instead when the user wants both done in one go.)
