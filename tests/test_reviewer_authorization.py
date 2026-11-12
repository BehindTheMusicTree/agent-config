import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRANT = "explicit request"


class ReviewerAuthorizationTests(unittest.TestCase):
    """Claude Code refuses unrequested subagents, so each workflow that spawns
    the reviewer must state inline that its invocation is the user's request."""

    def test_reviewer_grant_is_inline(self):
        for path in ('commands/review.md', 'skills/review/SKILL.md', 'commands/create-pr.md',
                     'skills/create-pr/SKILL.md', 'references/pr-policy.md'):
            with self.subTest(path=path):
                self.assertIn(GRANT, (ROOT / path).read_text())

    def test_claude_review_names_the_agent_call(self):
        self.assertIn('`subagent_type: general-purpose`', (ROOT / 'commands/review.md').read_text())

    def test_codex_skills_stay_client_neutral(self):
        for path in ('skills/review/SKILL.md', 'skills/create-pr/SKILL.md'):
            with self.subTest(path=path):
                text = (ROOT / path).read_text()
                self.assertNotIn('Agent tool', text)
                self.assertNotIn('subagent_type', text)

    def test_reviewer_does_not_delegate_further(self):
        self.assertIn('acting as the fresh reviewer', (ROOT / 'commands/review.md').read_text())


if __name__ == '__main__':
    unittest.main()
