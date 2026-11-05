import os
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
            (root / 'CONTRIBUTING.md').write_text('GitHub Flow: No develop or long-lived release branches.\n')
            (root / 'AGENTS.md').write_text('Detect strict Gitflow vs GitHub flow.\n')
            output = run(str(SCRIPTS / 'detect-branch-model.sh'), cwd=root)
            self.assertEqual(output, 'flow=github\ntrunk=main\n')
            output = run(str(SCRIPTS / 'new-worktree-setup.sh'), 'codex', 'feature/test', cwd=root)
            self.assertIn('flow=github\ntrunk=main\n', output)
            self.assertIn('status=ok', output)
            linked = root / '.codex/worktrees/feature-test'
            relative_script = os.path.relpath(SCRIPTS / 'new-worktree-setup.sh', linked.resolve())
            output = run(relative_script, 'claude', 'feature/relative', cwd=linked)
            self.assertIn('status=ok', output)
            run('git', 'update-ref', 'refs/remotes/origin/develop', 'HEAD', cwd=root)
            self.assertEqual(run(str(SCRIPTS / 'detect-branch-model.sh'), cwd=root),
                             'flow=gitflow\ntrunk=develop\n')

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
