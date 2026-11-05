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

## Compaction threshold

Set the compaction point once, in Claude: `env.CLAUDE_CODE_AUTO_COMPACT_WINDOW` in `~/.claude/settings.json`. Claude Code compacts at that window minus an internal, undocumented reserve; Codex compacts when the active context reaches `model_auto_compact_token_limit`. Synchronization writes `model_auto_compact_token_limit = window - claudeCompactReserveTokens` into the top level of `~/.codex/config.toml`, changing only that line, and `--check` reports drift. The reserve lives in `settings/compact.json`; re-measure it after a Claude Code upgrade (`/context`, "Autocompact buffer", or the observed compaction point). When the Claude variable is unset, Codex is left unchanged. The edit requires Python 3.11+ and is accepted only when the parsed file equals the original plus that key; otherwise synchronization stops and asks for a manual edit. Preview with `python3 scripts/sync-compact-limit.py`, write with `--apply`.

## Maintenir les workflows

Les fichiers `workflows/<name>.json` contiennent les blocs partagés et les variantes propres à Claude ou Codex. Modifier ces sources, puis exécuter `python3 scripts/render-workflows.py --apply`. Les fichiers sous `commands/` et `skills/` sont les sorties distribuées. `python3 scripts/render-workflows.py` vérifie leur concordance sans les modifier et fait partie de `scripts/lint.sh`. Le manifeste `.workflow-generated.json` protège les sorties modifiées localement ; vérifier et résoudre un conflit avant de régénérer. Les descriptions, modèles et chemins spécifiques au client restent dans les blocs de variante.

Une source (par exemple une extension privée) peut compléter un workflow existant sans le copier : `instructions/workflows/<workflow>.md` est installé dans `<agent home>/agent-config/workflow-policies/<workflow>.md`, que chaque workflow lit au démarrage ; ses règles priment sur les valeurs par défaut du workflow. Une politique visant un workflow inconnu, ou deux sources visant le même workflow, font échouer l'installation ; `scripts/validate.py` rejette aussi une politique visant un workflow inconnu. Seule la première source composée peut définir le titre de `global.md` ; les règles à portée de toutes les sources sont regroupées dans une seule section de routage.

Pour un projet adoptant la convention `AGENTS.md` / import `CLAUDE.md` et les liens de skills relatifs, `python3 scripts/check-project-agents.py /path/to/project` vérifie cette structure sans écriture. Ce contrôle est volontairement limité aux projets qui choisissent cette convention ; il ne vérifie pas le contenu métier ni le chargement effectif des agents.

Pour les règles à portée, `.agents/scopes.json` associe chaque nom à un objet `source` (chemin relatif) et `paths` (liste de globs). `AGENTS.md` référence chaque source et ses globs ; `.claude/rules/<name>.md` contient le frontmatter `paths:` suivi du texte exact de la source. Générer les adaptateurs avec `python3 scripts/render-project-rules.py /path/to/project --apply` ; sans `--apply`, la commande vérifie le résultat. Le manifeste `.agents/generated-rules.json` protège les sorties modifiées localement. Le routage dans `AGENTS.md` reste à maintenir dans le projet.

## Standalone review

Use `$review` in Codex or `/agent-config:review` in Claude to review a branch, commit range, or existing PR without changing it. `create-pr` invokes the same workflow on its final state. Independence requires a fresh reviewer session when available.

## Session handoff

Use `$handoff` in Codex or `/agent-config:handoff [focus]` in Claude to write a recap of at most about 30 lines: a freshness header (date, repository, branch, HEAD), a reminder to re-verify state, concise context, detailed remaining steps, state, a terse done list, and pointers. State claims are verified with read-only git/gh before they are written, and secret values are never included. The recap is saved to `agent-handoff-<branch>.md` in the repository's common git directory (one file per branch, so parallel worktrees do not overwrite each other; never in `git status`, survives worktree removal). Only the file path is printed, so the recap is not generated twice: `/clear`, then reference it with `@<path>` in Claude or ask a new Codex session to read it. When no file can be written (outside a git repository or after a failed write), the recap is printed instead.

## Release ownership

The release workflow detects a repository's `.github/release-policy.json` before running mutating tools. Adopted repositories delegate tag creation to CI; project tools prepare version, mirrors and changelog in a PR, then the agent verifies the exact merged SHA and required publications. Repositories without the contract keep their documented legacy publication owner. See [release ownership and recovery](references/release-contract.md). Editing these procedures does not itself authorize a release, plugin version bump or local reinstall.
