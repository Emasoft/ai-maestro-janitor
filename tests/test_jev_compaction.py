"""Tests for scripts/lib/jev_compaction.py (TRDD-RAEGS1D5 card 3, part A)."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import jev_compaction as jc  # noqa: E402
import pytest  # noqa: E402
from jevctx.openrouter import JevBlockedError  # noqa: E402
from jevctx.pipeline import find_pointers, parse_pointer  # noqa: E402
from jevctx.segments import detect_kind  # noqa: E402  -- card 6, TRDD-88DOI824
from jevctx.testing import FakeJevClient  # noqa: E402
from jevctx.types import JevUnavailableError, JevValidationError, NoulAnswer  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "jev_transcript_small.jsonl"
# TRDD-RAEGS1D5 (2026-09-23): a SEPARATE fixture, not an edit to the shared one above --
# `tests/test_jev_compact_cli.py` (a different worker's file) also reads FIXTURE, and its
# item-count/index assertions must not shift under it.
FIXTURE_ORIGIN = Path(__file__).resolve().parent / "fixtures" / "jev_transcript_origin.jsonl"


def _item(id_: str, kind: jc.ItemKind, text: str, turn: int, tokens: int | None = None) -> jc.Item:
    from jevctx.tokens import estimate_tokens

    return jc.Item(id=id_, kind=kind, text=text,
                    tokens=tokens if tokens is not None else estimate_tokens(text),
                    ts=None, turn=turn)


def test_extraction_skips_heartbeat_thinking_meta_and_system_and_pairs_tool_results() -> None:
    items = jc.extract_items(FIXTURE)
    ids = [it.id for it in items]

    # The fixture's isMeta (u3), heartbeat (u4), thinking-only (a2), and every
    # system/mode/file-history-snapshot/last-prompt/queue-operation/attachment line
    # contribute zero items.
    assert "u3:0" not in ids
    assert "u4:0" not in ids
    assert not any(id_.startswith("a2:") for id_ in ids)
    assert not any(id_.startswith("s1:") for id_ in ids)

    # A bare tool_use block (a3, a5) is never an item on its own.
    assert not any(id_.startswith("a3:") for id_ in ids)
    assert not any(id_.startswith("a5:") for id_ in ids)

    # A sidechain entry (sc1, isSidechain=true -- a subagent's own turn living in the same
    # main transcript file) contributes zero items either.
    assert not any(id_.startswith("sc1:") for id_ in ids)

    by_id = {it.id: it for it in items}
    tool_str = by_id["u2:0"]
    assert tool_str.kind == "tool"
    assert tool_str.text == 'Bash({"command": "grep -rn login src/"})\nsrc/auth.py:42: def login(...):'

    tool_list = by_id["u6:0"]
    assert tool_list.kind == "tool"
    assert tool_list.text == 'Read({"file_path": "src/signup.py"})\ndef signup(): ...'

    assert by_id["u1:0"].kind == "user"
    assert by_id["a1:0"].kind == "assistant"
    assert by_id["u5:0"].kind == "user"
    assert by_id["u7:0"].kind == "user"


def test_ids_stable_across_reruns() -> None:
    first = [it.id for it in jc.extract_items(FIXTURE)]
    second = [it.id for it in jc.extract_items(FIXTURE)]
    assert first == second


def test_digest_caps_tokens() -> None:
    heads = ["line " + str(i) for i in range(50)]  # a 50-line "STATE head"
    items = [_item(f"u{i}:0", "user", "x" * 500, i) for i in range(3)]
    digest = jc.build_digest(items, ["\n".join(heads)], cap_tokens=50)
    from jevctx.tokens import estimate_tokens

    assert estimate_tokens(digest) <= 50
    assert digest  # never collapses to nothing when there IS content


def test_digest_no_digest_raises() -> None:
    try:
        jc.build_digest([], [], cap_tokens=100)
    except jc.NoDigest:
        return
    raise AssertionError("expected NoDigest when there is no human message and no head")


def test_digest_empty_user_list_falls_back_to_heads_only() -> None:
    digest = jc.build_digest([], ["state head text"], cap_tokens=4000)
    assert digest == "state head text"


def test_keep_if_relevance_or_decision_passes() -> None:
    items = [
        _item("i0:0", "assistant", "the build is green", 0),
        _item("i1:0", "user", "always use tabs, never spaces", 1),
        _item("i2:0", "assistant", "irrelevant progress noise", 2),
    ]

    def answer(state: Any, questions: Any, key: Any) -> float:
        # Keys are now "<ref>:rel"/"<ref>:dec" (score_items sends both questions for an
        # item in ONE request -- see its docstring); the state.items ref is the part
        # before the ":".
        ref = str(key).split(":", 1)[0]
        item_text = ""
        if isinstance(state, dict):
            for entry in state.get("items", []):
                if entry.get("ref") == ref:
                    item_text = entry.get("text", "")
        # Matched against the module's own DECISION_QUESTION constant, not a hardcoded
        # substring literal -- a review found the earlier hardcoded substring
        # ("constraint, correction" in ...instructions) silently fragile to a wording
        # edit in jev_compaction.py that this test would not have caught.
        is_decision_q = jc.DECISION_QUESTION.instructions in questions[key].instructions
        if is_decision_q:
            return 0.9 if "tabs" in item_text else 0.1
        # relevance question
        return 0.9 if "build" in item_text else 0.1

    client = FakeJevClient(answer)
    scores = jc.score_items(items, "digest: fixing the build", client)

    assert scores["i0:0"].kept is True   # passes on relevance alone
    assert scores["i1:0"].kept is True   # passes on decision alone
    assert scores["i2:0"].kept is False  # fails both


def test_budget_ordering_drops_lowest_first_oldest_among_equals() -> None:
    # TRDD-RAEGS1D5 (release blocker): all four items are "user"/owner kind, so this now
    # exercises the owner-share admission -- not the plain evict_key sort the old assertions
    # described. `low:0` is the NEWEST owner message (turn=3) and is guaranteed a slot
    # regardless of its score (0.4, the lowest of the four) -- the whole point of the
    # guarantee is that recency can outrank a pessimistic relevance score. `low:0` alone
    # (100 tok) already exceeds the owner share (int(200 * 0.40) == 80), so `c:0`/`b:0`/`a:0`
    # all overflow the share and compete for what's left of the 200-token budget (100 tok):
    # `c:0` (turn=2, the next-newest) fits exactly and is admitted; `b:0`/`a:0` do not fit.
    items = [
        _item("a:0", "user", "aaaa", turn=0, tokens=100),
        _item("b:0", "user", "bbbb", turn=1, tokens=100),
        _item("c:0", "user", "cccc", turn=2, tokens=100),
        _item("low:0", "user", "llll", turn=3, tokens=100),
    ]
    scores = {
        "a:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True, decision_passed=False),
        "b:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True, decision_passed=False),
        "c:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True, decision_passed=False),
        "low:0": jc.Scores(relevance=0.4, decision=0.0, oversized=False, kept=True, decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=200,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user low:0 --" in doc
    assert "-- user c:0 --" in doc
    assert "-- user a:0 --" not in doc
    assert "-- user b:0 --" not in doc
    assert "id=a:0" in doc
    assert "id=b:0" in doc


def test_oversized_never_inlined() -> None:
    items = [_item("o:0", "assistant", "oversized text", turn=0, tokens=999999)]
    # kept=True on purpose: compose() must refuse to inline it anyway (the spec's own
    # invariant, not just something score_items happens to enforce upstream).
    scores = {"o:0": jc.Scores(relevance=1.0, decision=1.0, oversized=True, kept=True,
                                decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- assistant o:0 --" not in doc
    assert "id=o:0" in doc


def test_oversized_pointer_includes_first_20_lines() -> None:
    # Spec: "Oversized single item ... never inlined; pointer + first 20 lines" -- a
    # richer pointer than the plain single-line one every other elided item gets. A review
    # of the first draft flagged that `_format_pointer` alone (single 80-char preview line)
    # never actually carried those 20 lines -- this proves the fix.
    body_lines = [f"line {i}" for i in range(30)]
    items = [_item("o:0", "assistant", "\n".join(body_lines), turn=0, tokens=999999)]
    scores = {"o:0": jc.Scores(relevance=1.0, decision=1.0, oversized=True, kept=True,
                                decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    for line in body_lines[:20]:
        assert line in doc
    for line in body_lines[20:]:
        assert line not in doc


def test_both_guaranteed_owner_items_survive_even_combined_over_budget() -> None:
    # Coordinator ruling (fixing commit d4fa7685's over-narrowing, superseding this test's
    # earlier "one guaranteed slot" assertion): TWO owner items are guaranteed, uncapped,
    # regardless of `budget_tokens` -- the newest owner message ("rel", turn=1, NOT
    # decision_passed) and the newest `decision_passed` item ("dec", turn=0), which here are
    # DIFFERENT items. Both are admitted even though their combined 200 tokens alone already
    # exceeds the 100-token budget -- "ahead of the per-item cap" means the guarantee bypasses
    # `budget_tokens` too, exactly as the old single-guaranteed-item code already did. A
    # THIRD, non-guaranteed owner item ("extra" -- older than both, not decision_passed, and
    # scored HIGHLY relevant so its eviction cannot be blamed on a low score) still gets
    # evicted: the eviction mechanism is unchanged for anything outside the 2 guaranteed slots.
    items = [
        _item("extra:0", "user", "yet another owner message", turn=-1, tokens=100),
        _item("dec:0", "user", "policy: always use tabs", turn=0, tokens=100),
        _item("rel:0", "user", "merely relevant background", turn=1, tokens=100),
    ]
    scores = {
        "extra:0": jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
        "rel:0": jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                            decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=100,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user dec:0 --" in doc
    assert "-- user rel:0 --" in doc
    assert "-- user extra:0 --" not in doc
    assert "id=extra:0" in doc


def test_decision_passed_owner_item_wins_second_slot_when_not_newest() -> None:
    # TRDD-RAEGS1D5, updated for the coordinator's dual-guarantee ruling (compose()'s
    # `guaranteed_owner_ids`): "newest:0" and "dec_old:0" are now BOTH independently
    # guaranteed (the newest owner message, and the newest `decision_passed` item -- two
    # different items here), not "one guaranteed plus one winning the leftover share" as
    # before -- the assertions below are unchanged because the outcome coincides, but the
    # mechanism producing it does not: "rel_old:0" (merely relevant, higher raw relevance 0.9
    # than dec_old's 0.6, but neither newest nor decision_passed) is outside both guaranteed
    # slots and loses the owner-share competition to fit at all.
    items = [
        _item("newest:0", "user", "hi", turn=2, tokens=100),
        _item("rel_old:0", "user", "merely relevant background", turn=1, tokens=100),
        _item("dec_old:0", "user", "policy: always use tabs", turn=0, tokens=100),
    ]
    scores = {
        "newest:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "rel_old:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                decision_passed=False),
        "dec_old:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                                decision_passed=True),
    }
    doc = jc.compose(items, scores, budget_tokens=250,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user newest:0 --" in doc
    assert "-- user dec_old:0 --" in doc
    assert "-- user rel_old:0 --" not in doc
    assert "id=rel_old:0" in doc


def test_owner_share_ceiling_admits_non_owner_relevant_items() -> None:
    # TRDD-RAEGS1D5 (release blocker): the real bug this fix targets. Measured on this repo's
    # own 49 MB transcript, `decision_passed` "user" items ALONE totaled more tokens than the
    # 8000-token default budget, so the plain evict_key sort (decision_passed always ranked
    # above ANY non-decision_passed item, of ANY kind) evicted every single tool/assistant/
    # event item before ever touching a user item -- 0 of 158 relevance-passing non-user items
    # survived. Reproduced in miniature: three decision_passed "user" items alone cost more
    # than the whole budget, plus one highly relevant "tool" item. Post-fix, the owner share
    # (int(120 * 0.40) == 48 tokens) caps how much of the budget owner items can take, so the
    # tool item is no longer starved out entirely.
    items = [
        _item("u0:0", "user", "decision zero", turn=0, tokens=50),
        _item("u1:0", "user", "decision one", turn=1, tokens=50),
        _item("u2:0", "user", "decision two", turn=2, tokens=50),
        _item("t0:0", "tool", "highly relevant tool output", turn=3, tokens=40),
    ]
    scores = {
        "u0:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True, decision_passed=True),
        "u1:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True, decision_passed=True),
        "u2:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True, decision_passed=True),
        "t0:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True, decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=120,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- tool t0:0 --" in doc, "a highly relevant non-owner item must survive a budget owner items alone exceed"
    assert "-- user u2:0 --" in doc, "the newest owner message is still guaranteed"


def test_newest_owner_message_and_newest_decision_item_are_both_guaranteed() -> None:
    # Coordinator ruling, fixing commit d4fa7685's over-narrowing (which made the ONE
    # guaranteed slot "newest decision-passing, else newest plain" -- silently DROPPING the
    # genuinely newest owner message whenever an older decision-passing one existed; measured
    # on the 258 MB transcript, the chronologically newest owner item was absent from BOTH the
    # full and the injected copy). The newest owner message ("ok", not decision_passed) and an
    # OLDER decision-passing item ("policy: always use tabs") must BOTH be present -- neither
    # displaces the other. Supersedes this test's own earlier "prefers decision over plain"
    # assertion (the pre-fix single-guaranteed-slot behavior this ruling replaces); the
    # pre-fix failure mode this test originally pinned (an "always newest" rule dropping an
    # OLDER decision item entirely) is now covered structurally -- the newest-decision slot
    # never disappears regardless of recency.
    items = [
        _item("dec_older:0", "user", "policy: always use tabs", turn=0, tokens=100),
        _item("plain_newest:0", "user", "ok", turn=1, tokens=100),
    ]
    scores = {
        "dec_older:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                                  decision_passed=True),
        "plain_newest:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                                     decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=100,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user dec_older:0 --" in doc
    assert "-- user plain_newest:0 --" in doc


def test_guaranteed_slots_collapse_to_one_when_newest_is_also_decision_passing() -> None:
    # `guaranteed_owner_items`'s own dedup (compose()): when the newest owner message IS the
    # newest decision-passing item, there is only ONE guaranteed item, not two -- must not
    # render (or budget for) it twice.
    items = [_item("only:0", "user", "policy: always use tabs", turn=0, tokens=100)]
    scores = {"only:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                                   decision_passed=True)}
    doc = jc.compose(items, scores, budget_tokens=100,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert doc.count("-- user only:0 --") == 1


def test_newest_owner_item_is_guaranteed_even_when_jev_scored_it_below_threshold() -> None:
    # TRDD-RAEGS1D5 (jev newest+3, owner ruling fe38e095 "the owner's newest message
    # first"): card 6's own disclosure (TRDD-88DOI824) found the guarantee below silently
    # scoped to `kept_items`, dropping the genuinely newest owner message whenever Jev
    # itself scored it below threshold -- measured on a real 258 MB transcript, the
    # transcript's chronologically LAST owner message (content "resume") scored
    # relevance=0.29/decision=0.22, both under the 0.5 default thresholds, so `kept=False`
    # and it never reached `kept_items` at all. Reproduced directly: "newest:0" is the
    # newest owner item by `turn`, `kept=False`, and must still appear -- force-admitted,
    # not merely named by a pointer.
    items = [
        _item("older:0", "user", "an earlier owner message", turn=0, tokens=50),
        _item("newest:0", "user", "resume", turn=5, tokens=10),
        _item("tool:0", "tool", "some unrelated tool output", turn=6, tokens=50),
    ]
    scores = {
        "older:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
        "newest:0": jc.Scores(relevance=0.29, decision=0.22, oversized=False, kept=False,
                               decision_passed=False),
        "tool:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user newest:0 --" in doc
    assert "resume" in doc
    # Force-admitted, not merely pointer-referenced -- never BOTH.
    assert "id=newest:0" not in doc


def test_newest_owner_item_guarantee_never_duplicates_when_it_is_also_a_decision_item() -> None:
    # Assignment's own acceptance criterion: "never duplicated when it is also a decision
    # item" -- the unconditional newest-owner slot and the newest-decision-passing slot must
    # collapse to the SAME single rendering when one item satisfies both, exactly like the
    # pre-existing `test_guaranteed_slots_collapse_to_one_when_newest_is_also_decision_
    # passing` above already proves for two ALREADY-KEPT items; this is the same collapse,
    # but for an item Jev did NOT keep on its own (kept=False) -- reachable only through the
    # new unconditional force-admit path.
    items = [_item("only:0", "user", "policy: always use tabs", turn=0, tokens=100)]
    scores = {"only:0": jc.Scores(relevance=0.1, decision=0.9, oversized=False, kept=False,
                                   decision_passed=True)}
    doc = jc.compose(items, scores, budget_tokens=100,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert doc.count("-- user only:0 --") == 1
    assert "id=only:0" not in doc


def test_newest_owner_item_guarantee_excludes_an_oversized_item() -> None:
    # "excluding only `oversized` items" (card 6's own disclosure, TRDD-88DOI824): an
    # oversized item's raw text was never even sent to Jev, and this function's own "never
    # inlined" invariant (`_oversized_preview`) must still hold for it -- the guarantee
    # falls through to the next-newest NON-oversized owner item instead.
    items = [
        _item("older:0", "user", "an earlier owner message", turn=0, tokens=50),
        _item("newest_oversized:0", "user", "huge", turn=5, tokens=999999),
    ]
    scores = {
        "older:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
        "newest_oversized:0": jc.Scores(relevance=1.0, decision=1.0, oversized=True,
                                         kept=False, decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user newest_oversized:0 --" not in doc  # never inlined -- the invariant holds
    assert "id=newest_oversized:0" in doc  # still pointed at, with its own oversized preview
    assert "-- user older:0 --" in doc  # the next-newest NON-oversized owner item takes the slot


def test_unconditionally_guaranteed_newest_owner_item_still_capped_in_injected_render() -> None:
    # Coordinator addition 1 (review of commit 3006e92f): "the unconditionally guaranteed
    # newest owner message stays capped at the existing 1,500-byte newest-owner limit in the
    # injected render: prefix plus pointer beyond that. One huge last message must not eat
    # the room." The force-admitted item joins `guaranteed_owner_ids` exactly like an
    # already-kept guaranteed item does, so `render()`'s existing `NEWEST_OWNER_ITEM_BYTES`
    # cap check already covers it -- proven directly here rather than assumed.
    huge_text = "x" * (jc.NEWEST_OWNER_ITEM_BYTES * 3)
    items = [_item("newest:0", "user", huge_text, turn=0, tokens=50)]
    scores = {"newest:0": jc.Scores(relevance=0.1, decision=0.0, oversized=False, kept=False,
                                     decision_passed=False)}
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_bytes=6000, max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES,
    )
    assert "-- user newest:0 --" in doc
    assert huge_text not in doc
    assert huge_text[: jc.NEWEST_OWNER_ITEM_BYTES] in doc
    assert "id=newest:0" in doc  # pointer back to the rest


def test_owner_item_over_the_per_item_cap_renders_as_a_truncated_prefix_plus_pointer() -> None:
    # TRDD-RAEGS1D5 (owner per-item token cap, requirement 1): the core new mechanic. An owner
    # item beyond the guaranteed slot that is bigger than `_OWNER_ITEM_TOKEN_CAP` now renders as
    # a VERBATIM prefix plus a pointer to the rest -- the same shape the byte-capped injected
    # copy already uses (`max_item_bytes`) -- instead of the old all-or-nothing admit/evict
    # decision on its full size. `newest:0` (tiny, no decision_passed anywhere) claims the
    # guaranteed slot; `big:0` (huge, real text so its own `.tokens` is genuinely > the cap)
    # competes in the capped tier and fits truncated.
    big_text = "one two three four five six seven eight nine ten. " * 400  # ~5900 est. tokens
    items = [
        _item("big:0", "user", big_text, turn=0),
        _item("newest:0", "user", "hi", turn=1),
    ]
    scores = {
        "big:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True,
                            decision_passed=False),
        "newest:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=2000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user newest:0 --" in doc
    assert "-- user big:0 --" in doc  # admitted -- truncated, never evicted whole
    assert "id=big:0" in doc  # ...and carries a pointer back to the rest
    # The rendered excerpt is a real PREFIX of the original text, never the whole thing.
    assert big_text[:50] in doc
    assert big_text not in doc


def test_per_item_cap_lets_an_older_large_decision_item_and_a_relevant_tool_item_both_fit() -> None:
    # TRDD-RAEGS1D5 (owner per-item token cap, requirement 1): the named trade-off between an
    # older decision-passing owner item and a relevant non-owner item under a tight budget --
    # made genuinely DISCRIMINATING per the adversarial review's finding on the first version of
    # this test (its numbers made older_decision too big to fit either WITH or WITHOUT the cap,
    # so it passed identically under the pre-fix whole-item-cost code too, proving nothing about
    # the cap specifically). `older_decision`'s real text is 781 est. tokens -- comfortably over
    # `_OWNER_ITEM_TOKEN_CAP` (500), so its CAPPED admission cost (~536, cap + the pointer
    # line's own cost) is set here to fit the budget that remains once the guaranteed slot and
    # the tool item are placed, while its FULL 781-token cost would NOT have fit that same
    # remainder -- i.e. under the OLD whole-item-cost admission this item would have been
    # evicted outright; the cap is what lets it survive (truncated + pointer) instead.
    older_decision_text = "policy: always use tabs, never spaces. " * 70  # 781 est. tokens
    items = [
        _item("older_decision:0", "user", older_decision_text, turn=0),
        _item("tool_item:0", "tool", "highly relevant tool output", turn=1, tokens=30),
        _item("newest_decision:0", "user", "also: never commit secrets", turn=3, tokens=20),
    ]
    scores = {
        "older_decision:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                                       decision_passed=True),
        "tool_item:0": jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                                  decision_passed=False),
        "newest_decision:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                                        decision_passed=True),
    }
    doc = jc.compose(items, scores, budget_tokens=700,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user newest_decision:0 --" in doc  # the guaranteed slot
    assert "-- tool tool_item:0 --" in doc  # relevant work still fits
    assert "-- user older_decision:0 --" in doc  # the cap is what lets it fit too -- truncated
    assert older_decision_text not in doc  # ...never in full
    assert "id=older_decision:0" in doc  # ...alongside a pointer to the rest


def test_truncated_but_kept_owner_item_never_also_gets_an_elided_decision_pointer() -> None:
    """Coordinator check (adversarial review of commit 0cf40380 could not verify this from
    reading alone): an owner item beyond `_OWNER_ITEM_TOKEN_CAP` (500) that still gets
    ADMITTED renders inline as a verbatim prefix plus its OWN `_format_pointer` line (see
    `test_owner_item_over_the_per_item_cap_renders_as_a_truncated_prefix_plus_pointer`) --
    the worry was that the SAME item, being `decision_passed`, might ALSO be counted among
    `compose()`'s full-copy `decision_elided` list (commit 0cf40380) and get a SECOND,
    `_format_decision_pointer` line in "## Elided". It cannot: `elided_items` is built as
    `[it for it in items if it.id not in kept_ids]` (`kept_ids` = the FINAL admitted set,
    reassigned from `admitted` once the owner-share/token-cap admission runs), so an item
    that was admitted -- truncated or not -- is by construction excluded from
    `elided_items`, hence from `decision_elided` too; there is no separate "was this
    truncated" flag that could disagree with `kept_ids`. This test forces BOTH outcomes to
    occur side by side in one document (some 686-token decision items admitted-truncated,
    others genuinely elided once the owner share is spent) and asserts no id ever carries
    both an in-place pointer AND a separate elided decision-pointer line.
    """
    decision_items = [
        _item(f"dec{i}:0", "user", f"policy number {i}: always do the thing {i}. " * 60, turn=i)
        for i in range(8)  # each ~686 est. tokens, comfortably over the 500-token cap
    ]
    tool_item = _item("tool:0", "tool", "relevant work output", turn=100, tokens=20)
    items = [*decision_items, tool_item]
    scores = {
        **{it.id: jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                             decision_passed=True) for it in decision_items},
        "tool:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=3500,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})

    doc_lines = doc.splitlines()
    truncated_but_kept = [it.id for it in decision_items if f"-- user {it.id} --" in doc]
    genuinely_elided = [
        it.id for it in decision_items
        if any(line.startswith(f"{it.id}: ") for line in doc_lines)
        and f"-- user {it.id} --" not in doc
    ]
    # Sanity: the scenario actually exercises both branches, or this test proves nothing.
    assert truncated_but_kept, "no item landed in the admitted-but-truncated branch"
    assert genuinely_elided, "no item landed in the genuinely-elided-decision branch"
    assert set(truncated_but_kept).isdisjoint(genuinely_elided)

    for it_id in truncated_but_kept:
        assert doc.count(f"-- user {it_id} --") == 1
        assert not any(line.startswith(f"{it_id}: ") for line in doc.splitlines()), (
            f"{it_id} is kept (truncated + own pointer) but ALSO has an elided decision "
            "pointer -- double-pointered"
        )
    for it_id in genuinely_elided:
        elided_lines = [line for line in doc.splitlines() if line.startswith(f"{it_id}: ")]
        assert len(elided_lines) == 1
        assert f"-- user {it_id} --" not in doc


def test_non_owner_admission_skips_a_too_big_item_rather_than_stopping() -> None:
    # TRDD-RAEGS1D5 (owner per-item token cap, requirement 2): pins the SKIP semantics
    # (`continue`, never `break`) of the non-owner fill loop -- a higher-priority item that
    # does not fit is passed OVER, not treated as "the budget is full, stop trying". A smaller,
    # lower-priority item further down the (relevance-ordered) list can still be admitted. No
    # owner items here, so the owner tier is a no-op and the whole budget is available to this
    # loop.
    items = [
        _item("big:0", "tool", "a large highly relevant block", turn=0, tokens=90),
        _item("small:0", "tool", "a small less relevant block", turn=1, tokens=20),
    ]
    scores = {
        "big:0": jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                            decision_passed=False),
        "small:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=50,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- tool small:0 --" in doc
    assert "-- tool big:0 --" not in doc


def test_pointer_format_has_no_path() -> None:
    # kind="assistant", not "user" -- TRDD-RAEGS1D5 (jev newest+3): the newest owner item is
    # now unconditionally guaranteed a kept slot (see `test_newest_owner_item_is_guaranteed_
    # even_when_jev_scored_it_below_threshold`), so a single "user" item here would never be
    # elided at all; this test is about the POINTER FORMAT, not ownership, so a non-owner
    # kind keeps it decoupled from that guarantee.
    items = [_item("p:0", "assistant", "some elided line\nmore", turn=0)]
    scores = {"p:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                decision_passed=False)}
    header = {"transcript_path": "/Users/x/project/.claude/transcript.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header)

    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided")]
    assert len(pointer_lines) == 1
    assert header["transcript_path"] not in pointer_lines[0]
    assert pointer_lines[0] == '[[elided id=p:0 tokens=%d "some elided line"]]' % items[0].tokens


def test_elided_pointer_list_is_capped_with_an_m_more_line() -> None:
    """Card 5 measured fact: the largest real transcript elides ~18,041 items, one pointer per
    item -- `compose()` itself must never re-grow that unboundedly. Cap at `_MAX_ELIDED_
    POINTERS`, keep the highest-scoring ones, and say how many were left out; the trailing
    'pointers expand with' line must still survive (it is what makes every DROPPED item still
    reachable by id).

    kind="assistant", not "user" (TRDD-RAEGS1D5, jev newest+3): the newest owner item is now
    unconditionally guaranteed a kept slot, which would pull the single highest-turn item out
    of this elided pool entirely -- this test is about the pointer-CAP mechanism, independent
    of ownership, so a non-owner kind keeps the two concerns decoupled.
    """
    n = jc._MAX_ELIDED_POINTERS + 10
    items = [_item(f"e{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(n)]
    scores = {
        it.id: jc.Scores(relevance=(i / n), decision=0.0, oversized=False, kept=False,
                          decision_passed=False)
        for i, it in enumerate(items)
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})

    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided id=")]
    assert len(pointer_lines) == jc._MAX_ELIDED_POINTERS
    # Highest relevance == highest index here -- the last 40 items must be the ones shown.
    for it in items[-jc._MAX_ELIDED_POINTERS:]:
        assert f"id={it.id} " in doc
    for it in items[: n - jc._MAX_ELIDED_POINTERS]:
        assert f"id={it.id} " not in doc
    assert f"[[elided: {n - jc._MAX_ELIDED_POINTERS} more items not listed" in doc
    # Card 5 content-fit: the "N more" line names a live way back to an unlisted item (item 3
    # of the card) -- `expand --list`, not a dead end.
    assert "--list --grep" in doc
    assert "pointers expand with:" in doc


def test_elided_pointer_list_under_the_cap_has_no_m_more_line() -> None:
    items = [_item("only:0", "user", "one elided item", turn=0, tokens=10)]
    scores = {"only:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                   decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "more items not listed" not in doc
    assert "pointers expand with:" in doc


def test_max_bytes_backstop_drops_relevance_only_items_before_a_decision_passed_one() -> None:
    """Review finding, card 5 content-fit (TRDD-RAEGS1D5): `compose()`'s `max_bytes` backstop
    must drop kept items by the SAME `evict_key` priority the `budget_tokens` eviction already
    uses, never bare chronological order -- otherwise it would sacrifice an OLD
    `decision_passed` item (a user instruction/correction) before a NEWER relevance-only one,
    exactly the loss `evict_key` exists to prevent at the first checkpoint, reintroduced here
    at the second. Four items, budget_tokens generous (so the FIRST eviction pass keeps all
    four); `max_bytes` tight enough that only one item can survive the backstop -- it must be
    the oldest, decision-passed one, not simply the newest one."""
    decision_item = _item("old-decision", "user", "IMPORTANT decision text", turn=0, tokens=5)
    relevance_items = [
        _item(f"new-relevance-{i}", "user", f"background text {i}", turn=i, tokens=5)
        for i in range(1, 4)
    ]
    items = [decision_item, *relevance_items]
    scores = {
        decision_item.id: jc.Scores(relevance=0.5, decision=0.6, oversized=False, kept=True,
                                     decision_passed=True),
        **{
            it.id: jc.Scores(relevance=0.9, decision=0.1, oversized=False, kept=True,
                              decision_passed=False)
            for it in relevance_items
        },
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_bytes=310)
    assert len(doc.encode("utf-8")) <= 310
    assert f"-- user {decision_item.id} --" in doc
    for it in relevance_items:
        assert f"-- user {it.id} --" not in doc


def test_tool_result_without_matching_tool_use_falls_back(tmp_path: Path) -> None:
    # A review of this module flagged that a dangling tool_result (no prior tool_use with
    # its id -- a plausible real-transcript defect from a truncated/crashed write) was
    # untested. It must not raise; it degrades to an "<unknown tool>" item, never dropped.
    line = {
        "type": "user", "uuid": "u1", "parentUuid": None, "isMeta": False,
        "timestamp": "2026-09-22T10:00:00+0200",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "missing-id", "content": "orphaned result"}
        ]},
    }
    path = tmp_path / "orphan.jsonl"
    path.write_text(json.dumps(line) + "\n")

    items = jc.extract_items(path)
    assert len(items) == 1
    assert items[0].kind == "tool"
    assert items[0].text == "<unknown tool>()\norphaned result"


# --- TRDD-88DOI824 (card 6): jevctx.segments.segment() on large tool results ---


def _read_style_numbered_code(n_funcs: int = 80) -> str:
    """A synthetic `cat -n`-style Read tool output -- every line prefixed
    "<spaces><digits>\\t", the shape that misdetects as `kind="table"` without
    `jc._detection_view` (see that function's own docstring)."""
    lines = []
    n = 1
    for i in range(n_funcs):
        for body in (f"def func_{i}():", f"    return {i}", ""):
            lines.append(f"{n:6d}\t{body}")
            n += 1
    return "\n".join(lines) + "\n"


def test_small_tool_result_stays_one_item_unsegmented(tmp_path: Path) -> None:
    # Sanity/regression: `_SEGMENT_THRESHOLD_TOKENS` (1000) gates segmentation -- a small
    # result (the overwhelming majority of real tool results) must render EXACTLY the
    # pre-card-6 shape: one Item, id "<uuid>:<n>" with no "@", text "name(input)\nresult".
    line = {
        "type": "user", "uuid": "u1", "parentUuid": None,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "a small result"}
        ]},
    }
    path = tmp_path / "small.jsonl"
    path.write_text(json.dumps(line) + "\n")
    items = jc.extract_items(path)
    assert len(items) == 1
    assert items[0].id == "u1:0"
    assert "@" not in items[0].id
    assert items[0].protected is False


def test_read_style_numbered_fixture_detects_as_code_not_table() -> None:
    # The misdetection this fixes, proven both ways: RAW numbered text misdetects as
    # "table" (every line carries exactly one tab from the line-number prefix alone), the
    # DETECTION VIEW (prefix stripped) correctly sees the `def `/`return` structure as code.
    text = _read_style_numbered_code()
    origin = jc.Origin(source="tool", ref="Read", turn=0)
    assert detect_kind(text, origin) == "table"  # sanity: the misdetection is real
    assert detect_kind(jc._detection_view(text), origin) == "code"


def test_detection_view_never_vanishes_a_line_whose_content_is_only_the_prefix() -> None:
    # Real-data regression (258 MB transcript, TRDD-88DOI824): a Read line whose SOURCE line
    # is blank renders as just "<n>\t" with nothing after it -- when that IS the text's
    # UNTERMINATED final line, naively stripping the prefix would leave an empty string, and
    # `"".join(...)` then contributes zero bytes for it, so `segment()`'s own internal re-split
    # of the joined detection view sees ONE FEWER line than this function's caller does,
    # shifting every later `line_span` and silently dropping the tail (measured: exactly 4
    # bytes, "311\t", missing from a real tool result). `_detection_view` must leave such a
    # line UNSTRIPPED so line count never drifts.
    text = "".join(f"{i:6d}\tcontent {i}\n" for i in range(1, 300)) + "   300\t"
    view = jc._detection_view(text)
    assert len(view.splitlines(keepends=True)) == len(text.splitlines(keepends=True))
    assert view.endswith("   300\t")  # left unstripped -- the fallback that fixes it


def test_segment_tool_result_handles_blank_final_read_line_losslessly() -> None:
    # Same real-data regression, exercised through the actual production path
    # (`_segment_tool_result`, not `_detection_view` in isolation) -- the losslessness
    # assertion inside it is what first caught this on the 258 MB transcript. Reuses the
    # def/return/blank shape that reliably segments (`_read_style_numbered_code`'s pattern),
    # with the text's own FINAL line a blank source line -- numbered, no trailing newline,
    # exactly the shape that vanished before `_detection_view`'s fix.
    lines = []
    n = 1
    for i in range(80):
        for body in (f"def func_{i}():", f"    return {i}", ""):
            lines.append(f"{n:6d}\t{body}")
            n += 1
    result_text = "\n".join(lines) + "\n" + f"{n:6d}\t"
    items = jc._segment_tool_result("u1:0", "Read", "{}", result_text, None, 0)
    assert len(items) > 1  # sanity: this must actually exercise segmentation
    assert "".join(it.text for it in items) == result_text


def test_segmentation_failure_degrades_to_whole_item_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Adversarial review (TRDD-88DOI824): the first version of `_segment_tool_result` let
    ANY failure in the segmentation path (a `jevctx.segments.segment()` bug on unusual real
    content, or the losslessness check itself firing) propagate out of `extract_items()`,
    aborting the WHOLE `compact` run over ONE bad tool result -- not hypothetical, the real
    258 MB acceptance run hit exactly this before `_detection_view`'s fix. Segmentation
    failures now degrade the same way `_score_batch_resilient`'s failures already do
    elsewhere in this file: a stderr finding line, then the pre-card-6 whole-item shape,
    never a crash. Forces the failure via `monkeypatch` (a real `segment()` bug is not
    reproducible on demand) rather than asserting anything about `jevctx.segments` itself.
    """
    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated jevctx.segments.segment() failure")

    monkeypatch.setattr(jc, "segment", _boom)
    result_text = "one two three four five six seven eight nine ten. " * 400  # over threshold

    items = jc._segment_tool_result("u1:0", "Read", "{}", result_text, None, 0)

    assert len(items) == 1
    assert items[0].id == "u1:0"  # no "@" -- the pre-card-6 whole-item shape
    assert result_text in items[0].text  # kept whole, verbatim -- never lost, never split
    err = capsys.readouterr().err
    assert "u1:0" in err
    assert "RuntimeError" in err


def test_segmentation_failure_is_recorded_in_the_caller_supplied_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Coordinator follow-up (review of commit 3006e92f): "'Segmentation degrades to the
    # whole item on any failure' is silent... count it in the summary line." The stderr line
    # above already names the item id and exception type; this proves the OTHER half -- a
    # caller that wants to COUNT failures (`jev_compact.py::cmd_compact`'s own
    # `segmentation_failed=N` summary field) passes a list here and gets the failing item's
    # id appended, on top of the stderr line, never instead of it.
    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated jevctx.segments.segment() failure")

    monkeypatch.setattr(jc, "segment", _boom)
    result_text = "one two three four five six seven eight nine ten. " * 400

    failures: list[str] = []
    items = jc._segment_tool_result(
        "u1:0", "Read", "{}", result_text, None, 0, segmentation_failures=failures
    )

    assert len(items) == 1
    assert failures == ["u1:0"]


def test_extract_items_threads_segmentation_failures_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # `extract_items` must actually forward its own `segmentation_failures` parameter to
    # `_segment_tool_result` (not just declare it) -- exercised end to end through a real
    # transcript file, not by calling `_segment_tool_result` directly like the test above.
    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(jc, "segment", _boom)
    result_text = _read_style_numbered_code()
    line = {
        "type": "user", "uuid": "u1", "parentUuid": None,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "missing", "content": result_text},
        ]},
    }
    path = tmp_path / "boom.jsonl"
    path.write_text(json.dumps(line) + "\n")

    failures: list[str] = []
    items = jc.extract_items(path, segmentation_failures=failures)
    assert failures == ["u1:0"]
    assert any(it.id == "u1:0" for it in items)


def test_large_read_result_segments_losslessly_into_multiple_code_items(tmp_path: Path) -> None:
    # End to end: extract_items on ONE large Read-shaped tool_result must (1) split into
    # SEVERAL Items (not stay one all-or-nothing blob), (2) give each a "<uuid>:<n>@<a>-<b>"
    # id, (3) join back to the exact original result text (losslessness), and (4) keep the
    # numbered-line prefixes IN the stored text -- only the DETECTION view strips them, per
    # `_detection_view`'s own docstring; a stored segment is an exact slice of the original.
    result_text = _read_style_numbered_code()
    line = {
        "type": "assistant", "uuid": "a1", "parentUuid": None,
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x.py"}},
        ]},
    }
    line2 = {
        "type": "user", "uuid": "u1", "parentUuid": "a1",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": result_text},
        ]},
    }
    path = tmp_path / "read.jsonl"
    path.write_text(json.dumps(line) + "\n" + json.dumps(line2) + "\n")

    items = jc.extract_items(path)
    tool_items = [it for it in items if it.kind == "tool"]
    assert len(tool_items) > 1, "a large Read result must split into several Items"
    for it in tool_items:
        assert it.id.startswith("u1:0@"), it.id
    assert "".join(it.text for it in tool_items) == result_text
    # The stored text is a verbatim slice -- the numbered prefix is still there.
    assert tool_items[0].text.split("\n", 1)[0].endswith("def func_0():")


def test_segment_ids_are_positional_never_content_hash(tmp_path: Path) -> None:
    # Card spec: "never the upstream content-hash id, which collides for identical
    # outputs". Build a result with two IDENTICAL function bodies far enough apart to land
    # in different segments and assert their ids still differ (positional, not content-based).
    result_text = _read_style_numbered_code()
    line = {
        "type": "user", "uuid": "u1", "parentUuid": None,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "missing", "content": result_text},
        ]},
    }
    path = tmp_path / "dup.jsonl"
    path.write_text(json.dumps(line) + "\n")
    items = [it for it in jc.extract_items(path) if it.kind == "tool"]
    ids = [it.id for it in items]
    assert len(ids) == len(set(ids)), "segment ids must be unique even with repeated content"


def test_embedded_stacktrace_is_never_split_and_marked_protected(tmp_path: Path) -> None:
    # Card spec: "a trace is never split" + "Protected kinds stacktrace and diff ...".
    # Pad the result well past the segmentation threshold, embed one whole Python traceback,
    # and assert exactly one produced Item carries the ENTIRE trace verbatim (never split
    # across pieces) and is marked `protected=True`.
    trace = (
        'Traceback (most recent call last):\n'
        '  File "/app/server.py", line 118, in handle_request\n'
        "    payload = self._decode(body)\n"
        '  File "/app/codec.py", line 44, in _decode\n'
        "    return json.loads(raw)\n"
        "json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)\n"
    )
    padding = "irrelevant filler log line number {}\n"
    before = "".join(padding.format(i) for i in range(150))
    after = "".join(padding.format(i) for i in range(150, 300))
    result_text = before + trace + after

    line = {
        "type": "user", "uuid": "u1", "parentUuid": None,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "missing", "content": result_text},
        ]},
    }
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(line) + "\n")
    items = [it for it in jc.extract_items(path) if it.kind == "tool"]
    assert len(items) > 1, "the padded result must actually segment"
    assert "".join(it.text for it in items) == result_text  # losslessness holds regardless

    trace_items = [it for it in items if trace in it.text]
    assert len(trace_items) == 1, "the trace must land whole in exactly one segment"
    assert trace_items[0].text.count(trace) == 1
    assert trace_items[0].protected is True
    non_trace_protected = [it for it in items if it is not trace_items[0] and it.protected]
    assert non_trace_protected == []


def test_protected_segment_outranks_higher_scoring_plain_item_under_budget() -> None:
    # `evict_key`/the non-owner admission sort: a `protected` (stacktrace/diff) segment must
    # survive a tight budget ahead of a plain item that Jev scored MORE relevant -- "ranks
    # above relevance-only items ... below decision_passed" (card 6 spec, verified here for
    # the ADMISSION path; `evict_key` itself is exercised via the max_bytes backstop test).
    items = [
        _item("trace:0", "tool", "a protected stack trace segment", turn=0, tokens=40),
        _item("plain:0", "tool", "a plain, more relevant segment", turn=1, tokens=40),
    ]
    items = [
        jc.Item(items[0].id, items[0].kind, items[0].text, items[0].tokens, items[0].ts,
                items[0].turn, protected=True),
        items[1],
    ]
    scores = {
        "trace:0": jc.Scores(relevance=0.55, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
        "plain:0": jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=40,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- tool trace:0 --" in doc
    assert "-- tool plain:0 --" not in doc


def test_protected_boost_admits_at_most_one_segment_per_source_item() -> None:
    # Card 6 follow-up (coordinator review of commit 3006e92f, addition 2): "On the 258 MB
    # transcript, 3 segments of ONE diff took the budget and added no coverage. Admit at
    # most one protected segment per source item ahead of relevance-only items; any further
    # segments of that same item compete by relevance like everything else." Three segments
    # of the SAME source item ("src:0") are all `protected=True` and score identically
    # (0.5); three OTHER, distinct-source items are NOT protected but score higher
    # (0.6/0.65/0.7). Only ONE segment of "src:0" (the earliest by `turn`) may still use the
    # protected-tier boost -- the other two compete purely on relevance and lose to the
    # higher-scoring distinct items, so the budget (3 slots) ends up spread across 3
    # DISTINCT source items instead of 3 segments of the same one.
    def _protected_seg(a: int, turn: int) -> jc.Item:
        it = _item(f"src:0@{a}-{a + 9}", "tool", f"segment at {a}", turn=turn, tokens=100)
        return jc.Item(it.id, it.kind, it.text, it.tokens, it.ts, it.turn, protected=True)

    items = [
        _protected_seg(1, 0), _protected_seg(11, 1), _protected_seg(21, 2),
        _item("o1:0", "tool", "other result one", turn=3, tokens=100),
        _item("o2:0", "tool", "other result two", turn=4, tokens=100),
        _item("o3:0", "tool", "other result three", turn=5, tokens=100),
    ]
    scores = {
        "src:0@1-10": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                                 decision_passed=False),
        "src:0@11-20": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                                  decision_passed=False),
        "src:0@21-30": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                                  decision_passed=False),
        "o1:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True,
                           decision_passed=False),
        "o2:0": jc.Scores(relevance=0.65, decision=0.0, oversized=False, kept=True,
                           decision_passed=False),
        "o3:0": jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                           decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=300,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    kept_ids = {
        m.group(1) for m in re.finditer(r"^-- \S+ (\S+) --$", doc, re.MULTILINE)
    }
    src_kept = {i for i in kept_ids if i.startswith("src:0@")}
    assert len(src_kept) == 1, f"expected exactly one segment of one source item, got {src_kept}"
    assert src_kept == {"src:0@1-10"}  # earliest turn among the tied-score segments
    assert kept_ids == {"src:0@1-10", "o3:0", "o2:0"}  # 3 DISTINCT source items, not 3 segments


def test_protected_boost_winner_is_chosen_among_kept_segments_only() -> None:
    # Adversarial review of the per-source cap: `score_items` scores an oversized item
    # relevance=1.0/decision=1.0 with kept=False, so picking the source's boosted segment from
    # ALL items made the oversized segment win -- and, never being kept, it left the source's
    # one KEPT segment unboosted, losing to a merely higher-scoring plain item. Here only one
    # of the two fits the budget; the kept protected segment must win it.
    def _protected_seg(a: int, turn: int, tokens: int) -> jc.Item:
        it = _item(f"src:0@{a}-{a + 9}", "tool", f"segment at {a}", turn=turn, tokens=tokens)
        return jc.Item(it.id, it.kind, it.text, it.tokens, it.ts, it.turn, protected=True)

    items = [
        _protected_seg(1, 0, 5000),
        _protected_seg(11, 1, 100),
        _item("o1:0", "tool", "other result one", turn=2, tokens=100),
    ]
    scores = {
        "src:0@1-10": jc.Scores(relevance=1.0, decision=1.0, oversized=True, kept=False,
                                 decision_passed=False),
        "src:0@11-20": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                                  decision_passed=False),
        "o1:0": jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                           decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=150,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- tool src:0@11-20 --" in doc
    assert "-- tool o1:0 --" not in doc
    assert "-- tool src:0@1-10 --" not in doc  # oversized: never inlined


def test_compose_with_many_segmented_items_stays_under_max_bytes(tmp_path: Path) -> None:
    # Card spec: "compose stays under max_bytes" -- exercised with REAL segmented items (not
    # hand-built ones), the injected-copy shape (`max_item_bytes` set) that the byte backstop
    # actually has to hold to.
    result_text = _read_style_numbered_code(n_funcs=300)  # several hundred segments
    line = {
        "type": "user", "uuid": "u1", "parentUuid": None,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "missing", "content": result_text},
        ]},
    }
    path = tmp_path / "big.jsonl"
    path.write_text(json.dumps(line) + "\n")
    items = jc.extract_items(path)
    assert len(items) > 5
    scores = {
        it.id: jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in items
    }
    max_bytes = 5000
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_bytes=max_bytes, max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES,
    )
    assert len(doc.encode("utf-8")) <= max_bytes


def test_digest_shrinks_single_oversized_head() -> None:
    # A review flagged that build_digest's "halve the sole remaining part until it fits"
    # fallback was only reachable in principle, never actually exercised: the existing cap
    # test always has multiple parts to drop first. Force exactly one STATE head, alone
    # over cap, so the halving loop -- not the part-dropping loop -- is what runs.
    huge_head = "state fact. " * 2000
    digest = jc.build_digest([], [huge_head], cap_tokens=20)
    from jevctx.tokens import estimate_tokens

    assert digest
    assert estimate_tokens(digest) <= 20


def test_scorer_error_propagates_no_fail_open() -> None:
    items = [_item("e:0", "user", "text", turn=0)]
    client = FakeJevClient.failing(JevUnavailableError("simulated outage"))
    try:
        jc.score_items(items, "digest", client)
    except JevUnavailableError:
        return
    raise AssertionError("expected a scorer failure to propagate, not fail open")


def test_digest_includes_last_two_assistant_text_blocks() -> None:
    # On an unattended session the last HUMAN message can be old; the last two assistant
    # `text` blocks anchor relevance-scoring on what the agent last said it was doing.
    items = [
        _item("a0:0", "assistant", "assistant text zero", turn=0),
        _item("a1:0", "assistant", "assistant text one", turn=1),
        _item("a2:0", "assistant", "assistant text two", turn=2),
        _item("u0:0", "user", "user says hi", turn=3),
    ]
    digest = jc.build_digest(items, [], cap_tokens=4000)
    assert "assistant text one" in digest
    assert "assistant text two" in digest
    assert "assistant text zero" not in digest  # only the LAST two, per the spec
    assert "user says hi" in digest


def test_score_items_sends_each_item_text_once_per_batch() -> None:
    # The review's core finding: two sequential per-question scorer calls send every item's
    # TEXT twice (once per question's own state). Assert the fix -- one client.ask() call
    # per batch, and that call's state.items carries each item's text exactly ONCE, not
    # duplicated for the two questions.
    items = [_item("i0:0", "user", "distinctive-marker-text", turn=0)]
    client = FakeJevClient.constant(0.9)
    jc.score_items(items, "digest", client)

    assert len(client.calls) == 1  # ONE request, not two
    call = client.calls[0]
    assert call.state_text().count("distinctive-marker-text") == 1
    # Both questions travel in that same one request.
    assert len(call.questions) == 2
    assert {k.rsplit(":", 1)[1] for k in call.questions} == {"rel", "dec"}


def test_extraction_skips_sidechain_entries(tmp_path: Path) -> None:
    # A subagent's turns live in the SAME main transcript file (isSidechain: true) but are
    # not the main conversation -- they must contribute zero items.
    lines = [
        {
            "type": "user", "uuid": "sc1", "parentUuid": None, "isMeta": False,
            "isSidechain": True, "timestamp": "2026-09-22T10:00:00+0200",
            "message": {"role": "user", "content": "a subagent's own prompt"},
        },
        {
            "type": "assistant", "uuid": "sc2", "parentUuid": "sc1", "isSidechain": True,
            "timestamp": "2026-09-22T10:00:01+0200",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent reply"}]},
        },
        {
            "type": "user", "uuid": "main1", "parentUuid": None, "isMeta": False,
            "timestamp": "2026-09-22T10:00:02+0200",
            "message": {"role": "user", "content": "the real, main-conversation message"},
        },
    ]
    path = tmp_path / "sidechain.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    items = jc.extract_items(path)
    assert len(items) == 1
    assert items[0].id == "main1:0"
    assert items[0].text == "the real, main-conversation message"


def test_full_context_path_appends_pointer_line_before_the_trailer() -> None:
    """Card 5 two-renderings (TRDD-RAEGS1D5): the capped rendering's own way back to the
    uncapped document `jev_compact.py compact` composes from the SAME items/scores -- one line,
    right before the fixed "pointers expand with" trailer, never after it (the trailer is the
    model's own fixed anchor, always last). Card 5 injection-caps review: the pointer line's
    wording was reworded away from "Read it for everything not shown here" (an ~11k-token read
    invitation), so this pins the NEW wording instead."""
    items = [_item("k:0", "user", "kept text", turn=0)]
    scores = {"k:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                decision_passed=False)}
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      full_context_path="/tmp/full-compacted.md")

    lines = doc.splitlines()
    assert (
        "Full compacted context: /tmp/full-compacted.md -- read it ONLY if what you need is "
        'not shown above; try list/search first: uv run --script '
        '"$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript /tmp/t.jsonl --list '
        '--grep TEXT.'
    ) in lines
    pointer_idx = next(i for i, line in enumerate(lines) if line.startswith("Full compacted context:"))
    trailer_idx = next(i for i, line in enumerate(lines) if line.startswith("pointers expand with:"))
    assert pointer_idx < trailer_idx, "the pointer must precede the fixed trailer, not follow it"


def test_no_full_context_path_omits_the_pointer_line() -> None:
    """The default (`full_context_path=None`, what `--out`'s own uncapped compose call uses)
    must never grow this line -- it exists only for a SEPARATE capped rendering."""
    items = [_item("k:0", "user", "kept text", turn=0)]
    scores = {"k:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                decision_passed=False)}
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header)

    assert "Full compacted context:" not in doc


# --- TRDD-RAEGS1D5 (2026-09-23): task-notification/heartbeat-turn extraction bug fix ---
# On a real 4.7 MB transcript, 26 of 36 items `extract_items` classified "user" were task
# notifications (agent reports), not the human -- and a heartbeat fire's own reply/tool-call
# items dominated a long unattended session. `FIXTURE_ORIGIN` mirrors the real field shapes
# (`origin.kind`, `turnOrigin`) these four tests exercise.


def test_is_human_record_trusts_origin_kind_when_present() -> None:
    # The `origin` branch of `is_human_record` short-circuits the isMeta/prefix fallback
    # entirely -- prove it for all three real `origin.kind` values seen on a live transcript.
    assert jc.is_human_record({"origin": {"kind": "human"}, "message": {"content": "hi"}}) is True
    assert jc.is_human_record(
        {"origin": {"kind": "task-notification"}, "message": {"content": "<task-notification>x"}}
    ) is False
    assert jc.is_human_record({"origin": {"kind": "peer"}, "message": {"content": "hi"}}) is False


def test_heartbeat_detection_via_scheduled_turn_origin_marker() -> None:
    # Defect 2 (review of 2353a88a): `turnOrigin == "scheduled"` ALONE must NOT be treated as
    # a heartbeat fire any more -- the owner's own CronCreate/`/loop` jobs are scheduled too,
    # and their turns are requested work, not a machine-only fire. Only the fire's own fixed
    # prefix still counts.
    entry = {"turnOrigin": "scheduled", "message": {"content": "no prefix in this body"}}
    assert jc._is_heartbeat_entry(entry) is False
    # The prefix alone (no `turnOrigin` at all) is still sufficient -- unchanged.
    prefixed = {"message": {"content": "[janitor-heartbeat]\nfire body"}}
    assert jc._is_heartbeat_entry(prefixed) is True


def test_scheduled_prompt_without_janitor_prefix_becomes_event() -> None:
    # Defect 2's own consequence: a scheduled-but-not-heartbeat prompt is neither dropped
    # (it is real requested work) nor counted as "user" (`transcript_roles.classify_record`
    # has no way to know it came from the owner rather than a `/loop` job) -- it becomes
    # kind "event", kept, but excluded from `build_digest`'s "last three human messages".
    items = jc.extract_items(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}
    assert by_id["sched1:0"].kind == "event"
    assert by_id["sched1:0"].text == "Check nightly build status"


def test_task_notification_becomes_event_and_is_excluded_from_the_digest() -> None:
    items = jc.extract_items(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}

    assert by_id["u2:0"].kind == "event"  # not "user" -- see is_human_record
    digest = jc.build_digest(items, [], cap_tokens=4000)
    assert "Background lint check finished" not in digest


def test_origin_less_legacy_record_still_classified_human() -> None:
    # A pre-`origin` transcript entry (no `origin` key at all) must still fall back to the
    # pre-existing heuristic and come out "human" when it is plainly a real human message.
    entry = {"type": "user", "isMeta": False, "message": {"content": "plain legacy text"}}
    assert jc.is_human_record(entry) is True

    items = jc.extract_items(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}
    assert by_id["u4:0"].kind == "user"  # u4 in the fixture carries no `origin` field


def test_heartbeat_turn_skips_assistant_and_tool_items() -> None:
    items = jc.extract_items(FIXTURE_ORIGIN)
    ids = [it.id for it in items]

    # hb1 (the fire itself) was already dropped before this fix; the NEW behaviour is that
    # its whole turn -- the Bash tool_use (a2), the tool_result (u3), and the "janitor
    # heartbeat" reply (a3) -- contributes zero items too.
    assert not any(id_.startswith("hb1:") for id_ in ids)
    assert not any(id_.startswith("a2:") for id_ in ids)
    assert not any(id_.startswith("u3:") for id_ in ids)
    assert not any(id_.startswith("a3:") for id_ in ids)


def test_human_turn_after_heartbeat_resumes_extraction() -> None:
    items = jc.extract_items(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}

    # u4 (the next human record after the heartbeat) closes the skip window and is itself
    # kept; a4 (the assistant's reply to u4, not to the heartbeat) is extracted normally too.
    assert by_id["u4:0"].kind == "user"
    assert by_id["u4:0"].text == "Also update the changelog"
    assert by_id["a4:0"].kind == "assistant"
    assert by_id["a4:0"].text == "Sure, updating the changelog."


# --- TRDD-RAEGS1D5 (2026-09-23): adversarial review of 2353a88a, five more defects ---


def test_heartbeat_turn_keeps_real_work_after_the_quiet_stub_call() -> None:
    """Defect 1: a `[janitor-resume]` heartbeat turn in keep-going mode does real work --
    reads cards, dispatches agents, edits. The fixture's second heartbeat turn (hb2) mirrors
    that: the dispatcher-stub call (a5) and its result (u5, containing "[janitor-resume]") are
    still dropped, but the real assistant prose (a6, a7), the real tool call it makes (the Read
    remembered on a6) and that tool's result (u6) all survive -- the OLD whole-turn skip window
    would have dropped every one of these too."""
    items = jc.extract_items(FIXTURE_ORIGIN)
    ids = [it.id for it in items]
    by_id = {it.id: it for it in items}

    # Still dropped: the heartbeat's own prompt, the quiet dispatcher-stub call and its result.
    assert not any(id_.startswith("hb2:") for id_ in ids)
    assert not any(id_.startswith("a5:") for id_ in ids)
    assert not any(id_.startswith("u5:") for id_ in ids)

    # NEW behaviour: real work in the same turn is kept.
    assert by_id["a6:0"].kind == "assistant"
    assert by_id["a6:0"].text == "Reading the TRDD card and dispatching the fix agent."
    assert by_id["u6:0"].kind == "tool"
    assert "Read(" in by_id["u6:0"].text
    assert by_id["a7:0"].kind == "assistant"
    assert by_id["a7:0"].text == "Committed the fix (051625a4)."


def test_decision_question_never_asked_for_a_non_user_item() -> None:
    """Defect 3: `score_items` must ask the DECISION question ("a decision the user stated")
    for `kind == "user"` items only -- an event/assistant/tool item has no author signal in
    Jev's own `state`, so asking it there let that item's text alone earn `decision_passed`
    (and with it `compose`'s eviction protection) no matter how the relevance question answers.
    A permissive client (answers 0.9 to everything it IS asked) must still leave the event
    item's decision at 0.0/False, because the question was never sent for it.

    Card 5 (TRDD-HWF3QFAB) update: "user" and non-"user" items are now planned in SEPARATE
    batches (16-per-batch/2-questions for "user", 32-per-batch/1-question for everyone else),
    so these two items land in two DIFFERENT requests -- this asserts the decision question
    is present in the "user" item's own request and absent from the other's, not merely
    absent from one shared request."""
    items = [
        _item("u:0", "user", "policy: always use tabs", turn=0),
        _item("e:0", "event", "a task notification's report text", turn=1),
    ]
    client = FakeJevClient.constant(0.9)
    scores = jc.score_items(items, "digest", client)

    assert len(client.calls) == 2  # one batch per kind-group
    # Counted per call, not merged into one set: each batch's `question_keys` restarts at
    # "i0" (jevctx.budget._question_keys), so the "user" batch's lone item and the "other"
    # batch's lone item both get ref "i0" -- a set across calls would collapse the two
    # ":rel" keys into one, hiding the very thing this test exists to prove.
    dec_key_count = sum(1 for call in client.calls for k in call.questions if k.endswith(":dec"))
    rel_key_count = sum(1 for call in client.calls for k in call.questions if k.endswith(":rel"))
    # Exactly one ref got a :dec question -- the user item's, whichever ref string it got.
    assert dec_key_count == 1
    assert rel_key_count == 2  # both items still get scored for relevance

    assert scores["u:0"].decision == 0.9
    assert scores["e:0"].decision == 0.0
    assert scores["e:0"].decision_passed is False


def test_mid_turn_attachment_becomes_user_and_queued_notification_becomes_event() -> None:
    """Defect 4: Claude Code writes a mid-turn queued owner message (typed while a turn was
    running) or a queued task-notification delivery as `type: "attachment"`,
    `attachment.type == "queued_command"` -- a shape `_WALKED_ENTRY_TYPES` used to drop
    entirely (measured on a real 2026-09-23 session transcript, field shapes mirrored in the
    fixture's att1/att2/att3). `commandMode: "prompt"` is the owner's own words (kind "user");
    `commandMode: "task-notification"` is an agent report (kind "event", same as any other
    notification); any other `attachment.type` (att3: `hook_success`) contributes nothing."""
    items = jc.extract_items(FIXTURE_ORIGIN)
    ids = [it.id for it in items]
    by_id = {it.id: it for it in items}

    assert by_id["att1:0"].kind == "user"
    assert by_id["att1:0"].text == "you are slow"
    assert by_id["att2:0"].kind == "event"
    assert "Nightly benchmark finished" in by_id["att2:0"].text
    assert not any(id_.startswith("att3:") for id_ in ids)


def test_mid_turn_attachment_from_a_peer_agent_is_event_not_user() -> None:
    """Defect-5 real-data re-derivation caught this: `commandMode == "prompt"` alone is NOT
    "the owner typed it" -- measured on a real 49 MB transcript, 19 of 23 `commandMode:
    "prompt"` attachments carried `origin.kind: "peer"` (a cross-session SendMessage from
    ANOTHER agent, delivered through the SAME mid-turn queue a genuine keystroke uses). Only
    `origin.kind == "human"` is the owner's own words; a peer message is real content (kept)
    but must never be counted as the human in `build_digest`/`score_items`'s decision question."""
    items = jc.extract_items(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}
    assert by_id["att4:0"].kind == "event"
    assert by_id["att4:0"].text == "Consultation request from a peer agent, not the owner."


# --- TRDD-CC0CZLMO (card 3): score_items fans batches out on a ThreadPoolExecutor ---


def test_score_items_deterministic_across_worker_counts() -> None:
    """Upstream's own invariant (`jevctx/scorer.py`'s
    `test_results_do_not_depend_on_worker_count`): `max_workers=1` and `max_workers=8` must
    score the SAME items to the SAME `Scores`, since concurrency only changes execution
    order, never batch membership or the answers `client.ask` returns."""
    items = [_item(f"i{i}:0", "assistant", f"text number {i}", turn=i) for i in range(40)]
    client_serial = FakeJevClient.by_text(lambda t: 0.9 if "3" in t else 0.2)
    scores_serial = jc.score_items(items, "digest", client_serial, max_workers=1)

    client_parallel = FakeJevClient.by_text(lambda t: 0.9 if "3" in t else 0.2)
    scores_parallel = jc.score_items(items, "digest", client_parallel, max_workers=8)

    assert scores_serial == scores_parallel


def test_score_items_error_propagates_from_any_batch() -> None:
    """Card 3: fail-closed must hold even with several batches in flight at once -- a
    `JevError` from ANY one of them must still propagate out of `score_items`, never get
    swallowed because the other batches succeeded (unlike `jevctx.scorer`'s own
    `on_error="keep"` default, which this module never uses)."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(4 * 32)]
    call_count = 0
    lock = threading.Lock()

    class _FlakyOnThirdCallClient:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            nonlocal call_count
            with lock:
                call_count += 1
                n = call_count
            if n == 3:
                raise JevUnavailableError("simulated outage on batch 3")
            return {key: NoulAnswer(noul=0.9) for key in questions}

    try:
        jc.score_items(items, "digest", _FlakyOnThirdCallClient(), max_workers=4)
    except JevUnavailableError:
        return
    raise AssertionError("expected the batch-3 failure to propagate")


# --- TRDD-1ETALGDG: a Cloudflare block / oversized batch splits instead of aborting ---


def test_score_items_splits_a_blocked_batch_and_pointers_the_poison_item(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A client that blocks (`JevBlockedError`) any request whose state carries one marked
    item's text must not abort the whole compaction -- `score_items` splits the batch down
    until that item is isolated alone, still fails there too (proving it "still fails alone",
    the card's own test wording), and becomes a pointer (`kept=False`) -- every OTHER item
    from the same original batch is still scored normally, and exactly one finding line on
    stderr names the poison item."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(8)]
    poison_id = "i3:0"
    poison_marker = "text 3"  # substring-unique among "text 0".."text 7"

    class _BlocksAnyBatchContainingMarker:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            texts = [entry["text"] for entry in state["items"]]
            if any(poison_marker in t for t in texts):
                raise JevBlockedError(
                    "simulated cloudflare block", cf_ray="test-ray", body_sha256="ab" * 32
                )
            return {key: NoulAnswer(noul=0.9) for key in questions}

    scores = jc.score_items(items, "digest", _BlocksAnyBatchContainingMarker(), max_workers=1)

    assert set(scores) == {it.id for it in items}  # nothing dropped -- every item scored
    assert scores[poison_id].kept is False
    assert scores[poison_id].oversized is False  # a pointer, not the 20-line oversized preview
    for it in items:
        if it.id != poison_id:
            assert scores[it.id].kept is True, f"{it.id} should have scored normally"

    finding_lines = [line for line in capsys.readouterr().err.splitlines() if poison_id in line]
    assert len(finding_lines) == 1, f"expected exactly one finding line, got: {finding_lines}"


def test_score_items_splits_a_max_tokens_exceeded_batch_and_succeeds() -> None:
    """The live HTTP 400 `max_tokens_exceeded` case (commit 61cad99c's own measured
    defect: a batch `BudgetPlanner`'s token ESTIMATE thought fit, the real backend
    didn't) -- splitting the batch in half must recover it, with every item still scored,
    no pointers and no finding."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(8)]

    class _RejectsBatchesOverFourItems:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            if len(state["items"]) > 4:
                raise JevValidationError(
                    "Jev (OpenRouter) returned 400: {'error_type': 'max_tokens_exceeded'}"
                )
            return {key: NoulAnswer(noul=0.9) for key in questions}

    scores = jc.score_items(items, "digest", _RejectsBatchesOverFourItems(), max_workers=1)

    assert set(scores) == {it.id for it in items}
    assert all(s.kept for s in scores.values())


def test_score_items_raises_when_every_batch_is_blocked() -> None:
    """When literally nothing could be scored -- every batch blocked all the way down to
    single items -- `score_items` must raise, not return an all-pointers dict as if it had
    succeeded: `jev_compact.py`'s caller falls back to the fact-only template on any Jev
    error, and an all-pointers "success" would skip that fallback for a document with zero
    usable content."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(3)]

    class _AlwaysBlocks:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            raise JevBlockedError("simulated total block")

    with pytest.raises(JevBlockedError):
        jc.score_items(items, "digest", _AlwaysBlocks(), max_workers=1)


def test_score_items_retry_cap_bounds_total_split_requests() -> None:
    """A backend that blocks EVERY request, even split ones, must not let `score_items`
    grind through unbounded splits -- `max_retried_requests` caps the total EXTRA
    (non-original) requests, and hitting it raises rather than degrading further."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(8)]

    class _AlwaysBlocks:
        def __init__(self) -> None:
            self.calls = 0

        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            self.calls += 1
            raise JevBlockedError("simulated total block")

    client = _AlwaysBlocks()
    with pytest.raises(JevBlockedError):
        jc.score_items(items, "digest", client, max_workers=1, max_retried_requests=1)

    # Unbounded, an 8-item batch could split down to 1-item leaves over several levels
    # (many more than 4 requests); the cap=1 must have stopped it almost immediately.
    assert client.calls <= 4, f"expected the retry cap to bound the requests, got {client.calls}"


# --- TRDD-1ETALGDG followup: budget exhaustion pointers instead of raising, and the raise
# gate is "more than half of ALL items blocked", not "literally nothing was scored" -------


def test_score_items_retry_budget_exhaustion_pointers_the_rest_instead_of_raising() -> None:
    """Followup item 1: the OLD behaviour re-raised the moment `retry_budget.take()` failed,
    which `score_items`'s fail-closed `ThreadPoolExecutor` handling turned into a total
    compaction failure over ONE poison item exhausting a budget shared across every batch.
    With `max_retried_requests=1`, the batch containing item i4 can take only ONE more split
    (isolating i0-i3 into their own half, which scores cleanly) before the budget is spent --
    the SECOND half (i4-i7, still containing the poison marker) must become pointers
    directly, not raise. Exactly half (4/8) of all items end up blocked, which must NOT
    raise either (the gate is "more than half")."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(8)]

    class _BlocksBatchesContainingMarker:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            texts = [entry["text"] for entry in state["items"]]
            if any("text 4" in t for t in texts):
                raise JevBlockedError(
                    "simulated cloudflare block", cf_ray="test-ray", body_sha256="cd" * 32
                )
            return {key: NoulAnswer(noul=0.9) for key in questions}

    scores = jc.score_items(
        items, "digest", _BlocksBatchesContainingMarker(), max_workers=1,
        max_retried_requests=1,
    )

    assert set(scores) == {it.id for it in items}  # nothing dropped -- every item scored
    for i in range(4):  # isolated into the half that never contained the poison marker
        item_id = f"i{i}:0"
        assert scores[item_id].kept is True, item_id
        assert scores[item_id].blocked is False, item_id
    for i in range(4, 8):  # the retry-budget-exhausted half -- pointers, not a raise
        item_id = f"i{i}:0"
        assert scores[item_id].kept is False, item_id
        assert scores[item_id].blocked is True, item_id


def test_score_items_raises_when_more_than_half_the_items_end_up_blocked() -> None:
    """Followup item 1: the raise gate is now "more than half of ALL items ended up
    unscored", not just "literally nothing was scored" (the pre-followup gate, which let an
    almost-all-pointers result through as a "success"). 5 of 8 items carry a poison marker
    and get isolated down to single-item leaves (well inside the default retry budget, no
    budget exhaustion involved here); the 3 clean items DO get scored normally, but
    `score_items` must still raise because 5/8 is more than half."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(8)]
    poison_markers = {"text 3", "text 4", "text 5", "text 6", "text 7"}

    class _BlocksBatchesContainingAnyPoisonMarker:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            texts = [entry["text"] for entry in state["items"]]
            if any(any(marker in t for marker in poison_markers) for t in texts):
                raise JevBlockedError("simulated block", cf_ray="r", body_sha256="ab" * 32)
            return {key: NoulAnswer(noul=0.9) for key in questions}

    with pytest.raises(JevBlockedError):
        jc.score_items(
            items, "digest", _BlocksBatchesContainingAnyPoisonMarker(), max_workers=1,
        )


def test_blocked_item_pointer_is_marked_unscored_provider_firewall() -> None:
    """Followup item 2(c): an item `score_items` never got to send to Jev at all (a provider
    firewall block or an oversized batch that survived every split retry, `Scores.blocked`)
    must render distinguishably in `compose()`'s pointer list from an ORDINARY below-
    threshold item -- otherwise the model cannot tell "Jev never saw this" (worth an
    `expand`) apart from "Jev saw it and it wasn't relevant" (not worth one)."""
    items = [
        _item("blocked:0", "assistant", "poisoned content", turn=0, tokens=10),
        _item("skipped:0", "assistant", "ordinary low-relevance content", turn=1, tokens=10),
    ]
    scores = {
        "blocked:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                decision_passed=False, blocked=True),
        "skipped:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    lines = doc.splitlines()
    blocked_idx = next(i for i, ln in enumerate(lines) if "id=blocked:0" in ln)
    skipped_idx = next(i for i, ln in enumerate(lines) if "id=skipped:0" in ln)
    assert lines[blocked_idx + 1] == "unscored (provider firewall)"
    # An ordinary below-threshold item gets no such note right after its pointer line.
    assert lines[skipped_idx + 1] != "unscored (provider firewall)"


def test_score_items_parallel_is_faster_than_serial() -> None:
    """Card 3 (TRDD-CC0CZLMO): jevctx's own `scorer.py` fans batches out on a
    `ThreadPoolExecutor` (`scorer.py:149-154`); ours must too, or a large transcript's serial
    for-loop exceeds both compaction-lane timeouts (the bug this card fixes -- measured: a
    49 MB transcript took 168 s on HEAD, over the 60 s sync AND the 120 s detached timeouts).
    160 non-"user" items pack 32-per-batch (card 5's non-"user" batch size) into 5 batches; a
    client that sleeps 0.2 s per request makes the serial time ~1.0 s and the max_workers=8
    time close to 0.2 s -- assert a CLEAR speedup, not an exact ratio (thread-scheduling
    jitter makes an exact number flaky)."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(160)]

    def sleepy_client() -> Any:
        inner = FakeJevClient.constant(0.9)

        class _SleepyClient:
            def ask(self, state: Any, questions: Any) -> dict[str, Any]:
                time.sleep(0.2)
                return inner.ask(state, questions)

        return _SleepyClient()

    start = time.monotonic()
    jc.score_items(items, "digest", sleepy_client(), max_workers=1)
    serial_elapsed = time.monotonic() - start

    start = time.monotonic()
    jc.score_items(items, "digest", sleepy_client(), max_workers=8)
    parallel_elapsed = time.monotonic() - start

    assert parallel_elapsed < serial_elapsed / 2, (
        f"expected a clear speedup: serial={serial_elapsed:.2f}s parallel={parallel_elapsed:.2f}s"
    )


def test_no_batch_exceeds_32_questions() -> None:
    """Card 5 (TRDD-HWF3QFAB): "user" items are batched 16-per-request (32 real questions:
    16 x rel + 16 x dec) and every other kind 32-per-request (32 real questions: 32 x rel) --
    both group sizes are chosen so neither ever exceeds Jev's `MAX_QUESTIONS_PER_REQUEST`
    hard cap, even though a "user" batch has half as many ITEMS as a non-"user" one.
    `FakeJevClient`'s own limit enforcement (`enforce_limits=True` by default) would raise
    `JevBudgetError` if a batch actually violated the cap -- this also asserts it directly."""
    user_items = [_item(f"u{i}:0", "user", f"decision {i}", turn=i, tokens=10) for i in range(50)]
    other_items = [_item(f"o{i}:0", "assistant", f"note {i}", turn=i, tokens=10) for i in range(70)]
    client = FakeJevClient.constant(0.9)
    jc.score_items(user_items + other_items, "digest", client)

    assert client.calls  # sanity: the batches actually ran
    for call in client.calls:
        assert len(call.questions) <= 32


# --- TRDD-HWF3QFAB (card 5): pipeline.format_pointer/RETRIEVE_QUESTION ---


def test_every_pointer_in_compose_output_parses_and_count_matches_elided_shown() -> None:
    """Card 5: `_format_pointer` now goes through `pipeline.format_pointer`, so every
    pointer `compose()` emits must round-trip through `pipeline.find_pointers` -- proving the
    escaping is correct, not just "looks right" by eye. The parsed count must equal the
    number of elided pointer LINES actually shown (the capped list, not every elided item --
    `compose()` caps at `_MAX_ELIDED_POINTERS`).

    kind="assistant", not "user" (TRDD-RAEGS1D5, jev newest+3): decouples this from the
    newest-owner-item guarantee, same reasoning as the pointer-cap test above.
    """
    n = jc._MAX_ELIDED_POINTERS + 5
    items = [_item(f"e{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(n)]
    scores = {
        it.id: jc.Scores(relevance=(i / n), decision=0.0, oversized=False, kept=False,
                          decision_passed=False)
        for i, it in enumerate(items)
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})

    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided id=")]
    assert len(pointer_lines) == jc._MAX_ELIDED_POINTERS
    parsed = find_pointers(doc)
    assert len(parsed) == len(pointer_lines)


def test_pointer_summary_escapes_quotes_and_backslashes_and_round_trips() -> None:
    """Card 5: the local pointer literal this replaced had no escaping at all -- a `"` or
    `\\` in an item's first line produced a pointer `pipeline.parse_pointer` could not parse
    back. Prove the round trip: format, then parse, and the summary comes back byte-identical
    to the original first line.

    kind="assistant", not "user" (TRDD-RAEGS1D5, jev newest+3): the sole newest owner item
    would otherwise be force-admitted as kept rather than elided -- this test is about the
    pointer's escaping/round-trip, not ownership.
    """
    first_line = 'said "always use \\tabs\\", never spaces'
    items = [_item("q:0", "assistant", first_line + "\nmore text", turn=0)]
    scores = {"q:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})

    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided id=")]
    assert len(pointer_lines) == 1
    parsed = parse_pointer(pointer_lines[0])
    assert parsed is not None
    assert parsed.summary == first_line


def test_segment_pointer_is_unparseable_by_pipeline_find_pointers() -> None:
    """Adversarial-review disclosure (TRDD-88DOI824, `_format_pointer`'s own docstring): a
    segment id embeds its line span as `<uuid>:<n>@<a>-<b>` -- necessary so `expand <id>` is
    one copy-pasteable token (see that docstring) -- but `pipeline._POINTER_RE`'s id character
    class (`[A-Za-z0-9:_.-]+`) does not include `@`, so `find_pointers`/`parse_pointer` fail to
    match a segment's pointer line at all. Pinned here as KNOWN, CURRENT behavior (not a bug
    this test is asserting should be fixed) -- nothing in production reads `compose()` output
    back through `find_pointers` today, so this only guards against the gap being silently
    "fixed" by an unrelated future change to `_format_pointer`/`Pointer` without the same
    disclosure, or silently made worse."""
    seg_id = "550e8400-e29b-41d4-a716-446655440000:0@5-9"
    items = [_item(seg_id, "tool", "segment body text\nmore", turn=0)]
    scores = {seg_id: jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                 decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})

    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided id=")]
    assert len(pointer_lines) == 1
    assert seg_id in pointer_lines[0]  # the id IS rendered, verbatim, in the bracket text...
    assert parse_pointer(pointer_lines[0]) is None  # ...but the regex cannot parse it back
    assert find_pointers(doc) == []  # ...and find_pointers silently finds nothing at all


def test_pointer_summary_skips_a_leading_blank_line() -> None:
    """Card 5: the summary is the first NON-EMPTY line (was: the first line, blank or not --
    a leading blank line used to produce an empty preview).

    kind="assistant", not "user" (TRDD-RAEGS1D5, jev newest+3): same reasoning as the two
    pointer-format tests above -- the sole newest owner item would otherwise be guaranteed a
    kept slot instead of appearing as a pointer.
    """
    items = [_item("b:0", "assistant", "\n\n   \nreal first content", turn=0)]
    scores = {"b:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert 'id=b:0 tokens=%d "real first content"' % items[0].tokens in doc


# --- TRDD-RAEGS1D5 (injected-copy content fix, 2026-09-23) -------------------------------------
# Real-data measurement (reports/compaction-replacement/): three real transcripts rendered 3, 0
# and 0 kept items into the injected copy at `--inject-max-bytes 5000` -- the old byte backstop
# evicted whole kept items until the doc fit, and a real item is routinely bigger than the whole
# injected budget. These four tests exercise `max_item_bytes` (the injected-mode signal) in
# isolation, on synthetic data, without a network call.


def test_inject_mode_shows_at_least_five_kept_items_as_truncated_prefixes() -> None:
    """Requirement 1+2: ten kept ASSISTANT items (deliberately not "user" -- the owner-share
    tests below cover that axis separately), each 2000 bytes -- far bigger than both
    `max_item_bytes` (700) and the whole `max_bytes` budget (5000) -- reproduce the real-data
    failure directly: every kept item individually exceeds the injected budget. Before this
    fix, the byte backstop's whole-item eviction would have dropped ALL of them (the measured
    0-kept-item real-data failure). With `max_item_bytes` set, several must survive as
    verbatim-prefix + pointer instead."""
    items = [
        _item(f"k{i}:0", "assistant", ("x" * 2000) + f" tail-{i}", turn=i, tokens=10)
        for i in range(10)
    ]
    scores = {
        it.id: jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in items
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_bytes=5000, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 5000
    kept_headers = [line for line in doc.splitlines() if line.startswith("-- assistant k")]
    assert len(kept_headers) >= 5, f"expected >=5 kept items, got {len(kept_headers)}: {kept_headers}"
    # Each shown item is a genuine VERBATIM prefix (never paraphrased, never a shorter
    # summary) capped at exactly `max_item_bytes`, immediately followed by a pointer back to
    # the rest -- the `x` * 700 prefix is the item's own transcript bytes, not a description.
    assert doc.count("x" * 700) == len(kept_headers)
    assert doc.count("[[elided id=k") == len(kept_headers)


def test_inject_mode_caps_pointer_bytes_to_their_share_of_the_budget() -> None:
    """Requirement 3: thirty elided items, each pointer-worthy, against a 3000-byte budget --
    unrestrained, their pointer lines alone would run to ~3.3 KB, more than the WHOLE budget,
    starving the one kept item the way pointers used to. Verified directly against the
    rendered pointer lines' own byte total (not just the whole-document cap the final backstop
    would also enforce) so this proves the EARLIER, dedicated pointer-share trim actually ran."""
    kept = [_item("kept:0", "user", "short kept text", turn=0, tokens=5)]
    kept_scores = {kept[0].id: jc.Scores(relevance=0.9, decision=0.0, oversized=False,
                                          kept=True, decision_passed=False)}
    elided = [
        _item(f"e{i}:0", "assistant", f"elided background text number {i} " * 3, turn=i + 1,
              tokens=5)
        for i in range(30)
    ]
    elided_scores = {
        it.id: jc.Scores(relevance=(i / 30), decision=0.0, oversized=False, kept=False,
                          decision_passed=False)
        for i, it in enumerate(elided)
    }
    items = kept + elided
    scores = {**kept_scores, **elided_scores}
    max_bytes = 3000
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_bytes=max_bytes, max_item_bytes=700, max_elided_pointers=30)

    assert len(doc.encode("utf-8")) <= max_bytes
    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided id=e")]
    pointer_bytes = sum(len(line.encode("utf-8")) + 1 for line in pointer_lines)
    assert pointer_bytes <= int(max_bytes * jc._INJECT_POINTER_SHARE)
    assert "-- user kept:0 --" in doc  # the kept item survives, not starved by pointers


def test_inject_mode_never_shows_the_oversized_preview() -> None:
    """Requirement 4: `test_oversized_pointer_includes_first_20_lines` above already proves
    `--out` (`max_item_bytes=None`) keeps the 20-line oversized preview; the injected render
    (`max_item_bytes` given) must never receive that block -- only the ordinary single-line
    pointer every elided item gets (whose own 80-char summary legitimately echoes line 0)."""
    body_lines = [f"line {i}" for i in range(30)]
    items = [_item("o:0", "assistant", "\n".join(body_lines), turn=0, tokens=999999)]
    scores = {"o:0": jc.Scores(relevance=1.0, decision=1.0, oversized=True, kept=True,
                                decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_item_bytes=700)
    assert "id=o:0" in doc  # still pointed at -- just never previewed
    for line in body_lines[1:]:  # line 0 legitimately survives as the pointer's own summary
        assert line not in doc


def test_inject_mode_byte_cap_holds_through_the_full_degrade_chain() -> None:
    """Requirement 5: the `max_bytes` cap is a hard guarantee in injected mode too, down to a
    budget tight enough to force every degrade step in turn (per-item truncation already
    applied at render time, then whole-item eviction, then pointer eviction, then digest
    truncation) -- and the fixed "pointers expand with" trailer, the model's only way back to
    everything elided, must still survive even this squeeze."""
    items = [_item(f"k{i}:0", "user", "y" * 3000, turn=i, tokens=5) for i in range(5)] + [
        _item(f"e{i}:0", "assistant", f"elided {i}", turn=100 + i, tokens=5) for i in range(10)
    ]
    scores = {
        f"k{i}:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                              decision_passed=False)
        for i in range(5)
    }
    scores.update({
        f"e{i}:0": jc.Scores(relevance=0.1, decision=0.0, oversized=False, kept=False,
                              decision_passed=False)
        for i in range(10)
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s", "digest": "z" * 500}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=600, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 600
    assert "pointers expand with:" in doc


def test_inject_mode_owner_share_capped_and_nonuser_items_survive() -> None:
    """Orchestrator rebalance (2026-09-23): a real run on this repo's own 49 MB/258 MB
    transcripts showed the injected copy 100% kind "user" -- the owner's own messages crowded
    out every bit of what the session actually did. 20 owner (user) messages + 20 high-
    relevance tool items reproduces that shape directly. Four things must hold:

    1. the single NEWEST owner message survives in FULL when it fits `NEWEST_OWNER_ITEM_BYTES`
       (1500) -- here it does not (it is ~1900 bytes), so it must survive as exactly a
       1500-byte verbatim prefix, never the 700-byte `max_item_bytes` every OTHER item gets;
    2. every OTHER kept item -- owner or not -- is still capped at the general 700-byte
       `max_item_bytes`, proven here by an owner item whose 700-byte-prefix marker never
       exceeds that length;
    3. the owner group's total rendered bytes stay within `_OWNER_SHARE` of the kept-item
       section (a generous tolerance around the ~40% ceiling, since the selection-time
       estimate and the final render can differ by a little -- not a source of flakiness);
    4. at least 3 non-user (tool) items appear, proving they are no longer crowded out.
    """
    owner_items = [
        _item(f"u{i}:0", "user", f"short owner note number {i}", turn=i, tokens=5)
        for i in range(19)
    ]
    # The NEWEST owner message (turn=19, highest) -- deliberately over NEWEST_OWNER_ITEM_BYTES
    # (1500) so its truncation-to-1500 (not 700) is what this test actually proves.
    newest_owner_text = "owner instruction " * 100  # ~1900 bytes, no internal newline
    owner_items.append(_item("u19:0", "user", newest_owner_text, turn=19, tokens=5))
    tool_items = [
        _item(f"t{i}:0", "tool", ("tool output line " * 150) + f" id{i}", turn=100 + i, tokens=5)
        for i in range(20)
    ]
    items = owner_items + tool_items
    scores = {
        it.id: jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in owner_items
    }
    scores.update({
        it.id: jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tool_items
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                      max_bytes=6000, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 6000

    # (1) the newest owner message: present as exactly its own first 1500 bytes (cut at a
    # line boundary or UTF-8-safe, per `_truncate_prefix_bytes`), never the full ~1900-byte
    # text, and never truncated down to the smaller 700-byte general cap either.
    newest_prefix = jc._truncate_prefix_bytes(newest_owner_text, jc.NEWEST_OWNER_ITEM_BYTES)
    assert newest_prefix in doc
    assert newest_owner_text not in doc  # too long for even the 1500-byte exception
    smaller_prefix = jc._truncate_prefix_bytes(newest_owner_text, jc.DEFAULT_INJECT_ITEM_BYTES)
    assert len(smaller_prefix) < len(newest_prefix)
    assert "-- user u19:0 --" in doc

    # (2) every other item -- owner or not -- still respects the general 700-byte cap: no
    # kept item's rendered VERBATIM prefix is between 701 and 1499 bytes (that gap is only
    # reachable by the newest-owner exception, which is excluded above).
    kept_section = doc.split("## Kept items\n", 1)[1].split("\n\n## Elided", 1)[0]
    import re as _re
    for block in _re.split(r"\n(?=-- \w+ [^\n]+ --\n)", kept_section):
        m = _re.match(r"-- (\w+) ([^\n]+) --\n", block)
        if not m or m.group(2) == "u19:0":
            continue
        body = block[m.end():].split("\n[[elided", 1)[0]
        assert len(body.encode("utf-8")) <= jc.DEFAULT_INJECT_ITEM_BYTES, (
            f"{m.group(2)} exceeded the general per-item cap"
        )

    # (3) owner share stays close to the ~40% ceiling (generous tolerance -- see docstring).
    owner_bytes = sum(
        len(b.encode("utf-8")) for b in _re.split(r"\n(?=-- \w+ [^\n]+ --\n)", kept_section)
        if b.startswith("-- user ")
    )
    assert owner_bytes / len(kept_section.encode("utf-8")) <= 0.5

    # (4) non-user items are no longer crowded out.
    tool_headers = [line for line in doc.splitlines() if line.startswith("-- tool t")]
    assert len(tool_headers) >= 3, f"expected >=3 tool items, got {len(tool_headers)}"


def test_non_owner_item_bytes_caps_non_owner_items_smaller_than_owner_items() -> None:
    # TRDD-RAEGS1D5 (jev newest+3, task 2): `non_owner_item_bytes`, when given alongside
    # `max_item_bytes`, caps ONLY items whose `kind != "user"` -- an owner item beyond the
    # guaranteed slot still uses the general (bigger) `max_item_bytes`, unaffected by the
    # smaller non-owner cap. "owner2:0" (an owner item, NOT the guaranteed newest) proves the
    # former; "tool:0" proves the latter.
    owner_text = "o" * 600
    tool_text = "t" * 600
    items = [
        _item("newest:0", "user", "hi", turn=10, tokens=10),
        _item("owner2:0", "user", owner_text, turn=1, tokens=10),
        _item("tool:0", "tool", tool_text, turn=0, tokens=10),
    ]
    scores = {
        "newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "owner2:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "tool:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_item_bytes=500, non_owner_item_bytes=100,
    )
    assert owner_text[:500] in doc     # owner item: the general 500-byte cap applies
    assert tool_text[:500] not in doc  # tool item would fit whole at 500...
    assert tool_text[:100] in doc      # ...but only gets the smaller 100-byte non-owner cap
    assert tool_text[:101] not in doc


def test_non_owner_item_bytes_none_falls_back_to_max_item_bytes_for_every_caller() -> None:
    # Backward compatibility: `non_owner_item_bytes` defaults to `None` -- every existing
    # caller/test that never passes it (including `jev_compact.py`'s own `--out` full-copy
    # render, which never sets `max_item_bytes` either) must render a non-owner item exactly
    # as before this parameter existed.
    tool_text = "t" * 600
    items = [_item("tool:0", "tool", tool_text, turn=0, tokens=10)]
    scores = {"tool:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                   decision_passed=False)}
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_item_bytes=500,
    )
    assert tool_text[:500] in doc
    assert tool_text[:501] not in doc


def test_full_copy_uncaps_decision_pointers_while_tool_pointers_stay_capped_and_injected_copy_is_unchanged() -> None:
    """TRDD-RAEGS1D5 (coordinator addition, full-copy decision-pointer uncap): the FULL
    (`--out`) render must name EVERY elided decision-passing owner item by a pointer, with NO
    `max_elided_pointers` cap -- the 258 MB real transcript had 250 decision-passing owner
    items and only 40 pointer slots, so 180 were reachable only via `expand --list --grep`,
    never named in the document a resumed session actually reads. The non-decision elided
    items (here, relevant "tool" items) still respect the pre-existing 40-pointer cap, and the
    byte-budgeted INJECTED copy is unaffected -- it still applies ONE `max_elided_pointers` cap
    over every elided item together, decision-passing or not, exactly as before this fix.
    """
    guaranteed = _item("guaranteed:0", "user", "the newest decision", turn=1000, tokens=10)
    decision_items = [
        _item(f"dec{i}:0", "user", f"policy decision number {i} text " * 40, turn=i, tokens=1000)
        for i in range(50)
    ]
    tool_items = [
        _item(f"tool{i}:0", "tool", f"relevant tool output {i} " * 40, turn=100 + i, tokens=1000)
        for i in range(60)
    ]
    items = [guaranteed, *decision_items, *tool_items]
    scores = {
        "guaranteed:0": jc.Scores(relevance=0.5, decision=0.9, oversized=False, kept=True,
                                   decision_passed=True),
        **{
            it.id: jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                              decision_passed=True)
            for it in decision_items
        },
        **{
            it.id: jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                              decision_passed=False)
            for it in tool_items
        },
    }
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}

    # A tiny budget: only the guaranteed slot fits (unconditional), every other 1000-token
    # item -- decision or tool -- is evicted from "kept" and lands in "## Elided", which is
    # the code path this fix changes.
    full_doc = jc.compose(items, scores, budget_tokens=50, header=header)
    assert "-- user guaranteed:0 --" in full_doc
    for it in decision_items:
        assert f"-- user {it.id} --" not in full_doc  # sanity: genuinely elided, not kept

    elided_section = full_doc.split("## Elided\n", 1)[1]
    # (1) every elided decision item gets a pointer, uncapped, in the compact format --
    # never the standard `[[elided id=...]]` shape (that would cost more bytes at this count).
    for it in decision_items:
        assert f"{it.id}: " in elided_section, f"{it.id} missing a decision pointer"
        assert f"[[elided id={it.id} " not in elided_section

    # (2) the non-decision (tool) elided items stay under the pre-existing 40-pointer cap.
    tool_pointer_lines = [
        line for line in elided_section.splitlines() if line.startswith("[[elided id=tool")
    ]
    assert len(tool_pointer_lines) == jc._MAX_ELIDED_POINTERS
    assert "[[elided: 20 more items not listed" in full_doc

    # (3) the injected copy is unaffected: still one cap over every elided item, never the
    # compact format (`max_item_bytes` is always set for it, see `render`'s per-item cap).
    inject_doc = jc.compose(
        items, scores, budget_tokens=50, header=header,
        max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES,
    )
    inject_pointer_lines = [
        line for line in inject_doc.splitlines() if line.startswith("[[elided id=")
    ]
    assert len(inject_pointer_lines) == jc._MAX_ELIDED_POINTERS
    inject_lines = inject_doc.splitlines()
    assert not any(line.startswith(f"{it.id}: ") for it in decision_items for line in inject_lines)


def test_decision_pointer_hard_ceiling_keeps_newest_and_summarizes_the_rest() -> None:
    """TRDD-RAEGS1D5 (adversarial-review finding 1 on the full-copy decision-pointer uncap
    above, hard ceiling): uncapping every elided decision-passing item with NO ceiling at all
    reproduces the exact unbounded-growth failure `_MAX_ELIDED_POINTERS` was built to prevent
    (one pointer line per elided item, uncapped, measured ~2.4 MB on the largest real
    transcript) -- just scoped to decision items instead of every elided item. Past
    `_MAX_DECISION_POINTERS` (400), the OLDEST decision items fold into one summary line
    instead of each getting a pointer; the NEWEST ones are the ones kept, since what the owner
    said most recently matters most on resume.
    """
    n = jc._MAX_DECISION_POINTERS + 25
    guaranteed = _item("guaranteed:0", "user", "the newest decision", turn=n + 10, tokens=10)
    decision_items = [
        _item(f"dec{i}:0", "user", f"policy decision number {i} " * 5, turn=i, tokens=1000)
        for i in range(n)
    ]
    items = [guaranteed, *decision_items]
    scores = {
        "guaranteed:0": jc.Scores(relevance=0.5, decision=0.9, oversized=False, kept=True,
                                   decision_passed=True),
        **{
            it.id: jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                              decision_passed=True)
            for it in decision_items
        },
    }
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}

    # Same tiny-budget trick as the previous test: only the guaranteed slot is admitted, every
    # decision item is genuinely elided -- 425 of them, 25 over the ceiling.
    doc = jc.compose(items, scores, budget_tokens=50, header=header)
    assert "-- user guaranteed:0 --" in doc

    elided_section = doc.split("## Elided\n", 1)[1]
    oldest_25 = decision_items[:25]  # turn 0-24, the lowest -- must be dropped
    newest_400 = decision_items[25:]  # turn 25-449, the highest -- must survive

    for it in oldest_25:
        assert f"{it.id}: " not in elided_section, f"{it.id} should have been dropped (oldest)"
    for it in newest_400:
        assert f"{it.id}: " in elided_section, f"{it.id} should have survived (newest)"

    assert "... and 25 more decision items: run `" in doc
    assert "expand --transcript /tmp/t.jsonl --list --grep TEXT` to list them" in doc
