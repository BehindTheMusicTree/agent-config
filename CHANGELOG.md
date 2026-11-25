# Changelog

GitHub Releases are published through the shared release-tag workflow after repository
validation, replacing the separate tag-triggered publisher. A required check enforces
conventional PR titles, and Release Please maintains versioned entries from those titles.

## [3.10.1](https://github.com/BehindTheMusicTree/agent-config-public/compare/v3.10.0...v3.10.1) (2026-11-25)


### Bug Fixes

* **clean-repos:** ignore upstream tags in submodule unpushed check ([#123](https://github.com/BehindTheMusicTree/agent-config-public/issues/123)) ([0b022dd](https://github.com/BehindTheMusicTree/agent-config-public/commit/0b022ddda4445c86b869e5a652c60ffe291eca94))

## [3.10.0] - 2026-11-24

### Added

- `create-pr-and-fix-ci` now reports GitHub code-scanning alerts (blocking and non-blocking) from `ci-failure-context.py`, and forbids dismissing or suppressing them without approval.

## [3.9.0] - 2026-11-24

### Changed

- Select and verify the GitHub auto-merge method from the PR route for BehindTheMusicTree repositories, including resumed release, hotfix and back-merge PRs.

### Fixed

- Protect local files hidden by Git settings and recoverable unpublished submodule commits when cleaning worktrees.
- Cleanup removes worktrees with initialized submodules, using a single `--force` only after proving each submodule has no local changes, stash or unpushed commit; the scan announces it. A worktree that cannot be removed now reports git's message, and its branch is kept as `worktree-kept` instead of a false `not-fully-merged`. Branch deletion failures report `checked-out:<path>` or `delete-failed: <git message>`.

### CI

- Run organization conformance with the shared `github-workflows` v6.5.0 release.

## [3.8.1] - 2026-11-23

### Fixed

- Cleanup preserves the calling process and its ancestors during worktree removal. The caller’s active worktree is kept by default and can be removed with `--remove-caller-worktree`.
- Cleanup refreshes process observations during worker churn and reports `process-churn` when it cannot verify that a worktree is safe to clean.

### CI

- Check organization conformance on pushes and pull requests.

## [3.8.0] - 2026-11-23

### Added

- `pr-context.py` reports `release_please` (`none`, `manual` or `auto_merge`) from the base commit, and the PR policy gains a "Release-please repositories" section: the PR title sets the version, an auto-merged release is announced with its expected version, and a repository without release-please gets no release announcement.

### Fixed

- `clean-repos` no longer removes a merged worktree where a claude or codex session runs (detected by cwd, argv path or agent ancestor): the worktree, its branches and its processes are kept (`agent-session`). The session that runs the cleanup is ignored, so `cleanup-session` still removes its own worktree.

### Changed

- `create-pr` detects release-please from `pr-context.py` instead of looking for its files itself, and its report states the expected release (or none).
- The Python rule is shorter and limits the Django/DRF/PostgreSQL stack preference to new backend projects (mypy's Django plugin to Django projects), so it no longer reads as a default in other Python repositories.

### CI

- Declare the canonical workflow-level `concurrency` in `lint.yml` (cancels superseded PR runs) and `release-tag.yml` (one run per commit, never cancelled, so no release bump goes untagged) (refs BehindTheMusicTree/github-config#69).

## [3.7.2] - 2026-11-21

### Fixed

- `create-pr` and `create-pr-and-fix-ci` now fix every confirmed `introduced` review finding, `minor` ones included, before pushing; a finding is left unfixed only when it needs a design decision or exceeds the authorized scope, with the reason in the PR body. For actionable `pre-existing` findings they propose a tracking issue, created only with approval.

### Changed

- `create-pr` no longer asks whether CI enforces tests (organization settings own that), skips the changelog step in repositories managed by release-please, and reads the branch prefix check, PR template and merge method from `pr-context.py` (`--github` also queries the organization template and the allowed merge methods; an ambiguous merge method fails instead of being guessed).
- Plans handed to implementation must be implementation-ready (signatures, data shapes, API calls, files to change, tests to extend, saved contract excerpts); the handoff only classifies **Following** as `implement` when its plan is, otherwise the phase is `plan`, and **Pointers** reference local plan files and saved excerpts instead of sources to fetch again.

## [3.7.1] - 2026-11-19

### Fixed

- `new-worktree` and `new-worktree-and-serve` no longer document the removed `--plan` option, which made the setup script fail with `invalid-client`; the script now reports unknown options as `unknown-option:<opt>`.
- The README handoff examples show `<model flags>` in the Claude and Codex restart commands.

## [3.7.0] - 2026-11-19

### Added

- Handoff: a **Following** section holds the one task the next session handles; its phase (`plan`, `diag`, `implement`, `pr-bump-release`) selects the model and effort of the restart command from the handoff model table in the global instructions.

### Changed

- Handoff prints the restart command alone in a fenced block, on its own lines, so it copies in one selection.

## [3.6.2] - 2026-11-19

### Fixed

- In Claude, handoff compares the resume directory with the session's launch directory instead of the shell's current directory, so a session that `cd`-ed into another checkout prints `/exit` and `cd` rather than a `/clear` that would restart in the wrong project. The restart is a single command, `cd '<resume directory>' && claude '@<recap path>'`.
- In Codex, the handoff restart is also a single command: `codex -C '<resume directory>' '<instruction to read the recap>'` passes the read instruction as the first message.

## [3.6.1] - 2026-11-18

### Changed

- `new-worktree` and `new-worktree-and-serve` read a repository's setup instructions only when its root `CLAUDE.md` or `AGENTS.md` has a setup-like heading (setup, install, getting started, quick start, prerequisites, bootstrap): the script reports them as `setup_docs=` instead of always printing `check_claude_md_setup=true`, saving a file read in most repositories.

### Fixed

- Handoff recaps start with a resume check that stops a session started outside the resume directory.
- The graphify hook targets the repository of Read/Grep/Glob paths and seeds linked worktrees in the background.

## [3.6.0] - 2026-11-18

### Added

- `check-project-agents.py` verifies nested `AGENTS.md` / `CLAUDE.md` pairs and rejects client-specific instruction files (Copilot, Cursor, Windsurf, Cline, Gemini).
- Contributor `AGENTS.md` and `CLAUDE.md` for this repository.

## [3.5.0] - 2026-11-18

### Added

- Managed Claude permissions: `settings/permissions.json` fragments from each source are merged into `~/.claude/settings.json` during multi-source synchronization (`scripts/sync-claude-permissions.py` for a manual run).
- `clean-repos` / `cleanup-session`: `apply --remove-equivalent` removes clean, idle worktrees (branch or detached HEAD, no open PR) whose content is proven on trunk (`worktree-equivalent`, `reason=content-on-trunk`); without the flag they are kept (`equivalent-not-enabled`).
- `scripts/migrate-plans.sh [--apply] <root>` moves legacy `.agent-plans/` contents into the central plan directories (dry run by default, never overwrites).

### Changed

- Plans are centralized in `<git-common-dir>/agent-plans/<repo>-<branch>/` (same key as handoffs) instead of `.agent-plans/` in each worktree; `clean-repos` removes `agent-plans/<key>` together with its branch (`stale-handoff`).

### Removed

- `.agent-plans/` mechanics: `scripts/plan-ledger.py` and the `create-pr` plan reconciliation, `scripts/sync-plan-directory.py` and the `plansDirectory` setting, `new-worktree-setup.sh --plan`, the `agent-plans-present` / `archived-plans` clean-repos outputs, and `.agent-plans` from the global Git exclusion (`.agent-tmp/` is unchanged).

### Fixed

- `--exclude <sha>` protects a detached-HEAD worktree.
- `clean-repos` / `cleanup-session`: `--stale-empty-days 08` (or `09`) no longer fails as an invalid octal number; the value is read as base 10.

## [3.4.0] - 2026-11-18

### Changed

- Plan lifecycle: `create-pr` reconciles `.agent-plans/` into the PR body and follow-up issues and records it in a ledger (`scripts/plan-ledger.py record|status`); `cleanup-session` treats reconciled plans as disposable and asks only about unreconciled or modified ones.
- `new-worktree-setup.sh --plan <abs path>` moves the session's plan-mode file into the new worktree's `.agent-plans/`, verified with `cmp`.
- `clean-repos` / `cleanup-session` remove `agent-handoff-*.md` recaps from the common git dir once their branch is gone or deleted by the same `apply` (`stale-handoff`, `deleted-handoffs=`); trunk and detached-HEAD recaps expire after `--handoff-days` (default 7). `--keep-handoffs` disables it; `--exclude` with a branch or the recap's absolute path protects one.

### Fixed

- `clean-repos` / `cleanup-session`: `--exclude` accepts an absolute worktree path, which protects that worktree and its branch and is the only way to exclude a detached HEAD; `apply` no longer spends time on the scan-only `likely-superseded-by` hint for unmerged worktrees.

## [3.3.0] - 2026-11-17

### Changed

- `clean-repos` now inventories every worktree: a new `unmerged-worktree` category reports unmerged commits, open PRs and detached HEADs (with `likely-superseded-by=#N` hints) and `apply` never removes them.

## [3.2.1] - 2026-11-17

### Changed

- `clean-repos` stale-empty threshold default lowered from 7 to 1 day (`--stale-empty-days`).

## [3.2.0] - 2026-11-17

### Changed

- Store plans in ignored `.agent-plans/` directories and protect them from worktree cleanup until the user decides their fate; manage both agent directory exclusions.
- `clean-repos` removes never-committed worktrees and their branches once the branch is older than `--stale-empty-days` (default 7, lowered to 1 in a later release) and the worktree is clean and idle (no process mentions it, `lsof` shows nothing open); recent, dirty or in-use ones stay untouched.

## [3.1.3] - 2026-11-15

### Changed

- Instruction installation and release synchronization manage the global Git exclusion for `.agent-tmp/`, removing per-task ignore setup while preserving personal rules.
- Keep task scratch files in ignored worktree storage; session cleanup accounts for external artifacts and removes its own temporary logs.

### Fixed

- Protect task scratch files when a repository overrides the global Git excludes file.

## [3.1.2] - 2026-11-14

### Fixed

- Handoffs preserve task authorization without spreading recap-only restrictions; release workflows confirm a concrete proposal before mutations and retain approval across handoffs.

## [3.1.1] - 2026-11-13

### Fixed

- Worktree setup respects pinned Python versions and reports failed dev dependency installs.

## [3.1.0] - 2026-11-13

### Changed

- `create-pr` now carries the changelog conventions (category order, no "Test" category, entries under `[Unreleased]`) and says not to put contributor guidelines or example entries in the changelog itself, since examples duplicating the `[Unreleased]` heading misled agents.
- `cleanup-session` no longer asks before the machine-wide docker prunes or `docker-unstick`; apply runs them, and only other branches, worktrees and compose projects still need confirmation

### Fixed

- The graphify freshness tests wait for the hook's detached refresh before deleting their temporary directory, so CI no longer fails intermittently with "Directory not empty"
- The instruction adapter test ignores the checkout path when checking that the Codex output has no `/graphify` reference, so a checkout whose path contains "graphify" no longer fails it

## [3.0.2] - 2026-11-12

### Fixed

- The Claude adapter tells Claude to query an existing graphify graph (`graphify query --budget`, `explain`, `path`) for structure questions before broad `rg` or whole-file reads, as the Codex adapter already does; the once-per-session hook notice alone was lost in long sessions, which then read whole files to answer them

## [3.0.1] - 2026-11-12

### Fixed

- `review` and `create-pr` state inline that the user's invocation is their explicit request for the fresh reviewer subagent, and `review` names the Agent call to make, so Claude no longer declines the reviewer as an unrequested subagent; a standalone `review` now carries the same authorization

## [3.0.0] - 2026-11-11

### Changed

- `handoff` writes the recap with a Bash heredoc, so overwriting a previous recap no longer fails and forces a read of the old file, and its **Pointers** list only what the first remaining step needs
- `handoff` assumes the recap is resumed right away: it collects repository state in one read-only git call shared with the save step, no longer verifies each claim (including PR status) separately, and no longer tells the next session to re-verify state, saving tool round trips in the long session that writes it
- `handoff` targets a resume directory, the checkout of the feature in progress or of the next feature's repository: the recap is saved there as `agent-handoff-<repo>-<branch>.md`, and when that directory is not the current one the closing line says to start the new session there (`/exit`, then `cd <dir> && claude`; `codex -C <dir>`) so it loads that project's instructions
- The PR policy states that invoking `create-pr` authorizes its single independent reviewer (and `create-pr-and-fix-ci` its delta re-reviews), that a reviewer never delegates further, and that an unavailable independent reviewer stops the workflow when the project requires one; it allows `gh pr merge --admin` only when a required review on a solo-maintained repository is the last blocker, after every check has passed
- `create-pr-and-fix-ci` enables auto-merge right away when resuming an existing PR without it; `cleanup-session` runs only once the session's PR is merged; `release` places a release requested in a multi-PR plan once, at the end

### Removed

- **Breaking:** workflow policies. Workflows no longer read `<agent home>/agent-config/workflow-policies/<workflow>.md`, saving a tool call at each start; their rules now live in the workflows and the PR policy. An instruction source containing `instructions/workflows/` makes `install-instructions.py` and `validate.py` fail, and reinstalling or restoring removes the policies a previous version installed

### CI

- Pin the shared release workflows to the lag-tolerant github-workflows commit 79c1362, so tag creation tolerates GitHub read-after-write delays.

## [2.6.1] - 2026-11-11

### Changed

- The Claude graphify freshness hook tells each session once how to use the graph (`graphify query --budget`, `explain path::symbol`, `path` for structure; `rg`/`Read` for function bodies and call sites) instead of delegating to `graphify hook-guard` on every search, which repeated a `MANDATORY` nudge on each call, and it no longer tells the agent to use `rg`/`Read` on every edit-triggered refresh

### Fixed

- `scripts/validate.py` ignores gitignored top-level directories such as `graphify-out/`, so `scripts/lint.sh` passes in a local checkout the graphify hook has populated

## [2.6.0] - 2026-11-10

### Added

- Codex graphify freshness: release synchronization registers `scripts/graphify-fresh.sh --client codex` as a managed `PreToolUse` hook in `~/.codex/hooks.json` (`scripts/sync-codex-hooks.py`), preserving other hooks and rolling back with the rest of the synchronization; `--client codex` refreshes the graph in silence, without injected context or `graphify hook-guard`
- The Codex adapter points the agent to the installed graphify skill for codebase questions when a graph exists
- `create-pr-and-fix-ci` reviews each CI fix on its own delta (`<last reviewed SHA>..HEAD`) before pushing it, with mechanical exemptions reported, and its output lists the re-reviews
- Review findings carry a provenance: `pre-existing` bugs are reported separately and do not block the PR
- Bug-fix PRs are checked for root cause and other occurrences of the same bug class
- A confirmed finding that exposes a missing or outdated convention, or recurs, now proposes a durable fix (instruction line, rule, lint or check)

### Changed

- This repository now ignores `graphify-out/`, so the graphify freshness hook keeps its graph up to date here
- `create-pr` looks for the PR template locally, then in the organization's `.github` repo (which `--body-file` otherwise bypasses), then falls back to a built-in template with Summary, Changes, Test plan, Screenshots, Risk, How to revert and Deployment notes

## [2.5.1] - 2026-11-10

### Fixed

- Installing a release that adds plugin content (such as `hooks/`) no longer ships an incomplete plugin when the launching checkout is older than the release: `--sync-local` and `--check` now run the installer from the verified release snapshot instead of the checkout
- A stale marketplace stage or Claude plugin cache is rebuilt (and reinstalled) instead of aborting with "differs from release"; the check still fails if the result differs

### Changed

- The graphify freshness hook now activates on a versioned `.gitignore` entry for `graphify-out/` instead of an existing main-checkout graph, and builds the first graph in the background (with a one-time notice) when none exists
- The packaged plugin directories are defined once (`PLUGIN_DIRS`) and `validate.py` fails on an unpackaged top-level directory or a hook path outside them

## [2.5.0] - 2026-11-10

### Added

- Claude plugin `PreToolUse` hook (`hooks/hooks.json`, `scripts/graphify-fresh.sh`) that keeps graphify graphs fresh at read time: it seeds linked worktrees from the main checkout, refreshes stale graphs in the background and delegates the nudge to `graphify hook-guard` only when the graph matches the checkout

### Changed

- `create-pr` now requires filling test gaps at the right level and documentation gaps in the PR itself, instead of leaving them as stated limitations

## [2.4.3] - 2026-11-09

### Fixed

- `clean-repos` no longer kills processes of a different worktree whose path merely starts with the cleaned one (`feature-a` vs `feature-ab`); process matching is now literal and boundary-anchored
- `clean-repos` skips remote deletion for a repo when `gh` cannot list open PRs, instead of treating the failure as "no open PRs"
- `clean-repos` skill text now matches the script: verified/unverified squash-merged branches, `-D` after an ancestry or content check, `worktrees-new-empty`, and every skip reason

### Changed

- `clean-repos scan` reports each dirty worktree with its tracked and untracked counts, listing untracked files and flagging deletions-only changes

## [2.4.2] - 2026-11-07

### Changed

- Run the Claude `release` and `update-skill` workflows on the session model instead of forcing Opus or Sonnet, avoiding a model switch that discards the prompt cache.

## [2.4.1] - 2026-11-06

### Fixed

- Choose the correct worktree base when stale release or hotfix branches exist.

## [2.4.0] - 2026-11-06

### Changed

- Prepare version changes through PRs and delegate release tags to CI; publish version changelog notes with explicit retry checks.

### Fixed

- Install dependencies with `uv sync` in new worktrees of uv projects, and detect text `bun.lock` files.
- Detect Gitflow only from concrete branch evidence, not from documentation mentioning it; worktree scripts share the same detection.
- Preserve complete release notes when Markdown examples contain version headings.

## [2.3.0] - 2026-11-04

- Add session handoffs saved outside the working tree for resuming work in a fresh session.
