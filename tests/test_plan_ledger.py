import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('plan_ledger', ROOT / 'scripts' / 'plan-ledger.py')
plan_ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan_ledger)


class PlanLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='plan ledger ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.git('init', '-q', '-b', 'main')
        self.plans = self.root / '.agent-plans'
        self.plans.mkdir()
        (self.plans / '.gitignore').write_text('*\n!.gitignore\n')
        # Committed like in real repos, so status stays clean without a global exclude (as on CI);
        # -f because a local global exclude may ignore .agent-plans/ entirely.
        self.git('add', '-f', '.agent-plans/.gitignore')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-q', '-m', 'initial')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def states(self):
        return {plan['path']: plan['state'] for plan in plan_ledger.status(self.root)['plans']}

    def test_record_then_reconciled_modified_and_unrecorded(self):
        (self.plans / 'topic.md').write_text('decision\n')
        recorded = plan_ledger.record(self.root, 42)
        self.assertEqual(recorded['pr'], 42)
        self.assertEqual(recorded['head'], self.git('rev-parse', 'HEAD').strip())
        self.assertEqual(Path(recorded['ledger']).parent, Path(self.git('rev-parse', '--absolute-git-dir').strip()))
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.states(), {'.agent-plans/topic.md': 'reconciled'})
        self.assertEqual(plan_ledger.status(self.root)['pr'], 42)

        (self.plans / 'topic.md').write_text('decision changed after the PR\n')
        (self.plans / 'later.md').write_text('new\n')
        self.assertEqual(self.states(), {'.agent-plans/topic.md': 'modified', '.agent-plans/later.md': 'unrecorded'})

    def test_excluded_plan_stays_unrecorded(self):
        (self.plans / 'topic.md').write_text('this task\n')
        (self.plans / 'other.md').write_text('another task\n')
        plan_ledger.record(self.root, 7, ['.agent-plans/other.md'])
        self.assertEqual(self.states(), {'.agent-plans/topic.md': 'reconciled', '.agent-plans/other.md': 'unrecorded'})
        with self.assertRaises(ValueError):
            plan_ledger.record(self.root, 7, ['.agent-plans/typo.md'])

    def test_nested_plans_count_and_gitignore_is_excluded(self):
        nested = self.root / 'packages' / 'app' / '.agent-plans'
        nested.mkdir(parents=True)
        (nested / '.gitignore').write_text('*\n')
        (nested / 'app.md').write_text('nested\n')
        (self.plans / 'notes').mkdir()
        (self.plans / 'notes' / '.gitignore').write_text('a plan file named like an ignore file\n')
        self.assertEqual(set(plan_ledger.inventory(self.root)),
                         {'packages/app/.agent-plans/app.md', '.agent-plans/notes/.gitignore'})

    def test_linked_worktrees_own_their_plans(self):
        linked = self.root / '.claude' / 'worktrees' / 'other'
        self.git('worktree', 'add', '-q', '-b', 'other', str(linked))
        self.assertTrue((linked / '.agent-plans' / '.gitignore').is_file())
        (linked / '.agent-plans' / 'other.md').write_text('other session\n')
        self.assertEqual(plan_ledger.inventory(self.root), {})

    def test_no_plans_and_no_ledger(self):
        self.assertEqual(plan_ledger.status(self.root), {'ledger': None, 'pr': None, 'head': None, 'plans': []})
        (self.plans / 'topic.md').write_text('x\n')
        self.assertEqual(self.states(), {'.agent-plans/topic.md': 'unrecorded'})

    def test_corrupt_or_prless_ledger_fails(self):
        path = plan_ledger.ledger_path(self.root)
        for content in ('not json', '{"plans": {}}', '{"pr": true, "plans": {}}', '{"pr": 3, "plans": []}'):
            path.write_text(content)
            with self.assertRaises(ValueError):
                plan_ledger.status(self.root)

    def test_symlinked_plan_fails(self):
        (self.plans / 'link.md').symlink_to(self.root / 'elsewhere.md')
        with self.assertRaises(ValueError):
            plan_ledger.inventory(self.root)

    def test_symlinked_plan_directories_fail(self):
        target = self.root / 'outside'
        target.mkdir()
        (target / 'hidden.md').write_text('plan\n')
        (self.plans / 'sub').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            plan_ledger.inventory(self.root)
        (self.plans / 'sub').unlink()
        nested = self.root / 'pkg'
        nested.mkdir()
        (nested / '.agent-plans').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            plan_ledger.inventory(self.root)


if __name__ == '__main__':
    unittest.main()
