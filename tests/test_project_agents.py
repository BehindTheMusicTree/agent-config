import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check-project-agents.py'
RENDER = SCRIPT.parent / 'render-project-rules.py'


class ProjectAdapterTests(unittest.TestCase):
    def test_generate_update_and_protect_local_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.agents/rules').mkdir(parents=True)
            rule = root / '.agents/rules/python.md'
            rule.write_text('first\n')
            (root / '.agents/scopes.json').write_text(json.dumps({'python': {'source': '.agents/rules/python.md', 'paths': ['**/*.py']}}))
            command = [sys.executable, str(RENDER), str(root)]
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(command + ['--apply'], capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            rule.write_text('second\n')
            self.assertEqual(subprocess.run(command + ['--apply'], capture_output=True).returncode, 0)
            adapter = root / '.claude/rules/python.md'
            adapter.write_text('local edit')
            rule.write_text('third\n')
            self.assertNotEqual(subprocess.run(command + ['--apply'], capture_output=True).returncode, 0)
            self.assertEqual(adapter.read_text(), 'local edit')

    def test_scoped_rule_checks_both_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.agents/rules').mkdir(parents=True)
            (root / '.claude/rules').mkdir(parents=True)
            (root / '.agents/rules/python.md').write_text('Python rule\n')
            (root / '.agents/scopes.json').write_text(json.dumps({'python': {'source': '.agents/rules/python.md', 'paths': ['**/*.py']}}))
            (root / 'AGENTS.md').write_text('Read .agents/rules/python.md for **/*.py\n')
            (root / 'CLAUDE.md').write_text('@AGENTS.md\n')
            adapter = root / '.claude/rules/python.md'
            adapter.write_text('---\npaths:\n  - "**/*.py"\n---\n\nPython rule\n')
            command = [sys.executable, str(SCRIPT), str(root)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            scopes = root / '.agents/scopes.json'
            scopes.unlink()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            scopes.write_text(json.dumps({'python': {'source': '.agents/rules/python.md', 'paths': ['**/*.py', '**/*.pyi']}}))
            (root / 'AGENTS.md').write_text('Read .agents/rules/python.md for **/*.pyi\n')
            adapter.write_text('---\npaths:\n  - "**/*.py"\n  - "**/*.pyi"\n---\n\nPython rule\n')
            self.assertIn('must reference source and scope paths', subprocess.run(command, capture_output=True, text=True).stderr)
            scopes.write_text(json.dumps({'python': {'source': '.agents/rules/python.md', 'paths': ['**/*.py']}}))
            adapter.write_text('---\npaths:\n  - "**/*.py"\n---\n\nPython rule\n')
            (root / 'AGENTS.md').write_text('Read .agents/rules/python.md for **/*.ts\nOther rule: **/*.py\n')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (root / 'AGENTS.md').write_text('Read .agents/rules/python.md for **/*.py\n')
            (root / '.claude/rules/obsolete.md').write_text('obsolete')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (root / '.claude/rules/obsolete.md').unlink()
            adapter.write_text('stale')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_skill_roots_cannot_be_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'AGENTS.md').write_text('instructions')
            (root / 'CLAUDE.md').write_text('@AGENTS.md')
            (root / '.agents').mkdir()
            (root / '.agents/skills').write_text('invalid')
            result = subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('skill root must be a directory', result.stderr)

    def test_skill_link_and_instruction_drift(self):
        with tempfile.TemporaryDirectory(prefix='project with spaces ') as directory:
            root = Path(directory)
            (root / 'AGENTS.md').write_text('# Instructions\n')
            (root / 'CLAUDE.md').write_text('@AGENTS.md\n')
            skill = root / '.agents/skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            links = root / '.claude/skills'
            links.mkdir(parents=True)
            (links / 'example').symlink_to('../../.agents/skills/example')

            def run():
                return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)

            self.assertEqual(run().returncode, 0)
            (root / 'CLAUDE.md').write_text('@AGENTS.md\nExtra divergent instruction\n')
            self.assertNotEqual(run().returncode, 0)
            (root / 'CLAUDE.md').write_text('@AGENTS.md\n')
            (links / 'example').unlink()
            (links / 'example').mkdir()
            self.assertIn('expected relative Claude skill link', run().stderr)

    def run_check(self, root):
        return subprocess.run([sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True)

    def make_root(self, directory):
        root = Path(directory)
        (root / 'AGENTS.md').write_text('Root\n')
        (root / 'CLAUDE.md').write_text('@AGENTS.md\n')
        return root

    def test_nested_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_root(directory)
            nested = root / 'pkg'
            nested.mkdir()
            (nested / 'AGENTS.md').write_text('Nested\n')
            self.assertIn('pkg/CLAUDE.md', self.run_check(root).stderr)
            (nested / 'CLAUDE.md').write_text('@AGENTS.md\nextra\n')
            self.assertIn('CLAUDE.md must contain only @AGENTS.md', self.run_check(root).stderr)
            (nested / 'CLAUDE.md').write_text('@AGENTS.md\n')
            self.assertEqual(self.run_check(root).returncode, 0)
            (nested / 'AGENTS.md').unlink()
            self.assertIn('pkg/AGENTS.md', self.run_check(root).stderr)

    def test_nested_claude_edge_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_root(directory)
            nested = root / 'pkg'
            nested.mkdir()
            (nested / 'AGENTS.md').write_text('Nested\n')
            (nested / 'CLAUDE.md').write_bytes(b'\xff\xfe')
            self.assertIn('CLAUDE.md must contain only', self.run_check(root).stderr)
            (nested / 'CLAUDE.md').unlink()
            (nested / 'CLAUDE.md').symlink_to('missing')
            self.assertIn('pkg/CLAUDE.md', self.run_check(root).stderr)

    def test_unrelated_instruction_names_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_root(directory)
            (root / 'docs').mkdir()
            (root / 'docs/copilot-instructions.md').write_text('docs')
            self.assertEqual(self.run_check(root).returncode, 0)

    def test_client_specific_instructions_forbidden(self):
        forbidden = ['.github/copilot-instructions.md', '.github/instructions/a.instructions.md', '.cursorrules',
                     '.cursor/rules/a.mdc', '.windsurfrules', '.windsurf/rules/a.md', '.clinerules', 'sub/GEMINI.md']
        for name in forbidden + ['sub/.github/copilot-instructions.md']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self.make_root(directory)
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('x')
                self.assertIn(f'{name}: client-specific', self.run_check(root).stderr)
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_root(directory)
            (root / '.cursor').mkdir()
            (root / '.cursor/environment.json').write_text('{}')
            self.assertEqual(self.run_check(root).returncode, 0)


if __name__ == '__main__':
    unittest.main()
