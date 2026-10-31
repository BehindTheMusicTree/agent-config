# agent-config

Reusable agent workflows for Claude Code and Codex. The public source works independently; a private extension can add its own skills and instructions.

Released under the [MIT license](LICENSE).

## Development

Use Python 3.10 or later. Create a virtual environment, install `requirements-dev.txt`, then run `scripts/lint.sh`. ShellCheck is required for shell lint. To exercise real Claude installation in temporary homes, set `AGENT_CONFIG_RUN_CLAUDE_E2E=1` when running the relevant tests.

## Install public skills

Run `scripts/install-codex-skills.sh` from a persistent checkout to install Codex skills. Preview shared global instructions using `python3 scripts/install-instructions.py`; install them using `--apply`. Keep this checkout available. Generated instructions must be changed through their maintained sources.

Claude can install the plugin using `/plugin install agent-config --marketplace BehindTheMusicTree/agent-config`.

## Install a public/private release pair

Create a local JSON profile with `version: 1`, `public` and `private`. Both source entries require `repo` (owner/name) and `id` (the immutable GitHub repository id returned by `gh repo view OWNER/NAME --json id`). The private entry can also specify `version` for rollback; otherwise its latest stable release is selected. The private release must contain `agent-config-dependency.json` with `repo` and an exact public `tag`.

Run `python3 scripts/prepare-remote-release.py --profile /absolute/path/profile.json --sync-local`. Use `--check` to verify both installed snapshots, skills, instructions and cached plugins. Authentication through `gh` and Git is required for private downloads. A missing or changed source aborts installation.

After the first successful synchronization, macOS users can run `python3 scripts/manage-auto-sync.py install --profile /absolute/path/profile.json`. This replaces the managed legacy scheduler and follows the public updater through `current-profile`. Keep the profile file available. The job preserves the agent homes and authentication configuration from its installation environment.

The updater reconciles all configured sources together. Personal files and local modifications remain protected; missing sources require explicit removal. Claude plugin operations are journaled for retry. If a plugin update fails, Codex links and generated instructions are restored; Claude may already contain newly installed plugins. Retry the same pinned private version to finish that migration before selecting another pair.

Keep the previous release snapshots and configuration for recovery. Roll back a pair by pinning the preceding private version in the profile and synchronizing again. Global instruction originals can be restored through `scripts/install-instructions.py --restore`.
