import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'clean-repos.sh'
WRAPPER = SCRIPT.with_name('cleanup-session.sh')

FAKE_GH = """#!/usr/bin/env bash
case "$1 $2" in
  "repo view") exit 0 ;;
  "pr view") printf '%s' "${GH_PR_VIEW:-}"; [[ -n "${GH_PR_VIEW_FAIL:-}" ]] && exit 1; exit 0 ;;
  "pr list")
    if [[ "$*" == *"--state open"* ]]; then
      [[ -n "${GH_OPEN_FAIL:-}" ]] && exit 1
      printf '%s' "${GH_OPEN_BRANCHES:-}"
      [[ -n "${GH_OPEN_PRS:-}" ]] && printf '%s\n' "$GH_OPEN_PRS"
    elif [[ "$*" == *"--state merged"* ]]; then
      [[ -n "${GH_MERGED_PRS:-}" ]] && printf '%s\n' "$GH_MERGED_PRS"
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
        # The installer's global exclude hides scratch dirs locally but not in CI; mirror it.
        exclude = self.repo / '.git' / 'info' / 'exclude'
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text('.agent-tmp/\n')
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

    def add_worktree(self, branch, merged, slug=None):
        path = self.repo / '.claude' / 'worktrees' / (slug or branch.replace('/', '-'))
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
        path = self.add_empty_worktree('feature/fresh', days_old=0)
        self.assertIn('worktrees-new-empty', self.run_script('scan'))
        output = self.run_script('apply')
        self.assertNotIn('feature/fresh', output)
        self.assertTrue(path.exists())
        self.assertTrue(self.branch_exists('feature/fresh'))

    def test_stale_idle_empty_worktree_is_removed_with_its_branch(self):
        path = self.add_empty_worktree('feature/stale', days_old=30)
        scan = self.run_script('scan')
        self.assertIn('worktrees-stale-empty (never committed to, branch older than 1d', scan)
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
        self.assertIn('worktrees-stale-empty', self.run_script('scan'))
        self.assertIn('worktrees-new-empty', self.run_script('scan', '--stale-empty-days', '5'))

    def test_stale_empty_days_option_accepts_leading_zeros(self):
        self.add_empty_worktree('feature/month', days_old=30)
        self.assertIn('worktrees-stale-empty', self.run_script('scan', '--stale-empty-days', '08'))

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
        self.assertIn(f'running-processes (will be killed on apply): {target}: {target_proc.pid}:bash \n', scan)
        self.assertNotIn(str(sibling_proc.pid), scan)

        output = self.run_script('apply')
        self.assertIn(f'killed-processes={target}', output)
        self.assertIn('deleted-local=feature/a', output)
        self.assertIsNotNone(target_proc.wait(timeout=10))
        self.assertIsNone(sibling_proc.poll())
        self.assertTrue(sibling.exists())

    def agent_stub(self, name):
        stub = self.bin / name
        stub.write_text('#!/usr/bin/env bash\nif [[ "${1:-}" == "--cd" ]]; then shift 2; fi\nif [[ "${1:-}" == "--run" ]]; then shift; "$@"; exit $?; fi\nsleep 300; true\n')
        stub.chmod(0o755)
        return stub

    def start_agent(self, name, cwd, *args):
        proc = subprocess.Popen([str(self.agent_stub(name)), *args], cwd=cwd, start_new_session=True)
        self.procs.append(proc)
        time.sleep(0.3)
        return proc

    def assert_session_kept(self, path, branch, proc):
        scan = self.run_script('scan')
        self.assertIn('agent-session', scan)
        self.assertIn(f'{path}:{branch}', scan)
        self.assertNotIn('running-processes', scan)
        self.assertNotIn('unmerged-worktree (', scan)
        output = self.run_script('apply', GH_OPEN_BRANCHES='')
        self.assertIn(f'keep-worktree={path} branch={branch} reason=agent-session', output)
        self.assertNotIn('reason=unmerged-worktree', output)
        self.assertNotIn('killed-processes', output)
        self.assertIsNone(proc.poll())
        self.assertTrue(path.exists())
        self.assertTrue(self.branch_exists(branch))
        self.assertTrue(self.remote_has(branch))

    def test_keeps_worktree_of_claude_started_from_its_cwd(self):
        path = self.add_worktree('feature/a', merged=True)
        self.assert_session_kept(path, 'feature/a', self.start_agent('claude', path))

    def test_keeps_worktree_of_codex_with_path_in_argv(self):
        path = self.add_worktree('feature/a', merged=True)
        self.assert_session_kept(path, 'feature/a', self.start_agent('codex', self.root, '--cd', str(path)))

    def test_keeps_worktree_whose_process_descends_from_an_agent(self):
        path = self.add_worktree('feature/a', merged=True)
        proc = self.start_agent('claude', self.root, '--run', 'bash', '-c', 'sleep 300; true', 'child', str(path))
        self.assert_session_kept(path, 'feature/a', proc)

    def test_cwd_only_caller_can_opt_in_to_removal(self):
        path = self.add_worktree('feature/a', merged=True)
        stub = self.agent_stub('claude')
        result = subprocess.run(
            [str(stub), '--run', shutil.which('bash'), str(SCRIPT), 'apply', str(self.root), '--remove-caller-worktree'],
            cwd=path, text=True, capture_output=True,
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'GH_OPEN_BRANCHES': ''})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'removed-worktree={path}', result.stdout)
        self.assertFalse(path.exists())

    def run_as_codex(self, path, mode, *flags, via_wrapper=True, cwd=None):
        cmd = [str(WRAPPER), mode, '--no-docker'] if via_wrapper else [str(SCRIPT), mode, str(self.root)]
        proc = subprocess.Popen(
            ['bash', '-c', '"$@"; result=$?; echo ancestor-returned; exit "$result"', str(path),
             str(self.agent_stub('codex')), '--cd', str(path), '--run', 'bash', '-c',
             'echo "caller=$PPID"; ps -ww -o command= -p "$PPID"; "$@"; result=$?; echo caller-returned; exit "$result"',
             'tool-shell', *cmd, *flags],
            cwd=cwd or path, start_new_session=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'GH_OPEN_BRANCHES': ''},
        )
        self.procs.append(proc)
        stdout, stderr = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, stdout + stderr)
        self.assertIn(f"{self.bin / 'codex'} --cd {path}", stdout)
        self.assertIn('caller-returned', stdout)
        self.assertIn('ancestor-returned', stdout)
        if via_wrapper:
            self.assertIn('skipped: --no-docker', stdout)
        return stdout

    def test_wrapper_keeps_caller_worktree_by_default(self):
        branch = 'feature/caller'
        path = self.add_worktree(branch, merged=True)
        recap = self.handoff('repo-feature-caller')
        plans = self.plans('repo-feature-caller')
        other = self.add_worktree('feature/other', merged=True)
        for mode in ('scan', 'apply'):
            output = self.run_as_codex(path, mode)
            self.assertIn('caller-worktree', output)
            self.assertNotIn('running-processes', output)
            self.assertNotIn('stale-handoff', output)
            self.assertTrue(path.exists())
            self.assertTrue(self.branch_exists(branch))
            self.assertTrue(self.remote_has(branch))
            self.assertTrue(recap.exists())
            self.assertTrue(plans.exists())
        self.assertFalse(other.exists())

    def test_caller_with_only_an_argv_match_keeps_remote(self):
        branch = 'feature/caller'
        path = self.add_worktree(branch, merged=True)
        output = self.run_as_codex(path, 'apply', '--remote-only', via_wrapper=False, cwd=self.root)
        self.assertIn('reason=caller-worktree', output)
        self.assertTrue(self.remote_has(branch))

    def test_primary_checkout_keeps_active_callers_remote(self):
        branch = 'feature/caller'
        linked = self.add_worktree(branch, merged=True)
        git(self.repo, 'worktree', 'remove', str(linked))
        git(self.repo, 'switch', branch)
        output = self.run_as_codex(self.repo, 'apply', '--remote-only')
        self.assertIn('reason=caller-worktree', output)
        self.assertTrue(self.remote_has(branch))

    def test_nested_caller_keeps_only_its_own_remote(self):
        primary_branch = 'feature/primary'
        caller_branch = 'feature/caller'
        primary_linked = self.add_worktree(primary_branch, merged=True)
        caller = self.add_worktree(caller_branch, merged=True)
        git(self.repo, 'worktree', 'remove', str(primary_linked))
        git(self.repo, 'switch', primary_branch)
        output = self.run_as_codex(caller, 'apply', '--remote-only')
        self.assertIn(f'keep-worktree={caller} branch={caller_branch} reason=caller-worktree', output)
        self.assertIn(f'deleted-remote={primary_branch}', output)
        self.assertFalse(self.remote_has(primary_branch))
        self.assertTrue(self.remote_has(caller_branch))

    def test_new_cwd_only_agent_during_remote_recheck_keeps_branch(self):
        branch = 'feature/late'
        path = self.add_worktree(branch, merged=True)
        trigger = self.bin / 'trigger'
        ready = self.bin / 'ready'
        stub = self.bin / 'codex'
        stub.write_text(f'#!/usr/bin/env bash\ntouch "{ready}"\nsleep 300; true\n')
        stub.chmod(0o755)
        launcher = self.bin / 'launch-late-agent'
        launcher.write_text(
            f'#!/usr/bin/env bash\n'
            f'until [[ -e "{trigger}" ]]; do sleep 0.05; done\n'
            f'cd "{path}" && "{stub}"\n'
        )
        launcher.chmod(0o755)
        proc = subprocess.Popen([str(launcher)], cwd=self.root, start_new_session=True)
        self.procs.append(proc)
        first_probe = self.bin / 'first-probe'
        real_lsof = shutil.which('lsof')
        self.assertIsNotNone(real_lsof)
        shim = self.bin / 'lsof'
        shim.write_text(
            f'#!/usr/bin/env bash\n'
            f'if [[ ! -e "{first_probe}" ]]; then\n'
            f'  touch "{first_probe}"; exec "{real_lsof}" "$@"\n'
            f'fi\n'
            f'snapshot="$("{real_lsof}" "$@")" || exit\n'
            f'touch "{trigger}"\n'
            f'for _ in {{1..100}}; do\n'
            f'  if [[ -e "{ready}" ]]; then printf \'%s\\n\' "$snapshot"; exit; fi\n'
            f'  sleep 0.05\n'
            f'done\n'
            f'exit 2\n'
        )
        shim.chmod(0o755)
        output = self.run_script('apply', '--remote-only')
        self.assertTrue(ready.exists())
        self.assertIn(f'skip-remote={branch} reason=agent-session', output)
        self.assertTrue(self.remote_has(branch))
        self.assertIsNone(proc.poll())

    def test_removes_merged_worktree_with_colon_in_path(self):
        branch = 'feature/colon'
        path = self.add_worktree(branch, merged=True, slug='feature:colon')
        self.assertIn(f'worktrees: {path}:{branch}', self.run_script('scan'))
        self.assertIn(f'removed-worktree={path}', self.run_script('apply'))
        self.assertFalse(path.exists())

    def test_rechecks_new_checkout_before_remote_deletion(self):
        branch = 'feature/late'
        path = self.add_worktree(branch, merged=True)
        git(self.repo, 'worktree', 'remove', str(path))
        agent = self.start_agent('codex', self.root, '--cd', str(path))
        real_git = shutil.which('git')
        shim = self.bin / 'git'
        shim.write_text(
            f'#!/usr/bin/env bash\n'
            f'if [[ "$1 $2" == "worktree list" && ! -d "{path}" ]]; then\n'
            f'  "{real_git}" "$@" || exit\n'
            f'  exec "{real_git}" worktree add -q "{path}" "{branch}"\n'
            f'fi\n'
            f'exec "{real_git}" "$@"\n'
        )
        shim.chmod(0o755)
        output = self.run_script('apply', '--remote-only')
        self.assertIn(f'skip-remote={branch} reason=agent-session', output)
        self.assertIsNone(agent.poll())
        self.assert_worktree_kept(path, branch)
        self.assertTrue(self.remote_has(branch))

    def start_term_worker(self, path, *on_term):
        marker = self.bin / 'received-term'
        code = (
            'import pathlib, signal, subprocess, sys, time\n'
            'def handle_term(signum, frame):\n'
            '    if sys.argv[3:]:\n'
            '        subprocess.Popen(sys.argv[3:])\n'
            '    pathlib.Path(sys.argv[2]).touch()\n'
            'signal.signal(signal.SIGTERM, handle_term)\n'
            'print("ready", flush=True)\n'
            'time.sleep(300)\n'
        )
        proc = subprocess.Popen(
            [sys.executable, '-c', code, str(path), str(marker), *on_term],
            cwd=self.root, start_new_session=True, stdout=subprocess.PIPE, text=True,
        )
        self.procs.append(proc)
        with proc.stdout:
            self.assertEqual(proc.stdout.readline().strip(), 'ready')
        return proc, marker

    def test_wrapper_opt_in_signals_worker_but_preserves_caller_and_ancestors(self):
        branch = 'feature/caller'
        path = self.add_worktree(branch, merged=True)
        worker, marker = self.start_term_worker(path)
        flags = ['--remove-caller-worktree']
        scan = self.run_as_codex(path, 'scan', *flags)
        caller = scan.split('caller=', 1)[1].splitlines()[0]
        processes = [line for line in scan.splitlines() if 'running-processes' in line]
        self.assertEqual(len(processes), 1, scan)
        self.assertEqual(processes[0].split(f'{path}: ', 1)[1].split()[0].split(':')[0], str(worker.pid))
        self.assertEqual(len(processes[0].split(f'{path}: ', 1)[1].split()), 1, scan)
        self.assertNotIn(f'{caller}:', processes[0])
        output = self.run_as_codex(path, 'apply', *flags)
        self.assertIn(f'killed-processes={path}', output)
        self.assertTrue(marker.exists())
        self.assertEqual(worker.wait(timeout=10), -signal.SIGKILL)
        self.assertFalse(path.exists())
        self.assertFalse(self.branch_exists(branch))
        self.assertFalse(self.remote_has(branch))

    def test_opt_in_preserves_exclusions_and_independent_agents(self):
        branch = 'feature/caller'
        path = self.add_worktree(branch, merged=True)
        flags = ['--remove-caller-worktree']
        self.run_as_codex(path, 'apply', *flags, '--exclude', str(path))
        self.assertTrue(path.exists())
        agent = self.start_agent('claude', path)
        output = self.run_as_codex(path, 'apply', *flags)
        self.assertIn('reason=agent-session', output)
        self.assertNotIn('killed-processes', output)
        self.assertIsNone(agent.poll())
        self.assert_worktree_kept(path, branch)
        self.assertTrue(self.remote_has(branch))

    def test_late_agent_prevents_kill_and_branch_deletion(self):
        branch = 'feature/late'
        path = self.add_worktree(branch, merged=True)
        recap = self.handoff('repo-feature-late')
        plans = self.plans('repo-feature-late')
        # The child agent stays outside the argv path until TERM launches it.
        launcher = self.bin / 'launch-agent'
        launcher.write_text(
            f'#!/usr/bin/env bash\ncd "{path}"\nexec "{self.agent_stub("codex")}"\n'
        )
        launcher.chmod(0o755)
        worker, marker = self.start_term_worker(path, str(launcher))
        output = self.run_script('apply')
        self.assertTrue(marker.exists())
        self.assertIn(f'skip-worktree={path} branch={branch} reason=agent-session', output)
        self.assertIsNone(worker.poll())
        self.assert_worktree_kept(path, branch)
        self.assertTrue(self.remote_has(branch))
        self.assertTrue(recap.exists())
        self.assertTrue(plans.exists())

    def test_new_leftover_during_grace_period_is_not_sent_kill(self):
        branch = 'feature/late'
        path = self.add_worktree(branch, merged=True)
        launcher = self.bin / 'launch-leftover'
        child_pid = self.bin / 'child-pid'
        launcher.write_text(
            f'#!/usr/bin/env bash\n'
            f'bash -c \'echo $$ > "$2"; sleep 300; true\' worker "{path}" "{child_pid}"\n'
        )
        launcher.chmod(0o755)
        worker, marker = self.start_term_worker(path, str(launcher))
        output = self.run_script('apply')
        self.assertTrue(marker.exists())
        self.assertIn(f'skip-worktree={path} branch={branch} reason=processes-changed', output)
        self.assertIsNone(worker.poll())
        os.kill(int(child_pid.read_text()), 0)
        self.assert_worktree_kept(path, branch)
        self.assertTrue(self.remote_has(branch))

    def test_cwd_discovery_failure_during_grace_period_preserves_refs(self):
        branch = 'feature/late'
        path = self.add_worktree(branch, merged=True)
        worker, marker = self.start_term_worker(path)
        real_lsof = shutil.which('lsof')
        self.assertIsNotNone(real_lsof)
        lsof = self.bin / 'lsof'
        lsof.write_text(
            f'#!/usr/bin/env bash\n'
            f'if [[ -f "{marker}" ]]; then echo "test: cwd discovery failed" >&2; exit 1; fi\n'
            f'exec "{real_lsof}" "$@"\n'
        )
        lsof.chmod(0o755)
        output = self.run_script('apply')
        self.assertTrue(marker.exists())
        self.assertIn(f'skip-worktree={path} branch={branch} reason=agent-session', output)
        self.assertIsNone(worker.poll())
        self.assert_worktree_kept(path, branch)
        self.assertTrue(self.remote_has(branch))

    def test_keeps_worktree_when_ps_fails(self):
        path = self.add_worktree('feature/a', merged=True)
        ps = self.bin / 'ps'
        ps.write_text('#!/usr/bin/env bash\nexit 1\n')
        ps.chmod(0o755)
        output = self.run_script('apply', GH_OPEN_BRANCHES='')
        self.assertIn('reason=agent-session', output)
        self.assertTrue(path.exists())
        self.assertTrue(self.remote_has('feature/a'))

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

    def add_cherry_picked(self, branch='feature/c'):
        path = self.add_worktree(branch, merged=False)
        self.commit_on_main('trunk moves on', 'moved.txt')
        git(self.repo, 'cherry-pick', branch)
        git(self.repo, 'push', '-q', 'origin', 'main')
        return path

    def test_equivalent_worktree_needs_the_flag_to_be_removed(self):
        path = self.add_cherry_picked()
        scan = self.run_script('scan')
        self.assertIn(f'worktree-equivalent (content on trunk, removable with --remove-equivalent): {path}:feature/c', scan)
        output = self.run_script('apply')
        self.assertIn('reason=equivalent-not-enabled', output)
        self.assert_worktree_kept(path, 'feature/c')
        output = self.run_script('apply', '--remove-equivalent')
        self.assertIn(f'removed-worktree={path} reason=content-on-trunk', output)
        self.assertIn('deleted-local=feature/c reason=content-on-trunk', output)
        self.assertFalse(path.exists())
        self.assertFalse(self.branch_exists('feature/c'))

    def test_reworked_content_is_never_equivalent(self):
        path = self.add_worktree('feature/r', merged=False)
        self.commit_on_main('trunk moves on', 'moved.txt')
        git(self.repo, 'cherry-pick', 'feature/r')
        (path / 'work.txt').write_text('reworked after the pick\n')
        git(path, 'commit', '-qam', 'rework')
        git(self.repo, 'push', '-q', 'origin', 'main')
        self.assertNotIn('worktree-equivalent', self.run_script('scan'))
        self.run_script('apply', '--remove-equivalent')
        self.assert_worktree_kept(path, 'feature/r')

    def test_equivalent_worktree_with_changes_is_kept(self):
        path = self.add_cherry_picked()
        (path / 'work.txt').write_text('edited\n')
        self.run_script('apply', '--remove-equivalent')
        self.assert_worktree_kept(path, 'feature/c')

    def test_equivalent_worktree_with_open_pr_or_unknown_pr_state_is_kept(self):
        path = self.add_cherry_picked()
        self.run_script('apply', '--remove-equivalent', GH_OPEN_BRANCHES='feature/c\n')
        self.assert_worktree_kept(path, 'feature/c')
        self.run_script('apply', '--remove-equivalent', GH_OPEN_FAIL='1')
        self.assert_worktree_kept(path, 'feature/c')

    def test_equivalent_worktree_in_use_is_kept(self):
        path = self.add_cherry_picked()
        proc = self.start_process(path)
        self.run_script('apply', '--remove-equivalent')
        self.assert_worktree_kept(path, 'feature/c')
        self.assertIsNone(proc.poll())

    def test_equivalent_detached_head_is_removed_with_the_flag(self):
        path = self.repo / '.claude' / 'worktrees' / 'detached'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(path), 'main')
        (path / 'd.txt').write_text('d\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'detached work')
        sha = git(path, 'rev-parse', 'HEAD').strip()
        # Move trunk first so the cherry-pick yields a distinct commit, not the same SHA.
        (self.repo / 'other.txt').write_text('o\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'other')
        git(self.repo, 'cherry-pick', sha)
        git(self.repo, 'push', '-q', 'origin', 'main')
        self.assertIn('worktree-equivalent', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue(path.exists())
        output = self.run_script('apply', '--remove-equivalent')
        self.assertIn(f'removed-worktree={path} reason=content-on-trunk', output)

    def test_fresh_detached_head_at_trunk_is_kept(self):
        path = self.repo / '.claude' / 'worktrees' / 'fresh-detached'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(path), 'main')
        self.run_script('apply', '--remove-equivalent')
        self.assertTrue(path.exists())

    def test_long_lived_branch_worktree_at_trunk_is_kept(self):
        path = self.repo / '.claude' / 'worktrees' / 'develop-wt'
        git(self.repo, 'worktree', 'add', '-q', '-b', 'develop', str(path), 'main')
        self.run_script('apply', '--remove-equivalent')
        self.assertTrue(path.exists())
        self.assertTrue(self.branch_exists('develop'))

    def test_excluded_equivalent_worktree_is_kept_by_path_sha_and_branch(self):
        path = self.add_cherry_picked()
        for exclude in (self.unresolved(path), 'feature/c'):
            self.run_script('apply', '--remove-equivalent', '--exclude', exclude)
            self.assert_worktree_kept(path, 'feature/c')
        det = self.repo / '.claude' / 'worktrees' / 'det'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(det), 'main')
        (det / 'e.txt').write_text('e\n')
        git(det, 'add', '.')
        git(det, 'commit', '-q', '-m', 'det work')
        sha = git(det, 'rev-parse', 'HEAD').strip()
        git(self.repo, 'cherry-pick', sha)
        git(self.repo, 'push', '-q', 'origin', 'main')
        self.run_script('apply', '--remove-equivalent', '--exclude', sha)
        self.assertTrue(det.exists())

    def test_apply_output_has_no_hint(self):
        self.add_worktree('feature/s', merged=False)
        self.commit_on_main('work on feature/s (#39)', 'other.txt')
        self.assertNotIn('likely-superseded-by', self.run_script('apply', '--remove-equivalent'))

    def test_deletions_only_worktree_is_labelled_and_still_protected(self):
        path = self.add_worktree('feature/d', merged=True)
        (path / 'work.txt').unlink()

        scan = self.run_script('scan')
        self.assertIn('[tracked=1 (deletions only) untracked=0]', scan)

        output = self.run_script('apply')
        self.assertIn('reason=uncommitted-changes', output)
        self.assertTrue(path.exists())

    def commit_on_main(self, subject, filename):
        (self.repo / filename).write_text(f'{subject}\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', subject)
        git(self.repo, 'push', '-q', 'origin', 'main')

    def assert_worktree_kept(self, path, branch):
        self.assertTrue(path.exists())
        self.assertTrue(self.branch_exists(branch))

    def test_unmerged_worktree_is_reported_and_kept(self):
        path = self.add_worktree('feature/u', merged=False)
        scan = self.run_script('scan')
        self.assertIn('unmerged-worktree (not proven merged, never removed)', scan)
        self.assertIn('ahead=1 pushed=no pr=none', scan)
        output = self.run_script('apply')
        self.assertIn(f'keep-worktree={path} branch=feature/u reason=unmerged-worktree', output)
        self.assertIn('kept-unmerged=1', output)
        self.assertNotIn('skipped=1', output)
        self.assert_worktree_kept(path, 'feature/u')

    def test_unmerged_worktree_reports_push_and_pr_state(self):
        path = self.add_worktree('feature/p', merged=False)
        git(self.repo, 'push', '-q', 'origin', 'feature/p')
        git(self.repo, 'branch', '-q', '--set-upstream-to=origin/main', 'feature/p')
        scan = self.run_script('scan', GH_OPEN_PRS='feature/p\t12')
        self.assertIn('pushed=yes pr=#12', scan)
        (path / 'more.txt').write_text('more\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'local only')
        scan = self.run_script('scan', GH_OPEN_PRS='feature/p\t12')
        self.assertIn('pushed=partial:1 pr=#12', scan)

    def test_squash_under_another_name_is_hinted_and_kept(self):
        path = self.add_worktree('feature/s', merged=False)
        self.commit_on_main('work on feature/s (#39)', 'other.txt')
        scan = self.run_script('scan')
        self.assertIn('likely-superseded-by=#39', scan)
        output = self.run_script('apply')
        self.assertIn(f'keep-worktree={path} branch=feature/s reason=unmerged-worktree', output)
        self.assertNotIn('likely-superseded-by', output)
        self.assert_worktree_kept(path, 'feature/s')

    def test_merged_pr_title_gives_the_hint(self):
        self.add_worktree('feature/t', merged=False)
        sep = '\x1f'
        merged = sep.join(['elsewhere', 'a' * 40, 'b' * 40, '77', 'work on feature/t'])
        scan = self.run_script('scan', GH_MERGED_PRS=merged)
        self.assertIn('likely-superseded-by=#77', scan)

    def test_cherry_picked_content_is_flagged_and_kept(self):
        path = self.add_worktree('feature/c', merged=False)
        self.commit_on_main('trunk moves on', 'moved.txt')
        git(self.repo, 'cherry-pick', 'feature/c')
        git(self.repo, 'push', '-q', 'origin', 'main')
        scan = self.run_script('scan')
        self.assertIn('content-on-trunk=yes', scan)
        self.run_script('apply')
        self.assert_worktree_kept(path, 'feature/c')

    def test_excluded_branch_is_not_reported_as_unmerged(self):
        self.add_worktree('feature/x', merged=False)
        scan = self.run_script('scan', '--exclude', 'feature/x')
        self.assertNotIn('unmerged-worktree (', scan)

    def test_detached_head_worktree_is_reported(self):
        path = self.repo / '.claude' / 'worktrees' / 'detached'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(path), 'main')
        (path / 'd.txt').write_text('d\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'detached work')
        sha = git(path, 'rev-parse', '--short=7', 'HEAD').strip()
        scan = self.run_script('scan')
        self.assertIn(f'{path}:(detached {sha})', scan)
        self.assertIn('ahead=1 pushed=no', scan)
        self.run_script('apply')
        self.assertTrue(path.exists())

    def unresolved(self, path):
        # The temp dir as spelled before resolve() (on macOS /var/... for /private/var/...), plus a trailing slash.
        return str(Path(self.tmp.name) / path.relative_to(Path(self.tmp.name).resolve())) + '/'

    def test_excluded_detached_worktree_path_is_not_reported(self):
        path = self.repo / '.claude' / 'worktrees' / 'detached'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(path), 'main')
        scan = self.run_script('scan', '--exclude', self.unresolved(path))
        self.assertNotIn('unmerged-worktree (', scan)
        output = self.run_script('apply', '--exclude', self.unresolved(path))
        self.assertIn('kept-unmerged=0', output)
        self.assertTrue(path.exists())

    def test_excluded_worktree_path_protects_its_merged_branch(self):
        path = self.add_worktree('feature/a', merged=True)
        scan = self.run_script('scan', '--exclude', self.unresolved(path), GH_OPEN_BRANCHES='')
        self.assertNotIn('feature/a', scan)
        output = self.run_script('apply', '--exclude', self.unresolved(path), GH_OPEN_BRANCHES='')
        self.assertNotIn('feature/a', output)
        self.assert_worktree_kept(path, 'feature/a')
        self.assertTrue(self.remote_has('feature/a'))

    def test_excluded_path_of_a_deleted_worktree_protects_its_branch(self):
        path = self.add_worktree('feature/a', merged=True)
        excluded = self.unresolved(path)
        shutil.rmtree(path)
        output = self.run_script('apply', '--exclude', excluded, GH_OPEN_BRANCHES='')
        self.assertNotIn('feature/a', output)
        self.assertTrue(self.branch_exists('feature/a'))
        self.assertTrue(self.remote_has('feature/a'))

    def test_relative_exclude_is_a_branch_name(self):
        path = self.add_worktree('feature/a', merged=True)
        output = self.run_script('apply', '--exclude', 'repo/.claude/worktrees/feature-a', GH_OPEN_BRANCHES='')
        self.assertIn(f'removed-worktree={path}', output)

    def test_unmerged_worktree_reports_dirty_state(self):
        path = self.add_worktree('feature/dp', merged=False)
        (path / 'scratch.txt').write_text('s\n')
        scan = self.run_script('scan')
        self.assertIn('unmerged-worktree', scan)
        self.assertIn('scratch.txt', scan)

    def test_repo_with_only_unmerged_worktree_is_not_clean(self):
        self.add_worktree('feature/only', merged=False)
        scan = self.run_script('scan')
        self.assertIn('clean=0', scan)
        self.assertIn('unmerged-worktrees=1', scan)

    def handoff(self, name, days_old=0):
        path = self.repo / '.git' / f'agent-handoff-{name}.md'
        path.write_text('recap\n')
        stamp = time.time() - days_old * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_merged_branch_handoff_is_removed_with_its_branch(self):
        self.add_worktree('feature/a', merged=True)
        recap = self.handoff('repo-feature-a')
        scan = self.run_script('scan', GH_OPEN_BRANCHES='')
        self.assertIn(f'stale-handoff (recap or plans of a gone branch', scan)
        self.assertIn(f'{recap} [branch-deleted-on-apply]', scan)
        output = self.run_script('apply', GH_OPEN_BRANCHES='')
        self.assertIn('deleted-local=feature/a', output)
        self.assertIn(f'deleted-handoff={recap} reason=branch-gone', output)
        self.assertIn('deleted-handoffs=1', output)
        self.assertFalse(recap.exists())

    def plans(self, name):
        path = self.repo / '.git' / 'agent-plans' / name
        (path / 'nested').mkdir(parents=True)
        (path / 'nested' / 'topic.md').write_text('plan\n')
        return path

    def test_plans_of_a_merged_branch_are_removed_with_its_branch(self):
        path = self.add_worktree('feature/a', merged=True)
        plans = self.plans('repo-feature-a')
        self.assertIn(f'{plans} [branch-deleted-on-apply]', self.run_script('scan', GH_OPEN_BRANCHES=''))
        output = self.run_script('apply', GH_OPEN_BRANCHES='')
        self.assertIn(f'removed-worktree={path}', output)
        self.assertIn(f'deleted-handoff={plans} reason=branch-gone', output)
        self.assertFalse(plans.exists())

    def test_plans_of_live_or_excluded_branches_are_kept(self):
        self.add_worktree('feature/wip', merged=False)
        live = self.plans('repo-feature-wip')
        orphan = self.plans('repo-feature-gone')
        self.run_script('apply', '--exclude', str(orphan))
        self.assertTrue(live.exists())
        self.assertTrue(orphan.exists())
        self.run_script('apply', '--keep-handoffs')
        self.assertTrue(orphan.exists())
        self.run_script('apply')
        self.assertFalse(orphan.exists())

    def test_handoff_of_a_live_branch_is_kept(self):
        self.add_worktree('feature/wip', merged=False)
        recap = self.handoff('repo-feature-wip', days_old=30)
        self.assertNotIn('stale-handoff', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue(recap.exists())

    def test_handoff_of_a_protected_merged_branch_is_kept(self):
        path = self.add_worktree('feature/dirty', merged=True)
        (path / 'scratch.txt').write_text('s\n')
        recap = self.handoff('repo-feature-dirty')
        self.assertNotIn('stale-handoff', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue(recap.exists())

    def test_orphan_handoffs_are_removed_in_both_name_formats(self):
        current = self.handoff('repo-feature-gone')
        legacy = self.handoff('fix-gone')
        scan = self.run_script('scan')
        self.assertIn(f'{current} [branch-gone]', scan)
        self.assertIn(f'{legacy} [branch-gone]', scan)
        self.run_script('apply')
        self.assertFalse(current.exists())
        self.assertFalse(legacy.exists())

    def test_trunk_and_detached_handoffs_expire_by_age(self):
        recent = self.handoff('repo-main', days_old=1)
        old = self.handoff('repo-detached-abc1234', days_old=8)
        legacy_old = self.handoff('main', days_old=8)
        scan = self.run_script('scan')
        self.assertNotIn(str(recent), scan)
        self.assertIn(f'{old} [older-than-7d]', scan)
        self.assertIn(f'{legacy_old} [older-than-7d]', scan)
        self.assertNotIn('stale-handoff', self.run_script('scan', '--handoff-days', '30'))
        self.run_script('apply')
        self.assertTrue(recent.exists())
        self.assertFalse(old.exists())
        self.assertFalse(legacy_old.exists())

    def test_excluded_handoff_path_and_branch_are_kept(self):
        by_path = self.handoff('repo-feature-gone')
        by_branch = self.handoff('repo-feature-other')
        excluded = str(Path(self.tmp.name) / by_path.relative_to(Path(self.tmp.name).resolve()))
        output = self.run_script('apply', '--exclude', excluded, '--exclude', 'feature/other')
        self.assertIn('deleted-handoffs=0', output)
        self.assertTrue(by_path.exists())
        self.assertTrue(by_branch.exists())

    def test_keep_handoffs_and_remote_only_never_remove_recaps(self):
        recap = self.handoff('repo-feature-gone')
        for flag in ('--keep-handoffs', '--remote-only'):
            self.assertNotIn('stale-handoff', self.run_script('scan', flag))
            self.run_script('apply', flag)
            self.assertTrue(recap.exists())

    def test_handoff_days_must_be_an_integer(self):
        result = subprocess.run(
            [shutil.which('bash'), str(SCRIPT), 'scan', str(self.root), '--handoff-days', 'x'],
            text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--handoff-days needs a non-negative integer', result.stderr)

    def test_handoff_days_with_a_leading_zero_is_decimal(self):
        old = self.handoff('repo-main', days_old=9)
        self.assertIn(f'{old} [older-than-8d]', self.run_script('scan', '--handoff-days', '08'))

    def test_handoff_with_a_foreign_repo_prefix_of_a_live_branch_is_kept(self):
        self.add_worktree('feature/wip', merged=False)
        recap = self.handoff('old-name-feature-wip')
        orphan = self.handoff('old-name-feature-gone')
        scan = self.run_script('scan')
        self.assertNotIn(str(recap), scan)
        self.assertIn(f'{orphan} [branch-gone]', scan)
        self.run_script('apply')
        self.assertTrue(recap.exists())
        self.assertFalse(orphan.exists())

    def test_foreign_prefix_trunk_detached_and_protected_handoffs_are_not_orphans(self):
        detached = self.handoff('old-name-detached-abc1234', days_old=1)
        trunk = self.handoff('old-name-main', days_old=1)
        protected = self.handoff('old-name-feature-kept')
        expired = self.handoff('old-name-detached-def5678', days_old=8)
        scan = self.run_script('scan', '--exclude', 'feature/kept')
        for recap in (detached, trunk, protected):
            self.assertNotIn(str(recap), scan)
        self.assertIn(f'{expired} [older-than-7d]', scan)

    def test_handoff_of_a_live_branch_named_like_a_trunk_is_kept(self):
        self.add_worktree('feature/main', merged=False)
        legacy = self.handoff('feature-main', days_old=30)
        prefixed = self.handoff('repo-feature-main', days_old=30)
        self.assertNotIn('stale-handoff', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue(legacy.exists())
        self.assertTrue(prefixed.exists())

    def test_handoff_of_a_live_branch_named_like_a_detached_head_is_kept(self):
        self.add_worktree('detached-cafe', merged=False)
        recap = self.handoff('repo-detached-cafe', days_old=30)
        self.assertNotIn('stale-handoff', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue(recap.exists())

    def test_handoffs_are_kept_when_branches_cannot_be_listed(self):
        recap = self.handoff('repo-feature-gone')
        shim = self.bin / 'git'
        shim.write_text(
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == for-each-ref && "$3" == refs/heads ]]; then exit 1; fi\n'
            f'exec {shutil.which("git")} "$@"\n')
        shim.chmod(0o755)
        full_env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}'}
        result = subprocess.run(
            [shutil.which('bash'), str(SCRIPT), 'apply', str(self.root)],
            env=full_env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('cannot list branches, handoff recaps kept', result.stderr)
        self.assertTrue(recap.exists())

    def test_handoff_of_a_live_non_ascii_branch_is_kept(self):
        self.add_worktree('feature/café', merged=False)
        # The handoff workflow replaces the character, not its bytes.
        recap = self.handoff('repo-feature-caf-')
        self.assertNotIn('stale-handoff', self.run_script('scan'))
        self.run_script('apply')
        self.assertTrue(recap.exists())

    def test_handoff_of_a_live_branch_sharing_a_deleted_branch_key_is_kept(self):
        self.add_worktree('feature/x', merged=True)
        live = self.repo / '.claude' / 'worktrees' / 'live-x'
        git(self.repo, 'worktree', 'add', '-q', '-b', 'feature-x', str(live), 'main')
        (live / 'live.txt').write_text('live\n')
        git(live, 'add', '.')
        git(live, 'commit', '-q', '-m', 'live work')
        recap = self.handoff('repo-feature-x')
        self.assertNotIn('stale-handoff', self.run_script('scan', GH_OPEN_BRANCHES=''))
        output = self.run_script('apply', GH_OPEN_BRANCHES='')
        self.assertIn('deleted-local=feature/x', output)
        self.assertTrue(recap.exists())


if __name__ == '__main__':
    unittest.main()
