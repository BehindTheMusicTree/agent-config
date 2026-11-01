---
description: Read-only correctness review of a branch, commit range, or existing pull request.
model: sonnet
---

Review **$ARGUMENTS**. Read `${CLAUDE_PLUGIN_ROOT}/references/pr-policy.md` for risk depth and the reviewer contract.

Review the user-specified branch, `base..head` range, or PR number/URL; if omitted, review the current branch against its detected base. Resolve a PR's repository, base and head using `gh pr view`; fetch missing refs when necessary. Pin base, merge base and head SHAs, and inspect the committed diff and relevant callers, tests and project instructions. Report dirty worktree changes separately; do not silently include them in a committed-range review. For a release, also inspect the delivery range under the policy. If a range cannot be resolved, report the limitation rather than guessing.

Select intent and depth using the policy, or accept the caller's selection and evidence, escalating for identified risks. For standard/deep, use a fresh independent reviewer when authorized and available, passing the pinned range and focused context under the policy. Otherwise review in the current session and disclose the limitation. A standalone invocation may itself be the fresh reviewer when called in a separate session. Light reviews use the principal session. Do not duplicate a valid review supplied by the caller.

Review is read-only: do not edit files, push, or post comments. Verify findings against the code and report actionable correctness risks with severity, file/line references, and concrete failure scenarios. Report the repository, pinned SHAs, intent/depth, confirmed and rejected findings with reasons, validation evidence consulted, and limitations. If no findings remain, say so. Recheck the relevant head/base before reporting and flag a changed state as stale.
