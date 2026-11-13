## Claude integration
- Respect the project's CLAUDE.md and applicable .claude/rules instructions.
- Global path-scoped rules are installed under the `agent-config-` prefix in the user rules directory. Their content is generated from the shared sources; edit those sources to change a rule.
- When `graphify-out/graph.json` exists, answer structure questions (which modules use a symbol or file, how data flows between them) with `graphify query '<question>' --budget 800`, `graphify explain` or `graphify path` before broad `rg` or whole-file reads. Use `rg` and Read for function bodies, exact call sites and line-level work.
- When the user explicitly invokes `/graphify`, read `~/.claude/skills/graphify/SKILL.md` if it exists. If unavailable, report that instead of pretending the skill ran.
