import importlib.util
import json
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('remote_release', ROOT / 'scripts/prepare-remote-release.py')
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


class RemoteReleaseTests(unittest.TestCase):
    def test_repository_reuse_and_redirect_are_rejected(self):
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps({'id': 'R_replaced', 'nameWithOwner': 'org/public'}))
        with patch.object(remote.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                remote.verify_repository('org/public', 'R_original')
        response.stdout = json.dumps({'id': 'R_original', 'nameWithOwner': 'org/renamed'})
        with patch.object(remote.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                remote.verify_repository('org/public', 'R_original')

    def test_profile_uses_dependency_pinned_by_private_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / 'private-snapshot'
            private.mkdir()
            (private / 'agent-config-dependency.json').write_text(json.dumps({'repo': 'org/public', 'tag': 'v1.2.3'}))
            profile = {'version': 1, 'public': {'repo': 'org/public', 'id': 'R_public'}, 'private': {'repo': 'org/private', 'id': 'R_private'}}
            with patch.object(remote, 'verify_repository'), patch.object(remote, 'prepare_remote', side_effect=[private, root / 'public-snapshot']) as prepare:
                result = remote.prepare_profile(profile, root / 'releases')
            self.assertEqual(result['private'], private)
            self.assertEqual(prepare.call_args_list[0].args, ('org/private', None, root / 'releases/private'))
            self.assertEqual(prepare.call_args_list[1].args, ('org/public', 'v1.2.3', root / 'releases/public'))

    def test_profile_rejects_wrong_public_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'agent-config-dependency.json').write_text(json.dumps({'repo': 'other/repo', 'tag': 'v1.2.3'}))
            profile = {'version': 1, 'public': {'repo': 'org/public', 'id': 'R_public'}, 'private': {'repo': 'org/private', 'id': 'R_private'}}
            with patch.object(remote, 'verify_repository'), patch.object(remote, 'prepare_remote', return_value=root) as prepare:
                with self.assertRaisesRegex(ValueError, 'dependency'):
                    remote.prepare_profile(profile, root / 'releases')
            self.assertEqual(prepare.call_count, 1)

    def test_profile_activation_and_check_use_same_snapshot_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            releases = root / 'releases'
            sources = {}
            for name, commit in [('public', 'a' * 40), ('private', 'b' * 40)]:
                source = releases / 'sources' / name / commit
                source.mkdir(parents=True)
                (source / 'content').write_text(name)
                sources[name] = source
            fake = SimpleNamespace(
                synchronize_sources=lambda *args: None,
                plan_sources=lambda *args: ({}, [], []),
                plugins=SimpleNamespace(prepare_sources=lambda *args: {}, verify_sources=lambda *args: None),
            )
            fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
            with patch.object(remote, 'prepare_profile', return_value=sources), patch.object(
                    remote.importlib.util, 'spec_from_file_location', return_value=fake_spec), patch.object(
                    remote.importlib.util, 'module_from_spec', return_value=fake):
                result = remote.synchronize_profile({}, releases, root / 'claude', root / 'codex')
                self.assertEqual(result, sources)
                self.assertEqual((root / 'current-profile').resolve(), sources['public'])
                self.assertEqual(remote.check_profile({}, releases, root / 'claude', root / 'codex'), sources)
                with patch.object(fake, 'synchronize_sources', side_effect=AssertionError('unnecessary reinstall')):
                    self.assertEqual(remote.synchronize_profile({}, releases, root / 'claude', root / 'codex'), sources)

    def test_updater_does_not_write_bytecode_to_snapshot(self):
        with tempfile.TemporaryDirectory(prefix='snapshot-test-') as directory:
            scripts = Path(directory) / 'scripts'
            shutil.copytree(ROOT / 'scripts', scripts, ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('prepare-remote-release.py', 'sync-local-release.py'):
                subprocess.run([sys.executable, str(scripts / name), '--help'], check=True, capture_output=True)
            self.assertFalse((scripts / '__pycache__').exists())

    def test_only_accepts_published_stable_release(self):
        def response(tag='v1.0.0', draft=False, prerelease=False):
            return subprocess.CompletedProcess([], 0, stdout=json.dumps({
                'tagName': tag, 'isDraft': draft, 'isPrerelease': prerelease,
            }))
        with patch.object(remote.subprocess, 'run', return_value=response()):
            self.assertEqual(remote.published_tag('org/repo', 'v1.0.0'), 'v1.0.0')
        for result in (response(draft=True), response(prerelease=True), response(tag='v1.0.0-rc.1')):
            with patch.object(remote.subprocess, 'run', return_value=result):
                with self.assertRaises(ValueError):
                    remote.published_tag('org/repo')
        with patch.object(remote.subprocess, 'run', return_value=response()):
            with self.assertRaises(ValueError):
                remote.published_tag('org/repo', 'v2.0.0')

    def test_fetches_exact_tag_from_isolated_repository(self):
        with tempfile.TemporaryDirectory(prefix='remote test ') as directory:
            root = Path(directory).resolve()
            source = root / 'source'
            source.mkdir()
            def git(*args):
                return subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            (source / '.claude-plugin').mkdir()
            (source / '.claude-plugin/plugin.json').write_text('{"version":"1.0.0"}')
            (source / 'code').write_text('published')
            git('add', '.')
            git('commit', '-qm', 'release')
            git('tag', 'v1.0.0')
            (source / 'code').write_text('uncommitted')
            cache = root / 'isolated.git'
            remote.fetch_tag(str(source), 'v1.0.0', cache)
            snapshot = remote.release.prepare(cache, 'v1.0.0', root / 'releases')
            self.assertEqual((snapshot / 'code').read_text(), 'published')
            self.assertEqual((source / 'code').read_text(), 'uncommitted')

    def test_concurrent_synchronization_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='sync-lock-') as directory:
            releases = Path(directory) / 'releases'
            with remote.synchronization_lock(releases):
                with self.assertRaisesRegex(ValueError, 'Another synchronization'):
                    with remote.synchronization_lock(releases):
                        pass
            with remote.synchronization_lock(releases):
                pass

    def test_rejects_invalid_input_before_running_commands(self):
        with patch.object(remote.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                remote.published_tag('org/repo', '--bad')
            with self.assertRaises(ValueError):
                remote.published_tag('--bad/repo')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
