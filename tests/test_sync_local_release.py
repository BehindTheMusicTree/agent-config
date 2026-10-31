import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_release', ROOT / 'scripts/sync-local-release.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class LocalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='local release ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        for directory in ('instructions', 'adapters'):
            shutil.copytree(ROOT / directory, self.repo / directory)
        (self.repo / '.claude-plugin').mkdir()
        (self.repo / '.claude-plugin/plugin.json').write_text(json.dumps({'version': '1.0.0'}))
        (self.repo / 'skills/example').mkdir(parents=True)
        (self.repo / 'skills/example/SKILL.md').write_text('# example\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'release')
        self.git('tag', 'v1.0.0')
        self.claude = self.base / 'claude'
        self.codex = self.base / 'codex'
        self.releases = self.base / 'releases'
        plugin = patch.object(sync.plugins, 'install')
        self.plugin = plugin.start()
        self.addCleanup(plugin.stop)

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)

    def execute(self):
        return sync.synchronize(self.repo, 'v1.0.0', self.releases, self.claude, self.codex)

    def test_installs_and_repeats_from_tag(self):
        source = self.execute()
        self.assertEqual((self.codex / 'skills/example').resolve(), source / 'skills/example')
        self.assertIn(str(source), (self.codex / 'AGENTS.md').read_text())
        self.assertTrue((self.claude / 'CLAUDE.md').is_file())
        self.assertEqual(self.execute(), source)

    def test_plugin_failure_restores_both_agent_files_and_links(self):
        self.claude.mkdir()
        self.codex.mkdir()
        (self.claude / 'CLAUDE.md').write_text('original Claude')
        (self.codex / 'AGENTS.md').write_text('original Codex')
        self.plugin.side_effect = RuntimeError('installation failed')
        with self.assertRaisesRegex(RuntimeError, 'Codex and instructions restored'):
            self.execute()
        self.assertEqual((self.claude / 'CLAUDE.md').read_text(), 'original Claude')
        self.assertEqual((self.codex / 'AGENTS.md').read_text(), 'original Codex')
        self.assertFalse((self.codex / 'skills/example').is_symlink())
        self.assertFalse((self.codex / 'skills' / sync.skills.STATE).exists())

    def test_preflight_override_prevents_link_changes(self):
        self.codex.mkdir()
        (self.codex / 'AGENTS.override.md').write_text('private')
        with self.assertRaisesRegex(ValueError, 'override'):
            self.execute()
        self.assertFalse((self.codex / 'skills/example').exists())
        self.assertFalse((self.claude / 'CLAUDE.md').exists())

    def test_instruction_failure_restores_skills(self):
        with patch.object(sync.instructions, 'apply', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.execute()
        self.assertFalse((self.codex / 'skills/example').is_symlink())
        self.assertFalse((self.codex / 'skills' / sync.skills.STATE).exists())

    def test_multisource_preflight_checks_all_skills_and_instructions(self):
        private = self.base / 'private'
        (private / 'skills/ops').mkdir(parents=True)
        (private / 'skills/ops/SKILL.md').write_text('# private\n')
        (private / 'instructions/rules').mkdir(parents=True)
        (private / 'instructions/global.md').write_text('Private instructions')
        (private / 'instructions/rules/internal.md').write_text('Private rule')
        (private / 'instructions/scopes.json').write_text(json.dumps({
            'internal': {'source': 'instructions/rules/internal.md', 'when': 'Working internally'},
        }))
        desired, links, changes = sync.plan_sources({'public': self.repo, 'private': private}, self.claude, self.codex)
        self.assertEqual(set(desired), {'example', 'ops'})
        self.assertEqual(len(links), 2)
        self.assertTrue(any('Private instructions' in after['text'] for _, _, after in changes if after))
        self.assertFalse(self.claude.exists())
        self.assertFalse(self.codex.exists())

    def test_multisource_plugin_failure_rolls_back_both_agents(self):
        private = self.base / 'private'
        (private / 'skills/ops').mkdir(parents=True)
        (private / 'skills/ops/SKILL.md').write_text('# private\n')
        (private / 'instructions/rules').mkdir(parents=True)
        (private / 'instructions/global.md').write_text('Private instructions')
        (private / 'instructions/rules/internal.md').write_text('Private rule')
        (private / 'instructions/scopes.json').write_text(json.dumps({
            'internal': {'source': 'instructions/rules/internal.md', 'when': 'Working internally'},
        }))
        with patch.object(sync.plugins, 'prepare_sources', return_value={}), patch.object(
                sync.plugins, 'install_sources', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'Codex and instructions restored'):
                sync.synchronize_sources({'public': self.repo, 'private': private}, self.claude, self.codex,
                                         self.base / 'marketplaces')
        self.assertFalse((self.codex / 'skills/ops').exists())
        self.assertFalse((self.codex / 'AGENTS.md').exists())
        self.assertFalse((self.claude / 'CLAUDE.md').exists())


if __name__ == '__main__':
    unittest.main()
