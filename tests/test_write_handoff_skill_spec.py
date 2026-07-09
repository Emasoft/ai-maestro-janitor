"""Markdown-spec guards for the janitor-write-handoff skill (TRDD-498LEWZ4).

The skill IS the executable artifact — an agent follows the SKILL.md text — so these
tests pin the shipped instructions to the requested behavior: the rich handoff must
include an open-issues-and-why section, and must reference external memories (wikimem
pages, native memory notes) by pointer instead of restating their content.
"""

import unittest
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "janitor-write-handoff"
    / "SKILL.md"
)


class TestWriteHandoffSkillSpec(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_open_issues_section_is_instructed(self):
        """The authored handoff must cover the OPEN issues and WHY each is unsolved."""
        self.assertIn("Open issues", self.text)
        self.assertIn("WHY", self.text)
        # The WHY prompts an intelligent diagnosis, not a bare list.
        self.assertIn("blocked on", self.text.lower())

    def test_memory_pointer_economy_is_instructed(self):
        """Open issues must POINT at durable context (wikimem / memory / TRDD / issue)
        instead of restating it — the token-saving half of the user's ask."""
        self.assertIn("memgrep recall", self.text)
        self.assertIn("wikimem", self.text.lower())
        self.assertIn("TRDD-<id8>", self.text)
        self.assertIn("NEVER paste what a reference can carry", self.text)

    def test_restate_prohibition_covers_memories(self):
        """The complement-not-duplicate economy explicitly extends to memory pages."""
        self.assertIn("reference it by name instead of restating it", self.text)


if __name__ == "__main__":
    unittest.main()
