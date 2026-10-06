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


def _flat(text: str) -> str:
    """Collapse line wraps so a required sentence is matched whatever its wrapping."""
    return " ".join(text.split())


def test_split_skill_skips_over_cap_components_instead_of_stopping() -> None:
    """janitor#326 (9ad6b9f6): step 1 skips `tier: component` pages, never stops on one.

    Without the instruction the agent picks the largest over-cap page, hits a component
    nobody but a human can re-tier, and every later run re-dispatches into the same wall.
    """
    text = _flat(_skill_text("janitor-memory-split"))
    assert (
        "skipping `tier: component` (the scheduler surfaces those; never stop on one)" in text
    ), "split SKILL.md lost the rule that an over-cap component page is skipped, not stopped on"


def test_repair_skill_page_description_rule_keeps_and_proves_every_symptom_phrase() -> None:
    """janitor#331: a page-description rewrite keeps every symptom phrase, proven by recall.

    Recall ranks on description + title + tags only, so a dropped phrase makes the page
    unfindable by it. The rule text lives in references/repair-background.md; SKILL.md
    carries the one-line pointer.
    """
    skill = _flat(_skill_text("janitor-memory-repair"))
    assert "losing no recall phrase" in skill, "repair SKILL.md lost the no-recall-loss clause"
    background = _flat(
        (SKILLS_DIR / "janitor-memory-repair/references/repair-background.md").read_text(
            encoding="utf-8"
        )
    )
    for required in (
        "keep every distinctive symptom/error/name phrase",
        'memgrep recall "<phrase>"',
        "must still list this page",
    ):
        assert required in background, f"repair-background.md lost the #331 rule text: {required!r}"


def test_repair_skill_page_description_pointer_names_an_existing_heading() -> None:
    """janitor#331: SKILL.md's `(repair-background § <heading>)` pointer must name a real heading.

    bdbf5b16 folded the section the pointer named ("page description") into another one and
    left the pointer dangling.
    """
    headings = [
        ln[3:].strip()
        for ln in (SKILLS_DIR / "janitor-memory-repair/references/repair-background.md")
        .read_text(encoding="utf-8")
        .splitlines()
        if ln.startswith("## ")
    ]
    skill_lines = _skill_text("janitor-memory-repair").splitlines()
    pointer_lines = [ln for ln in skill_lines if "losing no recall phrase" in ln]
    assert pointer_lines, "the page-description pointer line vanished from repair SKILL.md"
    for ln in pointer_lines:
        assert any(f"repair-background § {h}" in ln for h in headings), (
            f"pointer does not name an existing repair-background.md heading: {ln.strip()!r}"
        )
