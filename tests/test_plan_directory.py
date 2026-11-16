import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('plan_directory', ROOT / 'scripts/sync-plan-directory.py')
plans = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plans)


class PlanDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='plan directory ')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home / 'settings.json'

    def test_creates_settings(self):
        [(path, before, after)] = plans.prepare(self.home)
        self.assertEqual(path, self.path)
        self.assertIsNone(before)
        self.assertEqual(json.loads(after['text']), {'plansDirectory': '.agent-plans'})
        self.assertEqual(after['mode'], 0o600)

    def test_preserves_keys_and_permissions_and_is_idempotent(self):
        original = {'env': {'EXAMPLE': 'value'}, 'model': 'opus', 'permissions': {'allow': []}}
        self.path.write_text(json.dumps(original))
        self.path.chmod(0o640)
        [(_, before, after)] = plans.prepare(self.home)
        self.assertEqual(json.loads(before['text']), original)
        self.assertEqual(json.loads(after['text']), {**original, 'plansDirectory': '.agent-plans'})
        self.assertEqual(after['mode'], 0o640)
        self.path.write_text(after['text'])
        self.assertEqual(plans.prepare(self.home), [])

    def test_refuses_differing_value(self):
        for value in ('plans', None, False, 1):
            with self.subTest(value=value):
                text = json.dumps({'plansDirectory': value})
                self.path.write_text(text)
                with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
                    plans.prepare(self.home)
                self.assertEqual(self.path.read_text(), text)

    def test_rejects_invalid_settings(self):
        for text in ('[]', 'null', '{broken'):
            self.path.write_text(text)
            with self.assertRaises(ValueError):
                plans.prepare(self.home)

    def test_rejects_symlink(self):
        target = self.home / 'target'
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            plans.prepare(self.home)
        self.assertFalse(target.exists())
