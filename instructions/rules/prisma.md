# Prisma projects

- Prefer typed queries with nested relations; avoid raw queries.
- After a schema change, follow the repository's migration workflow. `prisma migrate dev` is for the intended development database; verify that context before running it.
