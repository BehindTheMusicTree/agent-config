---
name: create-pr
description: Produce a PR description for the current branch, push it, and open the PR — including a changelog entry if needed and a proposed merge title.
---

Resolve `SKILL_REPO_ROOT` from this SKILL.md’s actual location: follow any symlink for the skill directory, then take its grandparent directory. Set this environment variable before running the commands below; it must contain the shared `scripts/` directory.

Write a PR description for the current branch, push, and open the PR. Optional `--draft`: **user-provided arguments** — if present, add `--draft` in Step 10.

## PR intent and review depth

Read `$SKILL_REPO_ROOT/references/pr-policy.md` once. It owns the intent/depth criteria and reviewer contract shared with CI and release. Accept `--intent`, `--depth`, `--base`, and `--draft`; apply project conventions and resolve the actual source/target. For a back-merge, prepare the dedicated integration branch as specified there before collecting context. Carry existing evidence through nested calls; a request for light review cannot override identified risk.

## Step 1 — Base branch and commits

```bash
python3 "$SKILL_REPO_ROOT/scripts/pr-context.py" [--base <ref>] [--intent <intent>] [--depth <depth>]
```

Use the JSON’s `flow`, `base_ref`, pinned SHAs, commit subjects, changed files, and separate worktree state. The script reuses the branch detector and reads `origin/<trunk>` without fetching; pass `--base <ref>` for an explicit base. Resolve the PR target branch from that base. Commits remain the source of truth. Counts marked `omitted` require targeted Git reads before conclusions about the complete change. `--validation-log <path>` references existing evidence without certifying test success.

## Step 2 — Branch prefix (Gitflow only)

Skip if `flow=github` or intent is `back-merge`.

Valid prefixes: `feature/`, `release/`, `hotfix/`, plus any prefix this repo already uses consistently (check `git branch -a --format='%(refname:short)'`, e.g. `fix/`).

No valid prefix → propose a name (`feature/` for new work, `hotfix/` only if cut from `main`), keeping the rest of the name. Confirm before renaming:
- Local: `git branch -m <old> <new>`.
- If `origin/<old>` exists, renaming the remote drops any PR/review thread on it — get a separate explicit confirmation, then:
  ```bash
  git push -u origin <new>
  git push origin --delete <old>
  ```

## Step 3 — Changelog

Skip a new changelog entry for `back-merge`. Otherwise, if a changelog exists (`CHANGELOG.md`, `HISTORY.md`, …) and doesn't cover this branch, add an entry in the file's existing format without asking. One plain-language line describing the effect for users/devs — not a commit message.

## Step 4 — CLAUDE.md

If `CLAUDE.md` (or `.claude/CLAUDE.md`) exists and this PR adds or contradicts a convention, dependency, or workflow a future session needs to know, propose a minimal bullet edit and wait for approval. Otherwise skip silently.

## Step 5 — Intent checks and validation

Select and announce intent/depth with evidence from the hunks, using the shared policy. Perform its intent-specific checks and coverage analysis in the principal session; delegate a bounded specialist task only when a concrete risk requires it. Add missing tests/docs for non-trivial changes, run new tests, and reuse prior checks only under the policy's evidence rules. A separate test agent is not the default.

Check whether CI enforces tests (a required test job or coverage threshold). If nothing enforces it, ask whether to add a gate unless the session already resolves that decision. Refresh affected validation after a base merge.

## Step 6 — Body

Use the first template found: `.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/PULL_REQUEST_TEMPLATE/*.md`, `docs/pull_request_template.md`. Fill every section; mark N/A sections as such rather than deleting the heading.

No template:
```
## Summary
## Changes
## Test plan
```

## Step 7 — Title

Conventional Commits, ≤72 chars: `<type>(<scope>): <description>`, type ∈ `feat fix refactor chore docs test perf ci build style`, chosen by the dominant change.

## Step 8 — Save the body

Write **only the body** (no title, no wrapper headings — it's passed verbatim as `--body-file`) to:
- `.github/pr-descriptions/<branch-name>.md` if that directory exists,
- else `.local/pr-desc.md`.

`git check-ignore -q <path>` must succeed; if not, add the directory to `.gitignore` first.

## Step 9 — Sync with base

```bash
git fetch origin <base-branch>
git log HEAD..origin/<base-branch> --oneline
```

Non-empty → `git merge origin/<base-branch>` (merge, not rebase — the branch may be shared) and resolve conflicts before continuing.

Refresh the context after tests/docs, edits, or a base merge so the PR text describes what will actually be pushed.

## Step 9a — Review the final state

Apply the selected depth's review contract from the shared policy to the final code and integration state. Reuse an existing review only when its range and relevant inputs still apply; disclose any unavailable independent-review capability. Revisit changed hunks/interactions after post-review edits. Incorporate intent-specific evidence and limitations into the PR body. Do not duplicate a review just because this skill was called by another workflow.

## Step 10 — Push and open

Push the final reviewed branch for both creation and update, within the authorized scope:
```bash
git push -u origin <branch-name>
```

Then look for an existing PR with the exact source and target. If found, update its title/body with `gh pr edit --body-file` and preserve its draft state unless the user requested a change. Otherwise create it:
```bash
gh pr create --base <base-branch> --title "<title>" --body-file <path> [--draft]
```

Read the PR back and verify its head SHA matches the reviewed/pushed commit before reporting success. Do not create a duplicate or report a review of a different head.

## Output format

Don't print the body.
1. **Title**
2. Branch rename (old → new), if any
3. Changelog line added, if any
4. CLAUDE.md change, if any
5. Tests/docs added, if any
6. **PR URL**
7. Intent/depth, review findings, validation evidence reused/run, and remaining limitations
