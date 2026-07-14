"""The two merge gates must not contradict each other (TRDD-MQBV844P).

`no_dangling_refs` demands that a merge REDIRECT the surviving page's link to the retired page.
`body_facts_preserved` / `lessons_preserved` demand that no body line or lesson change by a single
byte. For any cross-linked pair those demands are mutually unsatisfiable — and the wikimem LINK LAW
mandates bidirectional links, so EVERY merge candidate is cross-linked. CONSOLIDATE could therefore
never merge the pages it exists to merge, and it failed silently by abstaining.

The fix compares modulo the mandated redirect. The tests below pin BOTH halves of that claim:
the merge now succeeds, AND the anti-corruption guarantee (issue #48) is undiminished — a genuinely
dropped or paraphrased fact, and a dropped lesson, still fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import memory_edit_verify as V  # noqa: E402

A_TEXT = """---
name: page-a
metadata:
  type: user
---
# A
The rotator keeps three accounts in the OS keychain store.
See also [[page-b]] (the plan tiers and their capacities).

## Notes and lessons learned

[^1]: [ocd:2026-07-01 lmd:2026-07-01] The roster once said two accounts; it was three. Verify against
  the live rotator, not memory — see [[page-b]] for the plan tiers.
"""

B_TEXT = """---
name: page-b
metadata:
  type: user
---
# B
The small account is the cheap one and saturates fastest.
See also [[page-a]] (keychain location and how to query the live roster).

## Notes and lessons learned

[^2]: [ocd:2026-07-05 lmd:2026-07-05] The cheap account was mislabelled as the large one for a week.
"""

A_META = {"name": "page-a", "ocd": "2026-07-01", "lmd": "2026-07-01", "type": "user"}
B_META = {"name": "page-b", "ocd": "2026-07-05", "lmd": "2026-07-09", "type": "user"}
# Survivor keeps the OLDEST ocd and a fresh lmd.
R_META = {"name": "page-b", "ocd": "2026-07-01", "lmd": "2026-07-14", "type": "user"}

# The merge a competent executor produces: both bodies, both lessons, and the link to the retired
# `page-a` REDIRECTED to the survivor (which is what no_dangling_refs requires).
MERGED = """---
name: page-b
metadata:
  type: user
---
# B
The rotator keeps three accounts in the OS keychain store.
The small account is the cheap one and saturates fastest.
See also [[page-b]] (the plan tiers and their capacities).
See also [[page-b]] (keychain location and how to query the live roster).

## Notes and lessons learned

[^1]: [ocd:2026-07-01 lmd:2026-07-01] The roster once said two accounts; it was three. Verify against
  the live rotator, not memory — see [[page-b]] for the plan tiers.

[^2]: [ocd:2026-07-05 lmd:2026-07-05] The cheap account was mislabelled as the large one for a week.
"""


def _verify(result: str, meta: dict | None = None) -> tuple[bool, list[str]]:
    return V.verify_merge(
        [A_TEXT, B_TEXT],
        [A_META, B_META],
        result,
        meta or R_META,
        ["page-a"],
        {},
    )


def test_a_cross_linked_pair_can_now_merge() -> None:
    """The deadlock is gone: a correct merge of two mutually-linked pages verifies."""
    ok, reasons = _verify(MERGED)
    assert ok, f"a correct merge must verify, got: {reasons}"


def test_the_lesson_embedded_link_is_handled_too() -> None:
    """The lesson case is strictly WORSE than the body case: `lessons_preserved` demands the WHOLE
    lesson body as one continuous byte-identical substring, so a lesson containing a `[[retired]]`
    link was flatly unfixable by any edit. `[^1]` above carries such a link on purpose."""
    ok, reasons = _verify(MERGED)
    assert ok
    assert not any("lesson" in r for r in reasons)


def test_a_missed_redirect_still_fails() -> None:
    """We normalize for the COMPARISON only — never for the link law. A merge that forgot to redirect
    still leaves a dangling ref, and must still be refused."""
    stale = MERGED.replace("See also [[page-b]] (keychain location", "See also [[page-a]] (keychain location")
    ok, reasons = _verify(stale)
    assert not ok
    assert any("dangling" in r.lower() for r in reasons), reasons


def test_a_genuinely_dropped_fact_still_fails() -> None:
    """THE anti-corruption falsification. If the fix had merely weakened body_facts_preserved, this
    would now pass — and issue #48's guarantee would be gone. Dropping a real fact must still fail."""
    lossy = MERGED.replace("The rotator keeps three accounts in the OS keychain store.\n", "")
    ok, reasons = _verify(lossy)
    assert not ok
    assert any("body fact" in r for r in reasons), reasons


def test_a_paraphrased_fact_still_fails() -> None:
    """Rewording is how knowledge quietly rots. Still caught."""
    reworded = MERGED.replace(
        "The rotator keeps three accounts in the OS keychain store.",
        "The rotator manages a few accounts, stored securely.",
    )
    ok, reasons = _verify(reworded)
    assert not ok
    assert any("body fact" in r for r in reasons), reasons


def test_a_dropped_lesson_still_fails() -> None:
    """Lessons are the sacred never-lost layer. Unchanged."""
    lossy = MERGED.replace(
        "[^2]: [ocd:2026-07-05 lmd:2026-07-05] The cheap account was mislabelled as the large one for a week.\n",
        "",
    )
    ok, reasons = _verify(lossy)
    assert not ok
    assert any("lesson" in r for r in reasons), reasons


def test_canonicalize_preserves_aliases_and_leaves_others_alone() -> None:
    """Only the retired target is rewritten: an alias survives, and an unrelated link is untouched."""
    text = "see [[page-a|the old page]] and [[other-page]] and [[page-a]]"
    out = V.canonicalize_retired_links(text, ["page-a"], "page-b")
    assert out == "see [[page-b|the old page]] and [[other-page]] and [[page-b]]"
