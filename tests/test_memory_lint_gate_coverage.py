"""janitor#200: every memgrep lint CODE must map to a chore gate that can dispatch on it —
or be explicitly, consciously tracked as orphaned.

`memgrep lint` (scripts/memgrep/src/memory.rs) can emit ~30 distinct finding codes. The
seven `*_has_work` prechecks in `memory_content_precheck.py` are what actually turn a
finding into a dispatched agent. Before this file, the mapping between the two existed
only in an issue-tracker table (janitor#200) that nothing checked against the source —
so a code could be added, removed, or silently reclassified with nothing noticing.

This file has TWO jobs, both real (no mocks — every fixture is linted by the ACTUAL
`memgrep` binary built from this tree, matching the "test the live production bundle"
convention every other memgrep-adjacent test here follows):

1. GROUND-TRUTH DRIFT GUARD — extract the full code set directly from the Rust source
   (never hand-typed) and assert it matches the classification table below. A new code
   added to memory.rs without updating `_CODE_COVERAGE` here fails this test immediately,
   forcing the classification to be a conscious decision rather than a silent gap.

2. LIVE PROOF for three representative codes, chosen because they are the ones the
   issue itself measured or singled out:
   - `page-no-notes-section` (COVERED — repair_has_work) proves the "covered" half of
     the claim is not just documentation: a real fixture missing the Notes section is
     both flagged by the linter AND makes repair_has_work return True.
   - `atom-no-keywords` (ORPHANED — the issue's own "fix this first" pick: "the finding
     that means this memory is permanently unfindable is one that no scheduled chore
     can act on") and `atom-oversized` (ORPHANED — the code that gave the issue its
     title) each prove the opposite: flagged by the linter, yet NONE of the seven
     `content_has_work` interventions return True for that same corpus — a dispatch
     aimed at either finding is a guaranteed, structurally-provable no-op today.

Per the issue's own caveat, the full 30-code table was derived by reading each gate
against each code, not by fixture-testing all 30 — this file keeps that honest: it
proves 3 codes for real and holds the rest to the drift guard, not a fixture claim.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import MEMGREP_BIN_PATH

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MEMORY_RS = _PROJECT_ROOT / "scripts" / "memgrep" / "src" / "memory.rs"

sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_content_precheck as mcp  # noqa: E402

needs_memgrep = pytest.mark.skipif(MEMGREP_BIN_PATH is None, reason="memgrep binary unavailable")

# Every finding is built as `violations.push((Severity::X, path, line, msg, "code"))` — the
# call may close with `));` (a plain statement) or `)),` (a match-arm expression, used where
# the code itself is chosen by a ternary, e.g. `if key == "ocd" { "atom-no-ocd" } else {
# "atom-no-lmd" }`), so BOTH terminators are matched, non-greedy so one block never swallows
# the next. Scoping the kebab-literal search to the TEXT INSIDE each push call (not the whole
# file) is what excludes unrelated literals like `"atom-page"` (a CLI subcommand name) or
# `"footnote-integrity"` (a string a TEST asserts against, not a code memgrep emits) without
# needing an explicit denylist — neither ever appears inside a `violations.push(...)` call.
_PUSH_BLOCK_RE = re.compile(r"violations\.push\(\(.*?\)\)[;,]", re.DOTALL)
_KEBAB_LITERAL_RE = re.compile(r'"([a-z][a-z0-9]*(?:-[a-z0-9]+)+)"')


def _extract_lint_codes_from_source() -> frozenset[str]:
    """Every finding code memory.rs can emit, read directly from the source (never
    hand-typed) — the ground truth the classification table below is checked against."""
    text = _MEMORY_RS.read_text(encoding="utf-8")
    codes: set[str] = set()
    for block in _PUSH_BLOCK_RE.findall(text):
        codes.update(_KEBAB_LITERAL_RE.findall(block))
    return frozenset(codes)


# code -> covering `content_has_work` intervention name, or None (orphaned: no scheduled
# chore's precheck can detect this condition — a dispatch aimed at it is a provable no-op).
# Mirrors janitor#200's own table exactly; kept here as living, source-checked documentation
# rather than a claim that lives only in the issue tracker.
_CODE_COVERAGE: dict[str, str | None] = {
    # Covered — repair_has_work's required-key / tier / Notes-section checks.
    "page-no-description": "repair",
    "page-no-ocd": "repair",
    "page-no-lmd": "repair",
    "page-no-notes-section": "repair",
    # Covered — memory_edit_verify.atom_desc_violations (repair_has_work's own bar).
    "atom-unquoted-desc": "repair",
    # Covered — explicit, TRDD-QKWU26ZG.
    "superseded-atom-above-delimiter": "repair",
    "superseded-atom-no-delimiter-heading": "repair",
    # Covered — janitor#260 endgame, and the ONE code where "covered" was the whole point of
    # adding it. The condition already had a chore GATE (`repair_defect`) but no ARBITER: the
    # linter the repair agent consults could not see it, which is janitor#227's shape (a gate
    # dispatching work its arbiter cannot confirm re-dispatches forever). Measured, not assumed:
    # on a page whose ONLY defect is the placement, `repair_defect` returns 'atom-after-footer',
    # and '' once the atom moves above the footer.
    "atom-after-footer": "repair",
    # Covered — TRDD-VOWAUVE5 / USER ruling 2026-08-22. `split_has_work` asks `memgrep lint`
    # itself for over-budget atoms, so the gate and this linter cannot disagree. Rides the
    # `split` chore rather than an eighth intervention because it is the same trigger class
    # (something is too big, break it into smaller pieces of the same kind) and because
    # memgrep's own refusal message already names janitor-memory-split as the owner.
    "atom-oversized": "split",
    "lesson-uncited": None,
    "atom-no-keywords": None,
    "atom-no-lmd": None,
    "atom-no-ocd": None,
    "atom-bad-ocd": None,
    "atom-bad-lmd": None,
    "atom-bad-bracket": None,
    "atom-dup-id": None,
    "atom-dropped-props": None,
    "atom-unclosed-props": None,
    "lesson-no-id": None,
    "lesson-no-keywords": None,
    "lesson-no-meta": None,
    "lesson-empty-body": None,
    "lesson-bad-bracket": None,
    "lesson-unquoted-desc": None,
    "lesson-superseded-no-body": None,
    "lesson-superseded-no-pointer": None,
    "footnote-dangling-ref": None,
    "link-one-sided": None,
    "link-downward-cross-scope": None,
    "stray-display-bracket": None,
    # Orphaned BY DESIGN, not by oversight. `page-unclosed-fence` exists to explain a
    # SILENT read failure to whoever is standing in front of it: an odd fence count makes
    # every walker swallow the rest of the page, so atoms below it vanish from lint, from
    # recall, and from the refusal message that sent you looking. Its two consumers are
    # `memgrep lint` and the atom-not-found hint — both synchronous, both human-facing.
    # A repair chore is the wrong owner: closing a fence requires knowing WHERE the author
    # meant it to end, which is an editorial judgement, and a chore that guessed would
    # silently restructure a page nobody asked it to touch. `memory_content_precheck` is
    # deliberately not body-fence-aware for the same reason (see its own comment at the
    # `_footer_heading_line` twin).
    "page-unclosed-fence": None,
}

_ALL_INTERVENTIONS = (
    "split", "repair", "atomize", "harvest", "retro-lesson", "consolidate", "conflict",
)


def test_classification_table_matches_the_source_exactly():
    """Drift guard: every code memory.rs can emit is classified here, and nothing
    classified here has stopped existing in the source. A code that is added, removed,
    or renamed in memory.rs without a matching edit here fails loudly instead of
    silently going unclassified (the janitor#200 failure mode, generalized)."""
    extracted = _extract_lint_codes_from_source()
    classified = frozenset(_CODE_COVERAGE)
    missing_from_table = extracted - classified
    stale_in_table = classified - extracted
    assert not missing_from_table, (
        f"new lint code(s) in memory.rs have no coverage classification: {sorted(missing_from_table)} "
        "— decide whether a chore gate covers them and add the row"
    )
    assert not stale_in_table, (
        f"classified code(s) no longer exist in memory.rs: {sorted(stale_in_table)} — remove the row"
    )
    # A deliberate SPEED BUMP, not a redundant length check. The two set assertions above
    # already force every code to be classified — but they pass silently when a commit adds a
    # code AND its row together, which is precisely the moment someone should have to state
    # whether a chore gate covers it. This constant is the one thing that fails then.
    # 30 -> 31: `atom-after-footer` (janitor#260 endgame), classified `repair` on a measurement.
    # 31 -> 32: `page-unclosed-fence`, classified ORPHANED on a measurement — `repair_defect`
    # returns no fence code and the precheck's only fence logic is for FRONTMATTER, not the
    # body. Orphaned here means "human-facing by design", see the row's own comment.
    assert len(_CODE_COVERAGE) == 32


def test_covered_codes_name_a_real_content_has_work_intervention():
    """Every non-None coverage claim must name an intervention content_has_work actually
    dispatches — catches a typo'd chore name from silently meaning 'always fails'."""
    for code, intervention in _CODE_COVERAGE.items():
        if intervention is not None:
            assert intervention in _ALL_INTERVENTIONS, f"{code}: unknown intervention {intervention!r}"


def _lint_codes(memgrep_bin: str, path: Path) -> set[str]:
    """The set of finding codes `memgrep lint` reports for `path`, at INFO+ (everything)."""
    proc = subprocess.run(
        [memgrep_bin, "lint", str(path), "--min-severity", "info"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    out = proc.stdout + proc.stderr
    return set(re.findall(r"\[([a-z0-9-]+)\]", out))


def _content_has_work_everywhere(root: Path, *, scope: str = "LOCAL") -> dict[str, bool]:
    """content_has_work for all 7 interventions on the same corpus, generously
    parameterized (a real cap, a real scope) so a False is never an artifact of a
    missing/zero argument rather than a genuine 'no work'."""
    return {
        iv: mcp.content_has_work(iv, root, split_max_bytes=36000, scope=scope)
        for iv in _ALL_INTERVENTIONS
    }


@needs_memgrep
def test_page_no_notes_section_is_both_flagged_and_dispatchable(tmp_path):
    """COVERED, proven live: a page missing '## Notes and lessons learned' is flagged by
    the real linter AND makes repair_has_work (hence content_has_work('repair', ...))
    return True — the claim in _CODE_COVERAGE is not just documentation."""
    page = tmp_path / "no-notes.md"
    page.write_text(
        "---\nname: no-notes\ndescription: \"a page missing its notes section\"\n"
        "ocd: 2026-07-01\nlmd: 2026-07-08\nmetadata:\n  node_type: memory\n"
        "  type: project\n  tier: component\n---\n\nA durable fact with no notes section.\n",
        encoding="utf-8",
    )
    codes = _lint_codes(str(MEMGREP_BIN_PATH), page)
    assert "page-no-notes-section" in codes, f"fixture must reproduce the code: {codes}"

    results = _content_has_work_everywhere(tmp_path)
    assert results["repair"] is True, f"repair must dispatch on this: {results}"


@needs_memgrep
def test_atom_no_keywords_is_flagged_but_dispatched_by_nothing(tmp_path):
    """ORPHANED, proven live — the issue's own "fix this first" pick: 'the finding
    that means this memory is permanently unfindable is one that no scheduled chore
    can act on.' A fixture carrying ONLY this defect (everything else well-formed) is
    flagged by the real linter yet leaves every content_has_work gate False."""
    page = tmp_path / "no-keywords.md"
    page.write_text(
        "---\nname: no-keywords\ndescription: \"a page whose atom has no keywords\"\n"
        "ocd: 2026-07-01\nlmd: 2026-07-08\nmetadata:\n  node_type: memory\n"
        "  type: project\n  tier: component\n---\n\n"
        '^some-fact [desc: "a fact with no keywords", ocd: 2026-07-01, lmd: 2026-07-08]\n'
        "The body of the fact.\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    codes = _lint_codes(str(MEMGREP_BIN_PATH), page)
    assert "atom-no-keywords" in codes, f"fixture must reproduce the code: {codes}"

    results = _content_has_work_everywhere(tmp_path)
    dispatching = [iv for iv, has_work in results.items() if has_work]
    assert not dispatching, (
        f"atom-no-keywords is documented ORPHANED, but {dispatching} would dispatch on this "
        "fixture — either the classification is stale or a gate now covers it; update _CODE_COVERAGE"
    )


@needs_memgrep
def test_atom_oversized_is_flagged_and_dispatched_by_split(tmp_path):
    """COVERED by `split`, proven live — the code that gave janitor#200 its title, and the
    last of the three the issue singled out to still be orphaned.

    This test asserted the OPPOSITE until 2026-08-22, and the inversion is the point:
    janitor#200 demoted `atom-oversized` to INFO for one stated reason — decomposition is
    semantic, so no chore could act on it. The USER's ruling (TRDD-VOWAUVE5 #6) created that
    owner, so the premise is gone. The fixture is unchanged; only the verdict moved.

    The page here is TINY, which is exactly what makes this a real proof: `split`'s size
    gate measures the PAGE, so nothing about the page's own bytes can be what dispatches.
    Only the atom-level check can be."""
    filler = "word " * 400  # collapses to ~2000 chars, well past the 1500 budget
    page = tmp_path / "oversized.md"
    page.write_text(
        "---\nname: oversized\ndescription: \"a page with an oversized atom\"\n"
        "ocd: 2026-07-01\nlmd: 2026-07-08\nmetadata:\n  node_type: memory\n"
        "  type: project\n  tier: component\n---\n\n"
        f'^big-fact [desc: "a big fact", keywords: symptom words, ocd: 2026-07-01, lmd: 2026-07-08]\n'
        f"{filler}\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    codes = _lint_codes(str(MEMGREP_BIN_PATH), page)
    assert "atom-oversized" in codes, f"fixture must reproduce the code: {codes}"

    results = _content_has_work_everywhere(tmp_path)
    dispatching = [iv for iv, has_work in results.items() if has_work]
    assert "split" in dispatching, (
        f"atom-oversized is documented COVERED by split, but only {dispatching} would "
        "dispatch on this fixture — the gate and _CODE_COVERAGE disagree, which is the "
        "janitor#227 shape this whole file exists to catch"
    )
    # The gate must agree with the linter about WHICH page, not merely that some work exists
    # — a boolean that happens to be True for an unrelated reason would pass the assert above
    # while leaving the agent with nothing to find.
    named = [p for p, _line in mcp.oversized_atom_pages(tmp_path)]
    assert [Path(p).name for p in named] == ["oversized.md"], (
        f"the gate must name the page the linter flagged, got {named}"
    )
