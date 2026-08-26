"""All seven memory-editor chore SKILL.md files must run the dispatch claim step.

TRDD-EBQVHTP4: five of the seven wikimem-editor chore skills (consolidate,
conflict, repair, atomize, harvest) never got the claim-step patch that split
and retro-lesson received — they still told the dispatched agent to pick its
own scope. That reopened the two races the claim step exists to close
(janitor#150, janitor#242). This test pins the invariant for all seven at
once so an eighth chore skill cannot be added without it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

CHORE_SKILLS = [
    "janitor-memory-consolidate",
    "janitor-memory-conflict",
    "janitor-memory-repair",
    "janitor-memory-atomize",
    "janitor-memory-harvest",
    "janitor-memory-split",
    "janitor-memory-retro-lesson",
    "janitor-memory-enrich",
]


def _skill_text(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.is_file(), f"missing SKILL.md for {name}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("skill_name", CHORE_SKILLS)
def test_skill_runs_the_dispatch_claim_script(skill_name: str) -> None:
    """Every chore skill must invoke memory_dispatch_claim.py to get its scope."""
    text = _skill_text(skill_name)
    assert "memory_dispatch_claim.py" in text, (
        f"{skill_name}/SKILL.md never runs memory_dispatch_claim.py — it can "
        "still self-select a scope (the janitor#150 / janitor#242 failure class)"
    )


@pytest.mark.parametrize("skill_name", CHORE_SKILLS)
def test_skill_forbids_the_legacy_pending_slot(skill_name: str) -> None:
    """Every chore skill must explicitly BAN the legacy memory-maint-pending.json slot.

    Naming it is necessary but nowhere near sufficient: the retired file is still on disk,
    so a skill that merely mentions it — or, worse, still tells the agent to read it —
    would satisfy a presence check while leaving the janitor#242 race wide open. The
    prohibition is asserted POSITIVELY, on the sentence that names the slot.
    """
    text = _skill_text(skill_name)
    assert "memory-maint-pending.json" in text, (
        f"{skill_name}/SKILL.md does not name (and so cannot forbid) the legacy "
        "memory-maint-pending.json slot"
    )
    # The mention and its prohibition can be split across wrapped lines, so look at the
    # whitespace-flattened window that leads up to the slot name.
    flat = " ".join(text.split())
    idx = flat.index("memory-maint-pending.json")
    window = flat[max(0, idx - 160):idx]  # ENDS at the mention — an open-ended slice would
    # scan the whole rest of the file and pass on any stray "never" further down (it did).
    assert re.search(r"\b(do not|don't|never)\b", window, re.I), (
        f"{skill_name}/SKILL.md names the legacy slot without forbidding it. Ceasing to "
        "point at a file that still exists is not the same as banning it — that is exactly "
        "how the split skill lost this line during a size trim (ec28365d)."
    )


@pytest.mark.parametrize("skill_name", CHORE_SKILLS)
def test_skill_does_not_hand_the_agent_a_scope_to_pick(skill_name: str) -> None:
    """No chore skill may offer the agent a scope MENU.

    The defect TRDD-EBQVHTP4 documents was not a missing script — it was a line like
    `MEMDIR="$LOCAL_MEM"   # or $USER_MEM` that invited the agent to choose. The claim step
    is worthless while a choice is still on offer next to it, so the invitation is what
    this pins.
    """
    text = _skill_text(skill_name)
    offenders = [
        ln.strip()
        for ln in text.splitlines()
        if re.search(r"or \$?\{?(USER|LOCAL|PROJECT)_MEM", ln)
        or re.search(r"--scope\s+<[A-Z|]+>", ln)
    ]
    assert not offenders, (
        f"{skill_name}/SKILL.md still offers a scope to pick: {offenders}. The scope comes "
        "from memory_dispatch_claim.py, or the pass does not run."
    )
