# Shared working agreements

- Follow the user's task and the project's documented conventions.
- Preserve unrelated changes and explain material risks and validation results.

## Task artifacts

- Write plans and design proposals in `.agent-plans/<topic>.md` in the task worktree, never in tracked paths such as `docs/plans/`, unless the user asks to commit them. Each repo commits `.agent-plans/.gitignore` and `.agent-tmp/.gitignore` containing `*` followed by `!.gitignore`; their contents stay ignored. Verify the actual plan path with `git check-ignore -q` before writing, using `info/exclude` as a fallback when needed.
- Plans are not disposable. Before removing a worktree, inventory `.agent-plans/` and let the user decide whether to promote, keep or discard the files. Preserve retained plans outside the worktree before removal.
- Keep task-generated scratch files (captures, traces, diagnostics, temporary reports and exploratory scripts) in the task's worktree under `.agent-tmp/`. The installer manages a global Git exclusion, but repository rules can override it. Before creating a scratch file, verify its actual path with `git check-ignore -q`; if needed, add `.agent-tmp/` to the repository’s Git `info/exclude` and verify again. Repository rules can override individual paths; if the path is still not ignored, stop and resolve the conflicting rule. Do not commit scratch files.
- Do not leave task artifacts in home directories, shared application data or fixed `/tmp` paths. If a task requires an external location, explain why and record its exact paths, ownership and cleanup action in `.agent-tmp/external-artifacts.md`. Use unique paths for concurrent sessions. Short-lived system temporary files are allowed when removed on success and failure.
- Before removing a worktree, preserve requested deliverables at their intended destination and account for external artifacts. Delete only disposable files owned by this task; report anything retained with its path and reason. Shared runtimes, caches and conversation history follow their tools' lifecycle. Explicit workflow storage contracts (such as handoffs in the common Git directory) remain applicable.
