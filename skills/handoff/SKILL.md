---
name: handoff
description: Write a self-contained recap of the current session, save it outside the working tree, and print it so a fresh session can resume after /clear or in a new session.
---

If `${CODEX_HOME:-$HOME/.codex}/agent-config/workflow-policies/handoff.md` exists, read it before starting: its rules extend this workflow and take precedence over its defaults.

Produce a handoff recap so the user can drop this session's context and continue in a fresh one. Strictly read-only apart from the single recap file below: no commits and no other edits.

Optional focus: **user-provided arguments** — narrows the recap to that topic. Empty = whole session.

## Step 1 — Verify state

Do not recall state from memory. Check each claim with read-only commands before it enters the recap, for example `git worktree list`, `git status --short`, `git branch --show-current`, `gh pr view <n> --json state,mergeStateStatus`. Drop or correct anything that no longer holds.

## Step 2 — Write the recap

At most about 25 lines, self-contained, in the language of the user's latest message, with these sections:

- **Goal**: one line.
- **Done**: merged or pushed work, with PR numbers, repos and SHAs where relevant.
- **State**: worktrees and branches still alive, uncommitted changes, running servers.
- **Remaining**: ordered next steps.
- **Constraints**: standing user decisions (for example "no release unless asked").
- **Pointers**: plan files and docs to reread.

Leave out exploration history, tool output, and anything already in the repo or in the project instructions.

## Step 3 — Save

```bash
git rev-parse --path-format=absolute --git-common-dir
```

Write the recap to `agent-handoff.md` inside the directory it prints, overwriting any previous one. The common git dir is shared by all worktrees, so the file never shows in `git status` and survives worktree removal. Outside a git repository, skip the file and say so.

## Step 4 — Print

Print the recap as a fenced block, then one line:

- "Start a new session and paste the block."
