# Python defaults

Use these preferences where compatible with the project's conventions and configured tooling.

- Preferred backend stack: Django, DRF, Django ORM, PostgreSQL.
- snake_case for functions and variables; PascalCase for classes and Django models.
- Ruff for lint and format, line length 120; mypy with its Django plugin in Django projects.
- No `print()` in production code (Ruff T20); use the project's logger.
- Use explicit runtime checks rather than `assert` outside tests.
- Use documented project checks. Typical commands are `ruff check .`, `ruff format --check .`, and `pytest`.
