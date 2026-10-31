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

For standard/deep, delegate the independent review only when authorized and available. The reviewer gets the exact final range, project root, intent-specific facts, project instructions and focused questions, not the author's conversation or justification. Claude: a fresh general-purpose Sonnet subagent, not a fork. Codex: an available fresh reviewer under the client's supported settings; do not invent provider overrides. If independent execution is unavailable, perform the review in the current session, disclose that limitation and respect any project requirement for an independent reviewer.

Reviewer is read-only and reports concrete failure scenarios with file/line evidence, not style nits. Verify findings; preserve confirmed and rejected findings with brief reasons. Do not fix unrelated issues without authorization. A specialist is not another full review of the same diff. If post-review edits invalidate findings or validation, revisit the changed hunks and interactions; repeat the full review only when their scope warrants it.

## Intent-specific checks

### change

Review behavior, callers, error paths, tests and documentation. Apply depth from the actual change.

### release

Default at least standard. Verify source/target and branching model, canonical version, last published release and the full delivery range, included changes and release notes, migrations, compatibility and recovery. A small version-only PR can ship a large set of earlier changes: distinguish the PR diff from the release content. Reuse prior reviews only with exact ranges and relevant evidence; independently review uncovered release/integration risks rather than blindly re-reviewing all unchanged code. A deep included risk requires deep release handling. Never bump a version twice or tag an unmerged feature commit. Publication, merge permission and CI rules remain separate from review depth.

### version-bump

Light only when inspection confirms canonical version/changelog changes and any documented generated version files, with no dependency, build or behavior change. Check version consistency and the project's release validator. Standard otherwise, deep for a material release-process change. A mechanical bump does not authorize publication and does not establish that the release payload is low risk.

### dependency-bump

Default standard. Inspect direct and transitive changes, manifest/lock consistency, upstream breaking/security notes, runtime compatibility, install/build hooks and tests covering affected contracts. Patch/minor labels do not establish low risk. Escalate major/runtime changes, auth/data-layer effects or broad transitive changes as appropriate. Do not regenerate unrelated dependencies or upgrade tooling to silence CI.

### back-merge

Verify the released source and intended integration target from project conventions, both pinned SHAs, and whether the source is already an ancestor of the target. Already integrated means report no PR needed. Otherwise use a dedicated integration branch from the released source and merge the target there; never resolve by merging develop into main or another protected release source. Preserve both sides, never use an ours/theirs strategy to discard changes, and inspect integration behavior even without textual conflicts. Do not introduce a new version/changelog entry just to describe a back-merge. Skip feature-branch prefix renaming for the integration branch. Default standard; light only with complete evidence of an already-reviewed equivalent result and no unresolved semantic interaction. Escalate sensitive conflicts to deep. Record source/target SHAs, conflict resolutions and integration validations in the body.

## Handoff and reuse

`create-pr` owns coverage, intent checks, final review and PR body. `create-pr-and-fix-ci` calls it once and then owns the CI/mergeability loop. `release` supplies explicit intent/base for its release and back-merge PRs. Pass the selection, exact reviewed state, validation commands/results and limitations through nested calls; do not spawn another reviewer merely because another skill starts. Starting with an existing PR skips creation but still requires resolving its current intent/base/head and checking any missing evidence before claiming readiness.

Reuse validation only if all relevant inputs (including dirty edits, dependencies, environment and configuration) still match and project rules allow it. The context file and validation log paths alone do not prove this. New tests must run. Head, base or integration changes require reassessment. Keep summaries bounded and raw evidence available; mandatory checks apply at every depth. Report the chosen intent/depth, evidence, findings and remaining limitations with the PR URL.
