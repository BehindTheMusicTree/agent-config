## Codex integration
- Respect the applicable project AGENTS.md instructions. Claude's `paths:` metadata is not a Codex loading mechanism.
- Before working on files covered by a shared rule listed below, read that rule. Evaluate paths relative to the relevant working directory; `**/` also includes files at its root. Apply a rule only to its stated scope, even after it has been read.
- Invoke installed skills when relevant to the user's task. Do not assume a Claude-only tool or integration is installed in Codex.
- When `graphify-out/graph.json` exists and the graphify skill is installed, use it (`graphify query`, or `$graphify` when the user invokes it) for questions about the codebase before broad `rg` or file reads. If the skill is not installed, do not assume it.
