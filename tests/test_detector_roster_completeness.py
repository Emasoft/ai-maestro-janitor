"""The detector roster must name every registered detector (TRDD-IEW2K659).

THE DEFECT THIS EXISTS TO END, measured twice: on 2026-08-14 the roster documented 39 detectors
while `dispatch.py` registered 72; on 2026-08-16 it named 45 of 73. Nearly half the fleet was
undocumented, and nothing anywhere went red.

The card's own diagnosis is the reason this file exists: *"An inventory has no test. Every other
claim in this repo is defended by something that reddens — a wrong type fails mypy, a wrong
behaviour fails pytest, a wrong lint config fails ruff. A prose list of 39 things, in a file
nothing executes, cannot fail — it simply drifts, one un-updated addition at a time, while
continuing to read as authoritative."* That is the absence of a failure signal being mistaken for
the absence of a defect, so the fix is not another careful reconciliation (that decays again on
the next addition) but a signal that reddens the moment a detector is registered and not rostered.

REGISTRATION IS THE AUTHORITY, not the file listing. A `.py` in `scripts/detectors/` that nothing
registers does not run, so rostering it would document a thing that never fires; and a registered
name with no file is a different defect that `test_detector_executable_bits` already owns.

## What this guard does NOT prove — stated here so its green cannot be over-read

It checks that each name appears in a GROUP BULLET, i.e. that the detector is INVENTORIED. It
cannot tell whether the one-line description beside that name is true, current, or even about the
right detector. The USER-scope lesson `a-doc-guard-that-asserts-a-mention-cannot-see-a-stale-claim`
is explicit about the trap: a guard asserting that a NAME APPEARS is at its greenest exactly when
the surrounding claim has been reversed, and its existence then SUPPRESSES the suspicion that
anyone should re-read the prose. So: green here means "nothing is missing from the list", never
"the list is correct".

Membership is deliberately scoped to the group bullets rather than to the whole page, and that is
not pedantry — it was measured. Against the full page 45 detectors looked documented; against the
group bullets only 44 were, because `agent-context-integrity` appeared in surrounding prose while
being absent from every group. A whole-page grep would have counted a SUPERSEDED body, a lesson
footnote, or an atom as documentation and passed vacuously on exactly the file this guard exists
to defend.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DISPATCH = _REPO / "scripts" / "dispatch.py"
_ROSTER = _REPO / ".claude" / "project" / "memory" / "janitor-detector-and-hook-roster.md"

# The registration tuple shape in dispatch.py: ("name", cadence_seconds, "CLAUDE_PLUGIN_OPTION_…").
_REGISTRATION = re.compile(r'\(\s*"([a-z0-9-]+)"\s*,\s*\d+\s*,\s*"CLAUDE_PLUGIN_OPTION_')


def registered_detectors() -> set[str]:
    """Every detector name `dispatch.py` schedules."""
    return set(_REGISTRATION.findall(_DISPATCH.read_text(encoding="utf-8")))


def test_the_registration_scan_still_finds_the_fleet() -> None:
    """A control, so the real assertion below cannot pass by finding NOTHING to check.

    If the tuple shape in dispatch.py ever changes, `registered_detectors()` silently returns an
    empty set and every completeness check trivially passes — the roster would be declared perfect
    at the exact moment the scanner went blind. That is the `supply-chain-fingerprints` failure
    this repo already paid for once: a membership test that covered nothing while reading as
    covered.
    """
    found = registered_detectors()
    assert len(found) > 50, (
        f"only {len(found)} registrations parsed from dispatch.py — the tuple shape probably "
        "changed and this scanner has gone blind. Fix the regex before trusting any result here."
    )


def test_every_registered_detector_is_named_in_the_roster() -> None:
    """The inventory claim, now defended by something that reddens.

    A detector missing here is not a documentation nicety: the roster is what a future session
    reads to learn what the janitor already does, so an undocumented detector gets rebuilt,
    duplicated, or wrongly assumed absent.
    """
    assert _ROSTER.is_file(), (
        f"the detector roster is missing at {_ROSTER.relative_to(_REPO)} — the PROJECT-scope "
        "inventory is git-tracked and must not vanish silently."
    )
    # ONLY the group bullets count as inventory — see the module docstring for the measurement
    # that made this necessary.
    group_lines = "\n".join(
        line for line in _ROSTER.read_text(encoding="utf-8").splitlines()
        if line.startswith("- *")
    )
    assert group_lines.strip(), (
        "no group bullets (`- *group:*`) found in the roster page — either the page was "
        "restructured or this parser has gone blind; a completeness check with nothing to "
        "search would pass vacuously."
    )
    missing = sorted(name for name in registered_detectors() if name not in group_lines)
    assert not missing, (
        f"{len(missing)} registered detector(s) are absent from the roster page: {missing}. "
        "Add each to its group with a one-line description of what it DETECTS (not what its name "
        "suggests). Registration is the authority — if one of these should not run at all, "
        "unregister it in dispatch.py instead of leaving it undocumented."
    )
