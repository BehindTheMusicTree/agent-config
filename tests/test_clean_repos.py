import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'clean-repos.sh'

FAKE_GH = """#!/usr/bin/env bash
case "$1 $2" in
  "repo view") exit 0 ;;
  "pr list")
    if [[ "$*" == *"--state open"* ]]; then
      [[ -n "${GH_OPEN_FAIL:-}" ]] && exit 1
      printf '%s' "${GH_OPEN_BRANCHES:-}"
    fi
    exit 0 ;;
esac
exit 0
"""


def bash_major():
    bash = shutil.which('bash')
    if not bash:
        return 0
    out = subprocess.run([bash, '-c', 'echo ${BASH_VERSINFO[0]}'], text=True, capture_output=True)
    return int(out.stdout.strip() or 0)


def git(cwd, *args):
    result = subprocess.run(
        ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', *args],
        cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'git {args}: {result.stdout}\n{result.stderr}')
    return result.stdout


@unittest.skipIf(bash_major() < 4, 'clean-repos.sh needs Bash 4+ (mapfile)')
class CleanReposTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root = base / 'git'
        self.repo = self.root / 'repo'
        self.origin = base / 'origin.git'
        self.bin = base / 'bin'
        self.root.mkdir()
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        git(base, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        git(base, 'clone', '-q', str(self.origin), str(self.repo))
        git(self.repo, 'checkout', '-q', '-b', 'main')
        (self.repo / 'README.md').write_text('hello\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'initial')
        git(self.repo, 'push', '-q', '-u', 'origin', 'main')
        self.procs = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()

    def add_worktree(self, branch, merged):
        path = self.repo / '.claude' / 'worktrees' / branch.replace('/', '-')
        git(self.repo, 'worktree', 'add', '-q', '-b', branch, str(path), 'main')
        (path / 'work.txt').write_text(f'{branch}\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', f'work on {branch}')
        if merged:
            git(self.repo, 'merge', '-q', '--ff-only', branch)
            git(self.repo, 'push', '-q', 'origin', 'main')
            git(self.repo, 'push', '-q', 'origin', branch)
        return path

    def add_empty_worktree(self, branch, days_old):
        path = self.repo / '.claude' / 'worktrees' / branch.replace('/', '-')
        stamp = f'{int(time.time()) - days_old * 86400} +0000'
        subprocess.run(
            ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
             'worktree', 'add', '-q', '-b', branch, str(path), 'main'],
            cwd=self.repo, check=True, capture_output=True, env={**os.environ, 'GIT_COMMITTER_DATE': stamp})
        return path

    def branch_exists(self, branch):
        return bool(git(self.repo, 'branch', '--list', branch).strip())

    def test_recent_empty_worktree_is_kept(self):
        path = self.add_empty_worktree('feature/fresh', days_old=1)
        self.assertIn('worktrees-new-empty', self.run_script('scan'))
        output = self.run_script('apply')
        self.assertNotIn('feature/fresh', output)
        self.assertTrue(path.exists())
        self.assertTrue(self.branch_exists('feature/fresh'))

    def test_stale_idle_empty_worktree_is_removed_with_its_branch(self):
        path = self.add_empty_worktree('feature/stale', days_old=30)
        scan = self.run_script('scan')
        self.assertIn('worktrees-stale-empty (never committed to, branch older than 7d', scan)
        self.assertIn(f'{path}:feature/stale', scan)
        self.assertNotIn('worktrees-new-empty', scan)
        output = self.run_script('apply')
        self.assertIn(f'removed-worktree={path} reason=stale-empty', output)
        self.assertIn('deleted-local=feature/stale reason=stale-empty', output)
        self.assertFalse(path.exists())
        self.assertFalse(self.branch_exists('feature/stale'))

    def test_stale_empty_worktree_in_use_is_kept_and_not_killed(self):
        path = self.add_empty_worktree('feature/busy', days_old=30)
        proc = self.start_process(path)
        scan = self.run_script('scan')
        self.assertIn('worktrees-new-empty', scan)
        self.assertNotIn('worktrees-stale-empty', scan)
        self.run_script('apply')
        self.assertIsNone(proc.poll())
        self.assertTrue(path.exists())
        self.assertTrue(self.branch_exists('feature/busy'))

    def test_dirty_stale_empty_worktree_is_kept(self):
        path = self.add_empty_worktree('feature/scratch', days_old=30)
        (path / 'notes.txt').write_text('draft\n')
        self.assertNotIn('worktrees-stale-empty', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue((path / 'notes.txt').exists())

    def test_stale_empty_days_option_sets_the_threshold(self):
        self.add_empty_worktree('feature/week', days_old=3)
        self.assertIn('worktrees-new-empty', self.run_script('scan'))
        self.assertIn('worktrees-stale-empty', self.run_script('scan', '--stale-empty-days', '2'))

    def test_stale_empty_worktree_with_only_ignored_files_is_removed(self):
        path = self.add_empty_worktree('feature/ignored', days_old=30)
        (self.repo / '.git' / 'info' / 'exclude').write_text('*.env\n')
        (path / 'local.env').write_text('X=1\n')
        self.assertIn('worktrees-stale-empty', self.run_script('scan'))
        self.run_script('apply')
        self.assertFalse(path.exists())

    def test_stale_empty_worktree_is_kept_when_lsof_fails(self):
        path = self.add_empty_worktree('feature/nolsof', days_old=30)
        lsof = self.bin / 'lsof'
        lsof.write_text('#!/usr/bin/env bash\necho "lsof: WARNING: cannot stat" >&2\nexit 1\n')
        lsof.chmod(0o755)
        scan = self.run_script('scan')
        self.assertNotIn('worktrees-stale-empty', scan)
        self.run_script('apply')
        self.assertTrue(path.exists())

    def test_stale_empty_worktree_dirtied_after_scan_is_kept_at_apply(self):
        path = self.add_empty_worktree('feature/changed', days_old=30)
        self.assertIn('worktrees-stale-empty', self.run_script('scan'))
        (path / 'late.txt').write_text('x\n')
        output = self.run_script('apply')
        self.assertTrue(path.exists())
        self.assertNotIn('removed-worktree=', output)

    def remote_has(self, branch):
        return bool(git(self.repo, 'ls-remote', '--heads', 'origin', branch).strip())

    def run_script(self, mode, *args, **env):
        full_env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', **env}
        result = subprocess.run(
            [shutil.which('bash'), str(SCRIPT), mode, str(self.root), *args],
            env=full_env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def start_process(self, path):
        # The trailing `; true` stops bash from exec-ing sleep, which would drop the path from argv.
        proc = subprocess.Popen(
            ['bash', '-c', 'sleep 300; true', 'worktree-process', str(path)],
            start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.3)
        return proc

    def test_kills_only_processes_of_the_exact_worktree(self):
        target = self.add_worktree('feature/a', merged=True)
        sibling = self.add_worktree('feature/ab', merged=False)
        target_proc = self.start_process(target)
        sibling_proc = self.start_process(sibling)

        scan = self.run_script('scan')
        self.assertIn(f'running-processes (will be killed on apply): {target}: {target_proc.pid} \n', scan)
        self.assertNotIn(str(sibling_proc.pid), scan)

        output = self.run_script('apply')
        self.assertIn(f'killed-processes={target}', output)
        self.assertIn('deleted-local=feature/a', output)
        self.assertIsNotNone(target_proc.wait(timeout=10))
        self.assertIsNone(sibling_proc.poll())
        self.assertTrue(sibling.exists())

    def test_reports_no_processes_for_an_idle_worktree(self):
        self.add_worktree('feature/a', merged=True)
        scan = self.run_script('scan')
        self.assertIn('worktrees:', scan)
        self.assertNotIn('running-processes', scan)
        self.assertNotIn('killed-processes', self.run_script('apply'))

    def test_deletes_merged_remote_branch_when_open_prs_are_known(self):
        self.add_worktree('feature/a', merged=True)
        output = self.run_script('apply', GH_OPEN_BRANCHES='')
        self.assertIn('deleted-remote=feature/a', output)
        self.assertFalse(self.remote_has('feature/a'))

    def test_keeps_remote_branches_when_open_pr_lookup_fails(self):
        self.add_worktree('feature/a', merged=True)

        scan = self.run_script('scan', GH_OPEN_FAIL='1')
        self.assertIn('open-prs-unknown', scan)
        self.assertNotIn('remote: feature/a', scan)

        output = self.run_script('apply', GH_OPEN_FAIL='1')
        self.assertIn('skip-remote-all reason=open-prs-unknown', output)
        self.assertTrue(self.remote_has('feature/a'))
        self.assertIn('deleted-local=feature/a', output)

    def test_keeps_remote_branch_with_open_pr(self):
        self.add_worktree('feature/a', merged=True)
        output = self.run_script('apply', GH_OPEN_BRANCHES='feature/a')
        self.assertNotIn('deleted-remote=feature/a', output)
        self.assertTrue(self.remote_has('feature/a'))

    def test_dirty_worktree_reports_counts_and_untracked_files_and_is_kept(self):
        path = self.add_worktree('feature/d', merged=True)
        (path / 'work.txt').write_text('edited\n')
        (path / 'notes.md').write_text('notes\n')

        scan = self.run_script('scan')
        self.assertIn('dirty-worktree', scan)
        self.assertIn('[tracked=1 untracked=1: notes.md]', scan)

        output = self.run_script('apply')
        self.assertIn('reason=uncommitted-changes', output)
        self.assertTrue(path.exists())
        self.assertIn('feature/d', git(self.repo, 'branch', '--list', 'feature/d'))

    def test_ignored_plan_protects_worktree_and_branch(self):
        path = self.add_worktree('feature/plans', merged=True)
        plans = path / '.agent-plans'
        plans.mkdir()
        (plans / '.gitignore').write_text('*\n!.gitignore\n')
        git(path, 'add', '-f', '.agent-plans/.gitignore')
        git(path, 'commit', '-qm', 'add plan directory')
        git(self.repo, 'merge', '-q', '--ff-only', 'feature/plans')
        git(self.repo, 'push', '-q', 'origin', 'main')
        (plans / 'regional-multiparentality.md').write_text('plan\n')
        self.assertEqual(git(path, 'status', '--porcelain'), '')
        scan = self.run_script('scan')
        self.assertIn('dirty-worktree', scan)
        self.assertIn('plans=1: regional-multiparentality.md', scan)
        output = self.run_script('apply')
        self.assertIn('reason=agent-plans-present', output)
        self.assertTrue((plans / 'regional-multiparentality.md').exists())
        self.assertIn('feature/plans', git(self.repo, 'branch', '--list', 'feature/plans'))
        (plans / 'regional-multiparentality.md').unlink()
        output = self.run_script('apply')
        self.assertIn(f'removed-worktree={path}', output)

    def test_nested_plan_protects_worktree(self):
        path = self.add_worktree('feature/nested-plans', merged=True)
        plans = path / 'nested' / '.agent-plans'
        plans.mkdir(parents=True)
        (plans / 'topic.md').write_text('plan\n')
        self.assertIn('reason=agent-plans-present', self.run_script('apply'))
        self.assertTrue((plans / 'topic.md').exists())

    def test_plan_directory_symlink_is_protected(self):
        path = self.add_worktree('feature/symlink', merged=True)
        (path / '.agent-plans').symlink_to(path / 'missing', target_is_directory=True)
        self.assertIn('reason=agent-plans-present', self.run_script('apply'))
        self.assertTrue(path.exists())

    def test_deletions_only_worktree_is_labelled_and_still_protected(self):
        path = self.add_worktree('feature/d', merged=True)
        (path / 'work.txt').unlink()

        scan = self.run_script('scan')
        self.assertIn('[tracked=1 (deletions only) untracked=0]', scan)

        output = self.run_script('apply')
        self.assertIn('reason=uncommitted-changes', output)
        self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
