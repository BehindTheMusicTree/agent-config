---
description: Create or update shared Claude commands, Codex skills, and global agent instructions in agent-config.
model: sonnet
---

Work in the source checkout specified by the user or the configured owner of the requested skill. Inspect the working tree first and preserve existing changes. The requested change is: **$ARGUMENTS**. Ask only if the intended change is ambiguous.

For a shared workflow, update `commands/<name>.md` and `skills/<name>/SKILL.md` together, retaining each agent's invocation conventions. For global guidance, update `instructions/global.md`, `instructions/rules/`, `instructions/scopes.json`, and relevant `adapters/`. Never edit installed release snapshots or generated global files. Keep `CONVENTIONS.md` and the README consistent with their source files.

Run the source repository's documented validation commands. If Claude commands changed, bump `.claude-plugin/plugin.json` according to the change. Commit, publish, or update installed agents when requested or otherwise authorized. After publishing, synchronize the profile that owns the changed source and report publication and local synchronization separately.
