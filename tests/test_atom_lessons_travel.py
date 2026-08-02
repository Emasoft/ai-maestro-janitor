"""The atom↔lesson travel safety net for HAND-moves (TRDD-VJCMZ2OP item 1e).

`memgrep migrate` verifies itself. A hand-move does not — and the failure it can produce is
invisible to every other invariant, which is the whole reason this check exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import memory_edit_verify as mev  # noqa: E402


def _page(atoms: str, lessons: str = "") -> str:
    return f"---\nname: p\n---\n\n{atoms}\n\n## Notes and lessons learned\n\n{lessons}\n"


def test_an_atom_that_keeps_its_lesson_passes() -> None:
    src = _page("^alpha [id:A]\nThe fact.[^1]\n", "[^1]: DO NOT x, BECAUSE y. DO z.\n")
    dst = _page("^alpha [id:A]\nThe fact.[^1]\n", "[^1]: DO NOT x, BECAUSE y. DO z.\n")
    ok, lost = mev.atom_lessons_travel([src], [dst])
    assert ok, lost


def test_THE_GAP_an_atom_moved_without_its_lesson_is_CAUGHT() -> None:
    """The defect no other invariant sees. `^alpha` moves to page B and drops `[^1]`:
    page A keeps an ORPHAN DEF (legal) and page B cites nothing (no dangling ref), so both
    `footnote_refs_resolve` and `no_new_dangling_footnote_refs` pass — while the lesson is
    severed from the fact it explains."""
    src_a = _page("^alpha [id:A]\nThe fact.[^1]\n", "[^1]: DO NOT x, BECAUSE y. DO z.\n")
    res_a = _page("", "[^1]: DO NOT x, BECAUSE y. DO z.\n")   # orphan def left behind
    res_b = _page("^alpha [id:A]\nThe fact.\n", "")            # atom arrived, lesson did not

    # Prove the existing invariants are BLIND to it — otherwise this check is redundant.
    assert mev.footnote_refs_resolve(res_a)[0], "orphan def must be legal (else premise is wrong)"
    assert mev.footnote_refs_resolve(res_b)[0], "no ref, so nothing dangles"
    assert mev.no_new_dangling_footnote_refs([src_a], [res_a, res_b])[0], "no NEW dangling ref"

    ok, lost = mev.atom_lessons_travel([src_a], [res_a, res_b])
    assert not ok, "an atom that lost its lesson must be caught"
    assert lost == ["^alpha#[^1]"], lost


def test_a_lesson_that_travels_WITH_the_atom_to_another_page_passes() -> None:
    """The legal move: both the atom and its lesson land on the destination."""
    src_a = _page("^alpha [id:A]\nThe fact.[^1]\n", "[^1]: DO NOT x, BECAUSE y. DO z.\n")
    res_a = _page("", "")
    res_b = _page("^alpha [id:A]\nThe fact.[^1]\n", "[^1]: DO NOT x, BECAUSE y. DO z.\n")
    ok, lost = mev.atom_lessons_travel([src_a], [res_a, res_b])
    assert ok, lost


def test_a_DELETED_atom_is_not_this_checks_business() -> None:
    """If the atom itself is gone, that is `lessons_preserved`/`body_facts_preserved`'s
    concern. Flagging it here too would double-report one defect as two."""
    src = _page("^alpha [id:A]\nThe fact.[^1]\n", "[^1]: DO NOT x, BECAUSE y. DO z.\n")
    ok, lost = mev.atom_lessons_travel([src], [_page("", "")])
    assert ok and lost == []


def test_a_footnote_inside_a_CODE_FENCE_is_documentation_not_a_citation() -> None:
    """L-4, the same trap that once permanently failed every edit to a page documenting
    footnote syntax. A `[^1]` shown inside a fence is an example."""
    src = _page("^alpha [id:A]\nSee below.\n\n```\nuse [^1] like this\n```\n", "")
    ok, lost = mev.atom_lessons_travel([src], [_page("^alpha [id:A]\nSee below.\n", "")])
    assert ok, f"a fenced example must not count as a citation: {lost}"


def test_multiple_atoms_only_the_offender_is_named() -> None:
    src = _page("^alpha [id:A]\nA fact.[^1]\n^beta [id:B]\nB fact.[^2]\n",
                "[^1]: DO NOT a.\n[^2]: DO NOT b.\n")
    res = _page("^alpha [id:A]\nA fact.[^1]\n^beta [id:B]\nB fact.\n",
                "[^1]: DO NOT a.\n[^2]: DO NOT b.\n")
    ok, lost = mev.atom_lessons_travel([src], [res])
    assert not ok
    assert lost == ["^beta#[^2]"], lost


# --- the keywords-led metadata bracket deadlock (2026-08-02) ------------------


def test_adding_an_id_to_a_KEYWORDS_led_bracket_is_not_a_reworded_lesson() -> None:
    """THE DEADLOCK. memgrep reads only the FIRST bracket after `[^N]:` as metadata, so a
    stable `id:` must go inside it. Before this fix `_normalize_lesson` stripped a leading
    bracket only when it began `ocd:`/`lmd:` — so a legacy `keywords:`-led bracket stayed in
    the compared text, adding `id:` broke the literal-substring check, and `verify_repair`
    refused. Every alternative arrangement failed too (id in a 2nd leading bracket drops
    keywords from metadata; trailing, the parser stops seeing id), so three lessons could
    never be given the id the linter demands."""
    before = '[^1]: [keywords:"a_phrase another", ocd:2026-08-01, lmd:2026-08-01]\nDO NOT x, BECAUSE y. DO z instead.'
    after = '[^1]: [id:ATOM-AAAA-1111, keywords:"a_phrase another", ocd:2026-08-01, lmd:2026-08-02]\nDO NOT x, BECAUSE y. DO z instead.'
    assert mev._normalize_lesson(before) == mev._normalize_lesson(after)
    ok, missing = mev.lessons_preserved([f"## Notes and lessons learned\n\n{before}\n"],
                                        f"## Notes and lessons learned\n\n{after}\n")
    assert ok, f"adding a stable id must not read as a dropped lesson: {missing}"


def test_the_CLAIM_still_cannot_be_reworded_under_cover_of_metadata() -> None:
    """The complement — otherwise the fix would hand every editor a licence to rewrite the
    lesson body while calling it a metadata change."""
    before = '[^1]: [keywords:"k", ocd:2026-08-01]\nDO NOT x, BECAUSE y. DO z instead.'
    reworded = '[^1]: [id:ATOM-AAAA-1111, keywords:"k", ocd:2026-08-01]\nDO NOT q, BECAUSE r. DO s instead.'
    ok, _ = mev.lessons_preserved([f"## Notes and lessons learned\n\n{before}\n"],
                                  f"## Notes and lessons learned\n\n{reworded}\n")
    assert not ok, "the DO-NOT/BECAUSE/DO claim must still be protected verbatim"


def test_a_lesson_opening_with_a_markdown_LINK_keeps_its_content() -> None:
    """Why the strip is an explicit key allow-list and not 'any [..] bracket': a lesson that
    legitimately opens with bracketed prose must keep that prose in its comparable text."""
    body = "[^1]: [see the docs](https://example.invalid) DO NOT x, BECAUSE y. DO z."
    assert "see the docs" in mev._normalize_lesson(body)
