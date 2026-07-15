"""Tests for the wikimem edit verifier (TRDD-b92a9dd0).

Pure-function tests with literal note fixtures. The centerpiece is lesson
preservation — the strict, parser-independent anti-data-loss check: a DROPPED or
REWORDED `[^N]` lesson must FAIL, while a renumbered or compounded lesson PASSES.
Also covers the legality predicates (which merges/splits are refused), the
ocd/lmd invariants, dangling-link detection, duplicate detection, and the
split-specific globs-partition / convergence checks.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_edit_verify as v  # noqa: E402


def _note(*, name="x", ocd="2026-06-01", lmd="2026-06-01", tier="component",
          typ="project", body="A fact.", lessons="") -> str:
    return (
        f"---\nname: {name}\ndescription: \"d\"\nocd: {ocd}\nlmd: {lmd}\n"
        f"metadata:\n  node_type: memory\n  type: {typ}\n  tier: {tier}\n---\n\n"
        f"{body}\n\n## Notes and lessons learned\n{lessons}\n"
    )


# ---- frontmatter parsing ---------------------------------------------------

def test_parse_frontmatter_hoists_metadata_subkeys():
    """parse_frontmatter flattens top-level + metadata sub-keys into one dict."""
    fm = v.parse_frontmatter(_note(name="foo", tier="aspect", typ="reference"))
    assert fm["name"] == "foo" and fm["tier"] == "aspect" and fm["type"] == "reference"
    assert fm["ocd"] == "2026-06-01"


def test_parse_frontmatter_reads_flow_glob_list():
    """A flow-style globs list parses into a Python list of patterns."""
    text = "---\nname: h\nmetadata:\n  tier: hub\n  globs: [\"src/a/**\", \"src/b/**\"]\n---\n\nbody\n"
    fm = v.parse_frontmatter(text)
    assert fm["globs"] == ["src/a/**", "src/b/**"]


def test_parse_frontmatter_reads_flow_style_metadata_map():
    """Flow-style `metadata: {tier: …, globs: […]}` hoists the SAME keys as block
    style (audit Finding 1 — a flow-style page must NOT read tier=None and slip past
    the verify guards). Commas inside the globs list must not break the pairs."""
    flow = ("---\nname: h\nmetadata: {node_type: memory, type: project, tier: hub, "
            "globs: [\"src/a/**\", \"src/b/**\"]}\n---\n\nbody\n")
    fm = v.parse_frontmatter(flow)
    assert fm["tier"] == "hub"
    assert fm["type"] == "project"
    assert fm["node_type"] == "memory"
    assert fm["globs"] == ["src/a/**", "src/b/**"]


def test_parse_frontmatter_reads_block_style_glob_list():
    """M-4 (wikimem audit 2026-07-07): a BLOCK-style list (`globs:` followed by
    indented `- item` lines — what a generic YAML-writing agent naturally emits)
    parses into the same Python list flow style does. Pre-fix the no-colon item
    lines were skipped and `globs` read as an empty value."""
    text = (
        "---\nname: h\nmetadata:\n  tier: hub\n  globs:\n"
        "    - \"src/a/**\"\n    - 'src/b/**'\n---\n\nbody\n"
    )
    fm = v.parse_frontmatter(text)
    assert fm["globs"] == ["src/a/**", "src/b/**"]
    assert fm["tier"] == "hub"


def test_parse_frontmatter_reads_top_level_block_list():
    """A top-level block list (`tags:` + items) parses as a list too."""
    text = "---\nname: n\ntags:\n  - alpha\n  - beta\nocd: 2026-06-01\n---\nbody\n"
    fm = v.parse_frontmatter(text)
    assert fm["tags"] == ["alpha", "beta"]
    assert fm["ocd"] == "2026-06-01"  # a later scalar key closes the pending list


def test_block_style_hub_split_dropping_a_glob_fails():
    """M-4 regression: a hub whose globs are BLOCK-style must still trip the
    globs-partition gate when a split drops one of its patterns. Pre-fix the
    parent parsed as '' and split_globs_partition_ok('' vs ['']) was vacuous."""
    hub = (
        "---\nname: plat\nocd: 2026-06-01\nlmd: 2026-06-01\nmetadata:\n"
        "  tier: hub\n  type: project\n  globs:\n    - \"src/a/**\"\n    - \"src/b/**\"\n"
        "---\n\n## A\nx\n## B\ny\n\n## Notes and lessons learned\n"
    )
    meta = v.parse_frontmatter(hub)
    sub = v.parse_frontmatter(
        "---\nname: plat-a\nmetadata:\n  tier: hub\n  globs:\n    - \"src/a/**\"\n---\nx"
    )
    ok, why = v.split_globs_partition_ok(meta.get("globs"), [sub.get("globs")])
    assert ok is False and "src/b/**" in why


def test_flow_and_block_metadata_agree_for_legality():
    """A flow-style component pair merges legally exactly like block style, and a
    flow-style component is correctly REFUSED for splitting (reads tier=component,
    not None) — the bug was that flow-style read None and bypassed both guards."""
    flow_a = v.parse_frontmatter("---\nname: a\nmetadata: {tier: component, type: project}\n---\nx")
    flow_b = v.parse_frontmatter("---\nname: b\nmetadata: {tier: component, type: project}\n---\ny")
    assert v.is_legal_merge(flow_a, flow_b)[0] is True
    assert v.is_legal_split(flow_a, "## A\nx\n## B\ny")[0] is False


# ---- lesson preservation (THE strict check) --------------------------------

def test_lessons_preserved_tolerates_lmd_only_and_split_metadata_prefix():
    """A legal metadata-format change on a lesson prefix — `[lmd:…]` alone, or
    `[ocd:…] [lmd:…]` as two separate brackets — is NOT a reworded lesson, so
    preservation still passes when only the prefix differs (audit Finding 2)."""
    assert v.lessons_preserved(
        ["[^1]: [lmd:2026-06-09] the cap is 3, verified against source.\n"],
        "[^1]: the cap is 3, verified against source.\n",
    )[0] is True
    assert v.lessons_preserved(
        ["[^2]: [ocd:2026-06-01] [lmd:2026-06-09] timeouts default to 30s.\n"],
        "[^9]: timeouts default to 30s.\n",
    )[0] is True


# ---- repair (single-page page-shape / metadata backfill, TRDD-87935f21) -----

def test_verify_repair_passes_on_clean_backfill():
    """A repair that backfills the missing ocd/lmd/node_type/tier and keeps the
    lesson + the body PASSES (the source had only name/description/type)."""
    source = ("---\nname: x\ndescription: \"d\"\nmetadata:\n  type: project\n---\n\n"
              "A fact.\n\n## Notes and lessons learned\n[^1]: the cap is 3.\n")
    result = _note(name="x", ocd="2026-06-01", lmd="2026-06-19", tier="component",
                   typ="project", body="A fact.", lessons="[^1]: the cap is 3.\n")
    ok, reasons = v.verify_repair(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert ok, reasons


def test_verify_repair_fails_on_dropped_lesson():
    """Repair must never lose a lesson."""
    source = _note(lessons="[^1]: the cap is 3, verified.\n")
    result = _note(lessons="")
    ok, reasons = v.verify_repair(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("lesson" in r for r in reasons)


def test_verify_repair_passes_on_valid_tierless_page():
    """RECONCILE (issue #68 P3): the model says absent tier ⇒ component, so a minimal
    repair of a valid tier-less page must PASS — the gate used to demand tier and
    reject 22/28 legitimately tier-less LOCAL pages."""
    source = ("---\nname: x\ndescription: \"d\"\nmetadata:\n  type: project\n---\n\n"
              "A fact.\n\n## Notes and lessons learned\n[^1]: the cap is 3.\n")
    result = ("---\nname: x\ndescription: \"d\"\nocd: 2026-06-01\nlmd: 2026-06-19\n"
              "metadata:\n  node_type: memory\n  type: project\n---\n\n"
              "A fact.\n\n## Notes and lessons learned\n[^1]: the cap is 3.\n")
    ok, reasons = v.verify_repair(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert ok, reasons


def test_verify_repair_still_rejects_explicit_invalid_tier():
    """An EXPLICIT tier outside {hub, aspect, component} is still refused — only
    ABSENCE became valid, not junk values."""
    source = _note(tier="component")
    result = _note(tier="banana")
    ok, reasons = v.verify_repair(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("invalid tier" in r for r in reasons)


def test_verify_repair_fails_when_required_key_still_missing():
    """A 'repair' that did not actually backfill ocd/lmd/node_type is refused
    (tier is NOT required — absent means component per the model)."""
    txt = "---\nname: x\ndescription: \"d\"\nmetadata:\n  type: project\n---\n\nf\n\n## Notes and lessons learned\n"
    ok, reasons = v.verify_repair(txt, v.parse_frontmatter(txt), txt, v.parse_frontmatter(txt))
    assert not ok and any("missing required key" in r for r in reasons)


def test_verify_repair_fails_on_changed_ocd():
    """A repair must never rewrite a page's birth date (ocd)."""
    source = _note(ocd="2026-06-01", lmd="2026-06-01")
    result = _note(ocd="2026-06-19", lmd="2026-06-19")
    ok, reasons = v.verify_repair(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("ocd must not change" in r for r in reasons)


def test_verify_repair_fails_on_missing_notes_section():
    """The standing Notes section must be present after a repair."""
    source = _note()
    result = ("---\nname: x\ndescription: \"d\"\nocd: 2026-06-01\nlmd: 2026-06-19\n"
              "metadata:\n  node_type: memory\n  type: project\n  tier: component\n---\n\nA fact.\n")
    ok, reasons = v.verify_repair(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("Notes and lessons" in r for r in reasons)

def test_lessons_preserved_on_clean_merge():
    """Both sources' lessons survive in the result → preserved."""
    a = _note(name="a", lessons="[^1]: the cap is 3, verified against the source.\n")
    b = _note(name="b", lessons="[^1]: timeouts default to 30s per the config.\n")
    result = _note(name="c", lessons=(
        "[^1]: the cap is 3, verified against the source.\n"
        "[^2]: timeouts default to 30s per the config.\n"
    ))
    ok, missing = v.lessons_preserved([a, b], result)
    assert ok and missing == []


def test_lessons_preserved_fails_on_dropped_lesson():
    """A lesson present in a source but absent from the result → FAIL."""
    a = _note(name="a", lessons="[^1]: the cap is 3, verified against the source.\n")
    result = _note(name="c", lessons="")  # dropped it
    ok, missing = v.lessons_preserved([a], result)
    assert not ok and any("cap is 3" in m for m in missing)


def test_lessons_preserved_fails_on_reworded_lesson():
    """A silently REWORDED lesson (same number, changed words) → FAIL."""
    a = _note(name="a", lessons="[^1]: the cap is 3, verified against the source.\n")
    result = _note(name="c", lessons="[^1]: the limit is three, roughly.\n")
    ok, _ = v.lessons_preserved([a], result)
    assert not ok


def test_lessons_preserved_tolerates_renumber():
    """Renumbering [^1]→[^5] keeps the body → preserved (numbers are ignored)."""
    a = _note(name="a", lessons="[^1]: the cap is 3, verified against the source.\n")
    result = _note(name="c", lessons="[^5]: the cap is 3, verified against the source.\n")
    ok, _ = v.lessons_preserved([a], result)
    assert ok


def test_lessons_preserved_tolerates_compounding():
    """Appending later history to a lesson (compounding) keeps the original as a
    substring → preserved."""
    a = _note(name="a", lessons="[^1]: the cap is 3, verified against the source.\n")
    result = _note(name="c", lessons=(
        "[^1]: the cap is 3, verified against the source. Later raised to 5 in v2.\n"
    ))
    ok, _ = v.lessons_preserved([a], result)
    assert ok


def test_lessons_preserved_strips_ocd_lmd_prefix():
    """A lesson's [ocd:.. lmd:..] metadata prefix may change without false-failing."""
    a = _note(name="a", lessons="[^1]: [ocd:2026-06-01 lmd:2026-06-01] the cap is 3.\n")
    result = _note(name="c", lessons="[^3]: [ocd:2026-06-01 lmd:2026-06-09] the cap is 3.\n")
    ok, _ = v.lessons_preserved([a], result)
    assert ok


# ---- body-fact fidelity (issue #48) ----------------------------------------

def test_body_facts_preserved_on_clean_move():
    """Every substantive source fact appears in the result → preserved."""
    a = _note(name="a", body="The rotator retries three times then fails after a backoff.")
    result = _note(name="c", body="The rotator retries three times then fails after a backoff.")
    ok, missing = v.body_facts_preserved([a], result)
    assert ok and missing == []


def test_body_facts_preserved_fails_on_dropped_fact():
    """A substantive source fact absent from the result → FAIL (anti-corruption)."""
    a = _note(name="a", body="The rotator retries three times then fails after a backoff.")
    result = _note(name="c", body="An unrelated overview sentence about the whole system.")
    ok, missing = v.body_facts_preserved([a], result)
    assert not ok and any("rotator retries three times" in m for m in missing)


def test_body_facts_preserved_fails_on_paraphrase():
    """Issue #48: a PARAPHRASED body fact (a word changed) → FAIL."""
    a = _note(name="a", body="The rotator retries three times then fails after a backoff.")
    result = _note(name="c", body="The rotator retries five times then fails after a backoff.")
    ok, _ = v.body_facts_preserved([a], result)
    assert not ok


def test_body_facts_preserved_tolerates_dedup():
    """Two sources carrying the SAME fact → result keeps ONE copy → still preserved."""
    fact = "Timeouts default to thirty seconds per the platform config file."
    a = _note(name="a", body=fact)
    b = _note(name="b", body=fact)
    result = _note(name="c", body=fact)
    ok, missing = v.body_facts_preserved([a, b], result)
    assert ok and missing == []


def test_body_facts_preserved_tolerates_reorg_and_lead():
    """A reorganized result with an added lead, all facts kept verbatim → preserved."""
    a = _note(name="a", body=(
        "The rotator retries three times then fails after a backoff.\n"
        "Timeouts default to thirty seconds per the platform config file."
    ))
    result = _note(name="c", body=(
        "This page is the merged overview of the rotator behavior.\n\n"
        "## Timeouts\nTimeouts default to thirty seconds per the platform config file.\n\n"
        "## Retries\nThe rotator retries three times then fails after a backoff."
    ))
    ok, missing = v.body_facts_preserved([a], result)
    assert ok and missing == []


def test_body_facts_preserved_ignores_short_structural_lines():
    """A short (<24 char) line is structure, not a fact — dropping it does not fail."""
    a = _note(name="a", body="Retries: 3\nThe rotator retries three times then fails after a backoff.")
    result = _note(name="c", body="The rotator retries three times then fails after a backoff.")
    ok, _ = v.body_facts_preserved([a], result)
    assert ok


def test_verify_merge_fails_on_paraphrased_body_fact():
    """End-to-end: verify_merge catches a paraphrased body fact (issue #48 for merge)."""
    a = _note(name="a", body="The rotator retries three times then fails after a backoff.")
    b = _note(name="b", body="Timeouts default to thirty seconds per the platform config file.")
    result = _note(name="a", body=(
        "The rotator retries five times then fails after a backoff.\n"
        "Timeouts default to thirty seconds per the platform config file."
    ))
    ok, reasons = v.verify_merge(
        [a, b], [v.parse_frontmatter(a), v.parse_frontmatter(b)],
        result, v.parse_frontmatter(result), set(), {},
    )
    assert not ok and any("paraphrased body fact" in r for r in reasons)


def test_verify_split_fails_on_paraphrased_body_fact():
    """Issue #48: verify_split catches a sub-page that paraphrased a source fact."""
    src = _note(name="page", body=(
        "The USER scope lives in the plugin-data dir under dot-claude plugins.\n"
        "The rotator retries three times then fails after a backoff."
    ))
    sub1 = _note(name="page-a", body="The USER scope lives in the home dot-claude memory directory.")
    sub2 = _note(name="page-b", body="The rotator retries three times then fails after a backoff.")
    overview = _note(name="page", body="Overview linking the sub-pages of this topic together.")
    sizes = {"page.md": 100, "page-a.md": 100, "page-b.md": 100}
    ok, reasons = v.verify_split(
        src, v.parse_frontmatter(src), [sub1, sub2],
        [v.parse_frontmatter(sub1), v.parse_frontmatter(sub2)],
        overview, sizes, 12000,
    )
    assert not ok and any("body fact" in r for r in reasons)


# ---- harvest preservation (Part C) -----------------------------------------

def test_harvest_preservation_ok_when_pointer_target_exists():
    """A MEMORY.md pointer whose target note exists → preserved."""
    mem = "# MEMORY\n\n- [The cap rule](feedback_cap.md) — the retry cap is 3.\n"
    ok, missing = v.harvest_preservation_ok(mem, "irrelevant corpus", {"feedback_cap.md"})
    assert ok and missing == []


def test_harvest_preservation_fails_when_pointer_target_missing():
    """A pointer whose target note is gone → NOT preserved (would lose the memory)."""
    mem = "- [The cap rule](feedback_cap.md) — the retry cap is 3.\n"
    ok, missing = v.harvest_preservation_ok(mem, "", set())
    assert not ok and any("feedback_cap.md" in m for m in missing)


def test_harvest_preservation_ok_when_content_in_corpus():
    """A non-pointer content memory that now lives in a wiki page → preserved."""
    mem = "The OAuth rotator retries three times then fails after a backoff window.\n"
    corpus = "## Rotator\nThe OAuth rotator retries three times then fails after a backoff window.\n"
    ok, missing = v.harvest_preservation_ok(mem, corpus, set())
    assert ok and missing == []


def test_harvest_preservation_fails_when_content_not_in_corpus():
    """A content memory NOT yet in any wiki page → NOT preserved (abstain, keep MEMORY.md)."""
    mem = "The OAuth rotator retries three times then fails after a backoff window.\n"
    ok, missing = v.harvest_preservation_ok(mem, "an unrelated wiki page about other matters", set())
    assert not ok and any("rotator retries three times" in m for m in missing)


def test_harvest_preservation_stub_only_is_clean():
    """A MEMORY.md that is already the deprecation stub holds no memories → preserved."""
    stub = (
        "# MEMORY — index retired (managed by memgrep)\n\n"
        "⚠ DEPRECATED stub. Recall via memgrep.\n"
    )
    ok, missing = v.harvest_preservation_ok(stub, "", set())
    assert ok and missing == []


# ---- mirror preservation (TRDD-ab232dbd coexistence: buffer -> wiki) --------

def test_mirror_preservation_ok_when_buffer_fact_in_wiki():
    """A raw buffer note whose fact now lives in a curated wiki page → mirrored."""
    buffer = [("rotator.md", "The OAuth rotator retries three times then fails after a backoff.")]
    wiki = "## Rotator\nThe OAuth rotator retries three times then fails after a backoff.\n"
    ok, missing = v.mirror_preservation_ok(buffer, wiki)
    assert ok and missing == []


def test_mirror_preservation_fails_when_buffer_fact_absent():
    """A buffer note NOT yet mirrored into any wiki page → unmirrored (names the note)."""
    buffer = [("rotator.md", "The OAuth rotator retries three times then fails after a backoff.")]
    ok, missing = v.mirror_preservation_ok(buffer, "an unrelated wiki page about other matters")
    assert not ok
    assert any("rotator.md" in m for m in missing)


def test_mirror_preservation_ok_for_empty_buffer():
    """No raw buffer notes at all → trivially mirrored (the dormant-corpus case)."""
    ok, missing = v.mirror_preservation_ok([], "anything")
    assert ok and missing == []


def test_mirror_preservation_ignores_frontmatter_and_lessons():
    """Only substantive BODY facts must be mirrored — frontmatter/heading/lessons are
    not memories, so a buffer note whose only body fact is mirrored passes even though
    its frontmatter + a lessons footnote are absent from the wiki blob."""
    buffer = [(
        "cap.md",
        '---\nname: cap\ndescription: "d"\nmetadata:\n  type: feedback\n---\n'
        "The retry cap is three attempts then a hard fail.\n\n"
        "## Notes and lessons learned\n[^1]: earlier this said five — wrong.\n",
    )]
    wiki = "## Cap\nThe retry cap is three attempts then a hard fail.\n"
    ok, missing = v.mirror_preservation_ok(buffer, wiki)
    assert ok and missing == []


def test_mirror_preservation_reports_each_unmirrored_note():
    """Two unmirrored buffer notes → BOTH names surface (the agent mirrors them all)."""
    buffer = [
        ("a.md", "The first fact is a long enough sentence to count as substantive."),
        ("b.md", "The second fact is also a long enough sentence to be substantive."),
    ]
    ok, missing = v.mirror_preservation_ok(buffer, "")
    assert not ok
    assert any("a.md" in m for m in missing) and any("b.md" in m for m in missing)


# ---- duplicate detection ---------------------------------------------------

def test_no_new_duplicate_lines_flags_repeats():
    """A long content line repeated in the merged page → flagged."""
    text = "The widget retries three times then fails hard.\n\nThe widget retries three times then fails hard.\n"
    ok, dups = v.no_new_duplicate_lines(text)
    assert not ok and dups


def test_no_new_duplicate_lines_clean():
    """Distinct content lines → no duplicates."""
    ok, dups = v.no_new_duplicate_lines("First distinct sentence here.\nSecond distinct sentence here.\n")
    assert ok and dups == []


# ---- dangling-link / LINK LAW ----------------------------------------------

def test_no_dangling_refs_flags_retired_slug():
    """A surviving page still linking a retired slug → flagged (redirect missed)."""
    live = {"p": "see [[merged-c]] and [[old-a]] for detail"}
    ok, dangling = v.no_dangling_refs(live, {"old-a", "old-b"})
    assert not ok and any("old-a" in d for d in dangling)


def test_no_dangling_refs_clean_after_redirect():
    """All links point at survivors → no dangling refs."""
    live = {"p": "see [[merged-c]] for detail"}
    ok, dangling = v.no_dangling_refs(live, {"old-a", "old-b"})
    assert ok and dangling == []


# ---- ocd/lmd invariants ----------------------------------------------------

def test_ocd_lmd_ok_merge_keeps_oldest_origin():
    """The survivor's ocd is min(sources) and lmd advanced → ok."""
    metas = [{"ocd": "2026-05-01", "lmd": "2026-05-10"}, {"ocd": "2026-06-01", "lmd": "2026-06-09"}]
    result = {"ocd": "2026-05-01", "lmd": "2026-06-18"}
    ok, why = v.ocd_lmd_ok_merge(metas, result)
    assert ok, why


def test_ocd_lmd_ok_merge_fails_on_younger_ocd():
    """A survivor ocd newer than the oldest source loses origin history → FAIL."""
    metas = [{"ocd": "2026-05-01", "lmd": "2026-05-10"}, {"ocd": "2026-06-01", "lmd": "2026-06-09"}]
    result = {"ocd": "2026-06-01", "lmd": "2026-06-18"}
    ok, _ = v.ocd_lmd_ok_merge(metas, result)
    assert not ok


def test_ocd_lmd_ok_merge_fails_on_regressed_lmd():
    """A survivor lmd below the newest source lmd → FAIL."""
    metas = [{"ocd": "2026-05-01", "lmd": "2026-06-09"}]
    result = {"ocd": "2026-05-01", "lmd": "2026-05-01"}
    ok, _ = v.ocd_lmd_ok_merge(metas, result)
    assert not ok


# ---- legality: merge -------------------------------------------------------

def test_is_legal_merge_allows_same_tier_same_type():
    """Two components of the same type are a legal merge candidate."""
    ok, _ = v.is_legal_merge({"tier": "component", "type": "project"}, {"tier": "component", "type": "project"})
    assert ok


def test_is_legal_merge_refuses_cross_tier():
    """An aspect (radiating rule) cannot merge with a component (terminal leaf)."""
    ok, why = v.is_legal_merge({"tier": "aspect", "type": "project"}, {"tier": "component", "type": "project"})
    assert not ok and "cross-tier" in why


def test_is_legal_merge_refuses_two_hubs():
    """Two hubs are functionality overviews, not mergeable leaves."""
    ok, why = v.is_legal_merge({"tier": "hub", "type": "project"}, {"tier": "hub", "type": "project"})
    assert not ok and "not mergeable" in why


def test_is_legal_merge_refuses_cross_type():
    """A project note and a reference note are different kinds → refused."""
    ok, why = v.is_legal_merge({"tier": "component", "type": "project"}, {"tier": "component", "type": "reference"})
    assert not ok and "cross-type" in why


# ---- legality: split -------------------------------------------------------

def test_is_legal_split_refuses_component():
    """A component is one element (one element = one page) — never fragmented."""
    ok, why = v.is_legal_split({"tier": "component"}, "## Sec one\n## Sec two\n")
    assert not ok and "component" in why


def test_is_legal_split_allows_multi_section_hub():
    """A hub with several content sections is splittable."""
    body = "## Frontend\ndetail\n## Backend\ndetail\n## Database\ndetail\n"
    ok, _ = v.is_legal_split({"tier": "hub"}, body)
    assert ok


def test_is_legal_split_refuses_atomic_aspect():
    """A single-section aspect that is NOT oversized is one atomic note, left intact."""
    body = "## The only section\nbody\n## Notes and lessons learned\n[^1]: x\n"
    ok, why = v.is_legal_split({"tier": "aspect"}, body)
    assert not ok and "un-splittable" in why


def test_is_legal_split_synthesizes_seams_for_oversized_seamless():
    """Issue #57/#58 — a SEAMLESS hub/aspect that is OVER the cap is fail-safe
    splittable: the splitter synthesizes seams so it always converges, instead of
    abstaining every cycle forever."""
    seamless = "one long unbroken reference archive with no ## seams at all\n" * 3
    ok, why = v.is_legal_split({"tier": "aspect"}, seamless, oversized=True)
    assert ok and "synthesize" in why
    ok_hub, _ = v.is_legal_split({"tier": "hub"}, seamless, oversized=True)
    assert ok_hub


def test_is_legal_split_seamless_under_cap_left_intact():
    """A seamless page that is NOT oversized has nothing to gain from splitting —
    it stays one element (fail-safe synthesis is only for over-cap pages)."""
    ok, why = v.is_legal_split({"tier": "aspect"}, "tiny seamless note\n", oversized=False)
    assert not ok and "un-splittable" in why


def test_is_legal_split_oversized_component_still_refused():
    """Even oversized, a component is NEVER fragmented (one element = one page) —
    it is a mis-tier to surface for re-tiering, not a fail-safe split target."""
    big = "huge component body line\n" * 100
    ok, why = v.is_legal_split({"tier": "component"}, big, oversized=True)
    assert not ok and "component" in why


# ---- split-specific structural checks --------------------------------------

def test_split_globs_partition_ok_clean():
    """Sub-page globs that union to the parent with no overlap → ok."""
    ok, _ = v.split_globs_partition_ok(["a/**", "b/**", "c/**"], [["a/**"], ["b/**", "c/**"]])
    assert ok


def test_split_globs_partition_fails_on_overlap():
    """A glob owned by two sub-pages is an ambiguous owner → FAIL."""
    ok, why = v.split_globs_partition_ok(["a/**", "b/**"], [["a/**", "b/**"], ["b/**"]])
    assert not ok and "overlap" in why


def test_split_globs_partition_fails_on_missing_pattern():
    """A parent glob dropped from every sub-page → FAIL."""
    ok, why = v.split_globs_partition_ok(["a/**", "b/**", "c/**"], [["a/**"], ["b/**"]])
    assert not ok and "partition" in why


def test_split_converged_all_under_cap():
    """Every output page within the size cap → converged."""
    ok, oversized = v.split_converged({"overview.md": 800, "sub1.md": 5000}, max_bytes=12000)
    assert ok and oversized == []


def test_split_converged_fails_when_a_page_gave_up():
    """An over-cap page that is NOT flagged un-splittable means the split gave up."""
    ok, oversized = v.split_converged({"big.md": 30000}, max_bytes=12000)
    assert not ok and "big.md" in oversized


def test_split_converged_tolerates_flagged_unsplittable():
    """An over-cap page flagged un-splittable (one atomic note) is allowed."""
    ok, oversized = v.split_converged({"giant-note.md": 30000}, max_bytes=12000, unsplittable={"giant-note.md"})
    assert ok and oversized == []


# ---- composite verifier: verify_merge --------------------------------------

def test_verify_merge_clean_pass():
    """Both lessons preserved, ocd=min, no dups, no dangling → PASS."""
    a = _note(name="a", ocd="2026-05-01", lmd="2026-05-10",
              body="Auth uses JWT.", lessons="[^1]: the cap is 3, verified against the source.\n")
    b = _note(name="b", ocd="2026-06-01", lmd="2026-06-09",
              body="Tokens expire in 30s.", lessons="[^1]: timeouts default to 30s per the config.\n")
    result = _note(name="c", ocd="2026-05-01", lmd="2026-06-18",
                   body="Auth uses JWT. Tokens expire in 30s.", lessons=(
                       "[^1]: the cap is 3, verified against the source.\n"
                       "[^2]: timeouts default to 30s per the config.\n"))
    others = {"x.md": "see [[c]] for auth details"}
    ok, reasons = v.verify_merge(
        [a, b], [v.parse_frontmatter(a), v.parse_frontmatter(b)],
        result, v.parse_frontmatter(result), retired_slugs={"a", "b"}, other_live_pages=others,
    )
    assert ok, reasons


def test_verify_merge_fails_on_dropped_lesson():
    """A source lesson missing from the merged page → FAIL with a lesson reason."""
    a = _note(name="a", ocd="2026-05-01", lmd="2026-05-10",
              lessons="[^1]: the cap is 3, verified against the source.\n")
    b = _note(name="b", ocd="2026-06-01", lmd="2026-06-09",
              lessons="[^1]: timeouts default to 30s per the config.\n")
    result = _note(name="c", ocd="2026-05-01", lmd="2026-06-18",
                   lessons="[^1]: timeouts default to 30s per the config.\n")  # dropped a's lesson
    ok, reasons = v.verify_merge(
        [a, b], [v.parse_frontmatter(a), v.parse_frontmatter(b)],
        result, v.parse_frontmatter(result), retired_slugs={"a", "b"}, other_live_pages={},
    )
    assert not ok and any("lesson" in r for r in reasons)


def test_verify_merge_fails_on_dangling_ref():
    """A surviving OTHER page still linking a retired source slug → FAIL (redirect missed)."""
    a = _note(name="a", ocd="2026-05-01", lmd="2026-05-10", lessons="[^1]: cap is 3 per source.\n")
    b = _note(name="b", ocd="2026-06-01", lmd="2026-06-09", lessons="[^1]: 30s timeout per config.\n")
    result = _note(name="c", ocd="2026-05-01", lmd="2026-06-18", lessons=(
        "[^1]: cap is 3 per source.\n[^2]: 30s timeout per config.\n"))
    others = {"x.md": "still references [[a]] which no longer exists"}  # redirect missed
    ok, reasons = v.verify_merge(
        [a, b], [v.parse_frontmatter(a), v.parse_frontmatter(b)],
        result, v.parse_frontmatter(result), retired_slugs={"a", "b"}, other_live_pages=others,
    )
    assert not ok and any("dangling" in r for r in reasons)


# ---- composite verifier: verify_split --------------------------------------

def _hub(name, globs, body, lessons=""):
    glist = "[" + ", ".join(f'"{g}"' for g in globs) + "]"
    return (
        f"---\nname: {name}\ndescription: \"d\"\nocd: 2026-06-01\nlmd: 2026-06-01\n"
        f"metadata:\n  node_type: memory\n  type: project\n  tier: hub\n  globs: {glist}\n---\n\n"
        f"{body}\n\n## Notes and lessons learned\n{lessons}\n"
    )


def test_verify_split_clean_pass():
    """A hub split whose sub-pages partition the globs, preserve the lesson, and
    converge, with no dangling refs → PASS."""
    source = _hub("plat", ["src/a/**", "src/b/**"],
                  "## Frontend\nUI bits.\n## Backend\nServer bits.\n",
                  lessons="[^1]: the build flag is --release, learned the hard way.\n")
    overview = _hub("plat", ["src/a/**", "src/b/**"],
                    "Overview: see [[plat-frontend]] and [[plat-backend]].\n")
    sub1 = _hub("plat-frontend", ["src/a/**"],
                "UI bits.\n", lessons="[^1]: the build flag is --release, learned the hard way.\n")
    sub2 = _hub("plat-backend", ["src/b/**"], "Server bits.\n")
    sizes = {"plat.md": len(overview.encode()), "plat-frontend.md": len(sub1.encode()),
             "plat-backend.md": len(sub2.encode())}
    ok, reasons = v.verify_split(
        source, v.parse_frontmatter(source), [sub1, sub2],
        [v.parse_frontmatter(sub1), v.parse_frontmatter(sub2)], overview,
        sizes, max_bytes=12000, retired_slugs=set(), other_live_pages={},
    )
    assert ok, reasons


def test_verify_split_fails_on_dropped_lesson():
    """The source's lesson lost from every sub-page → FAIL."""
    source = _hub("plat", ["src/a/**", "src/b/**"],
                  "## Frontend\nUI.\n## Backend\nServer.\n",
                  lessons="[^1]: the build flag is --release, learned the hard way.\n")
    overview = _hub("plat", ["src/a/**", "src/b/**"], "Overview.\n")
    sub1 = _hub("plat-frontend", ["src/a/**"], "UI.\n")          # lesson dropped
    sub2 = _hub("plat-backend", ["src/b/**"], "Server.\n")
    sizes = {"plat.md": 500, "plat-frontend.md": 500, "plat-backend.md": 500}
    ok, reasons = v.verify_split(
        source, v.parse_frontmatter(source), [sub1, sub2],
        [v.parse_frontmatter(sub1), v.parse_frontmatter(sub2)], overview,
        sizes, max_bytes=12000, retired_slugs=set(), other_live_pages={},
    )
    assert not ok and any("lesson" in r for r in reasons)


def test_verify_split_fails_on_dangling_ref():
    """A retired source slug still linked by a surviving page → FAIL (redirect missed)."""
    source = _hub("plat", ["src/a/**"], "## Frontend\nUI.\n## Backend\nServer.\n",
                  lessons="[^1]: cap is 3.\n")
    overview = _hub("plat-overview", ["src/a/**"], "Overview.\n")  # source slug retired -> plat
    sub1 = _hub("plat-frontend", ["src/a/**"], "UI.\n", lessons="[^1]: cap is 3.\n")
    sizes = {"plat-overview.md": 500, "plat-frontend.md": 500}
    others = {"x.md": "links to [[plat]] still"}  # 'plat' retired, redirect missed
    ok, reasons = v.verify_split(
        source, v.parse_frontmatter(source), [sub1], [v.parse_frontmatter(sub1)], overview,
        sizes, max_bytes=12000, retired_slugs={"plat"}, other_live_pages=others,
    )
    assert not ok and any("dangling" in r for r in reasons)


# ---- verify_atomize (TRDD-3b9b2040 — prose -> atoms migration) -------------

_F1 = "The rotator drains the live account first when it is near a usage limit."
_F2 = "Credentials live in the macOS keychain, never in a plaintext slots directory."


def test_verify_atomize_passes_when_only_markers_added():
    """Atomize that appends `^id [keywords:..]` markers on their OWN lines, losing no
    fact or lesson, PASSES — the canonical happy path of the prose->atom migration."""
    source = _note(body=f"{_F1}\n\n{_F2}", lessons="[^1]: earlier said 5x; cap is 3.")
    atom_body = f"{_F1}\n^drain [keywords: rotator drain limit]\n\n{_F2}\n^keychain [keywords: keychain creds]"
    result = _note(body=atom_body, lessons="[^1]: earlier said 5x; cap is 3.")
    ok, reasons = v.verify_atomize(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert ok, reasons


def test_verify_atomize_fails_on_dropped_fact():
    """Atomize must NEVER drop a body fact while adding markers (the strict anti-corruption gate)."""
    source = _note(body=f"{_F1}\n\n{_F2}")
    result = _note(body=f"{_F1}\n^drain [keywords: rotator drain limit]")  # _F2 gone
    ok, reasons = v.verify_atomize(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("body fact" in r for r in reasons), reasons


def test_verify_atomize_fails_when_no_marker_added():
    """An atomize that added no `^id [..]` marker is a no-op and must not commit."""
    source = _note(body=f"{_F1}\n\n{_F2}")
    ok, reasons = v.verify_atomize(
        source, v.parse_frontmatter(source), source, v.parse_frontmatter(source)
    )
    assert not ok and any("no atom marker" in r for r in reasons), reasons


def test_verify_atomize_fails_on_non_marker_addition():
    """Atomize may ONLY add marker lines — smuggling in new prose is refused (additive-markers-only)."""
    atom_body = (
        f"{_F1}\n^drain [keywords: rotator drain limit]\n\n{_F2}\n^keychain [keywords: keychain creds]"
        "\n\nAn entirely new sentence that was never in the source page at all."
    )
    source = _note(body=f"{_F1}\n\n{_F2}")
    result = _note(body=atom_body)
    ok, reasons = v.verify_atomize(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("non-marker line" in r for r in reasons), reasons


def test_verify_atomize_fails_on_dropped_lesson():
    """A lesson is sacred even under atomize."""
    source = _note(body=f"{_F1}\n\n{_F2}", lessons="[^1]: the cap is 3, verified.")
    result = _note(body=f"{_F1}\n^drain [keywords: x]\n\n{_F2}\n^keychain [keywords: y]", lessons="")
    ok, reasons = v.verify_atomize(
        source, v.parse_frontmatter(source), result, v.parse_frontmatter(result)
    )
    assert not ok and any("lesson" in r for r in reasons), reasons


# ---- footnote-ref resolution: the shared-footnote move-rule (TRDD-3b9b2040 g3) ----

def test_footnote_refs_resolve_clean():
    """A `[^1]` ref with a matching `[^1]:` def on the same page → resolved."""
    ok, missing = v.footnote_refs_resolve("Fact.[^1]\n\n[^1]: the note.\n")
    assert ok and missing == []


def test_footnote_refs_resolve_flags_orphan_ref():
    """A `[^1]` ref with NO def on the page → a dangling footnote ref."""
    ok, missing = v.footnote_refs_resolve("Fact.[^1]\n\n(no def here)\n")
    assert not ok and missing == ["1"]


def test_footnote_refs_resolve_allows_orphan_def():
    """A `[^1]:` def with NO ref → allowed; an unreferenced def is harmless, only a
    ref-without-def is dangling (the def line's own `[^1]` marker cancels out)."""
    ok, missing = v.footnote_refs_resolve("Fact.\n\n[^1]: an unused note.\n")
    assert ok and missing == []


def test_no_new_dangling_footnote_refs_clean_move():
    """An atom + its SHARED def both land on each destination page → no new dangling."""
    src = ["A.[^1] B.[^1]\n\n[^1]: shared.\n"]
    res = ["A.[^1]\n\n[^1]: shared.\n", "B.[^1]\n\n[^1]: shared.\n"]  # def duplicated onto both
    ok, offenders = v.no_new_dangling_footnote_refs(src, res)
    assert ok and offenders == []


def test_no_new_dangling_footnote_refs_flags_dropped_shared_def():
    """The shared def is copied to only ONE result page while the other keeps the
    ref → a NEW dangling footnote ref → FAIL (the user's move-rule, violated)."""
    src = ["A.[^1] B.[^1]\n\n[^1]: shared.\n"]                        # 0 unresolved (def present)
    res = ["A.[^1]\n\n[^1]: shared.\n", "B.[^1]\n\n(def NOT copied here)\n"]  # page 2 orphaned
    ok, offenders = v.no_new_dangling_footnote_refs(src, res)
    assert not ok and offenders == ["[^1]"]


def test_no_new_dangling_footnote_refs_tolerates_preexisting():
    """A source that ALREADY had a dangling ref is not punished when the op merely
    carries it forward — the count does not INCREASE, so no new dangling."""
    src = ["Fact.[^9]\n\n(already broken — no def)\n"]                # 1 unresolved on the source
    res = ["Fact.[^9]\n\n(still broken — no def)\n"]                   # still 1, not more
    ok, _ = v.no_new_dangling_footnote_refs(src, res)
    assert ok


def test_no_new_dangling_footnote_refs_renumber_safe():
    """Renumbering a RESOLVED footnote keeps it resolved → no false positive (the
    check counts unresolved refs, it does not compare ids across the op)."""
    src = ["Fact.[^5]\n\n[^5]: note.\n"]
    res = ["Fact.[^1]\n\n[^1]: note.\n"]                               # 5 -> 1, still resolved
    ok, _ = v.no_new_dangling_footnote_refs(src, res)
    assert ok


def test_verify_split_fails_on_orphaned_shared_footnote():
    """g3 END-TO-END: a split that moves a SHARED `[^N]` footnote's ref onto a
    sub-page but fails to copy the def there → a dangling footnote ref on that
    sub-page → verify_split FAILS. The user's shared-footnote move-rule, enforced."""
    source = _hub("plat", ["src/a/**", "src/b/**"],
                  "## Frontend\nUI uses the shared retry policy.[^1]\n"
                  "## Backend\nServer uses the shared retry policy too.[^1]\n",
                  lessons="[^1]: retry policy is 3 attempts, shared by both layers.\n")
    overview = _hub("plat", ["src/a/**", "src/b/**"],
                    "Overview: see [[plat-frontend]] and [[plat-backend]].\n")
    sub1 = _hub("plat-frontend", ["src/a/**"],
                "UI uses the shared retry policy.[^1]\n",
                lessons="[^1]: retry policy is 3 attempts, shared by both layers.\n")
    sub2 = _hub("plat-backend", ["src/b/**"],
                "Server uses the shared retry policy too.[^1]\n")      # ref kept, def NOT copied
    sizes = {"plat.md": 500, "plat-frontend.md": 500, "plat-backend.md": 500}
    ok, reasons = v.verify_split(
        source, v.parse_frontmatter(source), [sub1, sub2],
        [v.parse_frontmatter(sub1), v.parse_frontmatter(sub2)], overview,
        sizes, max_bytes=12000, retired_slugs=set(), other_live_pages={},
    )
    assert not ok and any("footnote" in r for r in reasons), reasons


def test_verify_split_passes_when_shared_footnote_duplicated():
    """g3 regression: the CORRECT split copies the shared def onto BOTH sub-pages →
    every ref resolves → the new check does not block a clean split."""
    source = _hub("plat", ["src/a/**", "src/b/**"],
                  "## Frontend\nUI uses the shared retry policy.[^1]\n"
                  "## Backend\nServer uses the shared retry policy too.[^1]\n",
                  lessons="[^1]: retry policy is 3 attempts, shared by both layers.\n")
    overview = _hub("plat", ["src/a/**", "src/b/**"],
                    "Overview: see [[plat-frontend]] and [[plat-backend]].\n")
    sub1 = _hub("plat-frontend", ["src/a/**"],
                "UI uses the shared retry policy.[^1]\n",
                lessons="[^1]: retry policy is 3 attempts, shared by both layers.\n")
    sub2 = _hub("plat-backend", ["src/b/**"],
                "Server uses the shared retry policy too.[^1]\n",
                lessons="[^1]: retry policy is 3 attempts, shared by both layers.\n")  # def copied
    sizes = {"plat.md": 500, "plat-frontend.md": 500, "plat-backend.md": 500}
    ok, reasons = v.verify_split(
        source, v.parse_frontmatter(source), [sub1, sub2],
        [v.parse_frontmatter(sub1), v.parse_frontmatter(sub2)], overview,
        sizes, max_bytes=12000, retired_slugs=set(), other_live_pages={},
    )
    assert ok, reasons


def test_verify_merge_fails_on_orphaned_body_footnote():
    """g3 END-TO-END: a merge whose result body cites `[^2]` but only defines `[^1]:`
    → a dangling footnote ref → verify_merge FAILS (proves the merge wiring fires)."""
    a = _note(name="a", ocd="2026-05-01", lmd="2026-05-10",
              body="Auth uses JWT and rotates keys hourly.",
              lessons="[^1]: the cap is 3, verified against the source.\n")
    b = _note(name="b", ocd="2026-06-01", lmd="2026-06-09",
              body="Tokens expire after thirty seconds.", lessons="")
    result = _note(name="c", ocd="2026-05-01", lmd="2026-06-18",
                   body="Auth uses JWT and rotates keys hourly. [^2] Tokens expire after thirty seconds.",
                   lessons="[^1]: the cap is 3, verified against the source.\n")   # cites [^2], defines [^1]
    ok, reasons = v.verify_merge(
        [a, b], [v.parse_frontmatter(a), v.parse_frontmatter(b)],
        result, v.parse_frontmatter(result), retired_slugs={"a", "b"}, other_live_pages={},
    )
    assert not ok and any("footnote" in r for r in reasons), reasons


# ---- fact-preservation searches the WHOLE page, not the body (audit 2026-07-13) ----

def test_body_facts_preserved_counts_a_fact_demoted_into_a_lesson():
    """A fact MOVED from the body into a `[^N]` lesson is PRESERVED, not dropped — that
    relocation is exactly what the correction protocol mandates for a superseded fact."""
    src = _note(body="The rotator retries a failed refresh up to five times before failing over.")
    result = _note(
        body="The rotator retries a failed refresh three times before failing over.",
        lessons="[^1]: superseded — it used to be true that "
                "the rotator retries a failed refresh up to five times before failing over.\n",
    )
    ok, missing = v.body_facts_preserved([src], result)
    assert ok, missing


def test_body_facts_preserved_still_catches_a_truly_dropped_fact():
    """The widened haystack must not blunt the oracle: a fact present NOWHERE on the
    result page (neither body nor lessons) is still reported missing."""
    src = _note(body="The rotator retries a failed refresh up to five times before failing over.")
    result = _note(body="The rotator has a retry policy.", lessons="[^1]: unrelated lesson text.\n")
    ok, missing = v.body_facts_preserved([src], result)
    assert not ok and missing


def test_mirror_preservation_sees_past_the_first_pages_lessons_heading():
    """The harvest gate's `wiki_corpus` is a CONCATENATION of curated pages, each of which
    mandatorily carries `## Notes and lessons learned`. Truncating at the first such heading
    hid every page after the first, so a note mirrored into a LATER page read as unmirrored
    and the pass ABSTAINed forever. The whole-page haystack sees the later page."""
    buffer_note = ("raw-note.md", "The daemon holds a single machine-wide flock at all times.\n")
    page1 = _note(name="one", body="Something else entirely, unrelated to the daemon.",
                  lessons="[^1]: a lesson on page one.\n")
    page2 = _note(name="two", body="The daemon holds a single machine-wide flock at all times.")
    ok, missing = v.mirror_preservation_ok([buffer_note], "\n".join([page1, page2]))
    assert ok, missing


def test_verify_split_finds_a_fact_moved_into_a_later_subpages_body():
    """Regression for the same truncation on the split path: sub-page #1 carries lessons,
    and the source fact lives in sub-page #2's body — it must still be found."""
    source = _hub("plat", ["src/a/**", "src/b/**"],
                  "## Frontend\nUI bits render the agent profile sidepanel.\n"
                  "## Backend\nServer bits sign every request with the session key.\n",
                  lessons="[^1]: the build flag is --release, learned the hard way.\n")
    overview = _hub("plat", ["src/a/**", "src/b/**"],
                    "Overview: see [[plat-frontend]] and [[plat-backend]].\n")
    sub1 = _hub("plat-frontend", ["src/a/**"], "UI bits render the agent profile sidepanel.\n",
                lessons="[^1]: the build flag is --release, learned the hard way.\n")
    sub2 = _hub("plat-backend", ["src/b/**"],
                "Server bits sign every request with the session key.\n")
    sizes = {"plat.md": len(overview.encode()), "plat-frontend.md": len(sub1.encode()),
             "plat-backend.md": len(sub2.encode())}
    ok, reasons = v.verify_split(
        source, v.parse_frontmatter(source), [sub1, sub2],
        [v.parse_frontmatter(sub1), v.parse_frontmatter(sub2)], overview,
        sizes, max_bytes=12000, retired_slugs=set(), other_live_pages={},
    )
    assert ok, reasons


# ---- F2: a CONFLICT merge may supersede the RETIRED page's fact ------------------

def _conflict_pair():
    """The canonical conflict shape: an obsolete page contradicting the current one."""
    obsolete = _note(name="obsolete", ocd="2026-05-01", lmd="2026-05-02",
                     body="The rotator retries a failed refresh up to five times before failing over.")
    survivor = _note(name="current", ocd="2026-04-01", lmd="2026-06-01",
                     body="The rotator retries a failed refresh three times before failing over.")
    # Stage 4: survivor's body = the CURRENT truth; the obsolete claim is REWORDED into a lesson.
    result = _note(
        name="current", ocd="2026-04-01", lmd="2026-07-13",
        body="The rotator retries a failed refresh three times before failing over.",
        lessons="[^4]: [id:ATOM-234P-U35Q, status:valid, keywords:\"oauth_rotator retry_cap\", "
                "ocd:2026-07-13, lmd:2026-07-13] DO NOT assert the rotator retries 5x, as page "
                "obsolete did, BECAUSE 8f960ed capped it at 3. DO use 3 instead.\n",
    )
    return obsolete, survivor, result


def test_verify_merge_strict_facts_refuses_every_conflict_verdict():
    """FALSIFIER for the F2 fix: with the DEFAULT (all sources are fact sources), the
    conflict pass's only two output shapes are un-committable — the retired page's
    superseded claim is reworded, so it is not a substring of the survivor."""
    obsolete, survivor, result = _conflict_pair()
    ok, reasons = v.verify_merge(
        [obsolete, survivor],
        [v.parse_frontmatter(obsolete), v.parse_frontmatter(survivor)],
        result, v.parse_frontmatter(result),
        retired_slugs={"obsolete"}, other_live_pages={},
    )
    assert not ok and any("body fact" in r for r in reasons), reasons


def test_verify_merge_conflict_supersedes_the_retired_pages_fact():
    """F2: narrowing the fact sources to the SURVIVING pages lets the sanctioned conflict
    verdict commit — while lessons_preserved still guards every source's lessons."""
    obsolete, survivor, result = _conflict_pair()
    ok, reasons = v.verify_merge(
        [obsolete, survivor],
        [v.parse_frontmatter(obsolete), v.parse_frontmatter(survivor)],
        result, v.parse_frontmatter(result),
        retired_slugs={"obsolete"}, other_live_pages={},
        fact_source_texts=[survivor],          # the conflict pass's narrowing
    )
    assert ok, reasons


def test_verify_merge_conflict_still_guards_the_survivors_own_body():
    """F2's narrowing must not become a blanket exemption: a conflict that ALSO drops the
    SURVIVOR's own body fact is still refused (the survivor is the page it rewrites)."""
    obsolete, survivor, _ = _conflict_pair()
    corrupted = _note(
        name="current", ocd="2026-04-01", lmd="2026-07-13",
        body="The rotator has a retry policy.",          # the survivor's own fact: GONE
        lessons="[^4]: DO NOT assert the rotator retries 5x, BECAUSE 8f960ed capped it at 3. "
                "DO use 3 instead.\n",
    )
    ok, reasons = v.verify_merge(
        [obsolete, survivor],
        [v.parse_frontmatter(obsolete), v.parse_frontmatter(survivor)],
        corrupted, v.parse_frontmatter(corrupted),
        retired_slugs={"obsolete"}, other_live_pages={},
        fact_source_texts=[survivor],
    )
    assert not ok and any("body fact" in r for r in reasons), reasons


def test_verify_merge_conflict_still_guards_the_retired_pages_lessons():
    """The never-lost layer is untouched by F2: the retired page's `[^N]` lesson must still
    survive verbatim into the survivor, or the conflict verdict is refused."""
    obsolete, survivor, result = _conflict_pair()
    obsolete_with_lesson = obsolete.replace(
        "## Notes and lessons learned\n",
        "## Notes and lessons learned\n[^9]: DO NOT trust the cached count, BECAUSE it lags. "
        "DO re-read the source instead.\n",
    )
    ok, reasons = v.verify_merge(
        [obsolete_with_lesson, survivor],
        [v.parse_frontmatter(obsolete_with_lesson), v.parse_frontmatter(survivor)],
        result, v.parse_frontmatter(result),      # result never carried [^9]
        retired_slugs={"obsolete"}, other_live_pages={},
        fact_source_texts=[survivor],
    )
    assert not ok and any("lesson" in r for r in reasons), reasons


# ---- F11: a lesson body must not be truncated by its own quoted `#` line ----

def test_extract_lessons_does_not_truncate_at_a_shell_comment_in_the_body():
    """F11: the heading-stop `^#{1,6}\\s` also matched a SHELL COMMENT at column 0 inside a
    lesson that quotes a command. The truncation applied to source and result alike, so it
    could not false-fail — that is the problem: everything after that line silently fell
    OUTSIDE the sacred never-lost layer, and an editorial pass could drop it while still
    passing a check that advertises itself as STRICT."""
    text = (
        "## Notes and lessons learned\n"
        "[^1]: DO NOT stage with a wildcard, BECAUSE it sweeps in secrets. Use:\n"
        "# never use git add -A\n"
        "git add file1.ts file2.ts\n"
        "DO name every file instead.\n"
    )
    lessons = v.extract_lessons(text)
    assert len(lessons) == 1
    assert "do name every file instead" in lessons[0].lower(), lessons


def test_extract_lessons_still_stops_at_a_real_section_heading():
    """The L-2 stop must survive F11: a trailing `## See also` is NOT part of the last
    lesson (swallowing it contaminates the comparison and false-fails legitimate moves)."""
    text = (
        "## Notes and lessons learned\n"
        "[^1]: DO NOT trust the cached count, BECAUSE it lags. DO re-read the source.\n"
        "\n## See also\n"
        "- [[some-other-page]]\n"
    )
    lessons = v.extract_lessons(text)
    assert len(lessons) == 1
    assert "see also" not in lessons[0].lower()
    assert "some-other-page" not in lessons[0].lower()


def test_extract_lessons_keeps_code_a_lesson_quotes_inside_a_fence():
    """Fenced code is masked only to find BOUNDARIES — the lesson's real content (the code it
    quotes) must survive into the compared body, or it would fall outside the never-lost
    layer too."""
    text = (
        "## Notes and lessons learned\n"
        "[^1]: DO NOT use the wildcard form, BECAUSE it stages secrets:\n"
        "```bash\n"
        "# Setup\n"
        "git add -A\n"
        "```\n"
        "DO stage by name instead.\n"
    )
    lessons = v.extract_lessons(text)
    assert len(lessons) == 1
    assert "git add -a" in lessons[0].lower()               # the quoted code survived
    assert "do stage by name instead" in lessons[0].lower()  # ...and the fence did not stop it


def test_extract_lessons_stops_at_an_atom_marker():
    """MADJ00KA (issue #97): a `[^N]:` footnote followed by atomized fact content with NO
    closing `##` heading must STOP at the first atom marker — not swallow both atom blocks
    into one giant "lesson". Before the fix this returned one ~289-char lesson; the atomize
    and split passes collide on their own output otherwise (a split of an atomized oversized
    hub page false-fails, because no sub-page can reproduce the blob without staying unsplit)."""
    source = (
        "# Acme hub\n\n"
        "## Notes and lessons learned\n"
        "[^1]: the config key was misread; the cap is 3 not 5.\n\n"
        "^atom-1 [keywords: config, retries, cap]\n"
        "Retries are capped at 3 in acme.config.MAX_RETRIES, enforced at call time.\n\n"
        "^atom-2 [keywords: timeout, deadline]\n"
        "The request deadline defaults to 30s and is not configurable per-call.\n"
    )
    lessons = v.extract_lessons(source)
    assert len(lessons) == 1, lessons
    assert "the config key was misread" in lessons[0].lower()
    assert "atom-1" not in lessons[0].lower()   # the atom content is NOT part of the lesson
    assert "max_retries" not in lessons[0].lower()


def test_extract_lessons_still_captures_a_plain_footnote_to_eof():
    """DERIVED (MADJ00KA): the EOF alternative must remain — a page with NO atoms (a plain
    multi-line footnote running to end-of-file) still captures the WHOLE lesson body."""
    text = (
        "## Notes and lessons learned\n"
        "[^1]: a multi-line lesson body\n"
        "  that continues onto a second line and must be captured whole to EOF.\n"
    )
    lessons = v.extract_lessons(text)
    assert len(lessons) == 1
    assert "captured whole to eof" in lessons[0].lower()


def test_extract_lessons_atom_marker_inside_a_fence_does_not_stop_a_lesson():
    """DERIVED (MADJ00KA task 1): the atom-marker stop matches on the FENCE-MASKED `scan`,
    so an `^id [..]` line quoted inside a code fence is masked to spaces and cannot
    prematurely truncate a real lesson — same discipline as the `#`-heading boundary."""
    text = (
        "## Notes and lessons learned\n"
        "[^1]: an atomize marker looks like this:\n"
        "```\n"
        "^atom-x [keywords: a, b]\n"
        "```\n"
        "DO keep this trailing explanation in the lesson.\n"
    )
    lessons = v.extract_lessons(text)
    assert len(lessons) == 1
    assert "do keep this trailing explanation" in lessons[0].lower()
