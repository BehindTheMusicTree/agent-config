import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/render-workflows.py'


class RenderTests(unittest.TestCase):
    def test_write_failure_restores_previous_outputs(self):
        spec = importlib.util.spec_from_file_location('render_workflows', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'workflows').mkdir()
            (root / 'commands').mkdir()
            (root / 'skills/example').mkdir(parents=True)
            (root / 'workflows/example.json').write_text(json.dumps({'blocks': [{'shared': 'new'}]}))
            first = root / 'commands/example.md'
            second = root / 'skills/example/SKILL.md'
            first.write_text('original')
            second.write_text('original')
            digest = hashlib.sha256(b'original').hexdigest()
            (root / '.workflow-generated.json').write_text(json.dumps({'commands/example.md': digest, 'skills/example/SKILL.md': digest}))
            original_write = Path.write_text
            def failing_write(path, *args, **kwargs):
                if path == second:
                    raise PermissionError('read-only')
                return original_write(path, *args, **kwargs)
            with patch.object(Path, 'write_text', failing_write):
                with self.assertRaises(OSError):
                    module.render(root, True)
            self.assertEqual(first.read_text(), 'original')
            self.assertEqual(second.read_text(), 'original')

    def test_invalid_output_does_not_change_other_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workflows').mkdir()
            (root / 'commands').mkdir()
            (root / 'skills/example/SKILL.md').mkdir(parents=True)
            (root / 'commands/example.md').write_text('original')
            (root / 'workflows/example.json').write_text(json.dumps({'blocks': [{'shared': 'new'}]}))
            result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--apply'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'commands/example.md').read_text(), 'original')

    def test_creates_new_workflow_and_rejects_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workflows').mkdir()
            (root / 'workflows/example.json').write_text(json.dumps({'blocks': [{'shared': 'content\n'}]}))
            command = [sys.executable, str(SCRIPT), '--root', str(root)]
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(command + ['--apply'], capture_output=True).returncode, 0)
            self.assertEqual((root / 'skills/example/SKILL.md').read_text(), 'content\n')
            (root / 'workflows/example.json').unlink()
            self.assertNotEqual(subprocess.run(command + ['--apply'], capture_output=True).returncode, 0)
            self.assertTrue((root / 'commands/example.md').exists())

    def test_drift_and_regeneration(self):
        with tempfile.TemporaryDirectory(prefix='workflow project ') as directory:
            root = Path(directory)
            (root / 'workflows').mkdir()
            (root / 'commands').mkdir()
            (root / 'skills/example').mkdir(parents=True)
            (root / 'workflows/example.json').write_text(json.dumps({'blocks': [
                {'shared': 'common\n'}, {'claude': 'claude\n', 'codex': 'codex\n'}
            ]}))
            (root / 'commands/example.md').write_text('common\nclaude\n')
            (root / 'skills/example/SKILL.md').write_text('common\ncodex\n')
            def run(*args):
                return subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), *args], capture_output=True, text=True)
            self.assertEqual(run('--apply').returncode, 0)
            self.assertEqual(run().returncode, 0)
            (root / 'commands/example.md').write_text('changed')
            self.assertNotEqual(run().returncode, 0)
            self.assertNotEqual(run('--apply').returncode, 0)
            self.assertEqual((root / 'commands/example.md').read_text(), 'changed')
            (root / 'commands/example.md').write_text('common\nclaude\n')
            self.assertEqual(run().returncode, 0)

    def test_invalid_source_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workflows').mkdir()
            (root / 'workflows/example.json').write_text('{"blocks": [{"bad": "x"}]}')
            result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--apply'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'commands').exists())
