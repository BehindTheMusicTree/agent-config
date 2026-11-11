---
name: handoff
description: Write a self-contained recap of the current session, save it to a file outside the working tree so a fresh session can resume after /clear or in a new session.
---

If `${CODEX_HOME:-$HOME/.codex}/agent-config/workflow-policies/handoff.md` exists, read it before starting: its rules extend this workflow and take precedence over its defaults.

Produce a handoff recap so the user can drop this session's context and continue in a fresh one. Strictly read-only apart from the single recap file below: no commits and no other edits.

Optional focus: **user-provided arguments** — narrows the recap to that topic. Empty = whole session.

## Step 1 — Choose the resume directory

The resume directory is the absolute path of the checkout where the next session continues: the worktree of the feature in progress, or the checkout of the repository the next feature belongs to when that is another repository. Default to the current working directory. It must be an existing local git checkout; when the next work's repository has none, keep the current working directory and name that repository in **Remaining**. The next session starts there, so it loads that project's instructions.

## Step 2 — Collect state

A new session resumes from the recap right after it is written, so take decisions, PR numbers and remaining work from this session and run no other state check. Collect the repository state in one Bash call, adding `git status --short` and `git worktree list` for the current working directory when it is not the resume directory:

```bash
git -C <resume directory> rev-parse --path-format=absolute --git-common-dir
git -C <resume directory> branch --show-current
git -C <resume directory> rev-parse --short HEAD
git -C <resume directory> status --short
git -C <resume directory> worktree list
```

`<repo>` is the name of the repository's main checkout: the last component of the first path printed by `git -C <resume directory> worktree list`.

## Step 3 — Write the recap

At most about 30 lines, self-contained, in the language of the user's latest message. The recap exists to let the next session continue: spend the lines on context and remaining work, not on history.

Start with a header line: date, `<repo>`, branch and short HEAD SHA from Step 2, and the resume directory. Then these sections:

- **Context**: concise — the goal in one line, then only the decisions, constraints and facts the next session needs to continue (for example "no release unless asked", a chosen approach, a rejected alternative).
- **Remaining**: the core of the recap — ordered, actionable next steps, each specific enough to execute without rereading this session (files, commands, PR numbers, open questions for the user).
- **State**: worktrees and branches still alive, uncommitted changes, running servers.
- **Done**: very terse — one short line per item with its PR number or SHA, no description of how it was done.
- **Pointers**: only the plan files and docs the first **Remaining** step needs; the next session rereads nothing else.

Never include secret values, tokens, passwords or credentials; reference secrets by name or file path only. Leave out exploration history, tool output, and anything already in the repo or in the project instructions.

## Step 4 — Save

Write the recap to `agent-handoff-<repo>-<name>.md` inside the common git directory printed in Step 2, overwriting any previous recap for that name. Write it with one Bash heredoc (`cat > '<path>' <<'AGENT_HANDOFF_EOF'`), not a file-editing tool: such tools refuse to overwrite a file not read in this session, which would cost a failed call and a read of the old recap. `<name>` is the resume directory's branch; when `git branch --show-current` printed nothing, HEAD is detached and `<name>` is `detached-<short SHA>`. In both `<repo>` and `<name>`, replace every character outside `[A-Za-z0-9._-]` with `-`. Keep the absolute path for Step 5. One file per branch keeps parallel worktree sessions from overwriting each other. The common git dir is shared by all worktrees, so the file never shows in `git status` and survives worktree removal. Outside a git repository, or when the write fails, no file exists: say so and print the recap in Step 5.

## Step 5 — Report

When the file was written, do not print the recap: the file already holds it, and printing would generate it a second time. Reply with one line only:

- "Start a new session with `codex -C '<resume directory>'` and ask it to read `<absolute path of the file written in Step 4>`."

When no file was written, print the recap as a fenced block instead, followed by: "Start a new session with `codex -C '<resume directory>'` and paste the block."
