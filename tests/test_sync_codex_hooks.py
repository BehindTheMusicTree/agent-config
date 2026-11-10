import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('codex_hooks', ROOT / 'scripts/sync-codex-hooks.py')
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class CodexHooksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex hooks ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.codex = self.base / 'codex home'
        self.codex.mkdir()
        self.release = self.base / 'release one'
        (self.release / 'scripts').mkdir(parents=True)
        (self.release / hooks.SCRIPT).write_text('#!/bin/sh\n')
        self.path = self.codex / 'hooks.json'

    def installed(self):
        return json.loads(self.path.read_text())

    def apply(self, root=None):
        [(path, before, after)] = hooks.prepare(self.codex, root or self.release)
        self.assertEqual(path, self.path)
        self.path.write_text(after['text'])
        return before, after

    def test_creates_file_with_one_managed_entry(self):
        before, after = self.apply()
        self.assertIsNone(before)
        self.assertEqual(after['mode'], 0o600)
        [entry] = self.installed()['hooks']['PreToolUse']
        self.assertEqual(entry['matcher'], 'Bash')
        [handler] = entry['hooks']
        self.assertEqual(handler['type'], 'command')
        self.assertEqual(handler['timeout'], 5)
        self.assertEqual(handler['command'], f"'{self.release / hooks.SCRIPT}' --client codex")

    def test_up_to_date_has_no_change(self):
        self.apply()
        self.assertEqual(hooks.prepare(self.codex, self.release), [])

    def test_keeps_existing_hooks_and_other_events(self):
        existing = {
            'hooks': {
                'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': '/usr/bin/audit'}]}],
                'Stop': [{'hooks': [{'type': 'command', 'command': '/usr/bin/notify'}]}],
            },
            'other': 1,
        }
        self.path.write_text(json.dumps(existing))
        self.path.chmod(0o640)
        _, after = self.apply()
        self.assertEqual(after['mode'], 0o640)
        data = self.installed()
        self.assertEqual(data['other'], 1)
        self.assertEqual(data['hooks']['Stop'], existing['hooks']['Stop'])
        self.assertEqual(data['hooks']['PreToolUse'][0], existing['hooks']['PreToolUse'][0])
        self.assertEqual(len(data['hooks']['PreToolUse']), 2)

    def test_next_release_replaces_the_managed_entry_in_place(self):
        self.path.write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': '/usr/bin/audit'}]}]}}))
        self.apply()
        newer = self.base / 'release two'
        (newer / 'scripts').mkdir(parents=True)
        (newer / hooks.SCRIPT).write_text('#!/bin/sh\n')
        self.apply(newer)
        entries = self.installed()['hooks']['PreToolUse']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['hooks'][0]['command'], '/usr/bin/audit')
        self.assertIn('release two', entries[1]['hooks'][0]['command'])

    def test_managed_handler_sharing_an_entry_is_split_out(self):
        old = hooks.command_for(self.base / 'old release')
        self.path.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
            {'type': 'command', 'command': '/usr/bin/audit'}, {'type': 'command', 'command': old}]}]}}))
        self.apply()
        commands = [h['command'] for e in self.installed()['hooks']['PreToolUse'] for h in e['hooks']]
        self.assertEqual(sorted(commands), sorted(['/usr/bin/audit', f"'{self.release / hooks.SCRIPT}' --client codex"]))

    def test_invalid_json_or_shape_fails_without_writing(self):
        for text in ('{not json', '[]', '{"hooks": []}', '{"hooks": {"PreToolUse": {}}}'):
            self.path.write_text(text)
            with self.assertRaises(ValueError):
                hooks.prepare(self.codex, self.release)
            self.assertEqual(self.path.read_text(), text)

    def test_refuses_symlinked_hooks_file(self):
        target = self.base / 'elsewhere.json'
        target.write_text('{}')
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            hooks.prepare(self.codex, self.release)

    def test_missing_release_script_fails(self):
        with self.assertRaisesRegex(ValueError, 'Missing graphify freshness hook'):
            hooks.prepare(self.codex, self.base)


if __name__ == '__main__':
    unittest.main()
