---
name: release
description: Detect the project's branching model (strict Gitflow vs GitHub flow), verify the current branch follows it, and drive the release forward to a PR against main.
---

Resolve `SKILL_REPO_ROOT` from this SKILL.md’s actual location: follow any symlink for the skill directory, then take its grandparent directory. Set this environment variable before running the commands below; it must contain the shared `scripts/` directory.

Detect the repo's git flow, check the current branch against it, open the PR to `main`, and make sure a version release is actually cut. A merged PR is not a release.

Optional context: **user-provided arguments** (e.g. a version number or bump, optionally with `--auto`).

**`--auto`** — the caller has already authorized the full release. Every "confirm"/"ask" gate below is skipped: derive the version from the argument or Step 7.4's bump rule and proceed. Additionally, drive it to the end instead of stopping at the PR — see Step 6a. Repo `CLAUDE.md` rules (where tags are cut, `npm pkg set` vs `npm version`) still win over anything here. Genuinely contradictory signals (Step 1) or a gap other than a missing release branch (Step 4) still stop — report them instead of asking.

## Shared PR policy

Read `$SKILL_REPO_ROOT/references/pr-policy.md` once. This workflow owns branching, versioning and publication; `$create-pr` owns intent checks, coverage and final PR review. Forward exact source/target, intent/depth, release range and review/validation evidence. Select `release` for the delivery PR, `version-bump` only for a separate mechanical bump, and `back-merge` for integration into develop. Do not reuse light bump review as proof of low release risk.

## Step 1 — Flow

```bash
"$SKILL_REPO_ROOT/scripts/detect-branch-model.sh"   # flow=gitflow|github, trunk=<branch>
```

Signals look contradictory → state your read and ask.

## Step 2 — Current branch

```bash
git branch --show-current
git status
git log --oneline main...HEAD | head -20
```

Note: name vs. the flow's conventions, its base, ahead/behind.

## Step 3 — Required path to `main`

- **GitHub flow**: branch → PR to `main`.
- **Gitflow**:
  - `feature/*` → PR to `develop`, never `main`.
  - `release/*` (from `develop`) → PR to `main`, then merge-back PR to `develop`.
  - `hotfix/*` (from `main`) → PR to `main`, then merge-back PR to `develop`.
  - On `develop` with no release branch → create `release/*` first.

## Step 4 — Gaps

**Missing `release/*`/`hotfix/*` branch** — the only gap this command fixes itself:

1. Version: from `user-provided arguments`, else derive from `package.json`/`CHANGELOG.md`/tags, else ask.
2. Confirm name and base (`release/x.y.z` off `develop`, `hotfix/x.y.z` off `main`).
3. Detect release tooling:
   ```bash
   grep -E '"release"|"version"|"changeset"|"prepare-release"' package.json 2>/dev/null
   ls .changeset/ 2>/dev/null
   ls scripts/*release* scripts/*version* Makefile 2>/dev/null
   grep -rliE 'release-please|semantic-release|standard-version|changesets/action' .github/workflows/ 2>/dev/null
   ```
   Found → **read it before running it**: expected branch/tree state, required env/secrets, whether it pushes/tags itself. If it needs a CI-only secret, trigger it the way the workflow expects (tag, merge, `gh workflow run`) instead of running it locally. Use it wherever it covers branching, versioning, or tagging.
4. No tooling → create the branch:
   ```bash
   git checkout develop && git pull --ff-only && git checkout -b release/x.y.z && git push -u origin release/x.y.z
   # or: git checkout main && git pull --ff-only && git checkout -b hotfix/x.y.z && git push -u origin hotfix/x.y.z
   ```
5. No tooling but a manual release convention exists (see Step 7) → do the version cut **now, on this branch** (Step 7 manual path, committed here instead of on `main`), after confirming the version and the commit. The PR then carries the bump into both `main` and the merge-back.

**Any other gap** (wrong base, missing prefix, feature PR aimed at `main`, hotfix not merged back) → report it with the concrete fix (e.g. "retarget this PR at `develop`") and wait for confirmation. These touch branches that may already have PRs/reviewers.

## Step 5 — Sync with `main`

```bash
git fetch origin main
git log HEAD..origin/main --oneline
```

Non-empty → `git merge origin/main` (not rebase) and resolve conflicts before continuing.

## Step 6 — PR to `main`

Invoke `$create-pr --intent release --base origin/main`, passing the resolved release content and prior evidence. It creates or updates the intended PR; reuse an existing matching source/target PR rather than opening a duplicate. Do not publish before it merges. For Gitflow, record the required back-merge target now.

## Step 6a — Merge (only with `--auto` or equivalent session authorization)

1. Run the CI/mergeability loop from `$create-pr-and-fix-ci` on the release PR, carrying its profile and evidence; then merge with the project's permitted strategy.
2. Update local main with a fast-forward and complete Step 7 on the merged commit.
3. Gitflow: invoke `$create-pr --intent back-merge --base origin/develop` from a dedicated integration branch based on the released source, as specified by the policy. Never merge develop into main to resolve it. Run the same CI/mergeability loop, merge the back-merge PR, then remove the release branch when authorized. Do not publish another release or bump another version for the back-merge.

## Step 7 — Cut the release

If the release PR has not merged to `main`, stop after reporting the PR: do not tag or publish an unmerged commit. Once merged, fetch `origin/main` and verify the intended release commit is on it. If Step 4.5 already committed the version bump, do not bump again, but still ensure the release tag exists. Always check — regardless of flow — using Step 4.3's detection plus:

```bash
git tag -l | grep -vE -- '-(dev|rc|beta|alpha)\.' | sort -V | tail -5
```

A `vX.Y.Z` convention with an untagged `main` HEAD is the gap to close.

**agent-config path:** For `BehindTheMusicTree/agent-config`, the canonical version is `.claude-plugin/plugin.json`. Once the version bump has merged to `main`, tag that main commit `vX.Y.Z` using the manifest version; validate it with `scripts/check-release-version.py`, then push the tag with the user's authorization. If the tag already exists, compare its dereferenced remote commit with the intended main commit and stop on a mismatch. The tag triggers `.github/workflows/release.yml`, which publishes the GitHub release after validation. Do not bump the already-merged version again or create a tag on a feature branch. After verifying the remote tag and commit, skip the tooling and manual paths and continue to Step 8.

**Tooling path:**
1. Read it first: required state (clean tree, on `main`, pulled), version argument format (`patch`/`minor`/`major` vs `x.y.z`), and exactly what it does (changelog, version bump, deleting pre-release tags, commit, tag, push).
2. CI-only → trigger it (tag, PR merge, `gh workflow run`) and say so.
3. Local → on `main`, synced with `origin/main`, clean tree.
4. Version: from `user-provided arguments`, else propose a bump from what merged (breaking → major, or minor while below `1.0.0` per SemVer §4 — a `feat!:` never jumps `0.x` to `1.0.0`; feature → minor; fix → patch).
5. **Confirm before running**: state exactly what will be committed, tagged, pushed, and deleted. A version number in `user-provided arguments` is not authorization to push.
6. Verify: `git log origin/main --oneline -1` and `git ls-remote --tags origin | grep vX.Y.Z`.

**Manual path** (no tooling, but existing version tags, a versioned `CHANGELOG.md`, or a version field in `VERSION`/`package.json`/`pyproject.toml`/`.claude-plugin/plugin.json`):
1. Next version = highest current version bumped according to what merged (Step 7.4's rule); confirm it with the user.
2. If `CHANGELOG.md` exists, rename `Unreleased`/`Unpublished` to `x.y.z — <today>` using the file's heading format, and add a fresh empty `Unreleased` above it. First rewrite any entry that is a raw commit message, a PR title, a bare ticket ID, or a vague word ("fixes") into one plain-language line; keep existing categories. Too ambiguous → ask.
3. Bump the version file.
4. Commit (`chore: release x.y.z`, matching repo style), tag with the existing prefix, push both — same confirmation gate as the tooling path.
5. Verify as above.

**No convention at all** (no tags, no versioned changelog, no version field) → say "no release convention found — the merged PR is the release". Don't invent a versioning scheme.

## Step 8 — Confirm `main` workflows fired

GitHub occasionally drops the push event for a merge (no `PushEvent`, so no run at all), silently skipping deploy-on-push. After the PR to `main` merges (and after any tag push):

```bash
gh run list --commit "$(git rev-parse origin/main)" --limit 20 --json workflowName,event,status,conclusion
```

Every workflow in `.github/workflows/` whose `push` trigger covers `main` should have a run for that SHA. Missing after ~5 min → `gh workflow run <file> --ref main` if it has `workflow_dispatch`, else report it. Watch deploy runs to completion (`gh run watch <id>`); a release whose deploy didn't run isn't shipped.

## Step 9 — Synchronize agent-config locally

When releasing an agent-config source, use the configured local profile to synchronize its published release. A private profile pins a public release: publishing a new public version alone does not change that profile until its private dependency is updated and published. Report publication and local synchronization separately. If publication is pending, verify its status and retry synchronization after it is published.

## Output format

1. **Flow** and the signal that decided it
2. **Branch** — name, base, ahead/behind
3. **Gaps** (Step 4) — fixed or still needed
4. **PR URL**, or what blocks it
5. **Release** (Step 7) — tooling found or not; tag produced, or what's still needed
6. **Workflows on `main`** (Step 8) — ran / dispatched manually / missing
7. **Local synchronization** (Step 9) — installed version or pending/failure, when applicable
