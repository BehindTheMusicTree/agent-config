## Claude integration
- Respect the project's CLAUDE.md and applicable .claude/rules instructions.
- Global path-scoped rules are installed under the `agent-config-` prefix in the user rules directory. Their content is generated from the shared sources; edit those sources to change a rule.
- When the user explicitly invokes `/graphify`, read `~/.claude/skills/graphify/SKILL.md` if it exists. If unavailable, report that instead of pretending the skill ran.
