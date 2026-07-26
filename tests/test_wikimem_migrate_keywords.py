"""Tests for the atom-keyword recovery migration (plan Phase 1.3).

This script rewrites MEMORY — the least reversible thing in the system — so the tests below are
weighted toward what must never happen (losing a field, re-splitting a quoted value, guessing at a
key it has no rule for) rather than toward the happy path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import wikimem_migrate_keywords as mig  # noqa: E402


def test_orphan_phrases_are_recovered_and_joined():
    """Phrases after the first comma are recovered and each becomes ONE keyword."""
    props = "desc: a_slug, keywords: alpha one, beta two, gamma three, type: project"
    out, n = mig.repair_props(props)
    assert n == 2
    assert "keywords: alpha_one beta_two gamma_three" in out
    assert "type: project" in out
    assert "desc: a_slug" in out


def test_noop_when_already_correct():
    """An already-correct block is returned untouched — the migration is idempotent, so a second
    run (or a run over a partly-migrated corpus) can never double-join or corrupt."""
    props = "desc: a_slug, keywords: alpha_one beta_two, type: project"
    out, n = mig.repair_props(props)
    assert n == 0
    assert out == props


def test_running_twice_is_stable():
    """Explicit idempotency check on the repaired output, not just the pristine input."""
    props = "keywords: alpha one, beta two, type: project"
    once, n1 = mig.repair_props(props)
    twice, n2 = mig.repair_props(once)
    assert n1 == 1 and n2 == 0
    assert once == twice


def test_quoted_desc_commas_are_not_field_separators():
    """A quoted value may legitimately contain commas — splitting it would corrupt exactly the
    pages that already use the sanctioned grammar (TRDD-AP2X9A0H quoted prose)."""
    props = 'desc: "a summary, with commas, inside", keywords: alpha one, beta two, type: project'
    out, n = mig.repair_props(props)
    assert n == 1
    assert '"a summary, with commas, inside"' in out
    assert "keywords: alpha_one beta_two" in out


def test_unsupported_key_with_orphans_is_refused():
    """A key with no defined repair is REFUSED, never guessed — silently rewriting an unfamiliar
    shape would be the same class of quiet corruption this script exists to undo."""
    with pytest.raises(mig.Refused):
        mig.repair_props("type: project, some thing, ocd: 2026-07-20")


def test_split_respects_quotes():
    assert mig.split_top_level_commas('a: "x, y", b: z') == ['a: "x, y"', " b: z"]


def test_repair_text_only_touches_marker_lines():
    """Body prose that happens to contain commas must be left byte-identical."""
    page = (
        "---\nname: p\n---\n\n"
        "Body prose, with commas, that must not change.\n\n"
        "^an-atom [desc: d, keywords: alpha one, beta two, type: project]\n"
        "More body, also with commas.\n"
    )
    new, n, refusals = mig.repair_text(page)
    assert n == 1 and refusals == []
    assert "Body prose, with commas, that must not change." in new
    assert "More body, also with commas." in new
    assert "keywords: alpha_one beta_two" in new


def test_no_marker_no_change():
    text = "---\nname: p\n---\n\nJust prose, with commas.\n"
    new, n, refusals = mig.repair_text(text)
    assert (new, n, refusals) == (text, 0, [])
