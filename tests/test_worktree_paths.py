import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def run(*args, cwd, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}\n{result.stderr}')
    return result.stdout


class WorktreePathsTests(unittest.TestCase):
    def test_creation_from_linked_worktree_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            run('git', 'init', '-q', '-b', 'main', cwd=root)
            run('git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                'commit', '-q', '--allow-empty', '-m', 'initial', cwd=root)
            script = str(SCRIPTS / 'new-worktree-setup.sh')
            output = run(script, 'codex', 'feature/one', 'main', cwd=root)
            self.assertIn(f'worktree_path={root.resolve()}/.codex/worktrees/feature-one', output)
            linked = root / '.codex/worktrees/feature-one'
            output = run(script, 'claude', 'feature/two', 'main', cwd=linked)
            self.assertIn(f'worktree_path={root.resolve()}/.claude/worktrees/feature-two', output)
            self.assertEqual(run('git', 'status', '--porcelain', cwd=root), '')
            output = run(script, 'codex', 'feature/one', 'main', cwd=root)
            self.assertIn('status=blocked reason=worktree-path-exists', output)
            self.assertFalse((root / '.gitignore').exists())

    def test_github_flow_documentation_does_not_imply_gitflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run('git', 'init', '-q', '-b', 'main', cwd=root)
            run('git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                'commit', '-q', '--allow-empty', '-m', 'initial', cwd=root)
            run('git', 'update-ref', 'refs/remotes/origin/main', 'HEAD', cwd=root)
            run('git', 'branch', 'release/0.13.0', cwd=root)
            run('git', 'update-ref', 'refs/remotes/origin/hotfix/old', 'HEAD', cwd=root)
            (root / 'CONTRIBUTING.md').write_text('GitHub Flow: No develop or long-lived release branches.\n')
            (root / 'AGENTS.md').write_text('Detect strict Gitflow vs GitHub flow.\n')
            output = run(str(SCRIPTS / 'detect-branch-model.sh'), cwd=root)
            self.assertEqual(output, 'flow=github\ntrunk=main\n')
            output = run(str(SCRIPTS / 'new-worktree-setup.sh'), 'codex', 'feature/test', cwd=root)
            self.assertIn('flow=github\ntrunk=main\n', output)
            self.assertIn('base_ref=origin/main\n', output)
            self.assertIn('status=ok', output)
            linked = root / '.codex/worktrees/feature-test'
            relative_script = os.path.relpath(SCRIPTS / 'new-worktree-setup.sh', linked.resolve())
            output = run(relative_script, 'claude', 'feature/relative', cwd=linked)
            self.assertIn('status=ok', output)
            run('git', 'update-ref', 'refs/remotes/origin/develop', 'HEAD', cwd=root)
            self.assertEqual(run(str(SCRIPTS / 'detect-branch-model.sh'), cwd=root),
                             'flow=gitflow\ntrunk=develop\n')

    def test_branch_detection_default_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run('git', 'init', '-q', '-b', 'main', cwd=root)
            run('git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                'commit', '-q', '--allow-empty', '-m', 'initial', cwd=root)
            detector = str(SCRIPTS / 'detect-branch-model.sh')
            run('git', 'update-ref', 'refs/remotes/origin/main', 'HEAD', cwd=root)
            run('git', 'update-ref', 'refs/remotes/origin/master', 'HEAD', cwd=root)
            result = subprocess.run([detector], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('both exist', result.stderr)
            run('git', 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main', cwd=root)
            self.assertEqual(run(detector, cwd=root), 'flow=github\ntrunk=main\n')
            run('git', 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/master', cwd=root)
            self.assertEqual(run(detector, cwd=root), 'flow=github\ntrunk=master\n')
            run('git', 'config', 'gitflow.branch.develop', 'develop', cwd=root)
            result = subprocess.run([detector], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('origin/develop is missing', result.stderr)
            run('git', 'update-ref', 'refs/remotes/origin/develop', 'HEAD', cwd=root)
            self.assertEqual(run(detector, cwd=root), 'flow=gitflow\ntrunk=develop\n')

    def test_default_branch_name_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run('git', 'init', '-q', '-b', 'main', cwd=root)
            run('git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                'commit', '-q', '--allow-empty', '-m', 'initial', cwd=root)
            branch = 'main;touch${IFS}INJECTED'
            run('git', 'update-ref', f'refs/remotes/origin/{branch}', 'HEAD', cwd=root)
            run('git', 'symbolic-ref', 'refs/remotes/origin/HEAD', f'refs/remotes/origin/{branch}', cwd=root)
            output = run(str(SCRIPTS / 'new-worktree-setup.sh'), 'codex', 'feature/safe', cwd=root)
            self.assertIn(f'base_ref=origin/{branch}\n', output)
            self.assertIn('status=ok', output)
            self.assertFalse((root / 'INJECTED').exists())

    def test_install_tool_detection_from_lockfiles(self):
        cases = [
            ({'uv.lock': '', 'pyproject.toml': '[project]\nname = "x"\n'}, 'uv', 'uv sync', 0),
            ({'uv.lock': '', 'pyproject.toml': '[project]\nname = "x"\n'}, 'uv', 'uv sync', 1),
            ({'bun.lock': '{}'}, 'bun', 'bun install', 0),
        ]
        for files, tool, command, code in cases:
            with self.subTest(tool=tool, code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'repo'
                stubs = Path(directory) / 'bin'
                root.mkdir()
                stubs.mkdir()
                calls = Path(directory) / 'calls'
                stub = stubs / tool
                stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{calls}"\nexit {code}\n')
                stub.chmod(0o755)
                for name, content in files.items():
                    (root / name).write_text(content)
                run('git', 'init', '-q', '-b', 'main', cwd=root)
                run('git', 'add', '.', cwd=root)
                run('git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                    'commit', '-q', '-m', 'initial', cwd=root)
                env = {**os.environ, 'PATH': f'{stubs}:{os.environ["PATH"]}'}
                output = run(str(SCRIPTS / 'new-worktree-setup.sh'), 'codex', 'feature/x', 'main',
                             cwd=root, env=env)
                status = 'fail' if code else 'ok'
                self.assertIn(f'install_tool={tool}\ninstall_status={status}\n', output)
                self.assertEqual(calls.read_text(), f'{command}\n')
                self.assertFalse((root / '.codex/worktrees/feature-x/.venv').exists())

    def test_pyproject_venv_interpreter_and_install_failure(self):
        for scenario in ('uv', 'missing_pin', 'dev_failure', 'quoted_dev'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'repo'
                stubs = Path(directory) / 'bin'
                root.mkdir()
                stubs.mkdir()
                calls = Path(directory) / 'calls'
                (stubs / 'bash').symlink_to(shutil.which('bash'))
                (root / 'pyproject.toml').write_text(
                    '[project]\nname = "x"\n[project.optional-dependencies]\n'
                    + ('"dev"' if scenario == 'quoted_dev' else 'dev') + ' = []\n'
                )
                (root / '.python-version').write_text('3.12\n')
                run('git', 'init', '-q', '-b', 'main', cwd=root)
                run('git', 'add', '.', cwd=root)
                run('git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                    'commit', '-q', '-m', 'initial', cwd=root)
                python_stub = stubs / 'python3'
                python_stub.write_text(f'#!/bin/sh\necho python3 >> "{calls}"\nexit 1\n')
                python_stub.chmod(0o755)
                if scenario != 'missing_pin':
                    uv = stubs / 'uv'
                    uv.write_text(
                        f'#!/bin/sh\necho "uv $*" >> "{calls}"\nmkdir -p .venv/bin\n'
                        f"printf '#!/bin/sh\\nif [ \"$1\" = --version ]; then echo Python 3.12.13; exit 0; fi\\n"
                        f"echo \"pip $*\" >> \"{calls}\"\\nexit {1 if scenario == 'dev_failure' else 0}\\n' > .venv/bin/python\n"
                        'chmod +x .venv/bin/python\n'
                    )
                    uv.chmod(0o755)
                env = {**os.environ, 'PATH': f'{stubs}:/usr/bin:/bin:/usr/sbin:/sbin'}
                output = run(str(SCRIPTS / 'new-worktree-setup.sh'), 'codex', 'feature/x', 'main',
                             cwd=root, env=env)
                self.assertIn('install_tool=venv\n', output)
                if scenario == 'missing_pin':
                    self.assertIn('install_status=fail\n', output)
                    self.assertFalse(calls.exists())
                    log = Path(next(line.split('=', 1)[1] for line in output.splitlines()
                                    if line.startswith('install_log=')))
                    self.assertIn('python3.12', log.read_text())
                else:
                    self.assertIn('install_python=Python 3.12.13\n', output)
                    self.assertIn(f'install_status={"fail" if scenario == "dev_failure" else "ok"}\n', output)
                    self.assertEqual(calls.read_text().splitlines(),
                                     ['uv venv --seed .venv', 'pip -m pip install -e .[dev]'])

    def test_cleanup_scans_both_locations_and_skips_shared_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            run('git', 'init', '-q', cwd=root)
            script_dir = Path(directory) / 'scripts'
            script_dir.mkdir()
            script = script_dir / 'cleanup-session.sh'
            script.write_bytes((SCRIPTS / 'cleanup-session.sh').read_bytes())
            script.chmod(0o755)
            stub = script_dir / 'clean-repos.sh'
            stub.write_text('#!/bin/sh\nexit 0\n')
            stub.chmod(0o755)
            docker = script_dir / 'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\n" "$*" >> "$DOCKER_LOG"\nif [ "$1" = ps ] && [ "$2" = -a ]; then\n'
                              '  printf "feature-one\\t%s/.codex/worktrees/feature-one\\n" "$TEST_REPO"\n'
                              '  printf "feature-two\\t%s/.claude/worktrees/feature-two\\n" "$TEST_REPO"\n'
                              '  printf "shared\\t%s/.codex/worktrees/feature-one\\n" "$TEST_REPO"\n'
                              'fi\n')
            docker.chmod(0o755)
            env = dict(os.environ, PATH=f'{script_dir}:{os.environ["PATH"]}', TEST_REPO=str(root.resolve()), DOCKER_LOG=str(Path(directory) / 'docker.log'))
            output = run(str(script), 'scan', cwd=root, env=env)
            self.assertIn('compose-project=feature-one dir=gone', output)
            self.assertIn('compose-project=feature-two dir=gone', output)
            self.assertIn('compose-project=shared skipped=shared', output)
            (root / '.codex/worktrees/feature-one').mkdir(parents=True)
            docker.write_text(docker.read_text().replace('feature-one\\n', 'feature-one/missing\\n'))
            run(str(script), 'apply', cwd=root, env=env)
            self.assertNotIn('compose -p feature-one down', (Path(directory) / 'docker.log').read_text())


if __name__ == '__main__':
    unittest.main()
