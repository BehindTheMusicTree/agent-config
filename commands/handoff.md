---
description: Write a self-contained recap of the current session, save it to a file outside the working tree so a fresh session can resume after /clear or in a new session.
---

If `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agent-config/workflow-policies/handoff.md` exists, read it before starting: its rules extend this workflow and take precedence over its defaults.

Produce a handoff recap so the user can drop this session's context and continue in a fresh one. Strictly read-only apart from the single recap file below: no commits and no other edits.

Optional focus: **$ARGUMENTS** — narrows the recap to that topic. Empty = whole session.

## Step 1 — Collect state

A new session resumes from the recap right after it is written, so take decisions, PR numbers and remaining work from this session and run no other state check. Collect the repository state in one Bash call:

```bash
git rev-parse --path-format=absolute --git-common-dir
git branch --show-current
git rev-parse --short HEAD
git status --short
git worktree list
```

## Step 2 — Write the recap

At most about 30 lines, self-contained, in the language of the user's latest message. The recap exists to let the next session continue: spend the lines on context and remaining work, not on history.

Start with a header line: date, repository, branch, short HEAD SHA. Then these sections:

- **Context**: concise — the goal in one line, then only the decisions, constraints and facts the next session needs to continue (for example "no release unless asked", a chosen approach, a rejected alternative).
- **Remaining**: the core of the recap — ordered, actionable next steps, each specific enough to execute without rereading this session (files, commands, PR numbers, open questions for the user).
- **State**: worktrees and branches still alive, uncommitted changes, running servers.
- **Done**: very terse — one short line per item with its PR number or SHA, no description of how it was done.
- **Pointers**: plan files and docs to reread.

Never include secret values, tokens, passwords or credentials; reference secrets by name or file path only. Leave out exploration history, tool output, and anything already in the repo or in the project instructions.

## Step 3 — Save

Write the recap to `agent-handoff-<name>.md` inside the common git directory printed in Step 1, overwriting any previous recap for that name. `<name>` is the branch name with every character outside `[A-Za-z0-9._-]` replaced by `-`; when `git branch --show-current` prints nothing, HEAD is detached and `<name>` is `detached-<short SHA>`. Keep the absolute path for Step 4. One file per branch keeps parallel worktree sessions from overwriting each other. The common git dir is shared by all worktrees, so the file never shows in `git status` and survives worktree removal. Outside a git repository, or when the write fails, no file exists: say so and print the recap in Step 4.

## Step 4 — Report

When the file was written, do not print the recap: the file already holds it, and printing would generate it a second time. Reply with one line only:

- "Run `/clear`, then send `@<absolute path of the file written in Step 3>`."

When no file was written, print the recap as a fenced block instead, followed by: "Run `/clear`, then paste the block."
