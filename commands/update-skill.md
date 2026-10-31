---
description: Create or update shared Claude commands, Codex skills, and global agent instructions in agent-config.
model: sonnet
---

Work in the source checkout specified by the user or the configured owner of the requested skill. Inspect the working tree first and preserve existing changes. The requested change is: **$ARGUMENTS**. Ask only if the intended change is ambiguous.
For a shared workflow, edit its `workflows/<name>.json` source when that directory exists; run `python3 scripts/render-workflows.py --apply` to regenerate both clients, then verify the changes. For a source repository without workflow generation, maintain its Claude command and Codex skill according to its documented conventions. Keep client-specific invocation details in their respective variants. Never edit installed release snapshots or generated files directly.
For global guidance, update `instructions/global.md`, `instructions/rules/`, `instructions/scopes.json`, and relevant `adapters/`. Never edit installed release snapshots or generated global files. Keep `CONVENTIONS.md` and the README consistent with their source files.

Run the source repository's documented validation commands. If Claude commands changed, bump `.claude-plugin/plugin.json` according to the change. Commit, publish, or update installed agents when requested or otherwise authorized. After publishing, synchronize the profile that owns the changed source and report publication and local synchronization separately.
