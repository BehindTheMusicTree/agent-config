# Python defaults

Apply where compatible with the project's conventions and tooling.

- snake_case for functions and variables, PascalCase for classes.
- Ruff for lint and format, line length 120.
- No `print()` in production code (Ruff T20); use the project's logger.
- Explicit runtime checks rather than `assert` outside tests.
- Run the documented checks, typically `ruff check .`, `ruff format --check .` and `pytest`.
- New backend projects only: Django, DRF, PostgreSQL; in Django projects, mypy with its Django plugin.
