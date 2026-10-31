import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='validate agent ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.claude-plugin').mkdir()
        (self.root / '.claude-plugin/plugin.json').write_text(json.dumps({'name': 'agent-config', 'version': '1.0.0'}))
        (self.root / '.claude-plugin/marketplace.json').write_text(json.dumps({'plugins': [{'name': 'agent-config'}]}))
        (self.root / 'commands').mkdir()
        (self.root / 'commands/example.md').write_text('example')
        (self.root / 'skills/example').mkdir(parents=True)
        self.skill = self.root / 'skills/example/SKILL.md'
        self.skill.write_text('---\nname: example\ndescription: An example skill\n---\n\nDo work.\n')

    def validate(self):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/validate.py'), str(self.root)], capture_output=True, text=True)

    def test_missing_counterpart_and_dependency_are_reported(self):
        self.assertEqual(self.validate().returncode, 0)
        self.skill.write_text(self.skill.read_text() + '\nInvoke `$missing`.\n')
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing skill missing', result.stderr)
        (self.root / 'commands/example.md').unlink()
        result = self.validate()
        self.assertIn('Command/skill mismatch', result.stderr)

    def test_invalid_plugin_version_and_frontmatter_fail(self):
        (self.root / '.claude-plugin/plugin.json').write_text('{"name":"agent-config","version":"latest"}')
        self.skill.write_text('---\nname: example\ndescription: Example\nunknown: value\n---\n')
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('semantic version', result.stderr)
        self.assertIn('unsupported frontmatter', result.stderr)

    def test_shared_reference_must_exist_for_both_clients(self):
        self.skill.write_text(self.skill.read_text() + '\nRead `$SKILL_REPO_ROOT/references/pr-policy.md`.\n')
        (self.root / 'commands/example.md').write_text('Read `${CLAUDE_PLUGIN_ROOT}/references/pr-policy.md`.')
        self.assertNotEqual(self.validate().returncode, 0)
        (self.root / 'references').mkdir()
        (self.root / 'references/pr-policy.md').write_text('Policy')
        self.assertEqual(self.validate().returncode, 0)


if __name__ == '__main__':
    unittest.main()
