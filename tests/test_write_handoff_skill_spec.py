"""Markdown-spec guards for the janitor-write-handoff skill (TRDD-498LEWZ4, TRDD-ZQ02QG1L).

The skill IS the executable artifact — an agent follows the SKILL.md text — so these tests
pin the shipped instructions to the requested behavior.

THE CONTRACT INVERTED ON 2026-09-03 (owner directive). It used to require that the skill
INSTRUCT THE MODEL to author a rich handoff: an open-issues-and-why section, pointer economy,
a restate prohibition. Those tests were correct for a model-authored handoff and are exactly
what had to go: the handoff is now composed OUT OF PROCESS by `compose_agent_handoff.py` via
the `llm-ext` CLI, so instructing the model to write prose is the defect, not the requirement.

The sections themselves did not disappear — they moved into the summarizer's job. What these
tests now guard is that the SKILL never asks the model to do that work itself, and never
offers model authorship as a fallback when the CLI is unavailable. That fallback is the one
way the removed cost could silently return, since its output would look perfectly correct.
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

    def test_composition_is_delegated_to_the_script(self):
        """The skill's first instruction must be to RUN the composer, not to write."""
        self.assertIn("compose_agent_handoff.py", self.text)
        self.assertIn("--project-root", self.text)

    def test_the_summary_is_produced_out_of_process(self):
        """`llm-ext` is named as the summarizer, and the zero-cost claim is explicit —
        a reader must not have to infer where the intelligence comes from."""
        self.assertIn("llm-ext", self.text)
        self.assertIn("out of process", self.text.lower())

    def test_the_skill_never_asks_the_model_to_author_the_handoff(self):
        """The regression this whole change exists to prevent. `Write` here means the
        Write TOOL: a step telling the model to Write the handoff is model authorship
        returning under another name."""
        self.assertIn("you author nothing", self.text.lower())
        self.assertIn("Never Write a handoff by hand", self.text)

    def test_llm_ext_failure_does_not_fall_back_to_model_authorship(self):
        """SUMMARY_FAILED must degrade to the free mechanical handoff. A fallback to
        authoring would restore the exact cost this removed, and would look correct while
        doing it — which is why it is pinned rather than left to judgment."""
        self.assertIn("SUMMARY_FAILED", self.text)
        self.assertIn("Do NOT fall back to authoring the handoff yourself", self.text)
        self.assertIn("precompact-handoff.md", self.text)

    def test_the_single_writer_invariant_is_still_stated(self):
        """TRDD-5RXBI65T survives the rewrite: never Write to the fixed legacy path, which
        had several uncoordinated writers and lost handoffs twice in two days."""
        self.assertIn("agent-handoff.md", self.text)
        self.assertIn("handoff_files.write", self.text)


if __name__ == "__main__":
    unittest.main()
