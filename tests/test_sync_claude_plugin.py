import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('claude_plugin', ROOT / 'scripts/sync-claude-plugin.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


@unittest.skipUnless(
    shutil.which('claude') and os.environ.get('AGENT_CONFIG_RUN_CLAUDE_E2E') == '1',
    'set AGENT_CONFIG_RUN_CLAUDE_E2E=1 to run the Claude CLI integration test',
)
class ClaudePluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='claude plugin test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'claude home'
        self.stages = self.root / 'marketplaces'

    def source(self, commit, version):
        source = self.root / commit
        source.mkdir()
        for directory in ('.claude-plugin', 'commands', 'scripts', 'references'):
            shutil.copytree(ROOT / directory, source / directory, ignore=shutil.ignore_patterns('__pycache__'))
        manifest = source / '.claude-plugin/plugin.json'
        data = json.loads(manifest.read_text())
        data['version'] = version
        manifest.write_text(json.dumps(data))
        (source / '.agent-config-release.json').write_text(json.dumps({'tag': 'v' + version, 'commit': commit}))
        return source

    def test_install_repeat_upgrade_and_preserve_unmanaged_files(self):
        first = self.source('a' * 40, '2.0.0')
        second = self.source('b' * 40, '2.0.1')
        old_id = plugin.install(first, self.home, self.stages)
        self.assertEqual(plugin.install(first, self.home, self.stages), old_id)
        new_id = plugin.install(second, self.home, self.stages)
        installed = json.loads((self.home / 'plugins/installed_plugins.json').read_text())['plugins']
        self.assertIn(new_id, installed)
        self.assertNotIn(old_id, installed)
        self.assertEqual(installed[new_id][0]['version'], '2.0.1')

    def test_refuses_modified_marketplace(self):
        source = self.source('c' * 40, '2.0.0')
        plugin.install(source, self.home, self.stages)
        (self.stages / ('c' * 40) / 'commands/create-pr.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'differs from release'):
            plugin.install(source, self.home, self.stages)


class ClaudePluginMockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plugin mock ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.commit = 'd' * 40
        self.source = self.root / self.commit
        self.source.mkdir()
        for name in ('.claude-plugin', 'commands', 'scripts', 'references'):
            shutil.copytree(ROOT / name, self.source / name, ignore=shutil.ignore_patterns('__pycache__'))
        manifest = self.source / '.claude-plugin/plugin.json'
        data = json.loads(manifest.read_text())
        data['version'] = '2.0.0'
        manifest.write_text(json.dumps(data))
        (self.source / '.agent-config-release.json').write_text(json.dumps({'tag': 'v2.0.0', 'commit': self.commit}))
        self.old_id = 'claude-config@btmt-claude-config'
        self.personal_id = 'other@personal'
        self.listing = [{'id': self.old_id, 'scope': 'user', 'version': '1.0.0', 'enabled': True},
                        {'id': self.personal_id, 'scope': 'user', 'version': '1.0.0', 'enabled': True}]
        self.wrong_version = False
        self.calls = []

    def fake_cli(self, home, *args):
        self.calls.append(args)
        if args[0] == 'install':
            stage = Path(args[args.index('--marketplace') + 1])
            marketplace = json.loads((stage / '.claude-plugin/marketplace.json').read_text())['name']
            identifier = args[1] + '@' + marketplace
            cache = self.root / 'cache' / marketplace
            shutil.copytree(stage, cache, dirs_exist_ok=True)
            version = '9.9.9' if self.wrong_version else '2.0.0'
            self.listing = [item for item in self.listing if item['id'] != identifier]
            self.listing.append({'id': identifier, 'scope': 'user', 'version': version,
                                 'enabled': True, 'installPath': str(cache)})
        elif args[0] == 'uninstall':
            self.listing = [item for item in self.listing if item['id'] != args[1]]
        elif args[0] == 'list':
            return json.dumps(self.listing)
        directory = self.home / 'plugins'
        directory.mkdir(parents=True, exist_ok=True)
        entries = {}
        for item in self.listing:
            entries.setdefault(item['id'], []).append(item)
        (directory / 'installed_plugins.json').write_text(json.dumps({'plugins': entries}))
        (self.home / 'settings.json').write_text(json.dumps({'enabledPlugins': {item['id']: item['enabled'] for item in self.listing}}))
        return '{}'

    def test_migrates_only_managed_plugins(self):
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            identifier = plugin.install(self.source, self.home, self.root / 'stages')
            self.assertEqual(plugin.verify(self.source, self.home), identifier)
        ids = [item['id'] for item in self.listing]
        self.assertNotIn(self.old_id, ids)
        self.assertTrue(any(args[0] == 'uninstall' and '--keep-data' in args for args in self.calls))
        self.assertIn(self.personal_id, ids)
        self.assertIn(identifier, ids)

    def test_wrong_version_does_not_remove_previous_plugin(self):
        self.wrong_version = True
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            with self.assertRaisesRegex(RuntimeError, 'requested plugin version'):
                plugin.install(self.source, self.home, self.root / 'stages')
        self.assertIn(self.old_id, [item['id'] for item in self.listing])

    def test_missing_python_script_fails_verification(self):
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            identifier = plugin.install(self.source, self.home, self.root / 'stages')
            entry = next(item for item in self.listing if item['id'] == identifier)
            (Path(entry['installPath']) / 'scripts/prepare-remote-release.py').unlink()
            with self.assertRaisesRegex(ValueError, 'cache differs'):
                plugin.verify(self.source, self.home)

    def test_shared_policy_is_packaged_and_verified(self):
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            identifier = plugin.install(self.source, self.home, self.root / 'stages')
            entry = next(item for item in self.listing if item['id'] == identifier)
            policy = Path(entry['installPath']) / 'references/pr-policy.md'
            self.assertEqual(policy.read_bytes(), (self.source / 'references/pr-policy.md').read_bytes())
            policy.write_text('changed policy')
            with self.assertRaisesRegex(ValueError, 'cache differs'):
                plugin.verify(self.source, self.home)

    def test_missing_policy_during_install_preserves_previous_plugin(self):
        def incomplete_install(home, *args):
            result = self.fake_cli(home, *args)
            if args[0] == 'install':
                entry = next(item for item in self.listing if item['id'].startswith('agent-config@'))
                (Path(entry['installPath']) / 'references/pr-policy.md').unlink()
            return result

        with patch.object(plugin, 'run_claude', side_effect=incomplete_install):
            with self.assertRaisesRegex(RuntimeError, 'cache differs'):
                plugin.install(self.source, self.home, self.root / 'stages')
        self.assertIn(self.old_id, [item['id'] for item in self.listing])

    def test_multiple_sources_have_distinct_verified_marketplace_stages(self):
        private = self.root / ('e' * 40)
        shutil.copytree(self.source, private)
        manifest = private / '.claude-plugin/plugin.json'
        data = json.loads(manifest.read_text())
        data['name'] = 'agent-config-btmt'
        manifest.write_text(json.dumps(data))
        (private / '.agent-config-release.json').write_text(json.dumps({'tag': 'v2.0.0', 'commit': private.name}))
        stages = self.root / 'stages'
        prepared = plugin.prepare_sources({'public': self.source, 'private': private}, stages)
        self.assertNotEqual(prepared['public']['identifier'], prepared['private']['identifier'])
        plugin.stage_sources(prepared)
        plugin.stage_sources(prepared)
        for item in prepared.values():
            self.assertTrue((item['stage'] / '.claude-plugin/plugin.json').exists())
        (prepared['private']['stage'] / 'commands/create-pr.md').write_text('modified')
        with self.assertRaisesRegex(ValueError, 'differs from release'):
            plugin.stage_sources(prepared)

    def test_install_sources_verifies_both_before_removing_legacy(self):
        private = self.root / ('e' * 40)
        shutil.copytree(self.source, private)
        manifest = private / '.claude-plugin/plugin.json'
        data = json.loads(manifest.read_text())
        data['name'] = 'agent-config-btmt'
        manifest.write_text(json.dumps(data))
        (private / '.agent-config-release.json').write_text(json.dumps({'tag': 'v2.0.0', 'commit': private.name}))
        prepared = plugin.prepare_sources({'public': self.source, 'private': private}, self.root / 'stages')
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            identifiers = plugin.install_sources(prepared, self.home)
            plugin.verify_sources(prepared, self.home)
        self.assertEqual(identifiers, {item['identifier'] for item in prepared.values()})
        self.assertNotIn(self.old_id, [item['id'] for item in self.listing])
        state = json.loads((self.home / '.agent-config-plugin.json').read_text())
        self.assertEqual(set(state['sources']), {'public', 'private'})
        self.assertIn(self.personal_id, [item['id'] for item in self.listing])

    def test_failed_multisource_install_preserves_legacy(self):
        self.wrong_version = True
        prepared = plugin.prepare_sources({'public': self.source}, self.root / 'stages')
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            with self.assertRaisesRegex(RuntimeError, 'requested plugin version'):
                plugin.install_sources(prepared, self.home)
        self.assertIn(self.old_id, [item['id'] for item in self.listing])
        self.assertTrue((self.home / '.agent-config-plugin-pending.json').exists())
        self.wrong_version = False
        with patch.object(plugin, 'run_claude', side_effect=self.fake_cli):
            plugin.install_sources(prepared, self.home)
            plugin.verify_sources(prepared, self.home)
        self.assertFalse((self.home / '.agent-config-plugin-pending.json').exists())

    def test_multiple_sources_reject_duplicate_plugin_name_before_staging(self):
        second = self.root / ('e' * 40)
        shutil.copytree(self.source, second)
        (second / '.agent-config-release.json').write_text(json.dumps({'tag': 'v2.0.0', 'commit': second.name}))
        stages = self.root / 'stages'
        with self.assertRaisesRegex(ValueError, 'collision'):
            plugin.prepare_sources({'public': self.source, 'private': second}, stages)
        self.assertFalse(stages.exists())


if __name__ == '__main__':
    unittest.main()
