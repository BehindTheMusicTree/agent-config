# agent-config engine

Public engine that generates agent instructions, skills and workflow adapters from shared sources.

- Sources live in `instructions/`, `skills/`, `workflows/` and `settings/`; generated adapters are never edited by hand.
- Do not add client-specific instruction files; `AGENTS.md` is the only instruction source and `CLAUDE.md` contains only `@AGENTS.md`.
- Validate with `python3 -m unittest discover -s tests`; `tests/test_project_agents.py` covers `scripts/check-project-agents.py`.
- Release Please generates versioned `CHANGELOG.md` entries from PR titles, whose type sets the version bump (`fix` patch, `feat` minor, `!` major). CI auto-merges the release PR, so merging a `feat`, `fix` or breaking-change PR starts a release.
