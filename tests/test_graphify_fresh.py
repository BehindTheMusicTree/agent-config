import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/graphify-fresh.sh'


def git(cwd, *args):
    subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})


class GraphifyFreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='graphify fresh ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.main = self.root / 'main'
        self.main.mkdir()
        git(self.main, 'init', '-q', '-b', 'main')
        (self.main / 'a.py').write_text('x = 1\n')
        (self.main / '.gitignore').write_text('graphify-out/\n')
        git(self.main, 'add', '.')
        git(self.main, 'commit', '-q', '-m', 'init')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.calls = self.root / 'calls.log'
        self.fake_graphify()

    def fake_graphify(self, with_graphify=True):
        if not with_graphify:
            return
        fake = self.bin / 'graphify'
        fake.write_text(
            '#!/usr/bin/env bash\n'
            f'echo "$PWD|$*|${{GRAPHIFY_NO_BACKUP:-}}" >> "{self.calls}"\n'
            'if [ "$1" = hook-guard ]; then cat >/dev/null; printf NUDGE; fi\n')
        fake.chmod(0o755)

    def graph(self, repo):
        (repo / 'graphify-out').mkdir(exist_ok=True)
        (repo / 'graphify-out/graph.json').write_text('{}')

    def run_hook(self, cwd, tool='Grep', path=None, args=()):
        env = {**os.environ, 'PATH': f'{self.bin}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin'}
        if path is not None:
            env['PATH'] = path
        payload = json.dumps({'cwd': str(cwd), 'tool_name': tool, 'tool_input': {'pattern': 'x'}})
        result = subprocess.run([str(SCRIPT), *args], input=payload, text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0)
        return result.stdout

    def wait_for_idle(self, repo):
        for _ in range(100):
            if not (repo / 'graphify-out/.refresh.lock').exists():
                return
            time.sleep(0.05)
        self.fail('refresh did not finish')

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_silent_when_graphify_out_is_not_ignored(self):
        (self.main / '.gitignore').unlink()
        git(self.main, 'commit', '-q', '-am', 'drop ignore')
        self.graph(self.main)
        self.assertEqual(self.run_hook(self.main), '')
        self.assertEqual(self.calls_made(), [])

    def test_ignored_repo_without_graph_is_built_for_the_first_time(self):
        out = json.loads(self.run_hook(self.main))['hookSpecificOutput']['additionalContext']
        self.assertIn('built for the first time', out)
        self.wait_for_idle(self.main)
        self.assertEqual(len([c for c in self.calls_made() if '|update .|' in c]), 1)
        self.assertTrue((self.main / 'graphify-out/.fresh-key').exists())

    def test_silent_when_graphify_missing(self):
        self.graph(self.main)
        path = '/usr/bin:/bin'
        if subprocess.run(['sh', '-c', 'command -v graphify'], env={'PATH': path}).returncode == 0:
            self.skipTest('graphify installed in system path')
        self.assertEqual(self.run_hook(self.main, path=path), '')

    def test_non_search_tool_is_ignored(self):
        self.graph(self.main)
        self.assertEqual(self.run_hook(self.main, tool='Edit'), '')

    def test_stale_refreshes_once_in_background_and_notes_once(self):
        self.graph(self.main)
        first = self.run_hook(self.main)
        self.assertIn('refreshing in the background', json.loads(first)['hookSpecificOutput']['additionalContext'])
        self.wait_for_idle(self.main)
        self.assertEqual(self.run_hook(self.main, tool='Grep'), 'NUDGE')
        update = [c for c in self.calls_made() if '|update .|' in c]
        self.assertEqual(len(update), 1)
        self.assertTrue(update[0].endswith('|1'))

    def test_fresh_key_delegates_to_hook_guard_by_tool(self):
        self.graph(self.main)
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        self.run_hook(self.main, tool='Read')
        self.run_hook(self.main, tool='Bash')
        guards = [c.split('|')[1] for c in self.calls_made() if 'hook-guard' in c]
        self.assertEqual(guards, ['hook-guard read', 'hook-guard search'])

    def test_codex_client_refreshes_in_silence_and_never_delegates(self):
        codex = ('--client', 'codex')
        for _ in range(2):
            self.assertEqual(self.run_hook(self.main, tool='Bash', args=codex), '')
            self.wait_for_idle(self.main)
        self.assertEqual(self.run_hook(self.main, tool='Bash', args=codex), '')
        calls = self.calls_made()
        self.assertEqual(len([c for c in calls if '|update .|' in c]), 1)
        self.assertEqual([c for c in calls if 'hook-guard' in c], [])
        self.assertFalse((self.main / 'graphify-out/.notified-key').exists())
        self.assertTrue((self.main / 'graphify-out/.fresh-key').exists())

    def test_explicit_claude_client_keeps_the_nudge(self):
        self.graph(self.main)
        out = self.run_hook(self.main, args=('--client', 'claude'))
        self.assertIn('refreshing in the background', json.loads(out)['hookSpecificOutput']['additionalContext'])

    def test_unknown_client_does_nothing(self):
        self.graph(self.main)
        self.assertEqual(self.run_hook(self.main, args=('--client', 'other')), '')
        self.assertEqual(self.calls_made(), [])

    def test_lock_prevents_duplicate_refresh_and_stale_lock_is_cleared(self):
        self.graph(self.main)
        lock = self.main / 'graphify-out/.refresh.lock'
        lock.mkdir()
        self.run_hook(self.main)
        time.sleep(0.3)
        self.assertEqual([c for c in self.calls_made() if '|update .|' in c], [])
        old = time.time() - 3600
        os.utime(lock, (old, old))
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        self.assertEqual(len([c for c in self.calls_made() if '|update .|' in c]), 1)

    def test_dirty_edit_and_untracked_file_change_the_key(self):
        self.graph(self.main)
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        key = (self.main / 'graphify-out/.fresh-key').read_text()
        (self.main / 'a.py').write_text('x = 2\n')
        self.assertIn('refreshing', self.run_hook(self.main))
        self.wait_for_idle(self.main)
        edited = (self.main / 'graphify-out/.fresh-key').read_text()
        self.assertNotEqual(key, edited)
        (self.main / 'b.py').write_text('y = 1\n')
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        self.assertNotEqual(edited, (self.main / 'graphify-out/.fresh-key').read_text())

    def test_untracked_file_content_change_changes_the_key(self):
        self.graph(self.main)
        (self.main / 'b.py').write_text('y = 1\n')
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        key = (self.main / 'graphify-out/.fresh-key').read_text()
        (self.main / 'b.py').write_text('y = 2\n')
        self.assertIn('refreshing', self.run_hook(self.main))
        self.wait_for_idle(self.main)
        self.assertNotEqual(key, (self.main / 'graphify-out/.fresh-key').read_text())

    def test_failed_update_is_not_retried_for_the_same_key(self):
        self.graph(self.main)
        fake = self.bin / 'graphify'
        fake.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{self.calls}"\nexit 1\n')
        fake.chmod(0o755)
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        self.run_hook(self.main)
        time.sleep(0.3)
        self.assertEqual(len(self.calls_made()), 1)
        (self.main / 'a.py').write_text('x = 3\n')
        self.run_hook(self.main)
        self.wait_for_idle(self.main)
        self.assertEqual(len(self.calls_made()), 2)

    def test_linked_worktree_is_seeded_from_main_checkout(self):
        self.graph(self.main)
        out = self.main / 'graphify-out'
        (out / 'manifest.json').write_text('{}')
        (out / 'graph.html').write_text('x')
        (out / '2026-01-01').mkdir()
        (out / 'cache').mkdir()
        (out / 'cache/c').write_text('c')
        worktree = self.root / 'wt'
        git(self.main, 'worktree', 'add', '-q', '-b', 'feat', str(worktree))
        self.run_hook(worktree)
        self.wait_for_idle(worktree)
        seeded = worktree / 'graphify-out'
        self.assertTrue((seeded / 'graph.json').exists())
        self.assertTrue((seeded / 'manifest.json').exists())
        self.assertTrue((seeded / 'cache/c').exists())
        self.assertFalse((seeded / 'graph.html').exists())
        self.assertFalse((seeded / '2026-01-01').exists())
        self.assertTrue((seeded / '.fresh-key').exists())
        self.assertTrue(any(c.startswith(str(worktree)) and '|update .|' in c for c in self.calls_made()))


if __name__ == '__main__':
    unittest.main()
