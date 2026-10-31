---
description: Create a git worktree and branch for a new task, then start the repo's dev servers in it if it has a dev-up.sh script.
model: haiku
---

Same as `new-worktree`, plus starting dev servers in the new worktree — for when you know you'll want the servers running right away, not just the worktree set up.

The branch name is: **$ARGUMENTS**

If no branch name was given, ask for one before proceeding. Optionally the user may also specify a base ref (e.g. "off develop") — if so, pass it as a second argument below; otherwise let the script auto-detect the trunk.

## Step 1 — Run the setup script

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/new-worktree-setup.sh" <branch-name> [<base-ref>]
```

Same script and behavior as `new-worktree`'s Step 1 — see that command for the full description. Run it with the Bash tool's `timeout: 600000` (the dependency install can exceed the 120s default). If `install_status=fail`, show the tail of `install_log` in the output. If `status=blocked`, stop and report the reason rather than trying to work around it manually.

## Step 2 — Check for extra CLAUDE.md setup steps

Same as `new-worktree`'s Step 2: when the script prints `check_claude_md_setup=true`, check the repo root's `CLAUDE.md` for a documented Setup section and follow any additional commands it lists. Run these from inside the new worktree.

## Step 3 — Start dev servers, if the repo has a launcher

The setup script prints `dev_up_script=<path>` (relative to the worktree root) when it finds one, or `dev_up_script=none` otherwise — by convention, a repo-specific `scripts/dev-up.sh`, not something this shared script can generate generically since the startup sequence (Docker, migrations, build order, which processes to launch) is different in every repo.

- If `dev_up_script=none`: say so and stop here — there's nothing repo-specific to launch. Suggest the user check the repo's `CLAUDE.md`/`AGENTS.md` for its own manual dev-server instructions if they need one.
- Otherwise, run it from inside the new worktree:
  ```bash
  cd "<worktree-path>" && ./<dev_up_script>
  ```
  Pass through any flags the user mentioned (e.g. a specific port). Trust its own `key=value`/`status=` output the same way as the setup script — don't re-verify with manual `curl`/`lsof` calls unless it reports an error.

## Step 4 — Output format

Keep this terse, built from both scripts' `key=value` output:
1. Worktree path and branch name, base ref
2. Count of env files copied, port variables reassigned, cross-file references rewritten. Relay any `stale_ref=` lines (dead localhost port differing from `.env.example`) as a warning
3. Whether dependencies were installed (with which package manager)
4. Dev server result: URLs if `status=ok`, or the blocked/error reason and log tail if not (including `status=needs-decision` — relay the shared-API choice to the user rather than guessing `--own-api`/`--shared-api`)
