import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate-plans.sh"


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


class MigratePlansTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "myrepo"
        run("git", "init", "-q", "-b", "main", str(self.repo))
        run("git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-q", "--allow-empty", "-m", "init")
        self.wt = self.root / "wt"
        run("git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "feat/x", str(self.wt))
        plans = self.wt / ".agent-plans"
        (plans / "sub").mkdir(parents=True)
        (plans / "a.md").write_text("a")
        (plans / "sub" / "b.md").write_text("b")
        (plans / ".gitignore").write_text("*\n")
        self.dest = self.repo / ".git" / "agent-plans" / "myrepo-feat-x"

    def test_dry_run_changes_nothing(self):
        out = run(str(SCRIPT), str(self.root))
        self.assertIn("mode=dry-run dirs=1 moved=2 kept=0", out)
        self.assertTrue((self.wt / ".agent-plans" / "a.md").exists())
        self.assertFalse(self.dest.exists())

    def test_apply_moves_without_overwriting(self):
        self.dest.mkdir(parents=True)
        (self.dest / "a.md").write_text("existing")
        out = run(str(SCRIPT), "--apply", str(self.root))
        self.assertIn("moved=1 kept=1", out)
        self.assertEqual((self.dest / "a.md").read_text(), "existing")
        self.assertEqual((self.dest / "sub" / "b.md").read_text(), "b")
        self.assertTrue((self.wt / ".agent-plans" / "a.md").exists())

    def test_apply_removes_emptied_directory(self):
        run(str(SCRIPT), "--apply", str(self.root))
        self.assertEqual((self.dest / "a.md").read_text(), "a")
        self.assertFalse((self.wt / ".agent-plans").exists())


if __name__ == "__main__":
    unittest.main()
