# Changelog

## [Unreleased]

### Changed

- `handoff` assumes the recap is resumed right away: it collects repository state in one read-only git call shared with the save step, no longer verifies each claim (including PR status) separately, and no longer tells the next session to re-verify state, saving tool round trips in the long session that writes it
- `handoff` targets a resume directory, the checkout of the feature in progress or of the next feature's repository: the recap is saved there as `agent-handoff-<repo>-<branch>.md`, and when that directory is not the current one the closing line says to start the new session there (`/exit`, then `cd <dir> && claude`; `codex -C <dir>`) so it loads that project's instructions

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
