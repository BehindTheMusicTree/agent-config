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

Run `python3 scripts/prepare-remote-release.py --profile /absolute/path/profile.json --sync-local`. Use `--check` to verify both installed snapshots, skills, instructions and cached plugins. Authentication through `gh` and Git is required for private downloads. A missing or changed source aborts installation. Synchronization and `--check` run the installer from the downloaded release snapshot, so the launching checkout can be older than the release it installs.

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

Use `$handoff` in Codex or `/agent-config:handoff [focus]` in Claude to write a recap of at most about 30 lines: a header (date, repository, branch, HEAD, resume directory), concise context, detailed remaining steps, state, a terse done list, and pointers. The recap is meant to be resumed right away, so repository state comes from a single read-only git call, nothing else is re-checked, and the next session is not asked to re-verify. Secret values are never included. The resume directory is the checkout where the work continues: the feature in progress, or the repository of the next feature. The recap is saved to `agent-handoff-<repo>-<branch>.md` in that checkout's common git directory (one file per branch, so parallel worktrees do not overwrite each other; never in `git status`, survives worktree removal). Only the file path is printed, so the recap is not generated twice. In Claude, `/clear` and reference it with `@<path>` when the resume directory is the current one; otherwise `/exit` and start Claude in the resume directory, since `/clear` keeps the working directory and its project instructions. In Codex, start a session with `codex -C <resume directory>` and ask it to read the file. When no file can be written (outside a git repository or after a failed write), the recap is printed instead.

## Release ownership

The release workflow detects a repository's `.github/release-policy.json` before running mutating tools. Adopted repositories delegate tag creation to CI; project tools prepare version, mirrors and changelog in a PR, then the agent verifies the exact merged SHA and required publications. Repositories without the contract keep their documented legacy publication owner. See [release ownership and recovery](references/release-contract.md). Editing these procedures does not itself authorize a release, plugin version bump or local reinstall.

The public plugin itself uses `.github/release-policy.json`: `.claude-plugin/plugin.json`
is canonical, and `CHANGELOG.md` supplies versioned notes. Prepare both in a PR to `main`.
The shared workflow pinned in `release-tag.yml` owns tags after approved version bumps;
ordinary pushes and initial activation never create a tag. Provision the release App
variable/secret and immutable tag protections through `github-config` before the first bump.
The existing `release.yml` validates the tag's version, commit ancestry and repository before
creating its GitHub Release. Rerun a failed tag run to resume: an existing published stable
release is accepted; API errors, drafts and prereleases fail explicitly. Never recreate or
move a tag for recovery. Plugin publication and local installation remain separate actions.

## Graphify freshness hook

The Claude plugin ships a `PreToolUse` hook (`hooks/hooks.json`, matcher `Bash|Grep|Read|Glob`) that runs `scripts/graphify-fresh.sh`. It only acts when `graphify` is on `PATH` and the repository ignores `graphify-out/` in a versioned `.gitignore` (`git check-ignore graphify-out/graph.json`); every other repository is untouched. A repository that opts in without a graph gets its first one built in the background, with a one-time notice to use `rg`/`Read` meanwhile. It never blocks a tool call.

- A linked worktree without `graphify-out/` is seeded from the main checkout when it has a graph (graph, manifest, cache, report; not dated backups or `graph.html`).
- The freshness key is `HEAD` plus a hash of the uncommitted diff and untracked files. When it differs from `graphify-out/.fresh-key`, the hook starts one detached `graphify update .` (code-only, no backup dirs, guarded by `graphify-out/.refresh.lock`, stale after 10 minutes) and logs to `graphify-out/refresh.log`.
- Each session (`session_id`, recorded in `graphify-out/.notified-session`) gets one notice once a graph exists: use `graphify query --budget`, `explain path::symbol` or `path` for structure questions, and `rg`/`Read` for function bodies and call sites, since the static graph misses calls resolved at runtime. A session that starts during the first build is told again when the graph is ready. Edits and background refreshes add no further context.
- The hook never calls `graphify hook-guard`. Its per-call `MANDATORY` nudge was ignored after the first few calls and contradicted the refresh notice whenever an edit changed the key.

This replaces per-repository `graphify hook-guard` entries in `.claude/settings.json`; remove any that remain, or the per-call nudge comes back. The hook reaches installed sessions with the next plugin release.

### Codex

Codex has no plugin hooks, so release synchronization (`scripts/sync-local-release.py`, `--sync-local`; checked by `--check`) registers the same script in `~/.codex/hooks.json` as one managed `PreToolUse` entry (matcher `Bash`, timeout 5 s) that runs `graphify-fresh.sh --client codex` from the active release snapshot. Other hooks in the file are preserved, the managed entry is found again by its script name and replaced on the next release, and an invalid or symlinked file stops synchronization. Preview or write it alone with `python3 scripts/sync-codex-hooks.py` / `--apply`.

- With `--client codex` the hook only seeds worktrees and refreshes the graph in the background, in silence: it injects nothing and never calls `graphify hook-guard`, because Codex Desktop rejects `additionalContext` on `PreToolUse`. The Codex adapter and the graphify skill steer the agent instead.
- Codex asks you to trust a new or changed hook: review it once in `/hooks` after the first synchronization and after each release that changes its path.
- The graphify skill is a machine install, not part of this repository: run `graphify install` (Claude) and `graphify install --platform codex` (Codex) once, and again after `uv tool upgrade graphifyy`. Do not run `graphify codex install`, which writes into every `AGENTS.md`.
