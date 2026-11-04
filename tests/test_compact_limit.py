import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('compact_limit', ROOT / 'scripts/sync-compact-limit.py')
compact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compact)


class CompactLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='compact limit ')
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.claude = base / 'claude'
        self.codex = base / 'codex'
        self.claude.mkdir()
        self.codex.mkdir()
        self.reserve = compact.load_reserve()

    def set_claude(self, value):
        (self.claude / 'settings.json').write_text(json.dumps({'env': {compact.CLAUDE_KEY: value}, 'model': 'opus'}))

    def test_unset_claude_window_leaves_codex_alone(self):
        (self.claude / 'settings.json').write_text('{"env": {}}')
        self.assertEqual(compact.prepare(self.claude, self.codex), [])

    def test_replaces_top_level_key_and_preserves_the_rest(self):
        self.set_claude('160000')
        original = 'model = "gpt"\nmodel_auto_compact_token_limit = 150000 # mine\n\n[tui]\nmodel_auto_compact_token_limit = 1\n'
        (self.codex / 'config.toml').write_text(original)
        [(path, before, after)] = compact.prepare(self.claude, self.codex)
        expected = original.replace('150000 # mine', f'{160000 - self.reserve} # mine')
        self.assertEqual(after['text'], expected)
        self.assertEqual(before['text'], original)

    def test_inserts_key_before_first_table(self):
        self.set_claude(160000)
        (self.codex / 'config.toml').write_text('[tui]\nx = 1\n')
        [(_, _, after)] = compact.prepare(self.claude, self.codex)
        self.assertTrue(after['text'].startswith(f'model_auto_compact_token_limit = {160000 - self.reserve}\n[tui]'))

    def test_up_to_date_has_no_change(self):
        self.set_claude('160000')
        (self.codex / 'config.toml').write_text(f'model_auto_compact_token_limit = {160000 - self.reserve}\n')
        self.assertEqual(compact.prepare(self.claude, self.codex), [])

    def test_rejects_invalid_or_too_small_window(self):
        for value in ('abc', '-5', True):
            self.set_claude(value)
            with self.assertRaises(ValueError):
                compact.prepare(self.claude, self.codex)
        self.set_claude(str(self.reserve))
        with self.assertRaises(ValueError):
            compact.prepare(self.claude, self.codex)

    def test_rejects_duplicate_top_level_key(self):
        self.set_claude('160000')
        (self.codex / 'config.toml').write_text('model_auto_compact_token_limit = 1\nmodel_auto_compact_token_limit = 2\n')
        with self.assertRaises(ValueError):
            compact.prepare(self.claude, self.codex)

    def test_refuses_symlinked_codex_config(self):
        self.set_claude('160000')
        target = self.codex.parent / 'elsewhere.toml'
        target.write_text('')
        (self.codex / 'config.toml').symlink_to(target)
        with self.assertRaises(ValueError):
            compact.prepare(self.claude, self.codex)


    def test_ignores_key_text_inside_strings_and_arrays(self):
        self.set_claude('160000')
        original = ('a = [\n  [1, 2],\n]\nmodel_auto_compact_token_limit = 5\n'
                    'b = """\nmodel_auto_compact_token_limit = 7\n"""\n[tui]\nx = 1\n')
        (self.codex / 'config.toml').write_text(original)
        [(_, _, after)] = compact.prepare(self.claude, self.codex)
        self.assertEqual(after['text'], original.replace('= 5\n', f'= {160000 - self.reserve}\n'))

    def test_handles_indented_and_quoted_keys(self):
        self.set_claude('160000')
        for original in ('  model_auto_compact_token_limit = 5\n', '"model_auto_compact_token_limit" = 5\n'):
            (self.codex / 'config.toml').write_text(original)
            [(_, _, after)] = compact.prepare(self.claude, self.codex)
            self.assertIn(f'model_auto_compact_token_limit = {160000 - self.reserve}', after['text'])

    def test_refuses_key_defined_only_as_dotted_or_inline_table(self):
        self.set_claude('160000')
        (self.codex / 'config.toml').write_text('model_auto_compact_token_limit = 5 ; junk\n')
        with self.assertRaises(Exception):
            compact.prepare(self.claude, self.codex)

    def test_rejects_non_object_env(self):
        for settings in ('{"env": null}', '{"env": []}', '[]'):
            (self.claude / 'settings.json').write_text(settings)
            if settings == '{"env": null}':
                self.assertIsNone(compact.claude_window(self.claude))
                continue
            with self.assertRaises(ValueError):
                compact.claude_window(self.claude)

    def test_requires_tomllib(self):
        from unittest.mock import patch
        self.set_claude('160000')
        with patch.dict('sys.modules', {'tomllib': None}), self.assertRaises(ValueError):
            compact.prepare(self.claude, self.codex)

    def test_reserve_comes_from_given_source_root(self):
        self.set_claude('160000')
        source = self.codex.parent / 'snapshot'
        (source / 'settings').mkdir(parents=True)
        (source / 'settings/compact.json').write_text('{"claudeCompactReserveTokens": 10000}')
        [(_, _, after)] = compact.prepare(self.claude, self.codex, source)
        self.assertEqual(after['text'], 'model_auto_compact_token_limit = 150000\n')
        with self.assertRaises(ValueError):
            compact.prepare(self.claude, self.codex, self.codex.parent / 'old-snapshot')

if __name__ == '__main__':
    unittest.main()
