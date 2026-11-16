import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ignore_installer', ROOT / 'scripts/install-instructions.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class GlobalGitIgnoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='global git ignore ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        environment = patch.dict(os.environ, {
            'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.base / 'xdg'),
            'GIT_CONFIG_GLOBAL': str(self.home / 'gitconfig'),
            'GIT_CONFIG_NOSYSTEM': '1',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.default = self.base / 'xdg/git/ignore'

    def git(self, *arguments, cwd=None, check=True):
        return subprocess.run(['git', *arguments], cwd=cwd, check=check, capture_output=True, text=True)

    def test_default_applies_to_repositories_and_linked_worktrees(self):
        changes = installer.prepare_git_ignore()
        self.assertFalse(self.default.exists())
        installer.apply(changes)
        self.assertEqual(installer.prepare_git_ignore(), [])
        self.assertEqual(self.default.read_text(), '.agent-tmp/\n.agent-plans/\n')
        repo = self.base / 'repo'
        self.git('init', '-q', str(repo))
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '--allow-empty', '-qm', 'initial', cwd=repo)
        linked = self.base / 'worktree'
        self.git('worktree', 'add', '--detach', str(linked), cwd=repo)
        for checkout in (repo, linked):
            for relative in ('.agent-tmp/capture.png', 'nested/.agent-tmp/trace.json', '.agent-plans/topic.md'):
                scratch = checkout / relative
                scratch.parent.mkdir(parents=True, exist_ok=True)
                scratch.touch()
                self.assertEqual(self.git('check-ignore', relative, cwd=checkout).stdout.strip(), relative)
            (checkout / 'deliverable.txt').touch()
            self.assertIn('deliverable.txt', self.git('status', '--short', cwd=checkout).stdout)

    def test_custom_file_preserves_rules_mode_and_git_config(self):
        custom = self.home / 'custom ignores'
        custom.write_text('personal-rule\n.agent-tmp/\n!.agent-tmp/')
        custom.chmod(0o640)
        self.git('config', '--global', 'core.excludesFile', '~/custom ignores')
        config = (self.home / 'gitconfig').read_bytes()
        installer.apply(installer.prepare_git_ignore())
        self.assertEqual(custom.read_text(), 'personal-rule\n.agent-tmp/\n!.agent-tmp/\n.agent-tmp/\n.agent-plans/\n')
        self.assertEqual(custom.stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.home / 'gitconfig').read_bytes(), config)
        self.assertEqual(installer.prepare_git_ignore(), [])
        self.assertFalse(self.default.exists())
        repo = self.base / 'repo'
        self.git('init', '-q', str(repo))
        for path in ('.agent-tmp/trace.json', '.agent-plans/topic.md'):
            self.assertEqual(self.git('check-ignore', path, cwd=repo).returncode, 0)

    def test_home_default_when_xdg_is_unset(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': ''}):
            installer.apply(installer.prepare_git_ignore())
        self.assertEqual((self.home / '.config/git/ignore').read_text(), '.agent-tmp/\n.agent-plans/\n')

    def test_global_config_includes_are_respected(self):
        included = self.home / 'included config'
        custom = self.home / 'included ignore'
        self.git('config', '--file', str(included), 'core.excludesFile', str(custom))
        self.git('config', '--global', 'include.path', str(included))
        installer.apply(installer.prepare_git_ignore())
        self.assertEqual(custom.read_text(), '.agent-tmp/\n.agent-plans/\n')
        self.assertFalse(self.default.exists())
        repo = self.base / 'repo'
        self.git('init', '-q', str(repo))
        self.assertEqual(self.git('check-ignore', '.agent-tmp/trace.json', cwd=repo).returncode, 0)

    def test_existing_rule_with_trailing_comments_is_unchanged(self):
        self.default.parent.mkdir(parents=True)
        self.default.write_text('other-rule\n.agent-tmp/\n.agent-plans/\n\n# personal comment\n')
        self.assertEqual(installer.prepare_git_ignore(), [])

    def test_appends_only_missing_rules(self):
        self.default.parent.mkdir(parents=True)
        self.default.write_text('.agent-plans/\n# personal rule\n*.bak\n')
        installer.apply(installer.prepare_git_ignore())
        self.assertEqual(self.default.read_text(), '.agent-plans/\n# personal rule\n*.bak\n.agent-tmp/\n.agent-plans/\n')
        self.assertEqual(installer.prepare_git_ignore(), [])

    def test_rejects_symlinks_and_directories(self):
        self.default.parent.mkdir(parents=True)
        target = self.base / 'target'
        self.default.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            installer.prepare_git_ignore()
        self.assertFalse(target.exists())
        self.default.unlink()
        self.default.mkdir()
        with self.assertRaisesRegex(ValueError, 'non-file'):
            installer.prepare_git_ignore()

    def test_rejects_invalid_global_configuration(self):
        for value in ('', 'relative-ignore'):
            with self.subTest(value=value):
                self.git('config', '--global', 'core.excludesFile', value)
                with self.assertRaises(ValueError):
                    installer.prepare_git_ignore()
        (self.home / 'gitconfig').write_text('[invalid')
        with self.assertRaisesRegex(ValueError, 'Cannot read global Git'):
            installer.prepare_git_ignore()

    def test_installer_preview_apply_check_and_restore(self):
        arguments = ['install-instructions.py', '--claude-home', str(self.base / 'claude'),
                     '--codex-home', str(self.base / 'codex')]
        with contextlib.redirect_stdout(io.StringIO()):
            with patch.object(sys, 'argv', arguments):
                self.assertEqual(installer.main(), 0)
            self.assertFalse(self.default.exists())
            with patch.object(sys, 'argv', arguments + ['--apply']):
                self.assertEqual(installer.main(), 0)
            with patch.object(sys, 'argv', arguments + ['--check']):
                self.assertEqual(installer.main(), 0)
            self.default.write_text('personal-rule\n')
            with patch.object(sys, 'argv', arguments + ['--check']):
                self.assertEqual(installer.main(), 1)
            with patch.object(sys, 'argv', arguments + ['--apply']):
                self.assertEqual(installer.main(), 0)
            with patch.object(sys, 'argv', arguments + ['--restore']):
                self.assertEqual(installer.main(), 0)
        self.assertEqual(self.default.read_text(), 'personal-rule\n.agent-tmp/\n.agent-plans/\n')


if __name__ == '__main__':
    unittest.main()
