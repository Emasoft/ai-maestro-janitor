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
