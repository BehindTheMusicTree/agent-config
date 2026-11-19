---
name: handoff
description: Write a self-contained recap of the current session, save it to a file outside the working tree so a fresh session can resume after /clear or in a new session.
---

Produce a handoff recap so the user can drop this session's context and continue in a fresh one. While generating this recap, only write the recap file; do not commit or edit the repository. This restriction applies only to recap generation, not to work resumed from it.

Optional focus: **user-provided arguments** — narrows the recap to that topic. Empty = whole session.

## Step 1 — Choose the resume directory

The resume directory is the absolute path of the checkout where the next session continues: the worktree of the feature in progress, or the checkout of the repository the next feature belongs to when that is another repository. Default to the current working directory. It must be an existing local git checkout; when the next work's repository has none, keep the current working directory and name that repository in **Following**. The next session starts there, so it loads that project's instructions.

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

First choose the next session's model. Classify **Following** (not the whole plan) as `plan` (design, planning), `diag` (investigation, diagnosis), `implement`, or `pr-bump-release` (PR, CI fixes, version bump, tag, publication, local resynchronization). Look up that phase in the global instructions' **Handoff models** table: columns `phase`, `claude` and `codex`, one row per phase, each client cell written `<model>/<effort>` (for example `sonnet/medium`). When the table, the row or this client's cell is missing, the model flags are empty: drop `<model flags>` and its leading space from the commands below and say so in Step 5.

Start with a header line: date, `<repo>`, branch and short HEAD SHA from Step 2, the resume directory, and the phase. Then, on the next line, the **Resume check**: if the working directory of the session reading the recap is not the resume directory, that session does nothing else and tells the user to restart with `codex -C '<resume directory>' <model flags> '<instruction to read <absolute path of the file written in Step 4> and resume, in the recap language>'`, where `<model flags>` is `-m <model> -c model_reasoning_effort=<effort>`. Then these sections:

- **Context**: concise — the goal in one line, then only the decisions, constraints and facts the next session needs to continue (for example a chosen approach, a rejected alternative, or a pending release confirmation). Preserve the user's task scope, granted authorization and pending confirmations, including any approved release's repositories, version, scope and publication/deployment effects. Do not turn this workflow's read-only restriction into a constraint on resumed work. Distinguish state ("not committed yet", "no PR yet") from an explicit prohibition; do not invent restrictions or discard existing authorization.
- **Following**: the core of the recap — the one task the next session handles, often a small part of a longer plan, specific enough to execute without rereading this session (files, commands, PR numbers, open questions for the user). It alone sets the phase and the model.
- **Remaining**: the ordered steps after **Following**, as context; omit when there are none.
- **State**: worktrees and branches still alive, uncommitted changes, running servers.
- **Done**: very terse — one short line per item with its PR number or SHA, no description of how it was done.
- **Pointers**: only the plan files and docs **Following** needs; the next session rereads nothing else.

Never include secret values, tokens, passwords or credentials; reference secrets by name or file path only. Leave out exploration history, tool output, and anything already in the repo or in the project instructions.

## Step 4 — Save

Write the recap to `agent-handoff-<repo>-<name>.md` inside the common git directory printed in Step 2, overwriting any previous recap for that name. Write it with one Bash heredoc (`cat > '<path>' <<'AGENT_HANDOFF_EOF'`), not a file-editing tool: such tools refuse to overwrite a file not read in this session, which would cost a failed call and a read of the old recap. `<name>` is the resume directory's branch; when `git branch --show-current` printed nothing, HEAD is detached and `<name>` is `detached-<short SHA>`. In both `<repo>` and `<name>`, replace every character outside `[A-Za-z0-9._-]` with `-`. Keep the absolute path for Step 5. One file per branch keeps parallel worktree sessions from overwriting each other. The common git dir is shared by all worktrees, so the file never shows in `git status` and survives worktree removal. `clean-repos` and `cleanup-session` delete it once its branch is gone, and a trunk or detached-HEAD recap after 7 days. Outside a git repository, or when the write fails, no file exists: say so and print the recap in Step 5.

## Step 5 — Report

When the file was written, do not print the recap: the file already holds it, and printing would generate it a second time. Reply with the instruction below and nothing else. The restart command goes alone in a fenced `sh` block, on its own lines, so the user copies it in one selection:

- "Start a new session with:" followed by the fenced block holding `codex -C '<resume directory>' <model flags> '<instruction to read <absolute path of the file written in Step 4> and resume, in the recap language>'`. The prompt argument is sent as the first message, so no second step is needed.

Append "(no handoff model for `<phase>`)" when the model flags are empty.

When no file was written, print the recap as a fenced block instead, with the same note when the model flags are empty, followed by: "Start a new session with `codex -C '<resume directory>' <model flags>` and paste the block."
