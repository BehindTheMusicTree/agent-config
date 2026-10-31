---
name: update-skill
description: Create or update a shared Claude command and its Codex skill in the source configuration repository.
---

Work in the source checkout specified by the user or the configured owner of the requested skill. Verify that it is a Git checkout before editing. Never edit an installed release snapshot or a plugin cache. Inspect the working tree and preserve existing changes.

Use the user's request to determine the workflow and intended behavior. Update the Claude command in `commands/<name>.md` and its Codex counterpart in `skills/<name>/SKILL.md` together when both apply. Preserve their respective runtime conventions; scripts live under the repository's `scripts/`. For new skills use a lowercase hyphenated name and a YAML frontmatter with `name` and `description`. Update shared conventions and README when relevant.

Run the source repository's documented validation commands and exercise modified scripts as appropriate. Review both versions for behavioral consistency and report any intentional differences. Bump the Claude plugin version if its commands change. Commit, push, publish, or refresh installed plugins only when requested or otherwise authorized by the user and the applicable environment.

For global instructions, edit `instructions/global.md`, `instructions/rules/`, and `instructions/scopes.json`; use `adapters/` only for agent-specific loading instructions. `CONVENTIONS.md` is an index into these sources. Never edit generated global files directly. Preview with `python3 scripts/install-instructions.py`; apply authorized changes with `--apply`, and preserve any local edits reported by the installer.
