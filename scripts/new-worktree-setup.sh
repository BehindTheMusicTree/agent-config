#!/usr/bin/env bash
# Helper for the new-worktree command.
#
#   new-worktree-setup.sh <branch-name> [<base-ref>]
#
# Runs the deterministic steps of worktree creation in order: detect
# flow/trunk (unless <base-ref> is given), create the worktree+branch, copy
# gitignored env files, offset any PORT-style vars deterministically (and
# rewrite cross-file localhost:<port> references so they stay in sync), then
# install dependencies. Prints key=value lines; final line is always
# `status=ok` or `status=blocked reason=<reason>`.
#
# Run from inside the main worktree (the repo root, or any subdirectory of it).
set -uo pipefail

branch="${1:?usage: new-worktree-setup.sh <branch-name> [<base-ref>]}"
base_ref="${2:-}"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$repo_root" ]]; then
  echo "status=blocked reason=not-a-git-repo"
  exit 0
fi
cd "$repo_root" || exit 1
echo "repo_root=$repo_root"

# --- flow/trunk detection (mirrors refresh-worktree-precheck.sh) ---
if [[ -n "$base_ref" ]]; then
  trunk="$base_ref"
  flow="explicit"
else
  trunk="main"
  git show-ref --verify --quiet refs/remotes/origin/master && trunk="master"
  flow="github"
  if git show-ref --verify --quiet refs/remotes/origin/develop \
     || git config --get-regexp '^gitflow\.' >/dev/null 2>&1 \
     || grep -riqE 'gitflow|git flow|release branch|hotfix branch' CONTRIBUTING.md CLAUDE.md AGENTS.md README.md 2>/dev/null \
     || git branch -a --format='%(refname:short)' | grep -qE '(release|hotfix)/'; then
    flow="gitflow"
    trunk="develop"
  fi
fi
echo "flow=$flow"
echo "trunk=$trunk"

# --- worktree + branch ---
slug="$(echo "$branch" | tr '/' '-')"
wt_rel=".claude/worktrees/$slug"
wt_abs="$repo_root/$wt_rel"

if ! git check-ignore -q .claude/worktrees; then
  echo ".claude/worktrees/" >> .gitignore
  echo "gitignore_updated=true"
fi

if [[ -e "$wt_abs" ]]; then
  echo "status=blocked reason=worktree-path-exists"
  exit 0
fi

base_for_add="$trunk"
[[ "$flow" != "explicit" ]] && base_for_add="origin/$trunk"
if ! git worktree add -b "$branch" "$wt_rel" "$base_for_add" >/dev/null 2>&1; then
  # base ref might already be a plain local/explicit ref (no origin/ prefix)
  if ! git worktree add -b "$branch" "$wt_rel" "$trunk" >/dev/null 2>&1; then
    echo "status=blocked reason=worktree-add-failed"
    exit 0
  fi
  base_for_add="$trunk"
fi
echo "worktree_path=$wt_rel"
echo "branch=$branch"
echo "base_ref=$base_for_add"

# --- discover + copy gitignored env files ---
mapfile -t env_files < <(git -C "$repo_root" status --ignored --porcelain=v1 | awk '/^!!/{print $2}' | grep -E '(^|/)\.env(\.[A-Za-z0-9._-]+)?$')
echo "env_files_copied=${#env_files[@]}"

declare -A old_to_new_port=()
copied_abs_paths=()
port_target_paths=()

for rel in "${env_files[@]}"; do
  src="$repo_root/$rel"
  dst="$wt_abs/$rel"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  copied_abs_paths+=("$dst")
  # .example/.sample files are stable templates, not live config — never
  # offset their ports or rewrite cross-refs, or they stop being a reliable
  # "what's the repo's default port" reference for every worktree.
  case "$(basename "$dst")" in
    *.example|*.sample) ;;
    *) port_target_paths+=("$dst") ;;
  esac
done

if [[ ${#port_target_paths[@]} -eq 0 ]]; then
  echo "port_vars=none"
else
  # --- port offset ---
  offset=$(( $(echo -n "$branch" | cksum | cut -d' ' -f1) % 1000 ))
  echo "port_offset=$offset"

  any_port=false
  for dst in "${port_target_paths[@]}"; do
    while IFS='=' read -r key val; do
      [[ -z "$key" ]] && continue
      new_val=$(( val + offset ))
      old_to_new_port["$val"]="$new_val"
      any_port=true
      echo "port_var=$dst:$key:$val->$new_val"
    done < <(grep -E '^[A-Za-z_]*PORT=[0-9]+$' "$dst" 2>/dev/null | grep -vE '^[A-Za-z_]*_REMOTE_PORT=')

    OFFSET="$offset" perl -i -pe 's/^([A-Za-z_]*PORT)=(\d+)$/(substr($1, -11) eq "_REMOTE_PORT") ? "$1=$2" : $1 . "=" . ($2 + $ENV{OFFSET})/e' "$dst"
  done
  $any_port || echo "port_vars=none"

  # --- cross-file reference rewrite ---
  if [[ ${#old_to_new_port[@]} -gt 0 ]]; then
    for dst in "${port_target_paths[@]}"; do
      for old_port in "${!old_to_new_port[@]}"; do
        new_port="${old_to_new_port[$old_port]}"
        if grep -qE "localhost:${old_port}([^0-9]|$)" "$dst" 2>/dev/null; then
          while IFS= read -r var; do
            echo "cross_ref_rewritten=$dst:$var:$old_port->$new_port"
          done < <(grep -E "localhost:${old_port}([^0-9]|$)" "$dst" | cut -d= -f1)
          perl -i -pe "s/localhost:${old_port}(?!\\d)/localhost:${new_port}/g" "$dst"
        fi
      done
    done
  fi

  # --- stale external refs: localhost port that is dead and differs from .env.example (warn only) ---
  for dst in "${port_target_paths[@]}"; do
    example="$(dirname "$dst")/.env.example"
    [[ -f "$example" ]] || continue
    while IFS='=' read -r key val; do
      port=$(grep -oE 'localhost:[0-9]+' <<<"$val" | head -n1 | cut -d: -f2)
      [[ -z "$port" || " ${old_to_new_port[*]:-} " == *" $port "* ]] && continue
      example_val=$(grep -E "^${key}=" "$example" | head -n1 | cut -d= -f2-)
      [[ -z "$example_val" || "$example_val" == "$val" ]] && continue
      (exec 3<>"/dev/tcp/localhost/$port") 2>/dev/null && continue
      echo "stale_ref=${dst}:${key}:localhost:${port} not listening; .env.example has $example_val"
    done < <(grep -E '^[A-Za-z0-9_]+=.*localhost:[0-9]+' "$dst")
  done
fi

# --- install dependencies ---
cd "$wt_abs" || exit 1
install_tool="none"
install_status="skipped"
install_log="$(cd "$(git rev-parse --git-dir)" && pwd)/install.log"
: >"$install_log"
if [[ -f pnpm-lock.yaml ]]; then
  install_tool="pnpm"; pnpm install >>"$install_log" 2>&1 && install_status="ok" || install_status="fail"
elif [[ -f yarn.lock ]]; then
  install_tool="yarn"; yarn install >>"$install_log" 2>&1 && install_status="ok" || install_status="fail"
elif [[ -f package-lock.json ]]; then
  install_tool="npm"; npm install >>"$install_log" 2>&1 && install_status="ok" || install_status="fail"
elif [[ -f bun.lockb ]]; then
  install_tool="bun"; bun install >>"$install_log" 2>&1 && install_status="ok" || install_status="fail"
elif [[ -f poetry.lock ]]; then
  install_tool="poetry"; poetry install >>"$install_log" 2>&1 && install_status="ok" || install_status="fail"
elif [[ -f Pipfile.lock ]]; then
  install_tool="pipenv"; pipenv install >>"$install_log" 2>&1 && install_status="ok" || install_status="fail"
elif [[ -f pyproject.toml ]]; then
  install_tool="venv"
  if python3 -m venv .venv >>"$install_log" 2>&1 && source .venv/bin/activate; then
    if grep -q '^\s*dev\s*=' pyproject.toml || grep -q '\[project.optional-dependencies\]' pyproject.toml; then
      python3 -m pip install -e ".[dev]" >>"$install_log" 2>&1 || python3 -m pip install -e . >>"$install_log" 2>&1
    else
      python3 -m pip install -e . >>"$install_log" 2>&1
    fi && install_status="ok" || install_status="fail"
  else
    install_status="fail"
  fi
fi
echo "install_tool=$install_tool"
echo "install_status=$install_status"
echo "install_log=$install_log"
echo "check_claude_md_setup=true"

# --- convention: repo-specific dev-server launcher, if the repo has one ---
if [[ -f "$wt_abs/scripts/dev-up.sh" ]]; then
  echo "dev_up_script=scripts/dev-up.sh"
else
  echo "dev_up_script=none"
fi

echo "status=ok"
