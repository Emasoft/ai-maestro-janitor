"""Unit tests for scripts/lib/trdd_common.py.

Covers the hoisted shared parsing helpers (so the trdd-drift / trdd-reminder
refactor stays honest) AND the four state-reconciliation checks (TRDD-15ECPBSA).
The checks are PURE over a parsed TrddRecord + an injectable `commit -> {tags}`
map, so EVERY check here runs with a FAKE tag map — no real git, fully
deterministic. The load-bearing regression — shipped-but-blocked → review, NOT
closeable — is `test_reconcile_shipped_but_blocked_is_review_not_closeable`.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))

import trdd_common as tc  # noqa: E402

# ── filename id extraction ───────────────────────────────────────────────────


def test_extract_uid_modern_lowercase_hex():
    """A current-format lowercase-hex id is extracted verbatim."""
    name = "TRDD-20260101_000000+0000-3b9b2040-some-slug.md"
    assert tc.extract_uid(name) == "3b9b2040"


def test_extract_uid_modern_uppercase_base36():
    """The modern UPPERCASE base36 id (NOT [0-9a-f]) is extracted — the legacy
    regex dropped these, which is exactly the gap the reconciliation detector
    must not have."""
    name = "TRDD-20260625_160351+0200-15ECPBSA-trdd-state-reconciliation-detector.md"
    assert tc.extract_uid(name) == "15ECPBSA"


def test_extract_uid_legacy_uuid():
    """A legacy `TRDD-<full-uuid>-slug.md` filename yields the UUID."""
    name = "TRDD-deadbeef-0000-0000-0000-000000000000-slug.md"
    assert tc.extract_uid(name) == "deadbeef-0000-0000-0000-000000000000"


def test_extract_uid_rejects_non_trdd():
    """A non-TRDD filename (no slug, or not a TRDD) returns None."""
    assert tc.extract_uid("TRDD-deadbeef.md") is None
    assert tc.extract_uid("notes.md") is None


def test_extract_uid_catches_uppercase_and_lowercase_ids():
    """The SINGLE matcher catches BOTH the modern UPPERCASE base36 id and the
    legacy lowercase-hex id (TRDD-15ECPBSA consolidated the two). The old
    `[0-9a-f]{8}`-only matcher silently dropped uppercase ids, hiding every stale
    v2 TRDD from trdd-drift / trdd-reminder — this proves that bug is fixed."""
    upper = "TRDD-20260625_160351+0200-15ECPBSA-x-slug.md"
    lower = "TRDD-20260101_000000+0000-3b9b2040-x-slug.md"
    assert tc.extract_uid(upper) == "15ECPBSA"   # case preserved
    assert tc.extract_uid(lower) == "3b9b2040"


# ── frontmatter state parsing ────────────────────────────────────────────────


def test_parse_state_text_column():
    text = "---\ntrdd-id: X\ntitle: T\ncolumn: dev\n---\n\nbody\n"
    assert tc.parse_state_text(text) == ("", "dev")


def test_parse_state_text_legacy_status_fallback():
    """A pre-frontmatter `**Status:** In progress` body still parses, normalised."""
    text = "# Title\n\n**Status:** In progress\n\nbody\n"
    assert tc.parse_state_text(text) == ("in-progress", "")


def test_a_v2_column_suppresses_the_legacy_BODY_status_fallback():
    """A card declaring `column:` is v2, so body prose may not fabricate a v1 status (#135).

    LEGACY_STATUS_RE scans the whole 4 KiB head, which includes BODY text — so a v2 card
    whose body merely CONTAINS a `**Status:** …` line (a STATE block, a progress table, a
    quoted example) was handed a v1 status its frontmatter does not have. Downstream, v1
    status outranked the column, so a frozen `column: complete` TRDD was reported as
    `status='not-started'` — a value present nowhere in the file, and unclearable because
    §12 forbids editing a terminal TRDD.
    """
    text = (
        "---\ntrdd-id: X\ntitle: T\ncolumn: complete\n---\n\n"
        "## STATE\n\n**Status:** Not started\n\nbody\n"
    )
    assert tc.parse_state_text(text) == ("", "complete")


def test_a_genuine_v1_card_still_gets_its_body_status():
    """The fallback must survive for real v1 cards — no `status:` AND no `column:`."""
    text = "---\ntrdd-id: X\ntitle: T\n---\n\n**Status:** Not started\n\nbody\n"
    assert tc.parse_state_text(text) == ("not-started", "")


def test_an_explicit_frontmatter_status_still_wins_over_the_body():
    """A real `status:` key is authoritative; the body line must not override it."""
    text = (
        "---\ntrdd-id: X\ntitle: T\nstatus: in-progress\n---\n\n"
        "**Status:** Not started\n\nbody\n"
    )
    assert tc.parse_state_text(text) == ("in-progress", "")


def test_is_pipeline_state_value_gates_on_the_VALUE_not_the_field_name():
    """`status:` is a DISTINCT field; only a pipeline VALUE in it is v1 residue (3P-TRDD-09).

    The field-NAME shape is what cost ai-maestro a data-loss bug: treating `status:` itself as
    retired made its fixer delete the line whatever it held, or convert it into a `column:`
    with an invented value. The 3-pillars spec documents carry `status: normative` — a live,
    non-pipeline use that must be left strictly alone, not even warned about.
    """
    for v in ("not-started", "in-progress", "completed"):        # v1 pipeline spellings
        assert tc.is_pipeline_state_value(v)
    for v in ("todo", "dev", "complete", "blocked", "proposal"):  # v2 columns
        assert tc.is_pipeline_state_value(v)
    for v in ("normative", "draft", "ratified", "", "  "):        # NOT pipeline states
        assert not tc.is_pipeline_state_value(v)
    # Case/whitespace normalised, so a human's spelling cannot dodge the gate either way.
    assert tc.is_pipeline_state_value("  Not Started \r")
    assert not tc.is_pipeline_state_value(" Normative ")


def test_v1_not_started_maps_to_todo_not_backburner():
    """`todo` is v2's ready-to-start column; `backburner` is deliberately-deferred.

    Mapping a v1 `not-started` onto `backburner` buried a card that was ready to be worked;
    `todo` forces the next agent to evaluate it (3P-TRDD-11). `not-started` is not itself a
    v2 state at all — v2 has exactly one ready-to-start column and it is `todo`.
    """
    assert tc.V1_PIPELINE_STATUS_TO_COLUMN["not-started"] == "todo"
    assert tc.V1_PIPELINE_STATUS_TO_COLUMN["in-progress"] == "dev"
    assert tc.V1_PIPELINE_STATUS_TO_COLUMN["completed"] == "complete"
    # Every mapped target must be a real column, or the board grows a phantom lane.
    for col in tc.V1_PIPELINE_STATUS_TO_COLUMN.values():
        assert col in tc.ALL_COLUMNS


def test_norm_state_collapses_and_lowercases():
    assert tc.norm_state("  Not Started \r") == "not-started"


def test_terminal_and_active_column_sets():
    """The terminal set is the documented closed columns; the keystone treats
    everything else (incl. the parked entry columns) as non-terminal."""
    for c in ("published", "complete", "live", "failed", "superseded", "cancelled", "refused"):
        assert tc.is_terminal_column(c)
    for c in ("dev", "testing", "blocked", "backburner", "todo", "dispatch"):
        assert not tc.is_terminal_column(c)


# ── frontmatter defect detection (the invisible-TRDD guard) ──────────────────


def test_frontmatter_defect_none_for_wellformed():
    """A TRDD whose YAML block opens on byte 0 reports no defect."""
    head = "---\ntrdd-id: ABCD1234\ncolumn: dev\n---\n\n# Title\n"
    assert tc.frontmatter_defect(head) is None


def test_frontmatter_defect_heading_above_frontmatter():
    """The TRDD-WEBA1RMF defect: a `# title` ABOVE the frontmatter makes every
    machine field invisible. Asserts the invisibility first, so the test fails
    loudly if parse_state_text ever starts tolerating it and the guard silently
    becomes dead code."""
    head = "# Some title\n\n---\ntrdd-id: ABCD1234\ncolumn: dev\n---\n"
    assert tc.parse_state_text(head) == ("", "")
    defect = tc.frontmatter_defect(head)
    assert defect is not None
    assert "line 1" in defect
    assert "# Some title" in defect


def test_frontmatter_defect_blank_first_line():
    """A single leading blank line is enough to break the \\A anchor."""
    head = "\n---\ntrdd-id: ABCD1234\ncolumn: dev\n---\n"
    assert tc.parse_state_text(head) == ("", "")
    assert tc.frontmatter_defect(head) is not None


def test_frontmatter_defect_bom_is_named_specifically():
    """A UTF-8 BOM is invisible in an editor, so the message must NAME it — a
    generic 'line 1 is ---' would send the author hunting a fault they cannot
    see, which is worse than no message."""
    # chr(0xFEFF), not tc.BOM — an independent oracle. Reusing the module's own
    # constant would make this test pass even if that constant were wrong.
    head = chr(0xFEFF) + "---\ntrdd-id: ABCD1234\ncolumn: dev\n---\n"
    defect = tc.frontmatter_defect(head)
    assert defect is not None
    assert "BOM" in defect


def test_frontmatter_defect_unclosed_block():
    """Opens on line 1 but never closes — a distinct message from 'does not
    open', because the two need opposite fixes."""
    head = "---\ntrdd-id: ABCD1234\ncolumn: dev\n"
    defect = tc.frontmatter_defect(head)
    assert defect is not None
    assert "never closes" in defect


def test_frontmatter_defect_empty_file():
    """An empty file is reported as empty, not as a missing-frontmatter riddle."""
    assert tc.frontmatter_defect("   \n") == "file is empty"


def test_frontmatter_defect_for_unreadable_file_is_silent(tmp_path):
    """A file we cannot read is not evidence of a malformed TRDD — staying
    silent beats emitting a defect the author has no way to act on."""
    assert tc.frontmatter_defect_for(tmp_path / "nope.md") is None


def test_frontmatter_defect_for_reads_real_files(tmp_path):
    """End-to-end over real files on disk — no mocks."""
    good = tmp_path / "good.md"
    good.write_text("---\ncolumn: dev\n---\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("# T\n\n---\ncolumn: dev\n---\n", encoding="utf-8")
    assert tc.frontmatter_defect_for(good) is None
    assert tc.frontmatter_defect_for(bad) is not None


# ── flow-list / ref parsing ──────────────────────────────────────────────────


def test_blocked_by_ids_flow_list():
    assert tc.blocked_by_ids("[TRDD-3b9b2040, TRDD-15ECPBSA]") == ["3b9b2040", "15ECPBSA"]
    assert tc.blocked_by_ids("[]") == []
    assert tc.blocked_by_ids("[3b9b2040]") == ["3b9b2040"]


def test_impl_commit_shas_keeps_only_hex():
    raw = "[a1b2c3d4e5f6, deadbeef, null, not-a-sha]"
    assert tc.impl_commit_shas(raw) == ["a1b2c3d4e5f6", "deadbeef"]


def test_extract_trdd_refs_dedup_order():
    body = "publish BLOCKED on TRDD-3b9b2040; also see TRDD-15ECPBSA and TRDD-3b9b2040 again"
    assert tc.extract_trdd_refs(body) == ["3b9b2040", "15ECPBSA"]


# ── record parsing ───────────────────────────────────────────────────────────


def _record(*, column="dev", blocked_by="[]", impl="[]", body="\n# body\n") -> tc.TrddRecord:
    text = textwrap.dedent(
        f"""\
        ---
        trdd-id: TESTID01
        title: T
        column: {column}
        blocked-by: {blocked_by}
        implementation-commits: {impl}
        ---
        """
    ) + body
    return tc.parse_record_text(text, uid="TESTID01")


def test_parse_record_text_extracts_fields():
    rec = _record(column="dev", blocked_by="[TRDD-3b9b2040]", impl="[abc1234]")
    assert rec.column == "dev"
    assert rec.blocked_by == ["3b9b2040"]
    assert rec.impl_commits == ["abc1234"]
    assert "# body" in rec.body


# ── Check 1 — shipped-but-open (the keystone) ────────────────────────────────


def _tagmap(*shas: str) -> dict[str, list[str]]:
    """Fake `commit -> tags` map: every listed sha is in a released v-tag."""
    return {sha: ["v1.2.3"] for sha in shas}


def _in_tag(tagmap):
    return lambda sha: bool(tagmap.get(sha))


def test_check1_fires_when_commit_in_tag_and_open():
    rec = _record(column="dev", impl="[abc1234]")
    assert tc.check1_shipped_but_open(rec, _in_tag(_tagmap("abc1234"))) is True


def test_check1_silent_when_no_commit_in_tag():
    rec = _record(column="dev", impl="[abc1234]")
    assert tc.check1_shipped_but_open(rec, _in_tag(_tagmap())) is False


def test_check1_silent_when_terminal_even_if_in_tag():
    """A terminal (published) TRDD whose commits are in a tag is ALREADY closed —
    the keystone must not flag it."""
    rec = _record(column="published", impl="[abc1234]")
    assert tc.check1_shipped_but_open(rec, _in_tag(_tagmap("abc1234"))) is False


def test_check1_silent_when_no_commits_known():
    rec = _record(column="dev", impl="[]")
    assert tc.check1_shipped_but_open(rec, _in_tag(_tagmap("whatever"))) is False


# ── Check 2 — remaining-work gate ────────────────────────────────────────────


def test_check2_blocked_column_is_remaining():
    rec = _record(column="blocked")
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_unchecked_box_is_remaining():
    rec = _record(body="\n## plan\n- [ ] still to do\n- [x] done\n")
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_PARTIAL_box_is_remaining():
    """A `[~]` box is remaining work — it means started-and-honestly-not-tickable.

    This repo uses `[~]` for a box whose author judged that neither `[x]` nor `[ ]` was
    true: work is under way but the criterion is not met (a tally still accumulating, a
    superseded framing). Counting only `[ ]` read those cards as having NOTHING left, so
    a card with one `[~]` and no unchecked box was labelled a CLOSEABLE CANDIDATE.

    Measured on the real board 2026-08-21: TRDD-JEEQCHFG returned
    `check2_has_remaining_work() == False` while carrying a `[~]` whose own prose reads
    "Deliberately not ticked … closes only once enough real firings have been classified".
    That is the failure direction this function's docstring already calls the expensive
    one — nobody re-reads a card the board has called closeable.
    """
    rec = _record(body="\n## plan\n- [~] started, criterion not met yet\n- [x] done\n")
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_partial_box_counts_with_an_asterisk_bullet_too():
    """`* [~]` as well as `- [~]` — the board uses both bullet characters.

    JEEQCHFG, the card that exposed this, writes its acceptance list with `*`.
    """
    rec = _record(body="\n## plan\n* [~] started, not tickable\n")
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_next_action_without_done_marker_is_remaining():
    rec = _record(body="\n## STATE\n- NEXT ACTION: wire the thing\nstuff\n")
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_next_action_with_done_marker_is_not_remaining():
    """A NEXT-ACTION line whose latest STATE marker says ✅/DONE does NOT count as
    remaining work — the work the next-action named is finished."""
    rec = _record(body="\n## STATE\n- NEXT ACTION: ship it ✅ DONE — shipped in v1.2.3\n")
    assert tc.check2_has_remaining_work(rec) is False


def test_check2_clean_body_is_not_remaining():
    rec = _record(body="\n# body\nall shipped.\n")
    assert tc.check2_has_remaining_work(rec) is False


def test_check2_done_marker_on_subpart_does_not_mask_pending_next_action():
    """A ✅/DONE on a finished SUB-part must NOT mask a still-pending NEXT-ACTION:
    the done-marker check is scoped to the NEXT-ACTION line itself. The real-board
    smoke test caught the old whole-body check mislabeling standing / partly-done
    TRDDs (e.g. a USER-GATED next action) as closeable (TRDD-15ECPBSA)."""
    rec = _record(
        body=(
            "\n## STATE\n"
            "- g1 step ✅ DONE\n"
            "- g2 step ✅ SHIPPED\n"
            "- NEXT ACTION (the only remaining item — USER-GATED): the migration\n"
        )
    )
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_done_next_action_line_does_not_mask_a_pending_one():
    """A DONE-marked NEXT-ACTION line must not mask a still-pending NEXT-ACTION
    line elsewhere on the card (TRDD-N7NZOYAK).

    The per-line scoping fixed the case where the done marker sits on a
    NON-next-action line, but the quantifier still read "remaining only if NONE
    of these lines is done" — so one finished next action made the whole card
    look closeable. Found in the wild: a STATE refresh added a table row
    containing the phrase and a DONE marker, and the card's real pending action
    four lines below stopped being counted."""
    rec = _record(
        body=(
            "\n## STATE\n"
            "| the NEXT ACTION list was stale | **DONE** — shipped in v0.45.0 |\n"
            "**NEXT ACTION:** validate end-to-end against a real reauth\n"
        )
    )
    assert tc.check2_has_remaining_work(rec) is True


def test_check2_all_next_action_lines_done_is_not_remaining():
    """The complement, so the fix cannot be satisfied by always returning True:
    when EVERY next-action line carries a done marker there is no remaining
    work."""
    rec = _record(
        body=(
            "\n## STATE\n"
            "- NEXT ACTION: land the migration ✅ DONE\n"
            "- NEXT ACTION: publish it — SHIPPED in v1.2.3\n"
        )
    )
    assert tc.check2_has_remaining_work(rec) is False


# ── Check 3 — prose↔frontmatter mismatch ─────────────────────────────────────


def test_check3_prose_says_blocked_frontmatter_does_not():
    rec = _record(column="dev", blocked_by="[]", body="\npublish is BLOCKED on GROUP B\n")
    assert tc.check3_prose_frontmatter_mismatch(rec) is True


def test_check3_silent_when_column_is_blocked():
    """If the frontmatter ALREADY says blocked, prose+frontmatter agree → no
    mismatch."""
    rec = _record(column="blocked", body="\nthis is blocked on X\n")
    assert tc.check3_prose_frontmatter_mismatch(rec) is False


def test_check3_silent_when_blocked_by_populated():
    rec = _record(column="dev", blocked_by="[TRDD-3b9b2040]", body="\nblocked on TRDD-3b9b2040\n")
    assert tc.check3_prose_frontmatter_mismatch(rec) is False


def test_check3_silent_without_blocked_prose():
    rec = _record(column="dev", body="\nall good, nothing here\n")
    assert tc.check3_prose_frontmatter_mismatch(rec) is False


def test_check3_no_false_positive_on_unblocked_or_blocker():
    """The blocked-prose regex must NOT fire on `unblocked` (the OPPOSITE of
    blocked) or `blocker` (a different stem) — those are common in STATE prose of
    a TRDD that is fine. A non-letter boundary + lookbehind guards this."""
    for body in ("\nthe work is now unblocked and shipping\n",
                 "\nthis resolves the blocker cleanly\n"):
        rec = _record(column="dev", blocked_by="[]", body=body)
        assert tc.check3_prose_frontmatter_mismatch(rec) is False, body


def test_check3_silent_on_terminal_trdd_with_historical_blocked_prose():
    """A TERMINAL (complete/published/…) TRDD whose STATE mentions a past block is
    CLOSED — its prose is settled, not live drift, so Check 3 must skip it (mirrors
    Check 4's terminal guard). The real-board smoke test caught Check 3 flagging
    `complete` TRDDs whose prose said 'blocked on a CPV' (a long-shipped version)."""
    for col in ("complete", "published", "superseded", "failed"):
        rec = _record(column=col, blocked_by="[]", body="\npublish was BLOCKED on a CPV bug\n")
        assert tc.check3_prose_frontmatter_mismatch(rec) is False, col


# ── Check 4 — stale blocker ──────────────────────────────────────────────────


def _column_of(mapping):
    return lambda uid: mapping.get(uid, "")


def test_check4_frontmatter_blocker_now_terminal():
    rec = _record(column="blocked", blocked_by="[TRDD-3b9b2040]")
    stale = tc.check4_stale_blockers(rec, _column_of({"3b9b2040": "published"}))
    assert stale == ["3b9b2040"]


def test_check4_blocker_still_active_is_not_stale():
    rec = _record(column="blocked", blocked_by="[TRDD-3b9b2040]")
    stale = tc.check4_stale_blockers(rec, _column_of({"3b9b2040": "dev"}))
    assert stale == []


def test_check4_prose_named_blocker_now_terminal():
    """A STATE-named blocker (not in frontmatter) that is now terminal is caught,
    but only when the prose actually says blocked."""
    rec = _record(column="dev", blocked_by="[]", body="\npublish BLOCKED on TRDD-3b9b2040\n")
    stale = tc.check4_stale_blockers(rec, _column_of({"3b9b2040": "live"}))
    assert stale == ["3b9b2040"]


def test_check4_prose_blocker_spanning_lines_in_one_paragraph_is_reported():
    """The prose-named blocker is scoped to the PARAGRAPH, not the line
    (TRDD-FR4NS7I4).

    A real blocker declaration routinely wraps: the block word lands on one line
    and the id on the next. That shape is the reason the scope is a paragraph and
    not a line — taken from TRDD-3XS3PDCF's live text, which is the corpus's true
    positive for this check."""
    rec = _record(
        column="dev",
        blocked_by="[]",
        body=(
            "\n## STATE\n"
            "- HARVEST precheck stays BLOCKED (not merely deferred) because the\n"
            "  work-predicate is in flux — see TRDD-3b9b2040.\n"
        ),
    )
    stale = tc.check4_stale_blockers(rec, _column_of({"3b9b2040": "published"}))
    assert stale == ["3b9b2040"]


def test_check4_citation_in_another_paragraph_is_not_a_blocker():
    """An id cited ELSEWHERE in the body is not a blocker just because the card's
    prose says blocked somewhere (TRDD-FR4NS7I4).

    Live shape: TRDD-2C8XFOW9 is correctly blocked on an out-of-repo issue and
    cites EQ792YPX / T7N67AQP to REUSE them — it is the EHT of the first and takes
    a presence gate from the second, so their being terminal is what makes them
    useful. Whole-body scoping reported all of them, on a card that was already
    right and so could not be fixed by editing it."""
    rec = _record(
        column="dev",
        blocked_by="[]",
        body=(
            "\n## STATE\n"
            "This card is BLOCKED on an upstream answer.\n"
            "\n"
            "Reuse notes: this is the EHT of TRDD-3b9b2040, and it takes the\n"
            "presence gate from TRDD-aebedbff.\n"
        ),
    )
    stale = tc.check4_stale_blockers(
        rec, _column_of({"3b9b2040": "published", "aebedbff": "complete"})
    )
    assert stale == []


def test_check4_frontmatter_blocker_reported_even_without_block_prose():
    """Narrowing the PROSE path must not touch the frontmatter path: a declared
    blocked-by is authoritative whatever the body says (TRDD-FR4NS7I4)."""
    rec = _record(column="blocked", blocked_by="[TRDD-3b9b2040]", body="\nno block language here\n")
    assert tc.check4_stale_blockers(rec, _column_of({"3b9b2040": "published"})) == ["3b9b2040"]


def test_check4_silent_when_self_terminal():
    rec = _record(column="published", blocked_by="[TRDD-3b9b2040]")
    assert tc.check4_stale_blockers(rec, _column_of({"3b9b2040": "published"})) == []


# ── reconcile() — the consolidated verdict ───────────────────────────────────


def test_reconcile_shipped_and_clean_is_closeable():
    """Check1 fires + Check2 clear → the STRONG 'closeable-candidate' verdict."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nall shipped.\n")
    v = tc.reconcile(rec, _in_tag(_tagmap("abc1234")), _column_of({}))
    assert v.fires
    assert v.label == "closeable-candidate"
    assert v.shipped_commits == ["abc1234"]


def test_reconcile_shipped_but_blocked_is_review_not_closeable():
    """THE load-bearing regression (TRDD-15ECPBSA / 3b9b2040): a TRDD whose
    commits shipped BUT that still has remaining in-scope work (here:
    `column: blocked`) must surface as 'partially-shipped-review', NEVER as
    'closeable-candidate'. This is the exact over-claim the detector exists to
    prevent."""
    rec = _record(column="blocked", impl="[abc1234]", body="\npublish BLOCKED on GROUP B\n")
    v = tc.reconcile(rec, _in_tag(_tagmap("abc1234")), _column_of({}))
    assert v.fires
    assert "partially-shipped-review" in v.fired
    assert "closeable-candidate" not in v.fired
    assert v.label == "partially-shipped-review"


def test_reconcile_shipped_with_unchecked_box_is_review():
    """Remaining work can also be an unchecked `- [ ]` task, not just a blocked
    column — still review, not closeable."""
    rec = _record(column="dev", impl="[abc1234]", body="\n## plan\n- [ ] one more thing\n")
    v = tc.reconcile(rec, _in_tag(_tagmap("abc1234")), _column_of({}))
    assert v.label == "partially-shipped-review"
    assert "closeable-candidate" not in v.fired


def test_reconcile_genuinely_unshipped_in_progress_fires_nothing():
    """A genuinely in-progress, UNSHIPPED TRDD (commits not in any tag, no stale
    blocker, frontmatter & prose agree) must fire NOTHING — the no-false-positive
    case."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nstill working.\n")
    v = tc.reconcile(rec, _in_tag(_tagmap()), _column_of({}))
    assert not v.fires
    assert v.label == ""


def test_reconcile_prose_mismatch_independent_of_shipping():
    """Check 3 surfaces even when nothing shipped — prose claims a block the
    machine fields don't encode."""
    rec = _record(column="dev", blocked_by="[]", impl="[]", body="\nwe are BLOCKED on the API\n")
    v = tc.reconcile(rec, _in_tag(_tagmap()), _column_of({}))
    assert v.fires
    assert "prose-frontmatter-mismatch" in v.fired


def test_reconcile_stale_blocker_surfaces():
    """Check 4 surfaces a blocker that is now terminal even with no shipping."""
    rec = _record(column="blocked", blocked_by="[TRDD-3b9b2040]", impl="[]")
    v = tc.reconcile(rec, _in_tag(_tagmap()), _column_of({"3b9b2040": "published"}))
    assert v.fires
    assert "stale-blocker" in v.fired
    assert v.stale_blockers == ["3b9b2040"]


def test_check4_announced_list_in_next_paragraph_is_collected():
    """2026-08-02 review finding: 'blocked by the following:' with the ids listed in
    the NEXT paragraph is an ordinary declaration shape; the paragraph scoping
    dropped it. The fallback fires ONLY on the announcing colon — the FP test above
    (prose ending in a period, reuse citations in the next paragraph) must keep
    collecting nothing."""
    rec = _record(
        column="dev",
        blocked_by="[]",
        body=(
            "\n## STATE\n"
            "This card is BLOCKED by the following:\n"
            "\n"
            "- TRDD-3b9b2040\n"
            "- TRDD-aebedbff\n"
        ),
    )
    stale = tc.check4_stale_blockers(
        rec, _column_of({"3b9b2040": "published", "aebedbff": "complete"})
    )
    assert sorted(stale) == ["3b9b2040", "aebedbff"]


# ── has_stated_precondition (janitor#189: trdd-drift backburner narrowing) ──


def test_has_stated_precondition_true_when_blocked_by_populated():
    """A backburner card waiting on another TRDD has an on-file excuse — not forgotten."""
    head = "---\ncolumn: backburner\nblocked-by: [TRDD-3b9b2040]\n---\n"
    assert tc.has_stated_precondition(head) is True


def test_has_stated_precondition_true_when_npt_populated():
    """A card waiting on its own prerequisite tasks is parked on purpose, not idle."""
    head = "---\ncolumn: backburner\nnpt: [TRDD-aebedbff]\n---\n"
    assert tc.has_stated_precondition(head) is True


def test_has_stated_precondition_false_with_no_stated_reason():
    """The true-positive shape must still fire: nothing on file explains the staleness."""
    head = "---\ncolumn: backburner\ntitle: some forgotten idea\n---\n"
    assert tc.has_stated_precondition(head) is False


def test_has_stated_precondition_false_when_fields_are_empty_lists():
    """An explicit `[]` is 'no precondition', not a stated one — must not silence the card."""
    head = "---\ncolumn: backburner\nblocked-by: []\nnpt: []\n---\n"
    assert tc.has_stated_precondition(head) is False


# ── Check 5 — STATE block cites a symbol the tree no longer has (TRDD-FDV1RQEB) ─
#
# `token_is_dead` is the injectable git seam (production: absent from
# scripts/tests at HEAD AND present in `git log -S` history — real git is
# exercised separately in the detector's own integration tests). Here it's a
# plain fake: True for exactly the tokens the test wants to reproduce, so the
# predicate over the STATE block is proven with zero I/O.

_STATE_WITH_NEXT_ACTION = (
    "\n## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-12\n\n"
    "Progress so far: most of the cadence rework landed.\n\n"
    "NEXT ACTION: raise `should_emit_renew`'s `dwell_s` threshold once measured.\n\n"
    "See also `findings_ledger` for the ledger contract, and `resolve_ttl_minutes` used to\n"
    "compute the old TTL window (historical reference).\n\n"
    "## Approval log\n"
    "nothing here yet\n"
)


def _dead(*tokens: str):
    dead = set(tokens)
    return lambda t: t in dead


def test_check5_dead_symbol_in_next_action_is_high_severity():
    """A dead symbol cited in the NEXT-ACTION paragraph blocks the card — HIGH."""
    rec = _record(column="dev", body=_STATE_WITH_NEXT_ACTION)
    findings = tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    assert [(f.token, f.severity) for f in findings] == [("should_emit_renew", "high")]


def test_check5_dead_symbol_outside_next_action_is_low_severity():
    """A dead symbol cited ELSEWHERE in the STATE block only misleads — LOW."""
    rec = _record(column="dev", body=_STATE_WITH_NEXT_ACTION)
    findings = tc.check5_dead_symbol_citations(rec, _dead("resolve_ttl_minutes"))
    assert [(f.token, f.severity) for f in findings] == [("resolve_ttl_minutes", "low")]


# The shape STATE blocks are ACTUALLY written in: a TIGHT bullet list, no blank
# lines between items. `_STATE_WITH_NEXT_ACTION` above is blank-line-separated
# prose, which is why every check5 severity test passed while real cards were
# graded wrong — the fixture never reproduced the formatting the rule meets in
# production. Continuation lines are indented under their bullet, as authors write
# them, because the bullet must own them.
_STATE_TIGHT_BULLETS = (
    "\n## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-13\n\n"
    "- **CONTEXT:** most of the cadence rework landed.\n"
    "- **NEXT ACTION:** implement Phase 1 — see the plan below. Delegate the build to\n"
    "  ONE bounded agent; keep the orchestrator thin.\n"
    "- **LOAD-BEARING FACTS:** a nudge phase must be LATE and fail-open, like\n"
    "  `resolve_ttl_minutes` (the current tail of `dispatch.py`).\n"
    "- **ARTIFACTS:** `findings_ledger`.\n\n"
    "## Approval log\n"
    "nothing here yet\n"
)


def test_check5_severity_is_scoped_to_the_next_action_BULLET_not_the_whole_block():
    """In a tight bullet list, only the NEXT-ACTION bullet earns HIGH.

    The regression: `_paragraph_spans` splits on blank lines, so a tight list is ONE
    paragraph and the NEXT-ACTION span covered the entire STATE block — measured at
    (2, 3248) of 3249 chars on TRDD-GZXTSJSR. Every dead symbol anywhere in such a
    block was graded `high`, so the high/low split became a property of whether the
    author left blank lines between bullets rather than of where the symbol sits.
    """
    rec = _record(column="dev", body=_STATE_TIGHT_BULLETS)
    findings = tc.check5_dead_symbol_citations(rec, _dead("resolve_ttl_minutes"))
    assert [(f.token, f.severity) for f in findings] == [("resolve_ttl_minutes", "low")], (
        "a symbol in the LOAD-BEARING-FACTS bullet is not in the NEXT ACTION"
    )


def test_check5_next_action_bullet_still_earns_high_in_a_tight_list():
    """The other direction: narrowing must not cost a genuine NEXT-ACTION hit its HIGH.
    A fix that graded everything `low` would silence the finding this check exists for."""
    body = _STATE_TIGHT_BULLETS.replace(
        "implement Phase 1 — see the plan below.",
        "finish `should_emit_renew` — see the plan below.",
    )
    rec = _record(column="dev", body=body)
    findings = tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    assert [(f.token, f.severity) for f in findings] == [("should_emit_renew", "high")]


def test_check5_next_action_bullet_owns_its_continuation_lines():
    """A bullet's wrapped continuation lines belong to it — they carry no marker of
    their own, so scoping must walk BACK to the marker rather than treat the line as
    unbulleted (which would drop it to `low` and under-report a real blocker)."""
    body = _STATE_TIGHT_BULLETS.replace(
        "  ONE bounded agent; keep the orchestrator thin.",
        "  ONE bounded agent; keep `should_emit_renew` thin.",
    )
    rec = _record(column="dev", body=body)
    findings = tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    assert [(f.token, f.severity) for f in findings] == [("should_emit_renew", "high")]


def test_check5_blank_line_separated_prose_is_unchanged_by_the_bullet_narrowing():
    """Non-list prose keeps the original paragraph scope — the narrowing is additive,
    so the pre-existing behaviour this rule had for prose STATE blocks still holds."""
    rec = _record(column="dev", body=_STATE_WITH_NEXT_ACTION)
    assert [
        (f.token, f.severity)
        for f in tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    ] == [("should_emit_renew", "high")]


def test_check5_multiple_dead_symbols_ranked_independently():
    """Both the NEXT-ACTION token and an elsewhere token fire, each at its own
    severity, and a live token (`findings_ledger`) never fires."""
    rec = _record(column="dev", body=_STATE_WITH_NEXT_ACTION)
    findings = tc.check5_dead_symbol_citations(
        rec, _dead("should_emit_renew", "resolve_ttl_minutes")
    )
    by_token = {f.token: f.severity for f in findings}
    assert by_token == {"should_emit_renew": "high", "resolve_ttl_minutes": "low"}
    assert "findings_ledger" not in by_token


def test_check5_symbol_present_at_head_is_not_flagged():
    """A token still resolvable at HEAD (`token_is_dead` says False) is silent —
    citing live code in a STATE block is normal, not drift."""
    rec = _record(column="dev", body=_STATE_WITH_NEXT_ACTION)
    findings = tc.check5_dead_symbol_citations(rec, _dead())  # nothing is "dead"
    assert findings == []


def test_check5_token_never_existed_produces_no_finding():
    """A token that never existed anywhere is a typo or an external name, not a
    deleted symbol — `token_is_dead` returning False for it means silence."""
    body = (
        "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
        "NEXT ACTION: check `totallyMadeUpToken` once the probe lands.\n"
    )
    rec = _record(column="dev", body=body)
    # token_is_dead is production-faithful here: False unless BOTH conditions
    # hold, and a token that never existed can never satisfy "present in history".
    findings = tc.check5_dead_symbol_citations(rec, lambda t: False)
    assert findings == []


def test_check5_terminal_column_is_skipped():
    """A terminal (published) TRDD is frozen — Check 5 must not touch it even
    though its STATE block still cites a provably-dead symbol."""
    rec = _record(column="published", body=_STATE_WITH_NEXT_ACTION)
    findings = tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    assert findings == []


def test_check5_no_state_block_yields_nothing():
    """A body with no `## STATE` header at all has nothing for Check 5 to scan."""
    rec = _record(column="dev", body="\n## Plan\nDo `should_emit_renew` later.\n")
    findings = tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    assert findings == []


def test_check5_obituary_line_suppresses_the_finding():
    """A citation on a line that already RECORDS the deletion (a deletion verb
    plus the commit SHA that did it) is not "cites an absent symbol" — it is
    the card doing the finding's job itself. No finding (TRDD-Q4AMWYCY)."""
    body = (
        "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
        "NEXT ACTION: nothing runnable here.\n\n"
        "SUPERSEDED — do NOT carry forward: the exemplar this line used to name,\n"
        "`_phase_self_budget`, was deleted 2026-08-12-verified by `d9a7189d feat!: remove\n"
        "MAINTENANCE MODE and the self-budget actuation`.\n"
    )
    rec = _record(column="dev", body=body)
    findings = tc.check5_dead_symbol_citations(rec, _dead("_phase_self_budget"))
    assert findings == []


def test_check5_obituary_elsewhere_does_not_shield_a_genuine_stale_next_action():
    """A NEXT-ACTION citation with NO obituary marker on its own line must
    still fire HIGH, even when the SAME token has an unrelated obituary
    elsewhere in the STATE block — suppression is line-scoped, not
    paragraph- or token-scoped (TRDD-Q4AMWYCY)."""
    # The obituary sentence and the NEXT ACTION share ONE paragraph (no blank
    # line between them) — a paragraph-scoped suppression would wrongly
    # silence the genuine citation two lines below; only a line-scoped one
    # tells them apart.
    body = (
        "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
        "Historical note: `should_emit_renew` was removed by `af499ee3`.\n"
        "NEXT ACTION: raise `should_emit_renew`'s `dwell_s` threshold once measured.\n"
    )
    rec = _record(column="dev", body=body)
    findings = tc.check5_dead_symbol_citations(rec, _dead("should_emit_renew"))
    assert [(f.token, f.severity) for f in findings] == [("should_emit_renew", "high")]


def test_extract_state_block_stops_at_next_top_heading():
    """The STATE block ends at the next top-level '## ' heading, not at EOF."""
    body = (
        "\n## STATE\ninside the state block `should_emit_renew`\n\n"
        "## Approval log\noutside `resolve_ttl_minutes`\n"
    )
    block = tc.extract_state_block(body)
    assert "should_emit_renew" in block
    assert "resolve_ttl_minutes" not in block


# --- Check 6: `blocked` naming no blocker (TRDD-F4IBIDB6) -------------------------


def test_check6_fires_on_blocked_with_no_blocker():
    """`blocked` is the board's one licence to sit still, and the claim must be TRUE. A card
    that claims it while naming nothing is indistinguishable from an abandoned one — and worse
    than an unstarted card, because the column asserts the stall is understood."""
    assert tc.check6_blocked_without_blocker(_record(column="blocked", blocked_by="[]")) is True


def test_check6_silent_when_a_blocker_is_named():
    """A named blocker is the whole point; naming one must switch the check off, whether it is
    another card or a non-TRDD condition (this board already uses both: `ai-maestro#102`,
    `publish-of-7ceab3f`)."""
    assert tc.check6_blocked_without_blocker(_record(column="blocked", blocked_by="[QQ11WW22]")) is False
    assert tc.check6_blocked_without_blocker(
        _record(column="blocked", blocked_by="[publish-of-7ceab3f]")) is False


def test_check7_fires_on_a_work_column_nobody_has_touched():
    """A WORK column asserts someone is working the card RIGHT NOW. When that is false the
    board's most-populated columns become its least honest, and the stall is invisible from the
    only view anyone consults — worse than an unstarted card, which never claims to be handled.
    Measured on ai-maestro 2026-08-01: 37 cards in `dev`, exactly one touched that day."""
    for col in ("dev", "testing", "ai_review"):
        assert tc.check7_work_column_without_work(
            _record(column=col), idle_days=9.0, threshold_days=3.0) is True, col


def test_check7_is_silent_on_a_card_being_worked_right_now():
    """THE false positive that would get the whole check switched off. A card touched inside the
    window is exactly what the column claims, so it must stay silent — including right at the
    boundary, which is the value most likely to be hit by a card worked daily."""
    assert tc.check7_work_column_without_work(
        _record(column="dev"), idle_days=0.0, threshold_days=3.0) is False
    assert tc.check7_work_column_without_work(
        _record(column="dev"), idle_days=2.99, threshold_days=3.0) is False


def test_check7_is_scoped_to_the_columns_that_make_the_claim():
    """`todo`/`backburner` assert only that something is QUEUED, and a queued card sitting still
    is the system working as designed. Firing there would reproduce `trdd-drift` (which reports
    age on any card) and bury the distinct signal this check exists to give: a contradicted
    CLAIM, not mere idleness."""
    for col in ("todo", "backburner", "blocked", "human_review", "complete", "published"):
        assert tc.check7_work_column_without_work(
            _record(column=col), idle_days=400.0, threshold_days=3.0) is False, col


def test_check7_declines_when_the_age_is_unknown():
    """An unknown age is not evidence of a stall. Inventing one would fire on exactly the cards
    whose metadata is hardest to read — the least reliable place to make an accusation."""
    assert tc.check7_work_column_without_work(
        _record(column="dev"), idle_days=None, threshold_days=3.0) is False


def test_reconcile_reports_check7_without_mutating_the_record():
    """Acceptance box: neither check MUTATES a card. `reconcile` is a reader — it must surface
    the untrue claim and leave the destination to whoever reads it, because the right column
    differs per card (`backburner` for one waiting on a condition nobody can manufacture,
    `todo` for one simply unstarted, `blocked` only when a blocker can be NAMED)."""
    rec = _record(column="dev")
    before = (rec.column, rec.status, list(rec.blocked_by), list(rec.impl_commits), rec.body)
    verdict = tc.reconcile(rec, lambda _sha: False, lambda _uid: "", idle_days=30.0)
    assert verdict.idle_work is True
    assert "work-column-without-work" in verdict.fired
    assert (rec.column, rec.status, list(rec.blocked_by), list(rec.impl_commits), rec.body) == before


def test_check6_silent_on_every_other_column():
    """Only `blocked` makes the claim, so only `blocked` can make it falsely. An empty
    blocked-by is NORMAL everywhere else and firing there would bury the real signal."""
    for col in ("todo", "dev", "testing", "ai_review", "backburner", "human_review"):
        assert tc.check6_blocked_without_blocker(_record(column=col, blocked_by="[]")) is False, col


def test_check6_silent_on_terminal_columns():
    """A terminal card's body is frozen and it is never a board-drift candidate — the
    single-source-of-truth guard `reconcile` applies, restated here so a future caller of the
    check alone cannot leak one."""
    for col in ("complete", "superseded", "published", "live", "failed", "cancelled"):
        assert tc.check6_blocked_without_blocker(_record(column=col, blocked_by="[]")) is False, col


def test_reconcile_surfaces_the_unnamed_blocker():
    """End to end through the aggregator: the verdict fires, is labelled, and carries evidence."""
    v = tc.reconcile(_record(column="blocked", blocked_by="[]"), lambda _s: False, lambda _u: "")
    assert v.fires and v.unnamed_blocker
    assert "blocked-without-blocker" in v.fired


# ── Check 8: shipped but unreleased — the lower-confidence rung (TRDD-4ZSYW21E) ──


def _at_head(*shas: str):
    """Fake `commit -> reachable from HEAD` seam: every listed sha is at HEAD."""
    at_head = set(shas)
    return lambda sha: sha in at_head


def test_check8_fires_on_untagged_commit_at_head_with_no_remaining_work():
    """Between releases, Check 1 goes blind — a card whose commit landed but is not YET tagged
    still needs to surface. No remaining work (no unchecked box, no pending NEXT ACTION) means
    Check 8 is the ONLY reason a reader would learn this card shipped."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nall shipped.\n")
    assert tc.check8_shipped_unreleased(rec, _at_head("abc1234")) is True


def test_check8_silent_when_remaining_work():
    """Same shipped-at-HEAD commit, but the card still has an open acceptance box — the
    false-positive storm the tag requirement exists to prevent (F4IBIDB6). Check 8 must stay
    silent exactly like Check 1 does under the same condition."""
    rec = _record(
        column="dev",
        impl="[abc1234]",
        body="\n## plan\n- [ ] one more thing\n",
    )
    assert tc.check8_shipped_unreleased(rec, _at_head("abc1234")) is False


def test_check8_silent_when_terminal_column():
    """A terminal TRDD is already closed and frozen — never a board-drift candidate, mirroring
    every other check's terminal guard."""
    rec = _record(column="published", impl="[abc1234]", body="\n# body\nall shipped.\n")
    assert tc.check8_shipped_unreleased(rec, _at_head("abc1234")) is False


def test_check8_silent_when_no_commit_at_head():
    """No commit is reachable from HEAD at all (e.g. rebased away, or none recorded) — Check 8
    has nothing to report."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nall shipped.\n")
    assert tc.check8_shipped_unreleased(rec, _at_head()) is False


def test_reconcile_check1_wins_over_check8_when_commit_is_tagged():
    """A commit in a released tag is ALSO reachable from HEAD, so both checks' predicates are
    individually true — but `reconcile()` must report Check 1's stronger verdict, never the
    weaker `shipped-unreleased-review`, exactly per the card's acceptance criteria."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nall shipped.\n")
    v = tc.reconcile(
        rec,
        _in_tag(_tagmap("abc1234")),
        _column_of({}),
        commit_at_head=_at_head("abc1234"),
    )
    assert v.label == "closeable-candidate"
    assert "shipped-unreleased-review" not in v.fired
    assert v.shipped_unreleased is False


def test_reconcile_surfaces_shipped_unreleased_when_untagged():
    """The new rung end to end: an untagged-but-at-HEAD commit with no remaining work surfaces
    as the distinct, weaker verdict — never the tagged-keystone label."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nall shipped.\n")
    v = tc.reconcile(
        rec,
        _in_tag(_tagmap()),
        _column_of({}),
        commit_at_head=_at_head("abc1234"),
    )
    assert v.fires
    assert v.label == "shipped-unreleased-review"
    assert v.shipped_unreleased is True
    assert v.unreleased_commits == ["abc1234"]
    assert "closeable-candidate" not in v.fired
    assert "partially-shipped-review" not in v.fired


def test_reconcile_defaults_commit_at_head_to_never_fires():
    """Pre-existing call sites (production and the check-1 tests above) that never pass
    `commit_at_head` must behave EXACTLY as before Check 8 existed — the default seam never
    fires it, so an untagged-but-at-HEAD-in-reality commit stays silent when the caller simply
    never asked the question."""
    rec = _record(column="dev", impl="[abc1234]", body="\n# body\nall shipped.\n")
    v = tc.reconcile(rec, _in_tag(_tagmap()), _column_of({}))
    assert not v.fires
    assert v.shipped_unreleased is False
