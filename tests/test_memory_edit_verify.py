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


def test_verify_repair_fails_when_required_key_still_missing():
    """A 'repair' that did not actually backfill tier/ocd/lmd/node_type is refused."""
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
    """A single-section aspect is one atomic note, not splittable."""
    body = "## The only section\nbody\n## Notes and lessons learned\n[^1]: x\n"
    ok, why = v.is_legal_split({"tier": "aspect"}, body)
    assert not ok and "un-splittable" in why


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
