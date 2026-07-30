"""Tests for memory_content_precheck — the cheap, zero-LLM filesystem prechecks
the memory-maintenance SCHEDULER uses to suppress a cadence-due-but-no-content
editorial chore before it spawns a ~240k no-op opus agent (TRDD-3XS3PDCF).

Real I/O, no mocks: each case builds a temp corpus dir with real .md files and
asserts the pure predicate. The load-bearing property under test is FAIL-OPEN —
a chore is suppressed ONLY when its idleness is cheaply proven (today: SPLIT's
size gate); everything else returns True (unchanged cadence-only behavior).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import memory_content_precheck as mcp  # noqa: E402
import memory_refusals  # noqa: E402

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
    """A chore whose precheck cannot determine its inputs returns True (fail-open)
    so the scheduler keeps its cadence-only behavior. Since 2026-07-08 EVERY chore
    has a gate (harvest + conflict were the last), so the residual fail-open cases
    are: harvest WITHOUT its scope kwarg (the watermark ledger is scope-keyed) and
    any unknown chore name (the test below)."""
    _page(tmp_path, "raw-shaped.md", 100)  # a note that is provably idle for neither
    assert mcp.content_has_work("harvest", tmp_path, split_max_bytes=_CAP) is True
    assert mcp.content_has_work("harvest", tmp_path, split_max_bytes=_CAP, scope=None) is True


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
    _curated(tmp_path / "wikimem", "b.md", tier="component", type_="project")
    assert mcp.consolidate_has_work(tmp_path) is True


def test_content_has_work_consolidate_delegates_to_structural_gate(tmp_path):
    """consolidate routes through consolidate_has_work (False then True round-trip)."""
    assert mcp.content_has_work("consolidate", tmp_path, split_max_bytes=_CAP) is False
    _curated(tmp_path, "a.md", tier="component", type_="project")
    _curated(tmp_path, "b.md", tier="component", type_="project")
    assert mcp.content_has_work("consolidate", tmp_path, split_max_bytes=_CAP) is True


def _shaped(
    d: Path,
    name: str,
    *,
    tier: str = "component",
    notes: bool = True,
    dates_top_level: bool = True,
    body: str = "A durable fact line about the subject.",
    marker: bool = False,
    drop: tuple[str, ...] = (),
) -> Path:
    """Write a fully-SHAPED curated wikimem page (every verify_repair required key,
    top-level ocd/lmd, the standing Notes section, no tier inversion) and let each
    test break exactly ONE aspect of the shape via the knobs."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    top: list[str] = ["---", f"name: {name[:-3]}"]
    if "description" not in drop:
        top.append("description: what breaks when X happens — symptom words")
    if dates_top_level:
        top.append("ocd: 2026-07-01")
        top.append("lmd: 2026-07-08")
    top.append("metadata:")
    top.append("  node_type: memory")
    top.append("  type: project")
    if "tier" not in drop:
        top.append(f"  tier: {tier}")
    if not dates_top_level:
        # the historical NESTED placement repair normalizes (issue #56)
        top.append("  ocd: 2026-07-01")
        top.append("  lmd: 2026-07-08")
    top.append("---")
    parts = ["\n".join(top), ""]
    if marker:
        parts.append("^fact-1 [desc: the_fact, keywords: symptom words]")
    parts.append(body)
    if notes:
        parts += ["", "## Notes and lessons learned", ""]
    p.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# repair_has_work — the STRUCTURAL page-shape gate (TRDD-3XS3PDCF follow-up)
# --------------------------------------------------------------------------- #

def test_repair_has_work_false_on_well_formed_corpus(tmp_path):
    """Every page fully shaped (all required keys, valid tier, top-level dates,
    Notes section, no tier inversion) -> repair is provably idle."""
    _shaped(tmp_path, "a.md")
    _shaped(tmp_path / "wikimem", "b.md", tier="aspect")
    assert mcp.repair_has_work(tmp_path) is False


def test_repair_has_work_true_on_missing_notes_section(tmp_path):
    """A page without the standing '## Notes and lessons learned' section is
    repair work (verify_repair requires the section on the result)."""
    _shaped(tmp_path, "a.md", notes=False)
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_true_on_missing_required_key(tmp_path):
    """A page lacking any verify_repair required key (tier here) is repair work —
    this also covers RAW harness buffer notes (partial schema by construction),
    which the repair skill explicitly upgrades."""
    _shaped(tmp_path, "a.md", drop=("tier",))
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_true_on_nested_dates(tmp_path):
    """ocd/lmd nested under metadata: (the historical shape, issue #56) is
    placement-normalization work even though the FLATTENED keys are present."""
    _shaped(tmp_path, "a.md", dates_top_level=False)
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_true_on_invalid_tier(tmp_path):
    """A tier outside {hub, aspect, component} must be re-tagged -> work."""
    _shaped(tmp_path, "a.md", tier="banana")
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_true_on_inverted_aspect_shape(tmp_path):
    """An aspect that only RECEIVES (## Governed by, no ## Applies to) is built
    backwards — the skill re-shapes or re-tags it."""
    _shaped(tmp_path, "a.md", tier="aspect", body="A rule.\n\n## Governed by\n- [[x]]")
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_true_on_component_with_applies_to(tmp_path):
    """A component that RADIATES (## Applies to) is the mirror inversion."""
    _shaped(tmp_path, "a.md", body="A fact.\n\n## Applies to\n- [[x]]")
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_true_on_frontmatterless_page(tmp_path):
    """No leading --- fence at all -> invisible to ranked recall -> repair work."""
    (tmp_path / "bare.md").write_text("just prose, no frontmatter\n", encoding="utf-8")
    assert mcp.repair_has_work(tmp_path) is True


def test_repair_has_work_false_on_empty_and_missing_dir(tmp_path):
    """An empty or non-existent corpus has no repair work (not an error)."""
    assert mcp.repair_has_work(tmp_path) is False
    assert mcp.repair_has_work(tmp_path / "nope") is False


def test_content_has_work_repair_delegates(tmp_path):
    """repair routes through repair_has_work (False then True round-trip)."""
    assert mcp.content_has_work("repair", tmp_path, split_max_bytes=_CAP) is False
    _shaped(tmp_path, "a.md", notes=False)
    assert mcp.content_has_work("repair", tmp_path, split_max_bytes=_CAP) is True


# --------------------------------------------------------------------------- #
# atomize_has_work — free-prose curated pages without atom markers
# --------------------------------------------------------------------------- #

def test_atomize_has_work_true_for_unmarked_curated_page(tmp_path):
    """A curated page with a substantive body and ZERO atom markers is the
    atomize skill's exact candidate -> work."""
    _shaped(tmp_path, "a.md")
    assert mcp.atomize_has_work(tmp_path) is True


def test_atomize_has_work_false_when_every_curated_page_carries_a_marker(tmp_path):
    """The atomize skill skips any page with >=1 marker ('already atomized'), so
    an all-marked corpus is provably idle."""
    _shaped(tmp_path, "a.md", marker=True)
    _shaped(tmp_path / "wikimem", "b.md", marker=True)
    assert mcp.atomize_has_work(tmp_path) is False


def test_atomize_has_work_false_for_raw_buffer_notes_only(tmp_path):
    """RAW harness buffer notes are not curated wiki pages -> never atomize
    candidates (is_curated_wiki_page is the coexistence discriminator)."""
    _curated(tmp_path, "raw.md", tier=None, type_="reference")
    assert mcp.atomize_has_work(tmp_path) is False


def test_atomize_has_work_false_for_page_without_substantive_body(tmp_path):
    """Headings + the empty Notes pool only -> nothing an atom could mark -> the
    skill's 'free-prose-leaf-no-distinct-facts' abstain case -> no work."""
    _shaped(tmp_path, "a.md", body="## Some heading")
    assert mcp.atomize_has_work(tmp_path) is False


def test_atomize_has_work_false_on_empty_and_missing_dir(tmp_path):
    """An empty or non-existent corpus has no atomize work (not an error)."""
    assert mcp.atomize_has_work(tmp_path) is False
    assert mcp.atomize_has_work(tmp_path / "nope") is False


def test_content_has_work_atomize_delegates(tmp_path):
    """atomize routes through atomize_has_work (False then True round-trip)."""
    assert mcp.content_has_work("atomize", tmp_path, split_max_bytes=_CAP) is False
    _shaped(tmp_path, "a.md")
    assert mcp.content_has_work("atomize", tmp_path, split_max_bytes=_CAP) is True


# --------------------------------------------------------------------------- #
# FAIL-OPEN on unreadable pages (libs audit L-11)
# --------------------------------------------------------------------------- #

def test_unreadable_page_fails_open_for_read_based_prechecks(tmp_path):
    """A page the precheck cannot READ is NOT provably idle -> True (fail-open),
    never skip-and-suppress (libs audit L-11). The corpus is arranged so every
    readable page has NO work — the flip to True comes solely from the locked one."""
    if os.geteuid() == 0:
        pytest.skip("permission bits do not bind root")
    _shaped(tmp_path, "good.md", marker=True)  # readable: no repair/atomize/merge work
    locked = _shaped(tmp_path, "locked.md", marker=True)
    locked.chmod(0)
    try:
        assert mcp.consolidate_has_work(tmp_path) is True
        assert mcp.repair_has_work(tmp_path) is True
        assert mcp.atomize_has_work(tmp_path) is True
    finally:
        locked.chmod(0o644)  # let pytest's tmp_path cleanup delete it


# --------------------------------------------------------------------------- #
# harvest_has_work — un-mirrored raw buffer notes (the skill's step-1 scan;
# TRDD-3XS3PDCF follow-up, unblocked 2026-07-08)
# --------------------------------------------------------------------------- #

def _isolate_gstate(monkeypatch, tmp_path: Path) -> None:
    """Point the harvest watermark ledger (global_state_dir) at a scratch dir so
    a test never reads/writes the machine's real watermark files."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))


def test_harvest_has_work_true_for_unmirrored_raw_note(tmp_path, monkeypatch):
    """One raw buffer note, no watermark -> real harvest work."""
    _isolate_gstate(monkeypatch, tmp_path)
    _curated(tmp_path, "raw.md", tier=None, type_="reference")
    assert mcp.harvest_has_work("LOCAL", tmp_path) is True


def test_harvest_has_work_false_when_all_pages_curated(tmp_path, monkeypatch):
    """Every top-level page already curated -> nothing to mirror (the exact
    corpus shape of the two live 2026-07-08 no-op passes this gate kills)."""
    _isolate_gstate(monkeypatch, tmp_path)
    _curated(tmp_path, "a.md", tier="component", type_="reference")
    _curated(tmp_path, "b.md", tier="aspect", type_="project")
    assert mcp.harvest_has_work("LOCAL", tmp_path) is False


def test_harvest_has_work_false_when_raw_note_already_mirrored(tmp_path, monkeypatch):
    """A raw note whose exact content is watermarked as mirrored is done work."""
    _isolate_gstate(monkeypatch, tmp_path)
    import memory_settings
    p = _curated(tmp_path, "raw.md", tier=None, type_="reference")
    memory_settings.harvest_mark_mirrored("LOCAL", str(tmp_path), p.name, p.read_text(encoding="utf-8"))
    assert mcp.harvest_has_work("LOCAL", tmp_path) is False


def test_harvest_has_work_true_when_mirrored_note_edited(tmp_path, monkeypatch):
    """Editing a mirrored buffer note invalidates its watermark hash -> re-mirror."""
    _isolate_gstate(monkeypatch, tmp_path)
    import memory_settings
    p = _curated(tmp_path, "raw.md", tier=None, type_="reference")
    memory_settings.harvest_mark_mirrored("LOCAL", str(tmp_path), p.name, p.read_text(encoding="utf-8"))
    p.write_text(p.read_text(encoding="utf-8") + "\nnew fact.\n", encoding="utf-8")
    assert mcp.harvest_has_work("LOCAL", tmp_path) is True


def test_harvest_has_work_ignores_generated_names_and_subdirs(tmp_path, monkeypatch):
    """MEMORY.md / the generated index files are never mirrored, and the scan is
    TOP-LEVEL ONLY (skill parity: `root.glob('*.md')`) — a raw-shaped note inside a
    subdir must not claim work the skill's own scan would never see."""
    _isolate_gstate(monkeypatch, tmp_path)
    (tmp_path / "MEMORY.md").write_text("# MEMORY — stub\n", encoding="utf-8")
    (tmp_path / "memory-index.md").write_text("index\n", encoding="utf-8")
    (tmp_path / "memory-reorg-proposed.md").write_text("proposals\n", encoding="utf-8")
    _curated(tmp_path / "wikimem", "nested-raw.md", tier=None, type_="reference")
    assert mcp.harvest_has_work("LOCAL", tmp_path) is False


def test_harvest_has_work_false_on_empty_and_missing_dir(tmp_path, monkeypatch):
    """No candidates at all -> provably idle (empty dir and missing dir alike)."""
    _isolate_gstate(monkeypatch, tmp_path)
    assert mcp.harvest_has_work("LOCAL", tmp_path) is False
    assert mcp.harvest_has_work("LOCAL", tmp_path / "absent") is False


def test_harvest_unreadable_note_fails_open(tmp_path, monkeypatch):
    """An unreadable top-level note is NOT provably idle -> True (libs audit L-11)."""
    if os.geteuid() == 0:
        pytest.skip("permission bits do not bind root")
    _isolate_gstate(monkeypatch, tmp_path)
    _curated(tmp_path, "ok.md", tier="component", type_="reference")
    locked = _curated(tmp_path, "locked.md", tier="component", type_="reference")
    locked.chmod(0)
    try:
        assert mcp.harvest_has_work("LOCAL", tmp_path) is True
    finally:
        locked.chmod(0o644)


def test_content_has_work_harvest_fail_open_without_scope(tmp_path, monkeypatch):
    """Without the scope the watermark ledger is unkeyable -> never suppress."""
    _isolate_gstate(monkeypatch, tmp_path)
    _curated(tmp_path, "a.md", tier="component", type_="reference")  # provably idle corpus
    assert mcp.content_has_work("harvest", tmp_path, split_max_bytes=_CAP) is True


def test_content_has_work_harvest_delegates_with_scope(tmp_path, monkeypatch):
    """harvest routes through harvest_has_work (False then True round-trip)."""
    _isolate_gstate(monkeypatch, tmp_path)
    _curated(tmp_path, "a.md", tier="component", type_="reference")
    assert mcp.content_has_work("harvest", tmp_path, split_max_bytes=_CAP, scope="LOCAL") is False
    _curated(tmp_path, "raw.md", tier=None, type_="reference")
    assert mcp.content_has_work("harvest", tmp_path, split_max_bytes=_CAP, scope="LOCAL") is True


# --------------------------------------------------------------------------- #
# conflict_has_work — the librarian's surfaced candidates ("Empty/absent → stop"
# is the skill's own precondition; TRDD-3XS3PDCF follow-up)
# --------------------------------------------------------------------------- #

def _proposal(d: Path, conflict_lines: list[str]) -> Path:
    """Write a librarian-shaped memory-reorg-proposed.md whose Conflict-candidates
    section holds exactly `conflict_lines` (the librarian's own render shape)."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / "memory-reorg-proposed.md"
    body = [
        "## LOCAL scope", "",
        "### Aggregation candidates", "",
        "- topic `x` (2 notes): a.md, b.md",  # a bullet OUTSIDE the conflict section
        "", "### Conflict candidates", "",
        *conflict_lines,
        "", "### Page shape", "", "- (none)", "",
    ]
    p.write_text("\n".join(body) + "\n", encoding="utf-8")
    return p


def test_conflict_has_work_true_for_real_candidate(tmp_path):
    """A surfaced `- topic ...: a vs b` pair -> the pass has work."""
    _proposal(tmp_path, ["- topic `timeout`: widget-timeout-old vs widget-timeout-new"])
    assert mcp.conflict_has_work(tmp_path) is True


def test_conflict_has_work_false_for_none_sentinel(tmp_path):
    """The librarian's `- (none)` empty marker is NOT a candidate (the exact
    corpus shape of the live 260,931-token no-op of 2026-07-08)."""
    _proposal(tmp_path, ["- (none)"])
    assert mcp.conflict_has_work(tmp_path) is False


def test_conflict_has_work_false_when_proposal_absent(tmp_path):
    """No memory-reorg-proposed.md -> the skill's own 'absent → stop' idle case."""
    assert mcp.conflict_has_work(tmp_path) is False


def test_conflict_has_work_ignores_bullets_outside_the_section(tmp_path):
    """An aggregation/page-shape bullet must never count as a conflict candidate —
    only bullets INSIDE a Conflict-candidates section (any heading ends it)."""
    _proposal(tmp_path, ["- (none)"])  # helper already writes a non-conflict bullet
    assert mcp.conflict_has_work(tmp_path) is False


def test_conflict_has_work_unreadable_proposal_fails_open(tmp_path):
    """A PRESENT but unreadable proposal is not provably idle -> True (L-11)."""
    if os.geteuid() == 0:
        pytest.skip("permission bits do not bind root")
    p = _proposal(tmp_path, ["- (none)"])
    p.chmod(0)
    try:
        assert mcp.conflict_has_work(tmp_path) is True
    finally:
        p.chmod(0o644)


def test_content_has_work_conflict_delegates(tmp_path):
    """conflict routes through conflict_has_work (False then True round-trip)."""
    assert mcp.content_has_work("conflict", tmp_path, split_max_bytes=_CAP) is False
    _proposal(tmp_path, ["- topic `t`: a vs b"])
    assert mcp.content_has_work("conflict", tmp_path, split_max_bytes=_CAP) is True


# ---------------------------------------------------------------------------
# CONSOLIDATE gate 2 — the UNCHANGED-CORPUS proof (TRDD-3XS3PDCF, 2026-07-11).
#
# The structural (tier,type) gate is necessary but NOT sufficient: both live scopes hold
# many `component/reference` pages, so it passes, a ~260k-token agent spawns, and then
# abstains on SUBJECT — which the structural gate never examined. Subject-sameness is a
# semantic judgment we must not guess (the skill's own contract: same subject, "not merely
# sharing keywords"). What we CAN prove is that nothing changed since the agent last looked.
# ---------------------------------------------------------------------------


def _mergeable_pair(root: Path) -> None:
    """Two pages that PASS the structural gate (same tier+type) — so any suppression in
    these tests comes from the fingerprint gate, never from gate 1."""
    _curated(root, "a.md", tier="component", type_="reference")
    _curated(root, "b.md", tier="component", type_="reference")


def test_fingerprint_is_stable_and_stat_only(tmp_path: Path) -> None:
    _mergeable_pair(tmp_path)
    fp1 = mcp.corpus_fingerprint(tmp_path)
    assert fp1 is not None
    assert mcp.corpus_fingerprint(tmp_path) == fp1, "same corpus → same fingerprint"


def test_fingerprint_moves_when_a_page_changes(tmp_path: Path) -> None:
    _mergeable_pair(tmp_path)
    fp1 = mcp.corpus_fingerprint(tmp_path)
    _curated(tmp_path, "c.md", tier="component", type_="reference")   # a NEW page
    assert mcp.corpus_fingerprint(tmp_path) != fp1


def test_unchanged_corpus_is_suppressed(tmp_path: Path) -> None:
    """The whole point: the agent already read exactly this content and reached a verdict.
    Re-spawning it on byte-identical pages cannot produce a different answer."""
    _mergeable_pair(tmp_path)
    assert mcp.consolidate_has_work(tmp_path) is True, "no stamp → fail-open"
    fp = mcp.corpus_fingerprint(tmp_path)
    assert mcp.consolidate_has_work(tmp_path, last_fingerprint=fp, stamp_age_s=60.0) is False


def test_a_changed_corpus_re_arms_immediately(tmp_path: Path) -> None:
    """Any edit/add/delete must dispatch again on the very next cadence — a new page could
    be the other half of a real merge."""
    _mergeable_pair(tmp_path)
    stale = mcp.corpus_fingerprint(tmp_path)
    _curated(tmp_path, "c.md", tier="component", type_="reference")
    assert mcp.consolidate_has_work(tmp_path, last_fingerprint=stale, stamp_age_s=60.0) is True


def test_suppression_expires_so_nothing_is_hidden_forever(tmp_path: Path) -> None:
    """Bounds the two cases an unchanged corpus could still hide work: an agent that
    CRASHED mid-pass, and LLM non-determinism. After the recheck window we dispatch anyway."""
    _mergeable_pair(tmp_path)
    fp = mcp.corpus_fingerprint(tmp_path)
    fresh = mcp.consolidate_has_work(tmp_path, last_fingerprint=fp, stamp_age_s=60.0)
    expired = mcp.consolidate_has_work(
        tmp_path, last_fingerprint=fp, stamp_age_s=mcp._DEFAULT_CONSOLIDATE_RECHECK_S + 1.0
    )
    assert fresh is False and expired is True


def test_missing_stamp_fails_open(tmp_path: Path) -> None:
    """No fingerprint or no stamp age → dispatch. We never suppress on missing evidence."""
    _mergeable_pair(tmp_path)
    assert mcp.consolidate_has_work(tmp_path, last_fingerprint=None, stamp_age_s=60.0) is True
    assert mcp.consolidate_has_work(tmp_path, last_fingerprint="deadbeef", stamp_age_s=None) is True


def test_structural_gate_still_suppresses_regardless_of_fingerprint(tmp_path: Path) -> None:
    """Gate 1 is unchanged: a corpus with no legal-merge pair at all is still suppressed."""
    _curated(tmp_path, "a.md", tier="component", type_="reference")
    _curated(tmp_path, "b.md", tier="component", type_="project")   # different type
    assert mcp.consolidate_has_work(tmp_path) is False


def test_content_has_work_threads_the_stamp_through(tmp_path: Path) -> None:
    _mergeable_pair(tmp_path)
    fp = mcp.corpus_fingerprint(tmp_path)
    assert mcp.content_has_work(
        "consolidate", tmp_path, split_max_bytes=_CAP, last_fingerprint=fp, stamp_age_s=60.0
    ) is False
    assert mcp.content_has_work("consolidate", tmp_path, split_max_bytes=_CAP) is True


# --------------------------------------------------------------------------- #
# issue #114 — the dispatch that could only ever refuse
# --------------------------------------------------------------------------- #


def _tiered_page(root: Path, name: str, tier: str, size: int) -> Path:
    p = root / name
    p.write_text(
        f"---\nname: {name[:-3]}\ndescription: \"d\"\nocd: 2026-01-01\nlmd: 2026-01-02\n"
        f"metadata:\n  node_type: memory\n  tier: {tier}\n---\n" + ("x" * size) + "\n",
        encoding="utf-8",
    )
    return p


def test_an_oversized_COMPONENT_is_surfaced_not_dispatched(tmp_path: Path) -> None:
    """The split skill MUST refuse an over-cap `tier: component` — one element, one page — so
    dispatching the agent for it spends a full context (~260k tokens, twice in one session)
    reaching the same refusal, and nothing re-tiers the page, so it recurs forever. The finding is
    NOT dropped: it moves to `oversized_mistiered_pages`, which costs a stat + 2 KB."""
    _tiered_page(tmp_path, "big-component.md", "component", 5000)
    assert mcp.split_has_work(tmp_path, max_bytes=1000) is False, "must not dispatch a refusal"
    found = mcp.oversized_mistiered_pages(tmp_path, max_bytes=1000)
    assert [p.name for p, _t in found] == ["big-component.md"]
    assert found[0][1] == "component"


def test_an_oversized_HUB_still_dispatches(tmp_path: Path) -> None:
    """The narrowing must not suppress REAL work — a hub/aspect over the cap is splittable (the
    splitter synthesizes seams), and that is the case the chore exists for."""
    _tiered_page(tmp_path, "big-hub.md", "hub", 5000)
    assert mcp.split_has_work(tmp_path, max_bytes=1000) is True
    assert mcp.oversized_mistiered_pages(tmp_path, max_bytes=1000) == []


def test_an_oversized_page_with_NO_readable_tier_still_dispatches(tmp_path: Path) -> None:
    """Unknown is not refusable. A page whose tier cannot be read may well be splittable, so it
    falls through to the normal dispatch path — the fail-open direction."""
    (tmp_path / "untiered.md").write_text(
        "---\nname: untiered\ndescription: \"d\"\n---\n" + ("x" * 5000), encoding="utf-8"
    )
    assert mcp.split_has_work(tmp_path, max_bytes=1000) is True
    assert mcp.oversized_mistiered_pages(tmp_path, max_bytes=1000) == []


def test_a_component_UNDER_the_cap_is_not_a_mistier(tmp_path: Path) -> None:
    """Being a component is fine; being a component that outgrew one element is the finding."""
    _tiered_page(tmp_path, "small-component.md", "component", 10)
    assert mcp.oversized_mistiered_pages(tmp_path, max_bytes=1000) == []


# --------------------------------------------------------------------------- #
# the per-CANDIDATE refusal ledger (issue #131) — conflict_has_work's filter
# --------------------------------------------------------------------------- #

def _pair(d: Path) -> tuple[Path, Path]:
    """Two real pages a conflict bullet can name, so the ledger can hash them."""
    a, b = d / "alpha.md", d / "beta.md"
    a.write_text("alpha body\n", encoding="utf-8")
    b.write_text("beta body\n", encoding="utf-8")
    return a, b


def _bullet() -> str:
    return "- topic `keychain`: alpha.md vs beta.md"


def test_conflict_pairs_parses_the_librarian_render_shape(tmp_path):
    """The pair identity — not just the bullet count — is what a refusal is keyed on."""
    _proposal(tmp_path, [_bullet(), "- topic `x`: c.md vs d.md"])
    assert mcp.conflict_pairs(tmp_path) == [("alpha.md", "beta.md"), ("c.md", "d.md")]


def test_a_refused_pair_does_not_redispatch(tmp_path, monkeypatch):
    """THE defect (#131/#106): the librarian re-lists a pair the agent already declined, and a
    non-empty list was read as unfinished work — a full ~170k-token dispatch to re-derive one `no`."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    _proposal(tmp_path, [_bullet()])
    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is True  # nobody has ruled yet

    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="different subjects")

    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is False


def test_editing_a_judged_page_re_arms_the_chore(tmp_path, monkeypatch):
    """The precision the corpus fingerprint lacks: a refusal expires on ITS OWN candidates' content,
    so editing the very pages under judgement legitimately re-opens the question."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    _proposal(tmp_path, [_bullet()])
    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="different subjects")
    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is False

    a.write_text("alpha body, now claiming something new\n", encoding="utf-8")

    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is True


def test_an_unrelated_edit_does_NOT_re_arm_a_refused_pair(tmp_path, monkeypatch):
    """The whole reason this is keyed on the CANDIDATE: the fingerprint gate re-arms every refused
    pair at once on any edit anywhere in the scope."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    _proposal(tmp_path, [_bullet()])
    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="different subjects")

    (tmp_path / "unrelated.md").write_text("a page nobody judged\n", encoding="utf-8")

    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is False


def test_one_unrefused_pair_keeps_the_chore_due(tmp_path, monkeypatch):
    """Idle means EVERY surfaced pair is refused — one open question is still work."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    (tmp_path / "gamma.md").write_text("gamma\n", encoding="utf-8")
    (tmp_path / "delta.md").write_text("delta\n", encoding="utf-8")
    _proposal(tmp_path, [_bullet(), "- topic `x`: gamma.md vs delta.md"])
    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="different subjects")

    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is True


def test_a_refusal_expires_after_the_ttl(tmp_path, monkeypatch):
    """The backstop for a crashed agent and for LLM non-determinism — same 7 days the fingerprint
    gate already uses, because two expiries for the same doubt would be a coin flip."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="x", now=1_000_000)
    assert memory_refusals.is_refused("conflict", "LOCAL", tmp_path, [a, b], now=1_000_000) is True
    later = 1_000_000 + memory_refusals.DEFAULT_TTL_S
    assert memory_refusals.is_refused("conflict", "LOCAL", tmp_path, [a, b], now=later) is False


def test_pair_order_does_not_matter(tmp_path, monkeypatch):
    """`(a, b)` and `(b, a)` are the SAME candidate; a re-ordered listing must not walk past it."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="x")
    assert memory_refusals.is_refused("conflict", "LOCAL", tmp_path, [b, a]) is True


def test_an_unreadable_candidate_is_never_recorded_as_refused(tmp_path, monkeypatch):
    """An entry that cannot say what it was looking at can never be invalidated by an edit — that is
    a permanent silence, not a refusal."""
    _isolate_gstate(monkeypatch, tmp_path)
    missing = tmp_path / "gone.md"
    assert memory_refusals.record("conflict", "LOCAL", tmp_path, [missing], reason="x") is False
    assert memory_refusals.is_refused("conflict", "LOCAL", tmp_path, [missing]) is False


def test_without_a_scope_the_filter_never_suppresses(tmp_path, monkeypatch):
    """The ledger is keyed per (intervention, scope, root); no scope ⇒ no read ⇒ no suppression."""
    _isolate_gstate(monkeypatch, tmp_path)
    a, b = _pair(tmp_path)
    _proposal(tmp_path, [_bullet()])
    memory_refusals.record("conflict", "LOCAL", tmp_path, [a, b], reason="x")
    assert mcp.conflict_has_work(tmp_path) is True


def test_an_unparseable_bullet_is_not_a_refused_one(tmp_path, monkeypatch):
    """A rendering change must degrade to dispatch, never to silence."""
    _isolate_gstate(monkeypatch, tmp_path)
    _proposal(tmp_path, ["- some future bullet shape nobody parsed"])
    assert mcp.conflict_has_work(tmp_path, scope="LOCAL") is True


def test_the_refusal_ledger_is_bounded(tmp_path, monkeypatch):
    """Bounded store (repo invariant S3/S4) — newest kept, oldest evicted."""
    _isolate_gstate(monkeypatch, tmp_path)
    for i in range(memory_refusals.REFUSALS_MAX + 15):
        p = tmp_path / f"p{i}.md"
        p.write_text(f"page {i}\n", encoding="utf-8")
        memory_refusals.record("conflict", "LOCAL", tmp_path, [p], reason="x", now=1_000_000 + i)
    ledger = memory_refusals.read("conflict", "LOCAL", tmp_path)
    assert len(ledger) == memory_refusals.REFUSALS_MAX
    assert f"p{memory_refusals.REFUSALS_MAX + 14}.md" in ledger
    assert "p0.md" not in ledger
