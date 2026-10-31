---
name: create-pr-and-fix-ci
description: Open a PR for the current branch (with review depth matched to risk), then loop on failing CI checks and mergeability until everything is clean.
---

Resolve `SKILL_REPO_ROOT` from this SKILL.md’s actual location: follow any symlink for the skill directory, then take its grandparent directory. Set this environment variable before running the commands below; it must contain the shared `scripts/` directory.

Open a PR for the current branch, then keep fixing failing CI checks and mergeability conflicts until every check passes and the PR can merge.

Arguments: optional existing PR number/URL, plus `--intent`, `--depth`, and `--base` from the shared PR policy.

## Steps 1–2 — Select context and create or inspect the PR

Read `$SKILL_REPO_ROOT/references/pr-policy.md` once. If an existing PR was supplied, read its current source/target, HEAD and review/validation evidence, apply the policy to missing evidence, then continue to Step 3. Do not create another PR.

Otherwise invoke `$create-pr` once, forwarding intent/depth/base and existing evidence (ready for review, without `--draft`). It owns coverage, intent-specific checks and final review. Capture the returned PR number, selected profile, reviewed state and validation evidence. Do not spawn a second preliminary reviewer in this wrapper.

## Step 3 — Loop until CI is clean and the PR is mergeable

Repeat, capped at 5 iterations:

1. Wait for CI to settle and read check status:
   ```bash
   gh pr checks <pr> --watch > <local-watch-log> 2>&1
   gh pr checks <pr> --json name,state,bucket,link
   ```
   Run these separately: `--watch` and `--json` are incompatible. Capture each exit status; a check failure from the watcher must not prevent the JSON snapshot. Exit `8` means checks are pending, not passing; continue waiting within the task's bounded execution. Surface authentication, network, or retrieval errors instead of treating them as CI success. Keep watcher output in the local log and inspect bounded excerpts when needed.
   - All checks `pass` (or `skipping`) → go to step 2 below.
   - One or more checks `fail` → resolve `<owner/repo>` with `gh repo view --json nameWithOwner --jq .nameWithOwner`, then run:
     ```bash
     python3 "$SKILL_REPO_ROOT/scripts/ci-failure-context.py" <pr-number> --repo <owner/repo>
     ```
     Read the bounded JSON and use its raw log/index/manifest paths for deeper inspection. Exit `1` with `partial` or `stale` is not CI success: inspect reported collection failures, provider links, or refreshed checks. Excerpts are heuristic candidates; omitted checks/groups and unmatched errors require the saved artifacts. Diagnose and fix the actual failure without weakening checks.
2. Check the PR's mergeable state — CI checks passing does not mean the PR can merge; GitHub computes mergeability against the base branch separately:
   ```bash
   gh pr view <pr> --json mergeable,mergeStateStatus,baseRefName
   ```
   - `mergeable: MERGEABLE` → the loop ends, go to Step 4.
   - `mergeable: UNKNOWN` → GitHub hasn't finished computing it yet; wait a few seconds and re-check (cap at ~5 retries) before treating it as stuck.
   - `mergeable: CONFLICTING` → fetch the PR's base branch (`baseRefName`, not a guess) and merge it locally to surface the conflicting files, rather than guessing from the PR page:
     ```bash
     git fetch origin <base-branch>
     git merge origin/<base-branch>
     ```
     Resolve the conflicts like any other merge conflict (see the root CLAUDE.md guidance on not discarding work), commit the merge, and push. Do not use `git merge -X ours/theirs` or force-push over the branch to dodge the conflict.
3. If step 1 or step 2 produced a fix, commit and push it, then go back to step 1 — a new commit resets both CI and mergeability computation.
4. If nothing was fixed in either step but a check is still failing or the PR is still not mergeable (e.g. it needs input only the user can give, or it's flaky and won't recover), stop and report the state instead of looping again.
5. If the 5-iteration cap is hit before both exit conditions are met, stop and report the state instead of continuing indefinitely.

While triaging failures, also apply your own expert-developer read of the surrounding code — independent of what CI flagged. If you spot something real that CI didn't catch, do not fix it unprompted; note it for the final report.

Reuse a downloaded log only for the same repository, head SHA, run, attempt, and job. A rerun on the same SHA can have different logs. Keep fresh check and mergeability reads after every push; cached logs never establish current CI status. When waiting, retain the last status and report transitions or failures rather than repeatedly rereading unchanged output.

The run/job log commands apply to GitHub Actions. For external checks, use the provider's linked diagnostics with the same bounded-output discipline; do not invent GitHub run or job IDs.

## Step 4 — Output format

Keep this terse:
1. **PR URL** and selected intent/depth
2. **Review findings** (creation or existing-PR inspection) — confirmed findings, then rejected ones with the reason, or "none"
3. **CI summary** — per iteration, which checks failed and what fix was pushed, or "all green from the start"
4. **Mergeable state** — per iteration, `mergeable`/`mergeStateStatus` seen, and any conflicts resolved, or "mergeable from the start"
5. **Additional issues found** — things CI didn't catch, bullet list, or "none"
6. **Final state** — clean exit, or which cap was hit and what's still outstanding
