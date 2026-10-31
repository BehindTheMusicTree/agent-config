# TypeScript and JavaScript defaults

Use these preferences where compatible with the project's conventions and configured tooling.

- Preferred frontend stack: Next.js App Router, React, Tailwind CSS; Expo and React Native for mobile. Respect the project's versions; a normal code change is not an instruction to upgrade them.
- PascalCase for React components, NestJS classes, and DTOs; camelCase for functions and variables; kebab-case for NestJS files.
- Use `@/*` aliases when configured in the project; avoid deep relative imports in that case.
- TypeScript: strict typing, no implicit `any`; explicit `any` needs a justification comment.
- No `console.log` in production code; use the project's logging mechanism.
- Prefer ESLint flat configuration for new setup. Do not bypass lint rules without a targeted disable comment and reason.
- In NestJS projects, use class-validator DTOs, a global ValidationPipe, and explicit guards.
- Use the repo's validation commands. Typical pnpm projects provide lint, build, and test scripts; run the applicable ones.
