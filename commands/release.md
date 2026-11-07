---
description: Detect the project's branching model (strict Gitflow vs GitHub flow), verify the current branch follows it, and drive the release forward to a PR against main.
---

If `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/agent-config/workflow-policies/release.md` exists, read it before starting: its rules extend this workflow and take precedence over its defaults.

Detect the repo's git flow, check the current branch against it, open the PR to `main`, and make sure a version release is actually cut. A merged PR is not a release.


Prepare a reviewed release PR, then follow its tag, required publications and declared deployments. A merged PR alone does not establish publication. Read `references/release-contract.md` from this plugin/skill repository for the CI/legacy contract and recovery rules.

A release must be explicitly requested in this conversation. Planning, fixing release infrastructure or preparing a migration does not authorize a bump, tag, package publish or production deployment. Invoking this release workflow is a release request; `--auto` is valid only under that authorization. Honor existing session authorization instead of repeating confirmation gates.

Optional context: **$ARGUMENTS** (version/bump, optionally `--auto`).

## Step 1 — Resolve the release and its owner

Fetch each involved repository before assessing its current integration/main state. Preserve unrelated checkouts and use a task worktree. Read project instructions and documented release tools before any mutating command. Inspect scripts for commits, tags, pushes, required secrets and branch expectations.

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/detect-branch-model.sh"` and read `${CLAUDE_PLUGIN_ROOT}/references/pr-policy.md`.

Use the detector's documented branch model and explicit overrides; report genuinely contradictory evidence. Record canonical version, actual previous tag and its dereferenced commit, intended source/target and release range. Inspect the changes being delivered, including breaking changes, migrations, compatibility and rollback.

Before running release tooling, read `.github/release-policy.json` on `origin/main` and the intended release source when present. A present but invalid contract is an error, never a reason to fall back to legacy. A configured CI contract owns tag creation; a repository without it keeps its documented legacy owner. If the source introduces/changes a contract, merge that migration separately before preparing a bump: the shared tagger deliberately does not publish on activation and refuses policy changes combined with a bump.

## Step 2 — Prepare version and changelog in a PR

For CI ownership, the contract specifies the only canonical source, its mirrors, prefix, changelog and expected GitHub Release/packages. Read all sources explicitly; do not substitute a dummy root package version. Verify stable SemVer, synchronized mirrors, a nonempty versioned changelog and progression from main. No version change means no release intent, including an untagged existing main version. Do not tag that version to compensate.

Reuse project preparation tools only if they stop before tagging/pushing main. A tool that commits, tags and pushes main must be adapted to a preparation mode or replaced with a reviewed branch change; do not run it then try to undo its side effects. Preserve coordinated versions, generated mirrors and project validation. Do not impose a new versioning tool.

Choose the version from explicit arguments or the reviewed changes: breaking changes → major (or minor below 1.0.0 under SemVer §4); features → minor; fixes → patch. If the intended version is already prepared, validate it and do not bump it twice. State the exact planned version and effects; ask only for missing release scope or approval not already supplied.

Prepare on a task branch before its PR. GitHub Flow targets main. Gitflow features enter develop first; prepare a release branch from fresh develop, or a hotfix branch from main, then target main and record the back-merge target. Use the worktree workflow for creating task checkouts. Never push a bump directly to main. If a merged PR omitted its version preparation, make a new preparation PR.

For BehindTheMusicTree/agent-config, the canonical legacy version is `.claude-plugin/plugin.json`; run `scripts/check-release-version.py` as documented. Once a CI contract is adopted, use that contract and CI ownership instead of the legacy special case. Public publication, private dependency update/publication and local installation are separate operations; do not infer authorization for the latter steps from a procedure edit.

## Step 3 — Validate, synchronize and open the PR

Run documented checks for the affected code and release data. Fetch main, merge its changes into the task branch if needed (do not rebase a shared branch), and refresh validation/review evidence after integration changes. Preserve both sides when resolving conflicts.

Invoke `agent-config:create-pr --intent release --base origin/main` with the exact release range, source/target, review depth and reusable evidence. Reuse an existing matching PR. `agent-config:create-pr` owns coverage and final independent review.

Use `version-bump` only for a separate mechanical preparation PR, never to classify an unreviewed release payload as light. Auto-merge follows the shared PR policy; pass `--no-auto-merge` when the session requires holding the merge. Do not publish before the delivery PR merges.

## Step 4 — Follow the merged release

Carry the same profile/evidence into `agent-config:create-pr-and-fix-ci` until the PR checks and mergeability are clean.

Resolve the actual merged commit from the PR and fetch main. Verify that commit is on main; record it as the intended release SHA even if a later push advances main. Check required after-merge validations on that exact SHA before publication when the project contract requires them.

**CI-owned tag:** follow the declared main-push tag workflow for the exact merge SHA. Never run local tag/push or legacy publish/dispatch as a fallback. Read the contract's exact version/prefix and verify the remote tag's dereferenced commit. Existing tag on the intended SHA is a retry; the same name on another SHA is a collision and must fail without moving/deleting it. If activation or an ordinary push had no bump, expect no tag. Diagnose a missing tag from its run and configuration; do not invent a second bump.

**Legacy-owned tag:** follow only the project's existing publication contract after the prepared version merges. Read the publication mode before running it; run only its publication phase, never another bump. If manual tagging is the documented owner, tag the exact merged commit with the existing prefix after validating the version/changelog and release authorization. Verify an existing tag by its dereferenced remote commit; reuse a matching tag and fail on a mismatch. For legacy agent-config, a validated manifest-version tag triggers `.github/workflows/release.yml`. No convention means report the missing contract rather than inventing one.

## Step 5 — Verify publications and deployments

Inspect workflow triggers, paths filters, branch/tag filters, job conditions and declared prerequisites. List the actual runs for the exact branch SHA and tag, and follow relevant runs to completion. A workflow excluded by its own filters is not missing. A missing run requires diagnosis of the event and configuration; do not assume GitHub lost the event or replay every push workflow.

Verify the remote tag, expected GitHub Release and every required artifact/version against the contract. A GitHub Release's `target_commitish` is not proof of tag provenance. GitHub Release creation has one owner and must wait for required packages. Existing publisher workflow filenames, registry credentials and OIDC identities remain owned by the repository.

For partial publication, follow its declared recovery path: verify each package/version already published, then rerun the existing tag publisher or explicitly documented recovery entry point. For coordinated packages, skip only an artifact proven already published and correct. Network/auth/API errors never mean absent or successful. Never create a replacement tag, a second bump or an arbitrary dispatch. Distinguish publication complete from deployment complete; follow a production deployment only when it is declared and authorized by the requested release.

## Step 6 — Integrate and synchronize

For Gitflow, invoke `agent-config:create-pr --intent back-merge --base origin/develop` from a dedicated integration branch based on the released source, following the PR policy.

Merge the target into that integration branch, preserve both sides, run the CI/mergeability loop and merge the back-merge PR. Never merge develop into protected main to resolve it, and never create another version or release for a back-merge. If already integrated, no PR is needed.

For an explicitly requested agent-config release/synchronization, use the configured local profile and published public/private pair. A private profile keeps its pinned public release until its dependency update and private publication are separately authorized and complete. Retry synchronization after publication is verified; report installed versions and pending steps separately.

## Output

Report the branch model and its evidence, intended release SHA/version, PR URL and merge state, tag ownership and verified dereferenced commit, required publication/deployment results, back-merge and local synchronization where applicable. State failures and remaining prerequisites precisely; do not report an unverified publication as complete.
