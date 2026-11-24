# Shared PR policy

Load once per PR workflow. Project instructions and the user's authorization take precedence. Intent describes the delivery purpose; depth describes risk. Branch names, file extensions, diff size and requested flags are evidence, never proof of low risk.

## Inputs and selection

`create-pr` and `create-pr-and-fix-ci` accept `--intent change|release|version-bump|dependency-bump|back-merge`, `--depth auto|light|standard|deep`, and `--base <ref>`, alongside existing arguments. Defaults: `change`, `auto`, detected trunk. Resolve an intent from explicit user context when flags are absent; do not guess a release or back-merge from the branch name alone. Resolve the source, target, base SHA, merge base and HEAD before reviewing. Validate that an explicit base maps to an actual target branch; do not silently retarget a PR or use a tag as its target.

Run `pr-context.py` with these arguments and inspect the relevant hunks. Its `review_request` records a request, not an automatic safety classification. Announce the selected intent/depth and one concrete reason. Escalate when new evidence raises risk. A requested depth can increase scrutiny; it cannot remove a risk-required check or lower a project minimum. Ambiguous risk is standard until clarified by code; security or data-loss uncertainty is deep.

## Depth

| Depth | Eligibility | Review and validation |
| --- | --- | --- |
| light | Verified prose/comment-only edits or a mechanical transformation with a complete deterministic check; no behavior, executable examples, workflow, dependency or configuration changes | Principal reviews all relevant hunks and runs the applicable checks. No extra reviewer by default. |
| standard | Localized behavior changes with understood contracts; default for code and dependency changes | Principal checks coverage and runs/reuses applicable validation. One fresh independent correctness reviewer after the final edits and base synchronization. No separate test agent by default. |
| deep | Auth/permissions, secrets, data migration or deletion, concurrency, public contract breaks, broad dependency/runtime upgrades, or material interactions across services | Standard review plus explicit impact/compatibility and recovery analysis. Add a second specialist only for a concrete uncovered risk; give it a bounded independent question. |

Low-risk intent-specific exceptions below require the stated evidence. Do not count lines to assign depth. A version manifest or lockfile change is not a prose edit.

For standard/deep, delegate the independent review when available. Unless project instructions say otherwise, the user's invocation of `review`, `create-pr` or `create-pr-and-fix-ci`, directly or nested in another workflow, is their explicit request to spawn the single fresh reviewer this requires, and `create-pr-and-fix-ci` also requests its delta re-reviews (see **Handoff and reuse**). Do not ask for confirmation, and do not decline the reviewer as an unrequested subagent. A reviewer must not delegate further. The reviewer gets the exact final range, project root, intent-specific facts, project instructions and focused questions, not the author's conversation or justification. Claude: a fresh general-purpose Sonnet subagent, not a fork. Codex: an available fresh reviewer under the client's supported settings; do not invent provider overrides. Never skip the review silently: if independent execution is unavailable, perform it in the current session and disclose that limitation, unless the project requires an independent reviewer, in which case stop and report.

Reviewer is read-only and reports concrete failure scenarios with file/line evidence, not style nits. Verify findings; preserve confirmed and rejected findings with brief reasons. Do not fix unrelated issues without authorization.

Each finding carries a severity (`important` or `minor`) and a provenance: `introduced` when the diff adds or worsens the bug, `pre-existing` when it was already there and the diff neither introduces nor aggravates it. Fix every confirmed `introduced` finding, `important` or `minor`, in this PR before pushing, then review the fix as **Handoff and reuse** requires. Leave one unfixed only when its fix needs a design decision or exceeds the authorized scope: list it in the PR body with that reason and ask the user. Report `pre-existing` findings in a separate section: they do not block the PR and are not fixed without authorization. For each actionable one not already tracked by an open issue, propose an issue for the repository that owns it (title and summary); create it only with approval.

When a confirmed finding comes from a convention that is missing or outdated in the project's instructions, or the same kind of finding recurs within the PR, propose the smallest durable fix: a line in CLAUDE.md or AGENTS.md, a scoped rule, a lint rule or a check. Propose only; apply it with approval, like any other instruction change.

A specialist is not another full review of the same diff. If post-review edits invalidate findings or validation, revisit the changed hunks and interactions; repeat the full review only when their scope warrants it.

## Intent-specific checks

### change

Review behavior, callers, error paths, tests and documentation. Apply depth from the actual change.

**Test level.** For each non-trivial changed behavior, name the lowest test level able to observe it. A behavior that depends on real navigation, browser history, framework-managed document state or real rendering cannot be observed in a simulated DOM. If no test at that level covers it, fill the gap in this PR, including the missing level's tooling and CI job when the project does not have them yet.

**Documentation.** Identify the document that owns each changed contract. If it is stale, or missing while the project documents that kind of element, update or create it in this PR.

**Bug fixes.** When the PR fixes a bug, check that it addresses the root cause at the layer that owns the invariant, not only the symptom, and search for other occurrences of the same class of bug. A fix that treats only the symptom is an `important` finding.

A manual check, a "still to do" note or a limitation in the PR body does not close a test or documentation gap. If filling one requires something only the user can provide, stop and ask before opening a ready PR.

### release

Default at least standard. Verify source/target and branching model, canonical version, last published release and the full delivery range, included changes and release notes, migrations, compatibility and recovery. A small version-only PR can ship a large set of earlier changes: distinguish the PR diff from the release content. Reuse prior reviews only with exact ranges and relevant evidence; independently review uncovered release/integration risks rather than blindly re-reviewing all unchanged code. A deep included risk requires deep release handling. Never bump a version twice or tag an unmerged feature commit. Publication, merge permission and CI rules remain separate from review depth.

### version-bump

Light only when inspection confirms canonical version/changelog changes and any documented generated version files, with no dependency, build or behavior change. Check version consistency and the project's release validator. Standard otherwise, deep for a material release-process change. A mechanical bump does not authorize publication and does not establish that the release payload is low risk.

### dependency-bump

Default standard. Inspect direct and transitive changes, manifest/lock consistency, upstream breaking/security notes, runtime compatibility, install/build hooks and tests covering affected contracts. Patch/minor labels do not establish low risk. Escalate major/runtime changes, auth/data-layer effects or broad transitive changes as appropriate. Do not regenerate unrelated dependencies or upgrade tooling to silence CI.

### back-merge

Verify the released source and intended integration target from project conventions, both pinned SHAs, and whether the source is already an ancestor of the target. Already integrated means report no PR needed. Otherwise use a dedicated integration branch from the released source and merge the target there; never resolve by merging develop into main or another protected release source. Preserve both sides, never use an ours/theirs strategy to discard changes, and inspect integration behavior even without textual conflicts. Do not introduce a new version/changelog entry just to describe a back-merge. Skip feature-branch prefix renaming for the integration branch. Default standard; light only with complete evidence of an already-reviewed equivalent result and no unresolved semantic interaction. Escalate sensitive conflicts to deep. Record source/target SHAs, conflict resolutions and integration validations in the body.

## Auto-merge

After `create-pr` opens or updates a PR, enable auto-merge on it unless the user opted out (`--no-auto-merge`, or any instruction not to merge).

- Applies to ready, non-draft PRs of every intent, including `release`, `version-bump` and `back-merge`.
- Fetch origin and run `pr-context.py --pr <number> --intent <intent>` in the PR's repository immediately before arming. Use its GitHub source, target, head SHA and `merge_method`. Verify the head and target match the reviewed PR. The repository settings and active branch rules must allow the selected method.
- BehindTheMusicTree uses squash on a single integration branch, for ordinary work into develop, and for hotfixes into main. A Gitflow release from release/* into main and a release back-merge into develop use merge commits. Release intent applies to both release and hotfix branches. Use a dedicated back-merge/* branch based on the released commit for BehindTheMusicTree. For other organizations the method comes from the sole enabled repository method or the contributing docs at the PR head.
- Read `gh pr view <pr> --json state,isDraft,headRefOid,baseRefName,autoMergeRequest`. Leave drafts, closed PRs and opted-out PRs alone. If the request already uses the selected method, keep it. If it uses a different method, run `gh pr merge <pr> --disable-auto`, reread the PR, and revalidate the route, review SHA, and draft/open state before rearming. Stop if any read or mutation fails.
- Arm with `gh pr merge <pr> --auto --match-head-commit <reviewed-head-sha> --<method>`, where method is squash, merge or rebase. Omit branch deletion and administrative bypass. If GitHub rejects the request, leave the PR open and report the failure.
- Reread the PR and verify `autoMergeRequest.mergeMethod` matches the selected method (case-insensitive) and the head and base still match the reviewed PR. If GitHub completed the merge during the call, report the merged state and commit. Report a missing or mismatched request on an open PR as a failure.
- Refresh every check's state before any manual merge. `gh pr merge --admin` is allowed only when the sole remaining blocker is a required review on a repository the user maintains alone, as a separate step once every check has passed or been intentionally skipped. Never bypass failing, pending or missing checks, or conflicts.

## Release-please repositories

`pr-context.py` reports `release_please` from the base commit: `none` (no release-please config or manifest at the repository root), `manual` (configured, but no workflow job both calls a reusable `release-please.yml` and passes `auto-merge: true`) or `auto_merge`. The workflow check is a text heuristic over job blocks, not a YAML evaluation: an auto-merge passed through an expression reads as `manual`. The organization's release configuration owns the actual mechanics.

- `manual` and `auto_merge`: the PR title sets the changelog entry and the version (`feat` minor, `fix` patch, `!` breaking). Choose it from the effect on users, not from the type of the last commit.
- `auto_merge`: merging a PR whose title type is releasable starts a release. Report the expected version from the manifest and every unreleased change since the last release, not this title alone; another type releases nothing and is reported as no release. CI merges the release PR; if its auto-merge fails, **Auto-merge** applies: do not fall back to an immediate merge.
- `none`: do not announce a release.

## Handoff and reuse

`create-pr` owns coverage, intent checks, final review and PR body. `create-pr-and-fix-ci` calls it once and then owns the CI/mergeability loop. `release` supplies explicit intent/base for its release and back-merge PRs. Pass the selection, exact reviewed state, validation commands/results and limitations through nested calls; do not spawn another reviewer merely because another skill starts.

Approval is per commit: every commit pushed after the initial review (for example by the `create-pr-and-fix-ci` loop) is reviewed on its own delta, `<last reviewed SHA>..HEAD` plus its direct interactions, before the push, at the PR's depth (a fresh independent reviewer for standard/deep, the principal session for light). Exempt, with the reason reported: a re-run without a commit, formatting or lint fixes applied by the project's own tool, a deterministic regeneration verified by its check, and a clean merge of the base branch (review only its conflict resolutions). A confirmed `introduced` finding, `important` or `minor`, blocks the push: fix it and review only the new delta, at most twice per push. If a confirmed finding remains after the second re-review, do not push: report it to the user. Handle `pre-existing` findings as **Depth** requires: report them separately, do not fix them, and propose an issue for each actionable one not already tracked. Starting with an existing PR skips creation but still requires resolving its current intent/base/head and checking any missing evidence before claiming readiness.

Reuse validation only if all relevant inputs (including dirty edits, dependencies, environment and configuration) still match and project rules allow it. The context file and validation log paths alone do not prove this. New tests must run. Head, base or integration changes require reassessment. Keep summaries bounded and raw evidence available; mandatory checks apply at every depth. Report the chosen intent/depth, evidence, findings and remaining limitations with the PR URL.
