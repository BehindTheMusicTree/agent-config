# Changelog

## [Unreleased]

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
