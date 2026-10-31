import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install-instructions.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstructionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agent config tests ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'claude home'
        self.home.mkdir()

    def install(self, outputs):
        installer.apply(installer.prepare(self.home, outputs))

    def test_scopes_are_preserved_and_adapters_are_separate(self):
        claude = installer.render(ROOT, 'claude')
        codex = installer.render(ROOT, 'codex')['AGENTS.md']
        common = (ROOT / 'instructions/global.md').read_text().strip()
        self.assertIn(common, claude['CLAUDE.md'])
        self.assertIn(common, codex)
        self.assertIn('/graphify', claude['CLAUDE.md'])
        self.assertNotIn('/graphify', codex)
        for name, rule in installer.load_scopes(ROOT).items():
            source = ROOT / rule['source']
            self.assertIn(str(source), codex)
            if 'paths' in rule:
                rendered = claude[f'rules/agent-config-{name}.md']
                meta = yaml.safe_load(rendered.split('---', 2)[1])
                self.assertEqual(meta['paths'], rule['paths'])
                self.assertIn(source.read_text().strip(), rendered)
                self.assertNotIn(source.read_text().strip(), claude['CLAUDE.md'])
                self.assertNotIn(source.read_text().strip(), codex)
                for pattern in rule['paths']:
                    self.assertIn(pattern, codex)
            else:
                self.assertIn(rule['when'], claude['CLAUDE.md'])
                self.assertIn(str(source), claude['CLAUDE.md'])

    def test_composed_sources_install_and_restore_original(self):
        private = self.base / 'private'
        (private / 'instructions/rules').mkdir(parents=True)
        (private / 'instructions/global.md').write_text('Private working agreements')
        (private / 'instructions/rules/internal.md').write_text('Private rule')
        (private / 'instructions/scopes.json').write_text(json.dumps({
            'internal': {'source': 'instructions/rules/internal.md', 'paths': ['**/*.py']},
        }))
        original = self.home / 'CLAUDE.md'
        original.write_text('Personal original')
        sources = {'public': ROOT, 'private': private}
        claude = installer.render_sources(sources, 'claude')
        codex = installer.render_sources(sources, 'codex')
        self.assertIn('Private working agreements', claude['CLAUDE.md'])
        self.assertIn('Private rule', claude['rules/agent-config-private-internal.md'])
        self.assertIn(str(private / 'instructions/rules/internal.md'), codex['AGENTS.md'])
        self.install(claude)
        self.assertEqual(installer.prepare(self.home, claude), [])
        installer.apply(installer.prepare(self.home, {}, restore=True))
        self.assertEqual(original.read_text(), 'Personal original')

    def test_first_install_backup_reinstall_update_and_restore(self):
        original = '# Personal instructions\n'
        path = self.home / 'CLAUDE.md'
        path.write_text(original)
        path.chmod(0o640)
        unrelated = self.home / 'rules/private.md'
        unrelated.parent.mkdir()
        unrelated.write_text('Unrelated user rule')
        outputs = installer.render(ROOT, 'claude')
        self.install(outputs)
        self.assertEqual(installer.prepare(self.home, outputs), [])
        outputs['CLAUDE.md'] += '\nNew shared instruction\n'
        self.install(outputs)
        installer.apply(installer.prepare(self.home, {}, restore=True))
        self.assertEqual(path.read_text(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(unrelated.read_text(), 'Unrelated user rule')
        self.assertFalse((self.home / 'rules/agent-config-python.md').exists())
        self.assertFalse((self.home / installer.STATE).exists())

    def test_local_edits_block_install_and_restore(self):
        outputs = installer.render(ROOT, 'claude')
        self.install(outputs)
        path = self.home / 'CLAUDE.md'
        path.write_text(path.read_text() + '\nManual preference\n')
        for restore in (False, True):
            with self.assertRaisesRegex(ValueError, 'Locally modified'):
                installer.prepare(self.home, outputs, restore=restore)
        self.assertIn('Manual preference', path.read_text())

    def test_removed_scope_restores_original_rule(self):
        relative = 'rules/agent-config-python.md'
        path = self.home / relative
        path.parent.mkdir()
        path.write_text('Previous rule')
        outputs = installer.render(ROOT, 'claude')
        self.install(outputs)
        del outputs[relative]
        self.install(outputs)
        self.assertEqual(path.read_text(), 'Previous rule')

    def test_refuses_existing_symlink(self):
        target = self.base / 'elsewhere.md'
        target.write_text('Keep me')
        (self.home / 'CLAUDE.md').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            installer.prepare(self.home, installer.render(ROOT, 'claude'))
        self.assertEqual(target.read_text(), 'Keep me')

    def test_refuses_external_rule_directory(self):
        external = self.base / 'external rules'
        external.mkdir()
        (self.home / 'rules').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'external'):
            installer.prepare(self.home, installer.render(ROOT, 'claude'))

    def test_write_failure_rolls_back(self):
        (self.home / 'CLAUDE.md').write_text('Original')
        changes = installer.prepare(self.home, installer.render(ROOT, 'claude'))
        real_write = installer.write_snapshot
        counter = 0

        def fail_second(path, value):
            nonlocal counter
            counter += 1
            if counter == 2:
                raise PermissionError('Simulated restriction')
            real_write(path, value)

        with patch.object(installer, 'write_snapshot', side_effect=fail_second):
            with self.assertRaises(PermissionError):
                installer.apply(changes)
        self.assertEqual((self.home / 'CLAUDE.md').read_text(), 'Original')
        self.assertFalse((self.home / installer.STATE).exists())

    def test_detects_changes_after_preflight(self):
        outputs = installer.render(ROOT, 'claude')
        changes = installer.prepare(self.home, outputs)
        (self.home / 'CLAUDE.md').write_text('Concurrent edit')
        with self.assertRaisesRegex(ValueError, 'changed since preflight'):
            installer.apply(changes)
        self.assertEqual((self.home / 'CLAUDE.md').read_text(), 'Concurrent edit')

    def test_deterministic_render_from_checkout_with_spaces(self):
        root = self.base / 'checkout with spaces'
        for directory in ('instructions', 'adapters'):
            shutil.copytree(ROOT / directory, root / directory)
        first = installer.render(root, 'codex')
        self.assertEqual(first, installer.render(root, 'codex'))
        self.assertIn(str(root / 'instructions/rules/python.md'), first['AGENTS.md'])

    def test_invalid_scope_fails_instead_of_becoming_global(self):
        root = self.base / 'checkout'
        shutil.copytree(ROOT / 'instructions', root / 'instructions')
        path = root / 'instructions/scopes.json'
        scopes = json.loads(path.read_text())
        scopes['python']['paths'] = []
        path.write_text(json.dumps(scopes))
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            installer.load_scopes(root)

    def cli(self, *args):
        return subprocess.run([
            sys.executable, str(ROOT / 'scripts/install-instructions.py'),
            '--claude-home', str(self.home), '--codex-home', str(self.base / 'codex home'),
            *args,
        ], text=True, capture_output=True)

    def test_cli_dry_run_apply_check_restore(self):
        self.assertEqual(self.cli().returncode, 0)
        self.assertFalse((self.home / 'CLAUDE.md').exists())
        self.assertEqual(self.cli('--check').returncode, 1)
        self.assertEqual(self.cli('--apply').returncode, 0)
        self.assertEqual(self.cli('--check').returncode, 0)
        self.assertEqual(self.cli('--restore').returncode, 0)
        self.assertFalse((self.base / 'codex home/AGENTS.md').exists())

    def test_codex_override_blocks_entire_install(self):
        codex = self.base / 'codex home'
        codex.mkdir()
        (codex / 'AGENTS.override.md').write_text('Existing override')
        result = self.cli('--apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('masks AGENTS.md', result.stderr)
        self.assertFalse((self.home / 'CLAUDE.md').exists())


if __name__ == '__main__':
    unittest.main()
