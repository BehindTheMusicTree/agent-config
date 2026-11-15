# Shared working agreements

- Follow the user's task and the project's documented conventions.
- Preserve unrelated changes and explain material risks and validation results.

## Task artifacts

- Keep task-generated scratch files (captures, traces, diagnostics, temporary reports and exploratory scripts) in the task's worktree under `.agent-tmp/`. Ensure that directory is ignored before writing, using the repository's existing ignore rules or a local Git exclude; do not commit scratch files.
- Do not leave task artifacts in home directories, shared application data or fixed `/tmp` paths. If a task requires an external location, explain why and record its exact paths, ownership and cleanup action in `.agent-tmp/external-artifacts.md`. Use unique paths for concurrent sessions. Short-lived system temporary files are allowed when removed on success and failure.
- Before removing a worktree, preserve requested deliverables at their intended destination and account for external artifacts. Delete only disposable files owned by this task; report anything retained with its path and reason. Shared runtimes, caches and conversation history follow their tools' lifecycle. Explicit workflow storage contracts (such as handoffs in the common Git directory) remain applicable.
