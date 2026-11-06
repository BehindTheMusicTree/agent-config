# Changelog

## [Unreleased]

### Fixed

- Install dependencies with `uv sync` in new worktrees of uv projects, and detect text `bun.lock` files.

- Preserve complete release notes when Markdown examples contain version headings.

- Prepare version changes through PRs and delegate release tags to CI; publish version changelog notes with explicit retry checks.

## [2.3.0] - 2026-11-04

- Add session handoffs saved outside the working tree for resuming work in a fresh session.
