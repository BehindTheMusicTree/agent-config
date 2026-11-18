import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('claude_permissions', ROOT / 'scripts/sync-claude-permissions.py')
perms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perms)
spec = importlib.util.spec_from_file_location('global_instructions', ROOT / 'scripts/install-instructions.py')
instructions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(instructions)


class ClaudePermissionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='permissions ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / 'claude'
        self.home.mkdir()
        self.n = 0

    def source(self, fragment):
        self.n += 1
        root = self.base / f'source{self.n}'
        (root / 'settings').mkdir(parents=True)
        if fragment is not None:
            (root / 'settings/permissions.json').write_text(json.dumps(fragment))
        return root

    def settings(self, data=None):
        path = self.home / 'settings.json'
        if data is not None:
            path.write_text(json.dumps(data))
        return json.loads(path.read_text())

    def sync(self, *fragments):
        roots = [self.source(f) for f in fragments]
        instructions.apply(perms.prepare(self.home, roots))
        return roots

    def test_merges_and_keeps_user_rules_and_other_keys(self):
        self.settings({'model': 'opus', 'permissions': {'allow': ['Bash(ls)'], 'defaultMode': 'plan'}})
        self.sync({'allow': ['Bash(vps-read *)'], 'ask': ['Bash(rm *)']})
        data = self.settings()
        self.assertEqual(data['permissions']['allow'], ['Bash(ls)', 'Bash(vps-read *)'])
        self.assertEqual(data['permissions']['ask'], ['Bash(rm *)'])
        self.assertEqual((data['model'], data['permissions']['defaultMode']), ('opus', 'plan'))

    def test_second_sync_changes_nothing(self):
        roots = self.sync({'allow': ['Bash(a)']})
        self.assertEqual(perms.prepare(self.home, roots), [])

    def test_removed_managed_rule_disappears_but_user_rule_stays(self):
        self.settings({'permissions': {'allow': ['Bash(mine)']}})
        self.sync({'allow': ['Bash(a)', 'Bash(b)']})
        self.sync({'allow': ['Bash(b)']})
        self.assertEqual(self.settings()['permissions']['allow'], ['Bash(mine)', 'Bash(b)'])

    def test_user_rule_matching_a_managed_rule_is_released_when_fragment_drops_it(self):
        self.sync({'allow': ['Bash(a)']})
        self.sync(None)
        self.assertEqual(self.settings()['permissions']['allow'], [])

    def test_retire_removes_unmanaged_rules_from_any_list(self):
        self.settings({'permissions': {'allow': ['Bash(old)', 'Bash(keep)'], 'ask': ['Bash(old)']}})
        self.sync({'retire': ['Bash(old)']})
        permissions = self.settings()['permissions']
        self.assertEqual((permissions['allow'], permissions['ask']), (['Bash(keep)'], []))

    def test_no_fragment_and_no_state_writes_nothing(self):
        self.assertEqual(perms.prepare(self.home, [self.source(None)]), [])

    def test_conflicts_fail_fast(self):
        bad = [
            {'allow': ['Bash(a)'], 'deny': ['Bash(a)']},
            {'allow': ['Bash(a)', 'Bash(a)']},
            {'allow': ['Bash(a)'], 'retire': ['Bash(a)']},
            {'allow': 'Bash(a)'},
            {'allow': [' Bash(a)']},
            {'permit': []},
        ]
        for fragment in bad:
            with self.subTest(fragment=fragment), self.assertRaises(ValueError):
                perms.prepare(self.home, [self.source(fragment)])

    def test_same_rule_across_sources_fails(self):
        with self.assertRaises(ValueError):
            perms.prepare(self.home, [self.source({'allow': ['Bash(a)']}), self.source({'ask': ['Bash(a)']})])

    def test_unexpected_settings_shape_fails(self):
        for data in ({'permissions': []}, {'permissions': {'allow': 'x'}}, {'permissions': {'allow': [1]}}):
            with self.subTest(data=data):
                self.settings(data)
                with self.assertRaises(ValueError):
                    perms.prepare(self.home, [self.source({'allow': ['Bash(a)']})])

    def test_rollback_restores_files(self):
        self.settings({'permissions': {'allow': ['Bash(mine)']}})
        original = (self.home / 'settings.json').read_text()
        changes = perms.prepare(self.home, [self.source({'allow': ['Bash(a)']})])
        instructions.apply(changes)
        instructions.apply([(path, after, before) for path, before, after in reversed(changes)])
        self.assertEqual((self.home / 'settings.json').read_text(), original)
        self.assertFalse((self.home / perms.STATE).exists())
