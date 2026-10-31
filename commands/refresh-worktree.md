---
description: Reuse the current git worktree for a new feature — stop any dev server still running for it, reset onto the integration branch, create the new branch, then scan for available ports and start the project's dev server(s), reporting the URLs.
model: sonnet
---

Move the current worktree from an already-merged feature branch to a new one, without removing/re-adding the worktree directory or reinstalling dependencies, then serve the project again:

```text
stop old server → old branch → trunk → new branch → pick free ports → start server
```

Raw arguments: **$ARGUMENTS**

`$ARGUMENTS` may bundle a worktree hint with the branch name (e.g. `on worktree  down  (not main worktree).\n  branch: feature/x`). The new branch is the text after `branch:` if present, otherwise the whole string. No branch name → ask. Anything ambiguous for this repo (which server, which port, how it's served) → ask, don't guess.

## Step 0 — Enter the target worktree

The shell's cwd is not guaranteed to be the intended worktree. Resolve it before running anything else:

1. `git worktree list`.
2. If `$ARGUMENTS` names a worktree (folder name, path fragment, "not main worktree"), match it; otherwise use the cwd.
3. `cd` there and verify:
   ```bash
   pwd && git rev-parse --show-toplevel && git branch --show-current
   ```
   Branch doesn't match `git worktree list`, or the name matches several worktrees → stop and ask.
4. Run every later command from this directory.

## Steps 1–6 — Precheck (scripted, non-destructive)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/refresh-worktree-precheck.sh" precheck
```

Detects the flow, stops this worktree's dev server(s), checks branch / clean tree / merged into trunk, and fast-forwards trunk. Prints `flow=`, `trunk=`, `killed_pids=`, `old_branch=`, then either `merged=true trunk_updated=true status=ok` or `status=blocked reason=<reason>`. Trust the result; don't re-run the git checks by hand.

On `blocked`, stop and report — never work around it:
- `detached-head` — user must check out a branch first.
- `dirty-tree` — list the `dirty_file=` lines and ask. Never stash, reset, or clean.
- `fetch-failed` — network/auth issue; surface it.
- `not-merged` — branch tree differs from `origin/<trunk>` (content comparison, so squash merges count as merged). User must land it or confirm it's abandoned.
- `switch-trunk-failed` / `trunk-diverged` — ask; don't merge or reset trunk yourself.

The script only sends SIGTERM to PIDs whose cwd is inside this worktree. If `killed_pids` looks wrong, ask.

## Step 7 — Confirm

```text
Worktree: <cwd>
Old branch: <old_branch> (identical to origin/<trunk>)
Trunk: <trunk>
Old dev server: <killed_pids | none running>

Deleting: <old_branch>
Creating: <new-branch>
```

Wait for explicit confirmation.

## Step 8 — Switch branches

```bash
git branch -d <old-branch>
git switch -c <new-branch>
git branch --show-current && git status --short && git log -1 --oneline
```

Always `-d`, never `-D`. If `-d` refuses, stop and re-run the precheck.

## Step 9 — Detect how the project is served

First match wins:
1. **Nx** (`nx.json`): find `serve`/`dev` targets. If `AGENTS.md`/`CLAUDE.md`/`CONTRIBUTING.md` document a combined command (e.g. `nx run-many --target=serve --projects=...`) or a startup script, use it — serving one app alone can miss a required API.
2. **package.json** `dev`/`start` script, with the package manager matching the lockfile.
3. **docker-compose**, only if the docs point to it for local dev.

None apply → ask.

## Step 10 — Pick free ports

Read each server's port from the project's config (`.env*`, `next.config`, compose mappings, including any worktree offset `new-worktree-setup.sh` already wrote). Then:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/refresh-worktree-precheck.sh" check-port <port>
```

- `status=free` → use it.
- `status=occupied-in-worktree` → shouldn't happen after the precheck; investigate.
- `status=occupied-other` → don't kill it. Try the next port with `check-port`; if none nearby is free, ask.

## Step 11 — Start in the background

If a non-default port needs an env var (e.g. `PORT=3001`) and the command starts several projects at once, check for leakage first:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/refresh-worktree-precheck.sh" check-env-var <VARNAME> <other-project-dir>
```

`defines_<VARNAME>=true` for another project → a shell-level var would override that project's `.env` value too. Start the overridden project on its own with the var scoped to it, and the rest together.

Launch with `run_in_background: true`.

## Step 12 — Verify

Poll until each server is ready (bounded retries), then:

```bash
curl -sS -o /dev/null -w '%{http_code}' http://localhost:<port>
```

Use the ports actually chosen in Step 10. A server that fails to start → show the tail of its output and stop. Never report a URL that isn't live.

## Output format

1. Old dev server stopped (or none running)
2. Trunk used, and flow detected (gitflow/github)
3. Old branch deleted; new branch created from `<trunk>`
4. Working tree status
5. Worktree directory untouched (no `git worktree remove`/`add`)
6. Serve command(s)
7. Live URL(s), one per line, flagging any non-default port
