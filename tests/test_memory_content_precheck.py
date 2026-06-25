"""Tests for memory_content_precheck — the cheap, zero-LLM filesystem prechecks
the memory-maintenance SCHEDULER uses to suppress a cadence-due-but-no-content
editorial chore before it spawns a ~240k no-op opus agent (TRDD-3XS3PDCF).

Real I/O, no mocks: each case builds a temp corpus dir with real .md files and
asserts the pure predicate. The load-bearing property under test is FAIL-OPEN —
a chore is suppressed ONLY when its idleness is cheaply proven (today: SPLIT's
size gate); everything else returns True (unchanged cadence-only behavior).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import memory_content_precheck as mcp  # noqa: E402

_CAP = 36000


def _page(d: Path, name: str, size: int) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("x" * size, encoding="utf-8")
    return p


def _curated(d: Path, name: str, *, tier: str | None, type_: str) -> Path:
    """Write a CURATED wikimem page with a `tier` + `metadata.type` frontmatter —
    the exact shape `is_legal_merge` reads. `tier=None` writes a RAW buffer note
    (harness-minimal frontmatter, no `tier`), which is structurally unmergeable."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if tier is None:
        fm = f"---\nname: {name[:-3]}\ndescription: raw note\nmetadata:\n  type: {type_}\n---\n"
    else:
        fm = (
            f"---\nname: {name[:-3]}\ndescription: a page\nnode_type: memory\n"
            f"tier: {tier}\nmetadata:\n  type: {type_}\n---\n"
        )
    p.write_text(fm + "\nbody text.\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# split_has_work — the one cheap, unambiguous size gate
# --------------------------------------------------------------------------- #

def test_split_has_work_true_when_a_page_exceeds_cap(tmp_path):
    """A page strictly larger than the cap -> there is split work."""
    _page(tmp_path, "big.md", _CAP + 1)
    assert mcp.split_has_work(tmp_path, max_bytes=_CAP) is True


def test_split_has_work_false_when_all_pages_within_cap(tmp_path):
    """Every page at or under the cap -> no split work (the observed no-op case)."""
    _page(tmp_path, "a.md", _CAP)          # exactly the cap is NOT over (strict >)
    _page(tmp_path, "b.md", _CAP - 5000)
    assert mcp.split_has_work(tmp_path, max_bytes=_CAP) is False


def test_split_has_work_false_on_empty_dir(tmp_path):
    """An empty corpus has no split work."""
    assert mcp.split_has_work(tmp_path, max_bytes=_CAP) is False


def test_split_has_work_false_on_missing_dir(tmp_path):
    """A non-existent root is not an error — it simply has no work."""
    assert mcp.split_has_work(tmp_path / "nope", max_bytes=_CAP) is False


def test_split_has_work_ignores_staging_dir(tmp_path):
    """An over-cap page inside the transaction staging dir is NOT a real candidate
    (the split skill excludes `.maint-staging/`), so it does not count as work."""
    _page(tmp_path / ".maint-staging", "staged-big.md", _CAP + 1000)
    assert mcp.split_has_work(tmp_path, max_bytes=_CAP) is False


def test_split_has_work_finds_oversized_page_in_a_subdir(tmp_path):
    """The scan is recursive (rglob) like the skill's `find` — an over-cap page in
    a nested non-staging subdir still counts."""
    _page(tmp_path / "sub", "deep-big.md", _CAP + 1)
    assert mcp.split_has_work(tmp_path, max_bytes=_CAP) is True


# --------------------------------------------------------------------------- #
# content_has_work — the dispatcher + the FAIL-OPEN safety rule
# --------------------------------------------------------------------------- #

def test_content_has_work_split_delegates_to_size_gate(tmp_path):
    """split routes through split_has_work with the given cap."""
    assert mcp.content_has_work("split", tmp_path, split_max_bytes=_CAP) is False
    _page(tmp_path, "big.md", _CAP + 1)
    assert mcp.content_has_work("split", tmp_path, split_max_bytes=_CAP) is True


def test_content_has_work_split_fail_open_on_nonpositive_cap(tmp_path):
    """A non-positive cap (unreadable/disabled) -> fail-open: never suppress split,
    even on an empty corpus where the size gate would otherwise say 'no work'."""
    assert mcp.content_has_work("split", tmp_path, split_max_bytes=0) is True
    assert mcp.content_has_work("split", tmp_path, split_max_bytes=-1) is True


def test_content_has_work_unprechecked_chores_fail_open(tmp_path):
    """Every chore WITHOUT a cheap exact precheck returns True (fail-open) so the
    scheduler keeps its existing cadence-only behavior — harvest/repair/atomize are
    documented follow-ups; conflict is semantic + agent-discovered. (consolidate is
    NO LONGER in this set — it now has a STRUCTURAL precheck, TRDD-8UD3Q7K5.)"""
    for chore in ("harvest", "repair", "atomize", "conflict"):
        assert mcp.content_has_work(chore, tmp_path, split_max_bytes=_CAP) is True
        # ...and still True with content present (they are never suppressed here).
        _page(tmp_path, f"{chore}.md", 100)
        assert mcp.content_has_work(chore, tmp_path, split_max_bytes=_CAP) is True


def test_content_has_work_unknown_intervention_fails_open(tmp_path):
    """An unrecognised intervention name is never suppressed (fail-open default)."""
    assert mcp.content_has_work("totally-new-chore", tmp_path, split_max_bytes=_CAP) is True


# --------------------------------------------------------------------------- #
# consolidate_has_work — the cheap STRUCTURAL precheck (TRDD-8UD3Q7K5, issue #64)
#
# A merge is structurally possible iff >=2 candidate pages share the same
# (tier, type) with tier in {aspect, component} (the is_legal_merge necessary
# condition). Subject-sameness stays semantic/agent-discovered, so a structural
# pair present => fail-open (still dispatch; the agent decides subject).
# --------------------------------------------------------------------------- #

def test_consolidate_has_work_true_for_same_tier_type_pair(tmp_path):
    """>=2 pages sharing (component, project) -> a legal-merge pair could exist."""
    _curated(tmp_path, "a.md", tier="component", type_="project")
    _curated(tmp_path, "b.md", tier="component", type_="project")
    assert mcp.consolidate_has_work(tmp_path) is True


def test_consolidate_has_work_true_for_aspect_reference_pair(tmp_path):
    """The pairing works for any mergeable tier — aspect/reference here."""
    _curated(tmp_path, "a.md", tier="aspect", type_="reference")
    _curated(tmp_path, "b.md", tier="aspect", type_="reference")
    assert mcp.consolidate_has_work(tmp_path) is True


def test_consolidate_has_work_false_on_cross_type_pair(tmp_path):
    """Issue #64 case 1: feedback x reference (same aspect tier, DIFFERENT type) is
    a hard is_legal_merge cross-type refusal -> no structural pair -> no work."""
    _curated(tmp_path, "fb.md", tier="aspect", type_="feedback")
    _curated(tmp_path, "ref.md", tier="aspect", type_="reference")
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_false_when_every_pair_is_distinct(tmp_path):
    """Every page a distinct (tier, type) -> no two could merge -> no work."""
    _curated(tmp_path, "a.md", tier="component", type_="project")
    _curated(tmp_path, "b.md", tier="aspect", type_="reference")
    _curated(tmp_path, "c.md", tier="component", type_="reference")
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_false_for_hub_pair(tmp_path):
    """Two hubs share (hub, project) but hub is NOT a mergeable tier (a hub is an
    overview, not a leaf) -> is_legal_merge refuses -> no structural pair."""
    _curated(tmp_path, "a.md", tier="hub", type_="project")
    _curated(tmp_path, "b.md", tier="hub", type_="project")
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_false_for_raw_buffer_notes(tmp_path):
    """Issue #64 case 2 shape: pages share a generic subject keyword but carry NO
    tier (raw harness buffer notes) -> tier=None not in {aspect,component} ->
    unmergeable -> no work (mere keyword overlap is not a merge pair)."""
    _curated(tmp_path, "cpv-a.md", tier=None, type_="reference")
    _curated(tmp_path, "cpv-b.md", tier=None, type_="reference")
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_false_on_empty_dir(tmp_path):
    """An empty corpus has no merge pair."""
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_false_on_missing_dir(tmp_path):
    """A non-existent root is not an error — simply no work."""
    assert mcp.consolidate_has_work(tmp_path / "nope") is False


def test_consolidate_has_work_false_for_lone_mergeable_page(tmp_path):
    """A single (component, project) page has nothing to merge WITH -> no work
    (the count must reach 2 for the SAME key)."""
    _curated(tmp_path, "lonely.md", tier="component", type_="project")
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_ignores_staging_and_user_mem(tmp_path):
    """A mergeable pair placed ONLY in excluded subdirs (.maint-staging/, user-mem/)
    is not a real candidate (the SSOT iter_note_files filters them) -> no work."""
    _curated(tmp_path / ".maint-staging", "a.md", tier="component", type_="project")
    _curated(tmp_path / "user-mem", "b.md", tier="component", type_="project")
    assert mcp.consolidate_has_work(tmp_path) is False


def test_consolidate_has_work_finds_pair_across_subdirs(tmp_path):
    """The scan is recursive (iter_note_files rglob) — a pair split across the root
    and the curated wiki/ subdir still counts (both are real notes)."""
    _curated(tmp_path, "a.md", tier="component", type_="project")
    _curated(tmp_path / "wiki", "b.md", tier="component", type_="project")
    assert mcp.consolidate_has_work(tmp_path) is True


def test_content_has_work_consolidate_delegates_to_structural_gate(tmp_path):
    """consolidate routes through consolidate_has_work (False then True round-trip)."""
    assert mcp.content_has_work("consolidate", tmp_path, split_max_bytes=_CAP) is False
    _curated(tmp_path, "a.md", tier="component", type_="project")
    _curated(tmp_path, "b.md", tier="component", type_="project")
    assert mcp.content_has_work("consolidate", tmp_path, split_max_bytes=_CAP) is True
