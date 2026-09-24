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


def _ei(path: Any, **kwargs: Any) -> list[jc.Item]:
    """`jc.extract_items` wrapper: `malformed_lines` became a REQUIRED keyword (TRDD-DQXMND59,
    adversarial review 2026-09-24, finding A), and `segmentation_failures` followed it (stage
    3, item E) -- most tests below don't care about either count and would otherwise repeat
    both at every one of ~25 call sites."""
    kwargs.setdefault("malformed_lines", [])
    kwargs.setdefault("segmentation_failures", [])
    return jc.extract_items(path, **kwargs)


def _item(id_: str, kind: jc.ItemKind, text: str, turn: int, tokens: int | None = None) -> jc.Item:
    from jevctx.tokens import estimate_tokens

    return jc.Item(id=id_, kind=kind, text=text,
                    tokens=tokens if tokens is not None else estimate_tokens(text),
                    ts=None, turn=turn)


def test_extraction_skips_heartbeat_thinking_meta_and_system_and_pairs_tool_results() -> None:
    items = _ei(FIXTURE)
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
    first = [it.id for it in _ei(FIXTURE)]
    second = [it.id for it in _ei(FIXTURE)]
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
    # transcript's chronologically LAST owner message scored relevance=0.29/decision=0.22,
    # both under the 0.5 default thresholds, so `kept=False` and it never reached
    # `kept_items` at all. Reproduced directly: "newest:0" is the newest owner item by
    # `turn`, `kept=False`, and must still appear -- force-admitted, not merely named by a
    # pointer. TRDD-DZ1KOGAC: the original transcript's actual last message was the bare
    # word "resume" -- `extract_items` now demotes that to kind "event" before it ever
    # reaches `compose`, so this fixture uses a real (non-control) short owner message
    # instead, keeping the test's intent (the guarantee itself) unchanged.
    items = [
        _item("older:0", "user", "an earlier owner message", turn=0, tokens=50),
        _item("newest:0", "user", "check the deploy status", turn=5, tokens=10),
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
    assert "check the deploy status" in doc
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
    the oldest, decision-passed one, not simply the newest one.

    Kind is "assistant", not "user" (round 4 coordinator order fix, TRDD-RAEGS1D5): a "user"
    item can be one of `compose()`'s two GUARANTEED owner slots (the newest owner message, the
    newest decision-passing owner item), which now sit outside `evict_key`'s ordering entirely
    (see `guaranteed_owner_ids`) -- these 4 items being "user" was an accidental entanglement
    with that separate mechanism, not this test's own subject (the plain `evict_key` priority
    the narrower non-owner/non-guaranteed-owner byte-only fallback still uses, unchanged)."""
    decision_item = _item("old-decision", "assistant", "IMPORTANT decision text", turn=0, tokens=5)
    relevance_items = [
        _item(f"new-relevance-{i}", "assistant", f"background text {i}", turn=i, tokens=5)
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
    assert f"-- assistant {decision_item.id} --" in doc
    for it in relevance_items:
        assert f"-- assistant {it.id} --" not in doc


def test_decision_item_survives_a_budget_that_already_dropped_the_digest() -> None:
    """Round 5 coordinator order fix (TRDD-RAEGS1D5): the intended degrade order is pointers,
    non-owner items down to a floor of 3, non-guaranteed-owner items, the remaining non-owner
    items below the floor, the digest, then the newest DECISION item (the second guaranteed
    slot, held since aabd8b0c) -- so a budget tight enough to already have forced the digest
    down to `_DIGEST_TRUNCATED_NOTE` must still show the decision item; stage (6) only
    sacrifices it once (1)-(5) together are not enough.

    Two owner items -- "newest" (turn 5, plain) and "dec" (turn 0, `decision_passed`) -- are
    both guaranteed slots, so there are no non-guaranteed-owner items here for stage (3) to
    spend -- stage (4) (the floor itself) is what actually evicts the 3 non-owner "tool" items
    in this scenario, exactly at the floor to begin with (stage (2) is a no-op: evicting even
    one would fall BELOW the floor). A long digest gives stage (5) real material to drop after.
    `max_bytes=550` (measured): big enough that evicting the 3 non-owner items and truncating
    the digest is already enough to fit, small enough that none of it fits un-degraded -- so
    stage (6) never runs, and "dec" is still in the doc."""
    newest = _item("newest:0", "user", "hi there, just resuming", turn=5, tokens=5)
    dec = _item("dec:0", "user", "policy: always use tabs, never spaces", turn=0, tokens=5)
    non_owner = [
        _item(f"tool{i}:0", "tool", f"tool output {i} " * 5, turn=1 + i, tokens=5)
        for i in range(3)
    ]
    items = [dec, *non_owner, newest]
    scores = {
        "newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
    }
    scores.update({
        it.id: jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in non_owner
    })
    header = {
        "transcript_path": "/tmp/t.jsonl", "session_key": "s",
        "digest": "digest filler text " * 20,
    }
    doc = jc.compose(items, scores, budget_tokens=8000, header=header, max_bytes=550)

    assert len(doc.encode("utf-8")) <= 550
    # The digest genuinely degraded -- proof this budget forces real work, not a no-op.
    assert jc._DIGEST_TRUNCATED_NOTE in doc
    assert ("digest filler text " * 20) not in doc
    # ... and every non-owner item is gone too (stage (4) had to spend the floor itself, since
    # there was no non-guaranteed-owner item for stage (3) to sacrifice instead).
    for it in non_owner:
        assert f"-- tool {it.id} --" not in doc
    # Both guaranteed slots still present -- the decision item never had to be sacrificed.
    assert "-- user dec:0 --" in doc
    assert "-- user newest:0 --" in doc


def test_stage_6_actually_evicts_the_newest_decision_item_when_nothing_else_is_left() -> None:
    """Round 4 review finding (TRDD-RAEGS1D5), stage renumbered by round 5's floor-of-3
    reorder: the "survives" test above only proves the decision item is never at risk when it
    does not need to be -- no test drove the budget tight enough to force the decision-item
    eviction branch (`kept_order_list = [it for it in kept_order_list if it.id != decision_id]`,
    now stage (6)) to actually run. Just the two guaranteed items here (no pointers, no
    non-owner items, no digest -- stages (1)-(5) are all no-ops by construction), so shrinking
    the doc from over-budget to under can ONLY be stage (6) at work.

    "dec" is 2000 bytes (truncates to its own `NEWEST_OWNER_ITEM_BYTES` cap, ~1909 rendered
    bytes measured); "newest" is 2 bytes. `max_bytes=1800` (measured): fits with "newest" alone
    (279 bytes) but not with "dec" still present (1909) -- so stage (6) must fire, and only it,
    to reach budget. A mutated stage (6) (wrong id, or a guard that always no-ops) would leave
    "dec" in the doc and blow the 1800-byte bound, which `test_render_minimal_fallback_...`'s
    sibling terminal-stage tests do not cover (they exercise `_render_minimal_fallback`
    directly, never stage (6) inside `compose()` itself)."""
    newest = _item("newest:0", "user", "hi", turn=5, tokens=5)
    dec = _item("dec:0", "user", "d" * 2000, turn=0, tokens=5)
    items = [dec, newest]
    scores = {
        "newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
    }
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=1800, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 1800
    assert jc._MINIMAL_FIXED_LINE not in doc, "must fit via stage (6), never the terminal stage"
    assert "-- user newest:0 --" in doc
    assert "-- user dec:0 --" not in doc


def test_non_guaranteed_owner_tier_is_evicted_by_evict_key_when_max_item_bytes_is_none() -> None:
    """Round 4 review finding (TRDD-RAEGS1D5), stage renumbered by round 5's floor-of-3
    reorder: the `max_item_bytes is None` branch's stage (3) `evict_order` (non-guaranteed-owner
    items, `sorted(..., key=evict_key)`) -- the existing `test_max_bytes_backstop_drops_...`
    test was deliberately rewritten to `kind="assistant"` so it isolates stage (2)'s own
    non-owner group instead, leaving stage (3)'s `non_guaranteed_owner_tier` with zero direct
    coverage. Dead code in production today (`--out` never passes `max_bytes`, confirmed in
    this task's own report), but real, reachable code under direct test -- this exercises it.

    3 owner items, none of them the newest ("rel3", turn=3) or decision-passing ("dec", turn=0,
    both guaranteed): "rel1"/"rel2" (turns 1/2, plain relevance) must be evicted, by `evict_key`
    priority (oldest of equal, non-decision-passed score first), before either guaranteed item is
    ever touched."""
    dec = _item("dec:0", "user", "policy text", turn=0, tokens=5)
    rel1 = _item("rel1:0", "user", "background one", turn=1, tokens=5)
    rel2 = _item("rel2:0", "user", "background two", turn=2, tokens=5)
    rel3 = _item("rel3:0", "user", "newest owner message", turn=3, tokens=5)
    items = [dec, rel1, rel2, rel3]
    scores = {
        "dec:0": jc.Scores(relevance=0.5, decision=0.6, oversized=False, kept=True,
                            decision_passed=True),
        "rel1:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
        "rel2:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
        "rel3:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_bytes=330)
    assert len(doc.encode("utf-8")) <= 330
    assert "-- user rel1:0 --" not in doc
    assert "-- user rel2:0 --" not in doc
    # Both guaranteed items (newest owner message "rel3", decision item "dec") survive --
    # `non_guaranteed_owner_tier` never includes an id in `guaranteed_owner_ids`.
    assert "-- user rel3:0 --" in doc
    assert "-- user dec:0 --" in doc


def test_non_owner_floor_of_3_holds_while_non_guaranteed_owner_items_are_evicted() -> None:
    """Coordinator ruling (TRDD-RAEGS1D5, budget floor round 5): "the at-least-3 non-owner
    target stands; its purpose is that the resumed session learns what was DONE". 5 non-owner
    "tool" items, 2 non-guaranteed-owner items ("rel1"/"rel2"), plus the 2 guaranteed slots
    ("newest"/"dec"). `max_bytes=565` (measured -- was 590 before TRDD-EFA4P42B dropped the
    header's `transcript: <path>` line, shrinking the fixed baseline by 25 B and letting "rel2"
    fit at the old threshold): stage (2) evicts non-owner items down to
    EXACTLY the floor (2 of 5 tools gone, 3 remain) and stops there even though the doc still
    does not fit; stage (3) then evicts BOTH "rel1" and "rel2" -- non-guaranteed-owner items,
    sacrificed AHEAD of the floor -- which is enough to reach budget, so stage (4) (the
    below-the-floor continuation) never runs. This is the coordinator's own scenario: owner
    items give way before the floor does."""
    newest = _item("newest:0", "user", "hi there", turn=20, tokens=5)
    dec = _item("dec:0", "user", "policy decision text", turn=0, tokens=5)
    rel1 = _item("rel1:0", "user", "owner background one", turn=1, tokens=5)
    rel2 = _item("rel2:0", "user", "owner background two", turn=2, tokens=5)
    tools = [
        _item(f"tool{i}:0", "tool", f"tool output number {i} " * 3, turn=10 + i, tokens=5)
        for i in range(5)
    ]
    items = [dec, rel1, rel2, *tools, newest]
    scores = {
        "newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
        "rel1:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
        "rel2:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    scores.update({
        it.id: jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header, max_bytes=565)

    assert len(doc.encode("utf-8")) <= 565
    tool_count = sum(1 for i in range(5) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count == jc._NON_OWNER_FLOOR, (
        f"expected exactly the floor ({jc._NON_OWNER_FLOOR}) non-owner items, got {tool_count}"
    )
    # The owner items gave way instead -- both non-guaranteed-owner items are gone.
    assert "-- user rel1:0 --" not in doc
    assert "-- user rel2:0 --" not in doc
    # Both guaranteed slots survive throughout.
    assert "-- user newest:0 --" in doc
    assert "-- user dec:0 --" in doc


def test_non_owner_floor_holds_in_injected_mode_too() -> None:
    """Round 5 review finding (TRDD-RAEGS1D5): the sibling test above calls `compose()` WITHOUT
    `max_item_bytes`, so it only exercises the `max_item_bytes is None` (`evict_key`-sorted)
    construction of `non_owner_evict_order` -- never the `reversed(...)` construction the real
    injected copy (`jev_compact.py compact --inject-out`, `--out` never sets `max_item_bytes` in
    production) actually uses. The floor-stopping while loop itself is shared code either way,
    but without this test the floor was proven correct only empirically, via the real-transcript
    re-render in this task's own report -- never by a fast, isolated unit test on the production
    construction path. Same shape as the sibling test, `max_item_bytes=700` added.

    TRDD-BLGZTHQ9: the injected copy now meets the floor by reservation in `_select_injected`
    (step 2, before the owner tier), not by backstop eviction; `max_bytes=1120` re-pinned
    (measured: exactly 3 tools and no rel item across 1070-1190) because the fixed lines are
    now costed with the count line at its widest."""
    newest = _item("newest:0", "user", "hi there", turn=20, tokens=5)
    dec = _item("dec:0", "user", "policy decision text", turn=0, tokens=5)
    rel1 = _item("rel1:0", "user", "owner background one " * 5, turn=1, tokens=5)
    rel2 = _item("rel2:0", "user", "owner background two " * 5, turn=2, tokens=5)
    tools = [
        _item(f"tool{i}:0", "tool", f"tool output number {i} " * 10, turn=10 + i, tokens=5)
        for i in range(5)
    ]
    items = [dec, rel1, rel2, *tools, newest]
    scores = {
        "newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
        "rel1:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
        "rel2:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    scores.update({
        it.id: jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=1120, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 1120
    tool_count = sum(1 for i in range(5) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count == jc._NON_OWNER_FLOOR, (
        f"expected exactly the floor ({jc._NON_OWNER_FLOOR}) non-owner items, got {tool_count}"
    )
    assert "-- user rel1:0 --" not in doc
    assert "-- user rel2:0 --" not in doc
    assert "-- user newest:0 --" in doc
    assert "-- user dec:0 --" in doc


def test_injected_admission_keeps_more_than_the_floor_when_room_allows() -> None:
    """TRDD-AW4XD53Q: the actual bug this fix targets. Pre-fix, `compose()` admitted the
    injected copy's non-owner (and owner-share-overflow) items against the 8,000-token
    `budget_tokens` gate and then appended ALL of them to `kept_order_list` regardless of the
    injected render's own (much smaller) `max_bytes` -- so the coarse byte BACKSTOP, not any
    admission pass, decided what survived, and on every real transcript it evicted down to
    the exact non-owner floor (3) even when the byte budget had room for more (aabd8b0c
    reached 4/6/4 before this regression). Same item shape as the sibling
    `test_non_owner_floor_holds_in_injected_mode_too` above (which pins the floor itself at a
    TIGHT `max_bytes=1120` -> exactly 3 tools) -- loosened here to `max_bytes=1600` (measured:
    the render is 1547 bytes, fitting BEFORE any backstop stage ever runs -- `compose()`
    returns at its own `len(doc) <= max_bytes` early-return, so stages (1)-(7) never touch
    this document at all; re-pinned from 1500/1491 by TRDD-BLGZTHQ9, whose selection costs
    the count line at its widest). The two non-guaranteed-owner items ("rel1"/"rel2") also
    survive.
    Review finding (TRDD-AW4XD53Q): this specific fixture does NOT by itself discriminate the
    pre-fix code from the fix -- verified directly by running it against a scratch copy of the
    pre-fix eviction-only backstop, which produces the identical 4-tool/rel1/rel2 result here
    (eviction-worst-first-until-fit and admission-best-first-until-budget converge on the same
    final set absent the extra `owner_overflow` noise real transcripts carry). This test pins
    the CURRENT correct behaviour (room allows more than the floor -> more than the floor is
    kept); the actual regression proof against the historical bug is the cached-real-pickle
    re-render in this task's own report (3/3/3 -> 5/6/5), not this synthetic fixture."""
    newest = _item("newest:0", "user", "hi there", turn=20, tokens=5)
    dec = _item("dec:0", "user", "policy decision text", turn=0, tokens=5)
    rel1 = _item("rel1:0", "user", "owner background one " * 5, turn=1, tokens=5)
    rel2 = _item("rel2:0", "user", "owner background two " * 5, turn=2, tokens=5)
    tools = [
        _item(f"tool{i}:0", "tool", f"tool output number {i} " * 10, turn=10 + i, tokens=5)
        for i in range(6)
    ]
    items = [dec, rel1, rel2, *tools, newest]
    scores = {
        "newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                               decision_passed=False),
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
        "rel1:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
        "rel2:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    scores.update({
        it.id: jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=1600, max_item_bytes=700)

    doc_bytes = len(doc.encode("utf-8"))
    assert doc_bytes <= 1600
    assert doc_bytes < 1600, "must fit with room to spare -- proof admission alone did the work"
    tool_count = sum(1 for i in range(6) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count > jc._NON_OWNER_FLOOR, (
        f"expected more than the floor ({jc._NON_OWNER_FLOOR}) non-owner items, got {tool_count}"
    )
    assert "-- user rel1:0 --" in doc
    assert "-- user rel2:0 --" in doc
    assert "-- user newest:0 --" in doc
    assert "-- user dec:0 --" in doc


def test_injected_admission_floor_of_3_holds_with_no_non_guaranteed_owner_items_to_spend() -> None:
    """TRDD-AW4XD53Q: the floor must hold even when the eviction-side backstop's stage (3)
    (non-guaranteed-owner items) has NOTHING to sacrifice -- only the single guaranteed
    "newest" owner item exists here, no other owner items at all. So if the floor still holds
    at a tight budget, backstop stage (3) (buying room from non-guaranteed-owner items) cannot
    be why -- there is nothing there to spend. `max_bytes=1050` (measured after TRDD-BLGZTHQ9:
    stable at exactly 3 tools across the 1030-1250 range; below 1030 the third tool no longer
    fits and `_select_injected` excludes it rather than force-admitting it over budget -- the
    floor is a reservation, never an overrun)."""
    newest = _item("newest:0", "user", "hi", turn=50, tokens=5)
    tools = [
        _item(f"tool{i}:0", "tool", f"tool output number {i} " * 10, turn=10 + i, tokens=5)
        for i in range(6)
    ]
    items = [*tools, newest]
    scores = {"newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                     decision_passed=False)}
    scores.update({
        it.id: jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=1050, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 1050
    tool_count = sum(1 for i in range(6) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count == jc._NON_OWNER_FLOOR, (
        f"expected exactly the floor ({jc._NON_OWNER_FLOOR}) non-owner items, got {tool_count}"
    )
    assert "-- user newest:0 --" in doc
    assert jc._MINIMAL_FIXED_LINE not in doc


def test_injected_admission_with_fewer_than_the_floor_total_keeps_them_all() -> None:
    """TRDD-AW4XD53Q acceptance requirement: a transcript with fewer than `_NON_OWNER_FLOOR`
    non-owner items in total must not error, and must not try to manufacture a floor that
    cannot exist -- both non-owner items here (2, below the floor of 3) are simply admitted
    whole, same as the guaranteed owner item; `max_bytes=900` (measured: fits at 678 bytes,
    comfortable room, so this is about the ADMISSION path admitting everything there is, not
    about a tight-budget edge case -- that is the sibling floor test above)."""
    newest = _item("newest:0", "user", "hi", turn=50, tokens=5)
    tools = [
        _item(f"tool{i}:0", "tool", f"tool output number {i} " * 10, turn=10 + i, tokens=5)
        for i in range(2)
    ]
    items = [*tools, newest]
    scores = {"newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                     decision_passed=False)}
    scores.update({
        it.id: jc.Scores(relevance=0.7, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=900, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 900
    tool_count = sum(1 for i in range(2) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count == 2, f"expected both non-owner items (below the floor), got {tool_count}"
    assert "-- user newest:0 --" in doc


def test_owner_overflow_gets_a_partial_rescue_from_the_leftover_budget() -> None:
    """TRDD-AW4XD53Q review finding: the fix's OTHER necessary half (`owner_overflow`'s retry
    against the leftover budget once the non-owner tier is placed -- see that retry's own
    comment in `compose()`) had zero dedicated coverage; the other new tests only exercise the
    non-owner admission pass. Three non-guaranteed-owner items ("owx0" oldest/turn=1 through
    "owx2" newest/turn=3, so the owner tier's newest-first order tries owx2, then owx1, then
    owx0) are each ~179 measured bytes -- big enough that even ONE exceeds the tiny 40%
    owner share this `max_bytes` implies, so ALL THREE miss the direct owner-share
    admission and land in the owner overflow together; the retry against the leftover (after
    the 2 floor tool items and the guaranteed "newest" are placed) then rescues owx2 and
    owx1 -- proving a PARTIAL rescue, not all-or-nothing -- but owx0 (lowest priority, oldest,
    tried last) still does not fit and stays excluded. Review
    finding (TRDD-AW4XD53Q): this fixture does NOT discriminate the fix from the pre-fix
    unconditional-append code either -- verified directly against a scratch copy of the pre-fix
    logic, which produces the identical (owx0 absent, owx1/owx2 present) result here, because
    the pre-fix backstop's own stage (3) (non-guaranteed-owner eviction) ends up choosing the
    same priority-ordered subset once it has to evict SOMETHING to fit. This test exists to pin
    the RETRY MECHANISM's own contract (a genuine partial rescue, ordered by priority, not
    all-or-nothing) now that it is a real code path, not to reproduce the historical bug.

    TRDD-BLGZTHQ9 re-pin: the retry is now `_select_injected` step 6. The tools used to be
    `"x" * 10`, which the new content gate counts as content-free (10 body chars < 20), so they
    would never be placed; they are short real test summaries now, and "newest" is a real
    sentence (72 B rendered) so that the three owx items (179 B each) all miss the 40% share:
    measured baseline 311 B, so at `max_bytes=870` the room is 559 B, the share 223 B < 72 +
    179, and the floor (2 x 45 B) plus two rescued owx items fill 520 B -- a third does not fit.
    The same outcome holds across max_bytes 831-937."""
    newest = _item("newest:0", "user", "hi, please carry on with the release checklist now",
                   turn=100, tokens=5)
    owner_extra = [
        _item(f"owx{i}:0", "user", f"owner note number {i} " * 8, turn=1 + i, tokens=5)
        for i in range(3)
    ]
    tools = [_item(f"tool{i}:0", "tool", f"12 passed in 0.{i}1s, run {i}", turn=50 + i, tokens=5)
             for i in range(2)]
    items = [*owner_extra, *tools, newest]
    scores = {"newest:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                     decision_passed=False)}
    scores.update({
        it.id: jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in owner_extra
    })
    scores.update({
        it.id: jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=870, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 870
    assert "-- tool tool0:0 --" in doc and "-- tool tool1:0 --" in doc  # the floor was placed
    assert "-- user owx2:0 --" in doc, "highest-priority overflow item must be rescued"
    assert "-- user owx1:0 --" in doc, "the retry is a partial rescue, not a single item"
    assert "-- user owx0:0 --" not in doc, "lowest-priority overflow item still excluded"
    assert "-- user newest:0 --" in doc


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

    items = _ei(path)
    assert len(items) == 1
    assert items[0].kind == "tool"
    assert items[0].text == "<unknown tool>()\norphaned result"


def test_extract_items_survives_a_non_utf8_byte_line(tmp_path: Path) -> None:
    """TRDD-DQXMND59 (V7): a transcript line carrying raw non-UTF-8 bytes (e.g. a subprocess's
    unfiltered raw output landing in a tool_result) must not abort the whole walk -- only that
    line is unreadable, everything around it is still extracted. Fails on HEAD: `path.open(
    encoding="utf-8")` raises `UnicodeDecodeError` on the bad byte, aborting the whole walk."""
    good1 = {"type": "user", "uuid": "u1", "parentUuid": None,
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "first result"}]}}
    good2 = {"type": "user", "uuid": "u2", "parentUuid": "u1",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t2", "content": "second result"}]}}
    path = tmp_path / "badbytes.jsonl"
    with path.open("wb") as fh:
        fh.write((json.dumps(good1) + "\n").encode("utf-8"))
        fh.write(b"\xff\xfe not valid utf-8 at all\n")
        fh.write((json.dumps(good2) + "\n").encode("utf-8"))

    malformed: list[int] = []
    items = _ei(path, malformed_lines=malformed)

    assert [it.id for it in items] == ["u1:0", "u2:0"]
    assert malformed == [2]


def test_extract_items_survives_a_truncated_final_line(tmp_path: Path) -> None:
    """TRDD-DQXMND59 (V7): a session's transcript is written by another still-running process,
    so the LAST line can be a half-written JSON record (killed or read mid-append). It must not
    abort the walk -- earlier lines are still extracted, and the truncated line is counted.
    Fails on HEAD: `json.loads` raises `json.JSONDecodeError`, uncaught, aborting the whole
    `compact` run over the one line most likely to be incomplete."""
    good = {"type": "user", "uuid": "u1", "parentUuid": None,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "a result"}]}}
    path = tmp_path / "truncated.jsonl"
    path.write_text(json.dumps(good) + "\n" + '{"type": "user", "uuid": "u2", "mess')

    malformed: list[int] = []
    items = _ei(path, malformed_lines=malformed)

    assert [it.id for it in items] == ["u1:0"]
    assert malformed == [2]


def test_extract_items_and_compose_survive_a_lone_surrogate_in_tool_result_text(
    tmp_path: Path,
) -> None:
    """TRDD-DQXMND59 follow-up (adversarial review, 2026-09-24, finding C): a lone (unpaired)
    UTF-16 surrogate escape (e.g. an emoji cut in half by a writer's own bug) is VALID JSON --
    `json.loads` parses it into a normal-looking `str` -- so `extract_items` must not (and does
    not) flag the line as malformed. What must not happen is a crash LATER, the first time
    something calls `.encode("utf-8")` on that text -- `compose()`'s own byte-budget accounting
    does this on every item. This is a regression pin: `Item.__post_init__` sanitizes the
    surrogate at construction, so this must NOT crash on either HEAD or before the fix -- it
    pins the fix (`_drop_lone_surrogates`) rather than proving a bug, unlike the other tests in
    this file that fail on HEAD."""
    line = {"type": "user", "uuid": "u1", "parentUuid": None,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "before \ud83d after"}
            ]}}
    path = tmp_path / "surrogate.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    malformed: list[int] = []
    items = _ei(path, malformed_lines=malformed)
    assert malformed == []  # a parseable line, never flagged as damaged

    assert items[0].text.encode("utf-8")  # must not raise UnicodeEncodeError
    scores = {items[0].id: jc.Scores(relevance=1.0, decision=1.0, oversized=False, kept=True,
                                      decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": str(path), "session_key": "s"})
    assert "�" in doc  # the surrogate was replaced, not silently dropped


def test_extract_items_survives_a_line_that_is_not_a_json_object(tmp_path: Path) -> None:
    """TRDD-DQXMND59 follow-up (adversarial review, 2026-09-24, finding D): `json.loads`
    happily parses a line whose top level is a bare number/string/list/null -- not just a
    malformed line. The very next statement, `entry.get("type")`, then raises
    `AttributeError` on anything but a dict, aborting the whole walk. Fails on HEAD."""
    good1 = {"type": "user", "uuid": "u1", "parentUuid": None,
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "first result"}]}}
    good2 = {"type": "user", "uuid": "u2", "parentUuid": "u1",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t2", "content": "second result"}]}}
    path = tmp_path / "not_an_object.jsonl"
    path.write_text(
        json.dumps(good1) + "\n" + "42\n" + json.dumps(good2) + "\n", encoding="utf-8",
    )

    malformed: list[int] = []
    items = _ei(path, malformed_lines=malformed)

    assert [it.id for it in items] == ["u1:0", "u2:0"]
    assert malformed == [2]


def test_extract_items_survives_a_json_line_with_an_oversized_int_literal(tmp_path: Path) -> None:
    """TRDD-DQXMND59 stage 3, item F: CPython 3.11+'s integer-string-conversion length limit
    (PEP 3.11) makes `json.loads` raise a plain `ValueError` -- NOT a `json.JSONDecodeError` --
    for an integer literal longer than 4300 digits (`sys.set_int_max_str_digits`'s default).
    `jsonl_walk.parse_jsonl_line` used to catch only `json.JSONDecodeError`, so this ValueError
    propagated uncaught, aborting the whole walk. Fails on HEAD."""
    good1 = {"type": "user", "uuid": "u1", "parentUuid": None,
             "message": {"role": "user", "content": "before the oversized int"}}
    good2 = {"type": "user", "uuid": "u2", "parentUuid": "u1",
             "message": {"role": "user", "content": "after the oversized int"}}
    oversized_int_line = '{"n": ' + ("9" * 5000) + "}"
    path = tmp_path / "oversized_int.jsonl"
    path.write_text(
        json.dumps(good1) + "\n" + oversized_int_line + "\n" + json.dumps(good2) + "\n",
        encoding="utf-8",
    )

    malformed: list[int] = []
    items = _ei(path, malformed_lines=malformed)

    assert [it.id for it in items] == ["u1:0", "u2:0"]
    assert malformed == [2]


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
    items = _ei(path)
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
    items = _ei(path, segmentation_failures=failures)
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

    items = _ei(path)
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
    items = [it for it in _ei(path) if it.kind == "tool"]
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
    items = [it for it in _ei(path) if it.kind == "tool"]
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
    items = _ei(path)
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

    items = _ei(path)
    assert len(items) == 1
    assert items[0].id == "main1:0"
    assert items[0].text == "the real, main-conversation message"


def test_full_context_path_is_named_by_the_read_first_line() -> None:
    """Card 5 two-renderings (TRDD-RAEGS1D5): the capped rendering's own way back to the
    uncapped document `jev_compact.py compact` composes from the SAME items/scores.
    TRDD-D7RLXAN1: that way back is now the document's FIRST line, "READ FIRST: <path> ...",
    which replaced the old trailing "Full compacted context: ... read it ONLY if" line (the
    two contradict each other; the owner accepted the one-time full read, Q1 2026-09-24)."""
    items = [_item("k:0", "tool", "kept text", turn=0)]
    scores = {"k:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                decision_passed=False)}
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      full_context_path="/tmp/full-compacted.md")

    lines = doc.splitlines()
    assert lines[0].startswith("READ FIRST: /tmp/full-compacted.md holds every message")
    assert "Full compacted context:" not in doc


def test_no_full_context_path_omits_the_read_first_line() -> None:
    """The default (`full_context_path=None`, what `--out`'s own uncapped compose call uses)
    must never grow this line -- it exists only for a SEPARATE capped rendering."""
    items = [_item("k:0", "user", "kept text", turn=0)]
    scores = {"k:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                decision_passed=False)}
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header)

    assert "READ FIRST" not in doc


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
    items = _ei(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}
    assert by_id["sched1:0"].kind == "event"
    assert by_id["sched1:0"].text == "Check nightly build status"


def test_task_notification_becomes_event_and_is_excluded_from_the_digest() -> None:
    items = _ei(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}

    assert by_id["u2:0"].kind == "event"  # not "user" -- see is_human_record
    digest = jc.build_digest(items, [], cap_tokens=4000)
    assert "Background lint check finished" not in digest


def test_bare_owner_control_input_is_kind_control_in_every_branch(tmp_path: Path) -> None:
    """TRDD-D7RLXAN1 test 1 (was TRDD-DZ1KOGAC's "kind event"): a bare "resume"/"continue" typed
    by the owner is content-free, so it must stay out of `kind == "user"` (digest, newest-owner
    pick) -- but it is still the owner's words in the exchange, so it is kind "control"
    (conversation, never scored), not "event" (scored), in the str, text-block and mid-turn
    attachment branches alike. A peer's "resume" is not the owner's and stays "event"."""
    records = [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "resume"}},
        {"type": "user", "uuid": "u2",
         "message": {"role": "user", "content": "please fix the failing test"}},
        {"type": "user", "uuid": "u3",
         "message": {"role": "user", "content": [{"type": "text", "text": "continue"}]}},
        {"type": "attachment", "uuid": "att1", "attachment": {
            "type": "queued_command", "prompt": "resume", "commandMode": "prompt",
            "origin": {"kind": "human"}}},
        {"type": "attachment", "uuid": "att2", "attachment": {
            "type": "queued_command", "prompt": "resume", "commandMode": "prompt",
            "origin": {"kind": "peer"}}},
    ]
    path = tmp_path / "control.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    items = _ei(path)
    by_id = {it.id: it for it in items}
    assert by_id["u1:0"].kind == "control"
    assert by_id["u1:0"].text == "resume"
    assert by_id["u2:0"].kind == "user"
    assert by_id["u3:0"].kind == "control"
    assert by_id["att1:0"].kind == "control"
    assert by_id["att2:0"].kind == "event"


def test_origin_less_legacy_record_still_classified_human() -> None:
    # A pre-`origin` transcript entry (no `origin` key at all) must still fall back to the
    # pre-existing heuristic and come out "human" when it is plainly a real human message.
    entry = {"type": "user", "isMeta": False, "message": {"content": "plain legacy text"}}
    assert jc.is_human_record(entry) is True

    items = _ei(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}
    assert by_id["u4:0"].kind == "user"  # u4 in the fixture carries no `origin` field


def test_heartbeat_turn_skips_assistant_and_tool_items() -> None:
    items = _ei(FIXTURE_ORIGIN)
    ids = [it.id for it in items]

    # hb1 (the fire itself) was already dropped before this fix; the NEW behaviour is that
    # its whole turn -- the Bash tool_use (a2), the tool_result (u3), and the "janitor
    # heartbeat" reply (a3) -- contributes zero items too.
    assert not any(id_.startswith("hb1:") for id_ in ids)
    assert not any(id_.startswith("a2:") for id_ in ids)
    assert not any(id_.startswith("u3:") for id_ in ids)
    assert not any(id_.startswith("a3:") for id_ in ids)


def test_human_turn_after_heartbeat_resumes_extraction() -> None:
    items = _ei(FIXTURE_ORIGIN)
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
    items = _ei(FIXTURE_ORIGIN)
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
    items = _ei(FIXTURE_ORIGIN)
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
    items = _ei(FIXTURE_ORIGIN)
    by_id = {it.id: it for it in items}
    assert by_id["att4:0"].kind == "event"
    assert by_id["att4:0"].text == "Consultation request from a peer agent, not the owner."


def test_mid_turn_attachment_with_list_prompt_does_not_crash(tmp_path: Path) -> None:
    """TRDD-RAEGS1D5 crash fix: `attachment.prompt` is a plain str for a typed-only message but
    a list of content blocks (text + image, same shape as `message.content`) when the owner
    pastes an image alongside text -- measured on the real 183 MB `c8a95d7e` transcript, minimal
    redacted shape reproduced below. Before the fix, `extract_items` crashed with
    `AttributeError: 'list' object has no attribute 'strip'` inside `is_control_input`, which
    assumed `attachment.prompt` is always a str. The text blocks must be joined the same way
    `_tool_result_text` already joins a tool_result's block list -- an image block contributes
    nothing, the text block's text survives."""
    record = {
        "type": "attachment",
        "uuid": "att-list",
        "parentUuid": "p1",
        "isSidechain": False,
        "timestamp": "2026-09-24T00:00:00.000Z",
        "attachment": {
            "type": "queued_command",
            "commandMode": "prompt",
            "origin": {"kind": "human"},
            "prompt": [
                {"type": "text", "text": "what are you talking about??"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                              "data": "Zm9v"}},
            ],
            "timestamp": "2026-09-24T00:00:00.000Z",
        },
    }
    path = tmp_path / "list_prompt.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    items = _ei(path)  # must not raise

    assert len(items) == 1
    assert items[0].kind == "user"
    assert items[0].text == "what are you talking about??"


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
    verbatim-prefix + pointer instead.

    TRDD-U6C3YXEL rewrite: the old last line (`doc.count("[[elided id=k") == len(kept_headers)`)
    encoded the bug -- a k-item excluded for bytes had NO pointer and was not even counted.
    Now the truncation pointers are counted inside "## Kept items" only, and every excluded
    k-item is either pointed at under "## Elided" or counted in the count line."""
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
    kept_section, elided_section = doc.split("\n## Elided\n", 1)
    assert kept_section.count("[[elided id=k") == len(kept_headers)
    elided_ids = [it.id for it in items if f"[[elided id={it.id} " in elided_section]
    assert elided_ids, "the byte-excluded kept items must get pointers now"
    m = re.search(r"\[\[elided: (\d+) more items", elided_section)
    counted = int(m.group(1)) if m else 0
    assert len(kept_headers) + len(elided_ids) + counted == len(items)


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
    budget tight enough to force every degrade step in turn (pointer eviction, then non-owner/
    non-guaranteed-owner item eviction -- per-item truncation already applied at render time --
    then digest truncation) -- and the fixed "pointers expand with" trailer, the model's only
    way back to everything elided, must still survive even this squeeze.

    `max_bytes=2200` (round 4 coordinator order fix, TRDD-RAEGS1D5, up from 600): "k4:0" is the
    newest owner message, `compose()`'s FIRST guaranteed slot -- it is now excluded from every
    eviction stage (only the terminal `_render_minimal_fallback`, which drops this very trailer,
    ever sacrifices it -- see that function's own test coverage). 600 bytes could not hold even
    k4 alone truncated to `NEWEST_OWNER_ITEM_BYTES` (1500) plus the trailer, so it forced the
    terminal stage instead of the ordinary chain this test means to exercise; 2200 is the
    smallest budget (measured) that still empties every pointer, evicts every one of k0-k3, and
    truncates the digest, while leaving enough room for k4's capped rendering and the trailer.

    TRDD-BLGZTHQ9 + TRDD-U6C3YXEL re-pin: `_select_injected` now fits the render by
    construction, so the backstop only runs when the fixed lines plus the unconditional k4
    alone overflow -- `max_bytes=1500` (measured: 1400-1600 all truncate the digest, 1677 B is
    the first untouched fit). k4 renders at the general 700-B cap (the S4 cap never drops
    below `max_item_bytes`); k0-k3 are excluded AND now counted (the old count of 10 omitted
    every byte-stage exclusion), and the e-items ("elided 0"...) are content-free under the
    gate, so they are counted, not pointed at: 14 in all.
    """
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
                      max_bytes=1500, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 1500
    assert "pointers expand with:" in doc
    # The full chain actually fired, not just the byte bound: every pointer dropped to the
    # summary line, k0-k3 (non-guaranteed owner items) excluded, the digest truncated, and the
    # guaranteed k4 item is what survived.
    assert "[[elided id=" not in doc.split("\n## Elided\n", 1)[1]
    assert "[[elided: 14 more items not listed" in doc
    for i in range(4):
        assert f"-- user k{i}:0 --" not in doc
    assert "-- user k4:0 --" in doc
    assert jc._DIGEST_TRUNCATED_NOTE in doc


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

    TRDD-BLGZTHQ9: the tool items used to be 2,550 B each, shown as 700-B prefixes; a tool
    result over its cap is now a pointer, never a prefix, so they are ~500 B here and fit the
    700-B cap whole. Assertions unchanged.
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
        _item(f"t{i}:0", "tool", ("tool output line " * 29) + f" id{i}", turn=100 + i, tokens=5)
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
    # former; "reply:0" proves the latter. TRDD-BLGZTHQ9: the truncated non-owner item is an
    # ASSISTANT item now -- a TOOL item over its cap is never shown as a prefix at all, only as
    # a pointer ("tool:0").
    owner_text = "o" * 600
    reply_text = "r" * 600
    tool_text = "t" * 600
    items = [
        _item("newest:0", "user", "hi", turn=10, tokens=10),
        _item("owner2:0", "user", owner_text, turn=1, tokens=10),
        _item("reply:0", "assistant", reply_text, turn=0, tokens=10),
        _item("tool:0", "tool", tool_text, turn=2, tokens=10),
    ]
    scores = {
        it.id: jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                          decision_passed=False)
        for it in items
    }
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_item_bytes=500, non_owner_item_bytes=100,
    )
    assert owner_text[:500] in doc      # owner item: the general 500-byte cap applies
    assert reply_text[:500] not in doc  # the reply would fit whole at 500...
    assert reply_text[:100] in doc      # ...but only gets the smaller 100-byte non-owner cap
    assert reply_text[:101] not in doc
    assert "-- tool tool:0 --" not in doc  # a tool over its cap: never a prefix...
    assert tool_text[:100] not in doc
    assert "[[elided id=tool:0 " in doc.split("\n## Elided\n", 1)[1]  # ...only a pointer


def test_non_owner_item_bytes_none_falls_back_to_max_item_bytes_for_every_caller() -> None:
    # Backward compatibility: `non_owner_item_bytes` defaults to `None` -- every existing
    # caller/test that never passes it (including `jev_compact.py`'s own `--out` full-copy
    # render, which never sets `max_item_bytes` either) must render a non-owner item exactly
    # as before this parameter existed. TRDD-BLGZTHQ9: an ASSISTANT item, because a tool item
    # over the cap is now pointer-only and so could not show which cap applied.
    reply_text = "r" * 600
    items = [_item("reply:0", "assistant", reply_text, turn=0, tokens=10)]
    scores = {"reply:0": jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                                    decision_passed=False)}
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_item_bytes=500,
    )
    assert reply_text[:500] in doc
    assert reply_text[:501] not in doc


def test_full_copy_uncaps_decision_pointers_while_tool_pointers_stay_capped_and_injected_copy_is_unchanged() -> None:
    """TRDD-RAEGS1D5 (coordinator addition, full-copy decision-pointer uncap): the FULL
    (`--out`) render must name EVERY elided decision-passing owner item by a pointer, with NO
    `max_elided_pointers` cap -- the 258 MB real transcript had 250 decision-passing owner
    items and only 40 pointer slots, so 180 were reachable only via `expand --list --grep`,
    never named in the document a resumed session actually reads. The non-decision elided
    items (here, relevant "tool" items) still respect the pre-existing 40-pointer cap.

    TRDD-U6C3YXEL (part 3 rewritten): the INJECTED copy used to apply ONE `max_elided_pointers`
    cap over every elided item, decision-passing or not. Its decision pointers now come on top
    of that cap (amendment S8), in the ordinary `[[elided id=...]]` format (S2, never the
    compact `id: preview` form); with no `max_bytes` there is no byte share, so all 50 are
    named, bounded only by `_MAX_DECISION_POINTERS`.
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

    # (3) the injected copy: 50 decision pointers on top of the 40 ordinary (tool) ones, all in
    # the ordinary format, never the compact one.
    inject_doc = jc.compose(
        items, scores, budget_tokens=50, header=header,
        max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES,
    )
    inject_elided = inject_doc.split("\n## Elided\n", 1)[1].splitlines()
    for it in decision_items:
        assert any(line.startswith(f"[[elided id={it.id} ") for line in inject_elided), it.id
    tool_pointers = [line for line in inject_elided if line.startswith("[[elided id=tool")]
    assert len(tool_pointers) == jc._MAX_ELIDED_POINTERS
    assert not any(line.startswith(f"{it.id}: ") for it in decision_items for line in inject_elided)
    assert "[[elided: 20 more items not listed" in inject_doc


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


# --- TRDD-RAEGS1D5 (compose() budget floor round 3, coordinator review of round 2:
# reports/compaction-replacement/20260924_013141+0200-jev-inject-room-floor-round2.md finding
# 2) -- `render()`'s own fixed lines embed `transcript_path` up to FOUR times, so a long path
# or a tiny `max_bytes` used to leave the skeleton itself over budget even after every prior
# degrade step ran. ---

_LONG_TRANSCRIPT_PATH = (
    "/Users/emanuelesabetta/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/.claude/projects/"
    "some-very-long-slug-to-push-this-path-well-past-one-hundred-and-fifty-characters-"
    "for-the-test/transcript.jsonl"
)
assert len(_LONG_TRANSCRIPT_PATH) > 150  # the whole point of this fixture


def test_compose_never_exceeds_max_bytes_with_a_long_transcript_path() -> None:
    """Requirements 1+2 (compose() budget floor round 3): across every `max_bytes` value in
    the spec's own range -- including ones far below what the fixed skeleton alone costs once
    `transcript_path` (150+ chars here) is embedded several times -- the rendered document must
    NEVER exceed `max_bytes`, and the newest owner message must appear whenever there is
    genuinely enough room for it (never just because a bigger budget exists in the abstract --
    ten low-priority filler items are evicted first, same priority order as every other
    `max_bytes` backstop test in this file)."""
    newest_owner_text = "THE NEWEST OWNER MESSAGE CONTENT " * 3  # 99 bytes, no newline
    owner = _item("u-newest:0", "user", newest_owner_text, turn=50)
    filler = [
        _item(f"a{i}:0", "assistant", f"filler assistant output line {i} " * 20, turn=i, tokens=5)
        for i in range(10)
    ]
    items = [owner, *filler]
    scores = {
        owner.id: jc.Scores(relevance=0.9, decision=0.3, oversized=False, kept=True,
                             decision_passed=False),
        **{it.id: jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False)
           for it in filler},
    }
    header = {"transcript_path": _LONG_TRANSCRIPT_PATH, "session_key": "s"}  # no digest

    for max_bytes in (1, 50, 200, 800, 2000, 6000):
        doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                          max_bytes=max_bytes, max_item_bytes=700)
        assert len(doc.encode("utf-8")) <= max_bytes, f"max_bytes={max_bytes} overflowed"

    # Below the fixed skeleton's own cost (measured: 618 bytes for this path with nothing
    # kept), there is no room for owner content at all -- `""` is correct, not a bug.
    tiny_doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                           max_bytes=1, max_item_bytes=700)
    assert tiny_doc == ""

    # At 200 bytes the fixed skeleton (618) still does not fit -- this exercises the NEW
    # minimal-fallback stage specifically -- yet a truncated prefix of the newest owner
    # message still comes through, with its id still reachable.
    mid_doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                          max_bytes=200, max_item_bytes=700)
    assert "THE NEWEST" in mid_doc
    assert "u-newest:0" in mid_doc

    # At 800/2000/6000 the ordinary render (not the fallback) has room for the item whole.
    for max_bytes in (800, 2000, 6000):
        doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                          max_bytes=max_bytes, max_item_bytes=700)
        assert newest_owner_text in doc, f"max_bytes={max_bytes} lost the newest owner message"


def test_normal_budget_renders_unchanged_by_the_new_minimal_fallback_stage() -> None:
    """Requirement 3: a budget generous enough that the pre-existing degrade steps already fit
    must render EXACTLY as before this fix -- the new minimal-fallback stage only replaces the
    document once everything above it still overflows `max_bytes`. Pins the exact byte count
    and exact text of a small, ordinary `compose()` call so a future edit to the new stage
    cannot silently start firing on inputs that never needed it."""
    item = _item("k1:0", "user", "kept text", turn=1, tokens=5)
    elided = _item("e1:0", "assistant", "elided text", turn=2, tokens=5)
    items = [item, elided]
    scores = {
        item.id: jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                            decision_passed=False),
        elided.id: jc.Scores(relevance=0.1, decision=0.0, oversized=False, kept=False,
                              decision_passed=False),
    }
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s", "digest": "the digest"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header, max_bytes=6000)

    # TRDD-EFA4P42B: was 334 with a "transcript: <path>" header line -- that line was the
    # second of four `transcript_path` copies in the render and is gone now (the trailer below
    # is the only place the path still appears).
    assert len(doc.encode("utf-8")) == 309  # pinned -- must not move for a normal-budget call
    assert doc == (
        "# Compacted context (Jev compaction)\n"
        "session: s\n"
        "\n"
        "## Digest\n"
        "the digest\n"
        "\n"
        "usage: tokens=? cost=?\n"
        "\n"
        "## Kept items\n"
        "-- user k1:0 --\n"
        "kept text\n"
        "\n"
        "## Elided\n"
        '[[elided id=e1:0 tokens=5 "elided text"]]\n'
        "\n"
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        "expand --transcript /tmp/t.jsonl <id>"
    )


def test_injected_render_prints_the_transcript_path_exactly_once_and_trailer_is_last() -> None:
    """TRDD-EFA4P42B: the injected copy used to embed `transcript_path` up to FOUR times
    (header, the "N more items" line, the "Full compacted context" line, the trailer) --
    ~580 B of a ~1,360 B fixed baseline inside a ~3 KB injected room. Only the trailer may
    carry it now (`external_clear._split_trailing_pointer_line` depends on that line being
    last), and every other fixed line must still say what it needs to without repeating it."""
    path = "/Users/x/project/.claude/transcript.jsonl"
    kept = _item("k1:0", "user", "kept text", turn=1, tokens=5)
    elided = [
        _item(f"e{i}:0", "assistant", f"elided text {i}", turn=i + 2, tokens=5)
        for i in range(3)
    ]
    items = [kept, *elided]
    scores = {
        kept.id: jc.Scores(relevance=0.9, decision=0.0, oversized=False, kept=True,
                            decision_passed=False),
        **{
            it.id: jc.Scores(relevance=0.1, decision=0.0, oversized=False, kept=False,
                              decision_passed=False)
            for it in elided
        },
    }
    header = {"transcript_path": path, "session_key": "s", "digest": ""}
    doc = jc.compose(
        items, scores, budget_tokens=8000, header=header, max_bytes=2000,
        max_item_bytes=700, non_owner_item_bytes=350, max_elided_pointers=1,
        full_context_path="/tmp/full.md",
    )

    assert doc.count(path) == 1, doc
    lines = doc.rstrip("\n").splitlines()
    assert lines[-1].startswith("pointers expand with:")
    assert path in lines[-1]


def test_render_minimal_fallback_boundary_never_exceeds_and_drops_the_pointer_first() -> None:
    """Whitebox on the new `_render_minimal_fallback` itself (TRDD-RAEGS1D5, budget floor
    round 3): pins the exact byte boundary where even the constant-size marker line stops
    fitting (`""`), the boundary where it fits but a pointer/body would not (marker alone), and
    confirms the combined output is re-measured, never just trusted from the room arithmetic."""
    fixed_bytes = len(jc._MINIMAL_FIXED_LINE.encode("utf-8"))
    owner = _item("u1:0", "user", "some owner text " * 10, turn=1)

    assert jc._render_minimal_fallback(owner, fixed_bytes - 1) == ""
    assert jc._render_minimal_fallback(owner, fixed_bytes) == jc._MINIMAL_FIXED_LINE
    assert jc._render_minimal_fallback(None, 10_000) == jc._MINIMAL_FIXED_LINE

    generous = jc._render_minimal_fallback(owner, 10_000)
    assert generous.startswith(jc._MINIMAL_FIXED_LINE + "\n")
    assert "some owner text" in generous
    assert f"id={owner.id}" in generous  # the pointer -- the id survives even this degrade
    assert len(generous.encode("utf-8")) <= 10_000

    # Adversarial-review finding (round 3): the two boundary cases above only cover `room < 0`
    # (two cases) and `room` generously positive -- neither pins the exact `room == 0`/`room ==
    # 1` transition, precisely where an off-by-one in the "-1 -1" separator accounting would
    # hide. `room == 0` means exactly enough space for the fixed line, both "\n" separators and
    # the pointer, with a ZERO-byte truncated body between them; `room == 1` is the first byte
    # that actually shows.
    pointer = jc._format_pointer(owner)
    pointer_bytes = len(pointer.encode("utf-8"))
    room0_max_bytes = fixed_bytes + 1 + pointer_bytes + 1  # room == 0
    room0 = jc._render_minimal_fallback(owner, room0_max_bytes)
    assert room0 == f"{jc._MINIMAL_FIXED_LINE}\n\n{pointer}"
    assert len(room0.encode("utf-8")) == room0_max_bytes

    room1 = jc._render_minimal_fallback(owner, room0_max_bytes + 1)  # room == 1
    assert room1 == f"{jc._MINIMAL_FIXED_LINE}\n{owner.text[0]}\n{pointer}"
    assert len(room1.encode("utf-8")) == room0_max_bytes + 1


# --- TRDD-DZ1KOGAC follow-up: compose() must never seat a demoted "resume"/"continue" in the
# guaranteed newest-owner slot, regardless of whether a real owner instruction exists alongside
# it or is the transcript's only owner-typed record. `extract_items` already demotes a bare
# control word from kind "user" to kind "event" (see the docstring on
# `test_newest_owner_item_is_guaranteed_even_when_jev_scored_it_below_threshold` above); these
# two tests pin `compose()`'s OWN side of that contract directly, at the `Item` level, so a
# future change to the guaranteed-slot selection cannot silently start treating "event" like
# "user" again.


def test_guaranteed_owner_slot_shows_the_real_instruction_not_a_later_demoted_resume() -> None:
    # A real owner instruction, followed chronologically by a bare "resume" (already demoted to
    # kind "event" by extract_items -- built here directly as an Item, the way extract_items
    # would produce it, rather than round-tripped through a fixture file). "resume" must never
    # occupy the guaranteed newest-owner slot, and must never render as a "-- user --" item at
    # all: kind "event" items are outside `kind == "user"` scoring/rendering entirely.
    items = [
        _item("instr:0", "user", "please rename the config field to max_retries", turn=0,
              tokens=20),
        _item("resume:0", "event", "resume", turn=1, tokens=5),
    ]
    scores = {
        "instr:0": jc.Scores(relevance=0.6, decision=0.0, oversized=False, kept=True,
                              decision_passed=False),
        "resume:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                               decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_bytes=6000, max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES)
    assert "-- user instr:0 --" in doc  # the real instruction takes the guaranteed slot
    assert "-- user resume:0 --" not in doc  # never rendered as a user item
    assert "-- event resume:0 --" not in doc  # and events are not inlined at all here


def test_compose_still_valid_when_the_only_owner_typed_record_is_a_bare_resume() -> None:
    # A transcript whose only owner-typed record is a bare "resume" has, by the time it reaches
    # `compose()`, zero kind=="user" items at all (extract_items demoted it to "event"). compose
    # must not crash or produce an oversized/invalid document -- it just has no guaranteed
    # owner slot to fill -- and "resume" must never surface as a "-- user --" item.
    items = [
        _item("resume:0", "event", "resume", turn=0, tokens=5),
        _item("tool:0", "tool", "some unrelated tool output", turn=1, tokens=20),
    ]
    scores = {
        "resume:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                               decision_passed=False),
        "tool:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                             decision_passed=False),
    }
    max_bytes = 6000
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_bytes=max_bytes, max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES)
    assert len(doc.encode("utf-8")) <= max_bytes
    assert "-- user resume:0 --" not in doc
    assert "-- user " not in doc  # no owner item exists to render at all


# --- TRDD-BLGZTHQ9 + TRDD-U6C3YXEL: the injected copy's one reservation-first selection
# (`_select_injected`). Measured defects on three real injected copies: 3/3/4 kept tool items
# were truncated prefixes, 1/1/4 kept non-owner items were content-free stubs, 0 decision
# pointers while 21/22/7 decision-passing owner messages were invisible, and a count line that
# omitted every byte-stage exclusion. ---

_H = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
# An informative non-owner line: over the 80-char content gate (86 body chars for i < 10).
_WORK = ("Step {i}: re-rendered the cached transcripts, compared the full copies byte for byte, "
         "and all matched.")


def _scores(rel: float, *, kept: bool = True, decision: bool = False) -> jc.Scores:
    return jc.Scores(relevance=rel, decision=0.9 if decision else 0.0, oversized=False,
                     kept=kept, decision_passed=decision)


def _count_line_n(doc: str) -> int:
    m = re.search(r"\[\[elided: (\d+) more items not listed", doc)
    return int(m.group(1)) if m else 0


def _shown_ids(doc: str, items: list[jc.Item]) -> tuple[set[str], set[str]]:
    """(ids shown inline, ids pointed at under "## Elided") -- a truncated kept item's own
    pointer line sits inside "## Kept items" and does not count as an elided pointer."""
    kept_section, elided_section = doc.split("\n## Elided\n", 1)
    inline = {it.id for it in items if f"-- {it.kind} {it.id} --" in kept_section}
    pointed = {it.id for it in items if f"[[elided id={it.id} " in elided_section}
    return inline, pointed


def test_select_injected_reserves_floor_and_decision_pointers_before_the_owner_tier() -> None:
    """The fill order on hand-made exact costs (available=1000): the guaranteed item (100),
    the non-owner floor (3 x 150), then decision-pointer reservations (3 x 50, newest first),
    THEN the owner tier -- whose one admission (the newest decision item, 300) refunds its own
    50-B reservation. The other two decision items stay pointers, and the 4th non-owner item
    (150 inline, 60 as a pointer) fits neither way: it is counted. Total 950 <= 1000."""
    def cand(id_: str, kind: jc.ItemKind, turn: int, score: float, inline: int, pointer: int,
             *, decision: bool = False, guaranteed: bool = False) -> jc._InjectCandidate:
        return jc._InjectCandidate(id=id_, kind=kind, turn=turn, score=score,
                                   decision_passed=decision, guaranteed=guaranteed,
                                   inline_cost=inline, pointer_cost=pointer,
                                   pointer_eligible=True)

    cands = [
        cand("g", "user", 100, 0.9, 100, 50, guaranteed=True),
        *(cand(f"n{i}", "assistant", 10 + i, 0.9 - i / 10, 150, 60) for i in range(4)),
        *(cand(f"d{i}", "user", 20 + i, 0.9, 300, 50, decision=True) for i in range(3)),
    ]
    sel = jc._select_injected(cands, available=1000, max_pointers=12)

    assert sel.kept == ["g", "d2", "n0", "n1", "n2"]
    assert sel.decision_pointers == ["d1", "d0"]  # newest first; d2's reservation refunded
    assert sel.pointers == []
    assert sel.hidden == 1  # n3
    costs = {c.id: c for c in cands}
    total = (sum(costs[i].inline_cost or 0 for i in sel.kept)
             + sum(costs[i].pointer_cost for i in sel.decision_pointers))
    assert total == 950


def test_select_injected_holds_the_decision_reserve_when_a_reserved_item_goes_inline() -> None:
    """TRDD-U6C3YXEL (D2): the reserve always names the newest excluded decision items up to
    its limit -- a reserved item may go inline only if the next-newest one can take its pointer
    place. Hand costs, available=880: the limit is 220 B (4 pointers of 50); ten decision items
    at 200 B inline. Held, d9 and d8 go inline and d7..d4 keep 4 pointers. Refunding a
    reserved item's bytes to general admission (the design's literal rule) ended with 1
    pointer here; re-reserving only from leftover room ended with 3 (d7 inline, no room left
    for d3's pointer)."""
    cands = [
        jc._InjectCandidate(id="g", kind="user", turn=100, score=0.9, decision_passed=False,
                            guaranteed=True, inline_cost=100, pointer_cost=50,
                            pointer_eligible=True),
        *(
            jc._InjectCandidate(id=f"d{i}", kind="user", turn=i, score=0.9, decision_passed=True,
                                guaranteed=False, inline_cost=200, pointer_cost=50,
                                pointer_eligible=True)
            for i in range(10)
        ),
    ]
    sel = jc._select_injected(cands, available=880, max_pointers=12)

    assert sel.kept == ["g", "d9", "d8"]
    assert sel.decision_pointers == ["d7", "d6", "d5", "d4"]
    assert sel.hidden == 4  # d3..d0, past the reserve's limit


def test_injected_tool_item_over_its_cap_is_a_pointer_never_a_prefix() -> None:
    """TRDD-BLGZTHQ9: a tool result over `non_owner_item_bytes` used to render as a 350-B
    verbatim prefix plus a pointer -- a few lines of a diff for 3-4x the bytes of the pointer,
    whose preview already says what it is. It is now pointer-only; a tool result that fits the
    cap is still shown whole."""
    big_text = "".join(f"-    old line {i} of the patched function\n" for i in range(20))
    small_text = "commit 8a623a28: fix the injected selection, all 194 tests green"
    items = [
        _item("big:0", "tool", big_text, turn=1),
        _item("small:0", "tool", small_text, turn=2),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert "-- tool big:0 --" not in doc
    assert "old line 1 of" not in doc  # not even the first lines as a prefix
    assert "[[elided id=big:0 " in doc.split("\n## Elided\n", 1)[1]
    assert f"-- tool small:0 --\n{small_text}\n" in doc


def test_injected_content_free_non_owner_items_are_neither_inlined_nor_pointed() -> None:
    """TRDD-BLGZTHQ9 content gate: whole-but-empty non-owner items won inline slots on
    relevance alone in the real injected copies -- a bare `resume` event, a Read result that is
    just a heading (`57\\t## The open work`), a task notification that is only its wrapper. Each
    is now counted, never inlined and never pointed at (a content-free pointer is content-free
    too); an informative item beside them is still inlined."""
    prose = _WORK.format(i=0)
    items = [
        _item("resume:0", "event", "resume", turn=1),
        _item("heading:0", "tool", "57\t## The open work\n58\t", turn=2),
        _item("notif:0", "event",
              "<task-notification><status>done</status></task-notification>", turn=3),
        _item("prose:0", "assistant", prose, turn=4),
        _item("newest:0", "user", "hi", turn=5),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    for gated in ("resume:0", "heading:0", "notif:0"):
        assert gated not in doc, f"{gated} must be neither inlined nor pointed at"
    assert f"-- assistant prose:0 --\n{prose}\n" in doc
    assert _count_line_n(doc) == 3
    assert jc._body_chars(prose) >= jc._INJECT_MIN_BODY_CHARS  # fixture sanity


def test_injected_excluded_decision_items_get_newest_first_pointers_and_the_count_is_exact() -> None:
    """TRDD-U6C3YXEL: excluded decision-passing owner messages had NO pointer in the injected
    copy (21/22/7 on the three real transcripts) and the count line omitted them, so the resumed
    session could not tell they existed. The NEWEST excluded ones now get pointers up to
    `_INJECT_DECISION_POINTER_SHARE`, the rest are counted, and the count line's N is exactly
    `len(items) - shown`. The newest decision items also go inline through the owner tier and
    its overflow retry; each such admission refunds its reservation, which must go to the next-
    newest excluded decision item -- not to a further inline item (measured: 0 decision
    pointers on this fixture when the refunds were spent that way)."""
    decisions = [
        _item(f"dec{i}:0", "user", f"decision {i}: always run the full gate before publishing. " * 5,
              turn=i)
        for i in range(20)
    ]
    work = [_item(f"work{i}:0", "assistant", _WORK.format(i=i), turn=30 + i) for i in range(3)]
    newest = _item("newest:0", "user", "carry on", turn=50)
    items = [*decisions, *work, newest]
    scores = {it.id: _scores(0.9, decision=it.id.startswith("dec")) for it in items}
    doc = jc.compose(items, scores, budget_tokens=80000, header=_H, max_bytes=3000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert len(doc.encode("utf-8")) <= 3000
    inline, pointed = _shown_ids(doc, items)
    excluded = [it for it in decisions if it.id not in inline]
    pointed_dec = [it for it in excluded if it.id in pointed]
    counted_dec = [it for it in excluded if it.id not in pointed]
    assert pointed_dec, "excluded decision items must get pointers"
    assert counted_dec, "past the share, the rest must be counted (fixture sanity)"
    assert min(it.turn for it in pointed_dec) > max(it.turn for it in counted_dec)  # newest first
    assert _count_line_n(doc) == len(items) - len(inline) - len(pointed)


def test_injected_selection_is_exact_including_decision_pointers() -> None:
    """TRDD-BLGZTHQ9 exactness (amendment S9: with decision pointers in the fixture): the render
    is the fixed lines plus the exact cost of every selected item, so a `max_bytes` equal to the
    unconstrained render shows everything, and one byte less drops exactly one selection -- the
    last-reserved decision pointer -- with no backstop stage running. A gated "resume" event
    keeps the count line present (N=1 -> N=2, same width) so the fixed lines never change."""
    newest = _item("newest:0", "user", "carry on", turn=50, tokens=5)
    dec_new = _item("decnew:0", "user", "never push; publish only via publish.py", turn=40, tokens=5)
    dec_old = [_item(f"dec{t}:0", "user", f"rule {t}", turn=t, tokens=1000) for t in (10, 20)]
    work = [_item(f"work{i}:0", "assistant", _WORK.format(i=i), turn=30 + i, tokens=5)
            for i in range(3)]
    resume = _item("resume:0", "event", "resume", turn=45, tokens=5)
    items = [*dec_old, *work, dec_new, resume, newest]
    scores = {it.id: _scores(0.9, decision=it.id.startswith("dec")) for it in items}
    # budget_tokens=100: the two 1000-token decision items leave the token stage, so they can
    # only ever be pointers (amendment S1); dec_new is the guaranteed newest decision item.
    kwargs: dict[str, Any] = {"budget_tokens": 100, "header": _H, "max_item_bytes": 700,
                              "non_owner_item_bytes": 350}

    full = jc.compose(items, scores, max_bytes=10**6, **kwargs)
    inline, pointed = _shown_ids(full, items)
    assert inline == {"newest:0", "decnew:0", "work0:0", "work1:0", "work2:0"}
    assert pointed == {"dec10:0", "dec20:0"}
    assert {p.id for p in find_pointers(full)} == pointed  # ordinary, parseable format (S2)
    exact = len(full.encode("utf-8"))

    assert jc.compose(items, scores, max_bytes=exact, **kwargs) == full
    tight = jc.compose(items, scores, max_bytes=exact - 1, **kwargs)
    assert _shown_ids(tight, items) == (inline, {"dec20:0"})  # newest reservation kept
    assert len(tight.encode("utf-8")) == exact - len(jc._format_pointer(dec_old[0]).encode()) - 1
    assert _count_line_n(tight) == 2
    assert jc._DIGEST_TRUNCATED_NOTE not in tight and jc._MINIMAL_FIXED_LINE not in tight


def test_injected_gate_keeps_a_short_whole_tool_result_but_not_a_heading_stub() -> None:
    """Amendment S3 thresholds, both sides: a WHOLE tool result needs only 20 body chars, so a
    real `pytest -q` result ("...  [100%]" then "3 passed in 0.18s", 23 chars) is shown; a Read
    result that is just a heading (17 chars) is not. Prose and events need 80: a 60-char
    assistant line is gated even though a tool result of the same length would pass."""
    pytest_out = "...                                                          [100%]\n3 passed in 0.18s"
    reply = "Looked at the diff; it is fine and ready to go ahead. Done."
    items = [
        _item("pytest:0", "tool", pytest_out, turn=1),
        _item("heading:0", "tool", "57\t## The open work\n58\t", turn=2),
        _item("reply:0", "assistant", reply, turn=3),
        _item("newest:0", "user", "hi", turn=4),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert f"-- tool pytest:0 --\n{pytest_out}\n" in doc
    assert "heading:0" not in doc
    assert "reply:0" not in doc
    assert jc._body_chars(pytest_out) == 23 and jc._body_chars(reply) < 80  # fixture sanity


def test_injected_small_jev_kept_tool_results_render_inline_beside_a_large_admitted_one() -> None:
    """TRDD-U6C3YXEL amendment S1, re-read 2026-09-24: the `budget_tokens` stage fills its budget
    by score, so one large tool result wins it and the smaller results Jev also kept are skipped;
    the injected copy can only point at the large one (a tool over its cap is never a prefix).
    With S1 read as the token stage's set nothing was inline (d30bf250: 0 tool/event items). A
    non-owner item Jev kept may now be inline, so the small results are shown."""
    big = _item("big:0", "tool", "Bash({})\n" + "".join(
        f"line {i}: a real row of the command's output\n" for i in range(100)), turn=1, tokens=900)
    small = [_item(f"small{i}:0", "tool", f"Bash({{}})\n{i}{i} passed in 0.{i}s, all green",
                   turn=2 + i, tokens=50) for i in range(3)]
    newest = _item("newest:0", "user", "hi", turn=10, tokens=2)
    items = [big, *small, newest]
    scores = {"big:0": _scores(0.95), "newest:0": _scores(0.9),
              **{it.id: _scores(0.8) for it in small}}
    doc = jc.compose(items, scores, budget_tokens=920, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    inline, pointed = _shown_ids(doc, items)
    assert {it.id for it in small} <= inline
    assert "big:0" not in inline and "big:0" in pointed
    # Precondition: the token stage really skipped the small ones (900 + 50 > 920).
    full = jc.compose(items, scores, budget_tokens=920, header=_H)
    assert _shown_ids(full, items)[0] == {"big:0", "newest:0"}


def test_injected_non_owner_items_jev_did_not_keep_or_marked_oversized_stay_pointer_only() -> None:
    """TRDD-U6C3YXEL amendment S1 negative case: `jev_kept = s.kept and not s.oversized` gates a
    non-owner item's inline eligibility in the injected copy -- a small tool result Jev did NOT
    keep (kept=False) and one it marked oversized (oversized=True) must stay pointer-only even
    with an enormous room, because the gate is `jev_kept`, not membership in the token stage's
    `kept_ids` (the pre-S1 read S1 replaced)."""
    not_kept = _item("notkept:0", "tool", "Bash({})\n42 passed in 0.1s, all green", turn=1, tokens=50)
    oversized = _item("oversz:0", "tool", "Bash({})\n7 passed in 0.2s, all green", turn=2, tokens=50)
    newest = _item("newest:0", "user", "hi", turn=3, tokens=2)
    items = [not_kept, oversized, newest]
    scores = {
        "notkept:0": _scores(0.9, kept=False),
        "oversz:0": jc.Scores(relevance=0.9, decision=0.0, oversized=True, kept=True,
                              decision_passed=False),
        "newest:0": _scores(0.9),
    }
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=10**6,
                     max_item_bytes=700, non_owner_item_bytes=350)

    inline, pointed = _shown_ids(doc, items)
    assert "notkept:0" not in inline and "oversz:0" not in inline
    assert "notkept:0" in pointed and "oversz:0" in pointed


def test_injected_whole_tool_call_with_no_result_fails_the_gate() -> None:
    """TRDD-BLGZTHQ9 addendum (2026-09-24): the 20-char whole-tool-result gate must count only
    the RESULT part -- a bare call echo (`_segment_tool_result`'s synthetic `name(input)` first
    line) with no result at all must not pass on its own name and arguments."""
    call_echo_only = 'ToolSearch({"max_results": 5, "query": "advisor design"})'
    items = [
        _item("echo:0", "tool", call_echo_only, turn=1),
        _item("newest:0", "user", "hi", turn=2),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert "echo:0" not in doc
    assert jc._tool_result_part(call_echo_only) == ""


_TASK_NOTIFICATION_WITH_RESULT = (
    "<task-notification>\n"
    "<task-id>ae5ce5f0fb9b8f119</task-id>\n"
    "<tool-use-id>toolu_01A5LkrwmwkhtCU5fGNAoMXH</tool-use-id>\n"
    "<output-file>/tmp/tasks/ae5ce5f0fb9b8f119.output</output-file>\n"
    "<status>completed</status>\n"
    '<summary>Agent "Review commit 4b479214" finished</summary>\n'
    "<note>A task-notification fires each time this agent stops.</note>\n"
    "<result>ADVERSARIAL-REVIEW\n\n"
    "This reviews commit 4b479214: the stopgap has probably been overtaken, its gate would now "
    "read a switch as a renewal. Fix: gate Step 1 on \"no auto: switched line since 07:16\".</result>\n"
    "<usage><subagent_tokens>239883</subagent_tokens></usage>\n"
    "</task-notification>"
)

_TASK_NOTIFICATION_METADATA_ONLY = (
    "<task-notification>\n"
    "<task-id>a21335f6afcef1aae</task-id>\n"
    "<tool-use-id>toolu_01Xyz</tool-use-id>\n"
    "<output-file>/tmp/tasks/a21335f6afcef1aae.output</output-file>\n"
    "<status>completed</status>\n"
    "</task-notification>"
)


def test_injected_task_notification_with_a_result_shows_the_excerpt_not_the_wrapper() -> None:
    """Coordinator addendum (2026-09-24): a `<task-notification>` with a real `<summary>`/
    `<result>` is shown -- but only the excerpt (verbatim `<summary>`/`<result>` substrings), an
    excerpt label, and the pointer, never the `<task-id>`/`<tool-use-id>`/`<output-file>`/
    `<status>` metadata that gave a content-free notification the same eligibility before this
    fix."""
    items = [
        _item("notif:0", "event", _TASK_NOTIFICATION_WITH_RESULT, turn=1),
        _item("newest:0", "user", "hi", turn=2),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=1500, non_owner_item_bytes=900)

    assert '<summary>Agent "Review commit 4b479214" finished</summary>' in doc
    assert "ADVERSARIAL-REVIEW" in doc
    assert "(excerpt: summary and result)" in doc
    assert "[[elided id=notif:0 " in doc  # the pointer always follows, even when shown
    assert "<task-id>" not in doc
    assert "<tool-use-id>" not in doc
    assert "<output-file>" not in doc
    assert "<status>completed</status>" not in doc
    assert "<usage>" not in doc


def test_injected_task_notification_with_only_metadata_is_neither_shown_nor_pointed_at() -> None:
    """Coordinator addendum: a `<task-notification>` whose `<summary>`/`<result>` are absent
    (only ids/path/status/"completed") is content-free -- neither inlined nor pointed at, only
    counted, exactly like any other content-free non-owner item (measured gap: this cleared the
    old 80-char gate on the wrapper alone on 3 of 3 holdout-transcript items, TRDD-BLGZTHQ9)."""
    items = [
        _item("notif:0", "event", _TASK_NOTIFICATION_METADATA_ONLY, turn=1),
        _item("newest:0", "user", "hi", turn=2),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=1500, non_owner_item_bytes=900)

    assert "notif:0" not in doc
    assert "<task-id>" not in doc
    # counted, not silently dropped: the "N more items not listed" count line includes it.
    assert "[[elided: 1 more items not listed" in doc
    assert jc._task_notification_excerpt(_TASK_NOTIFICATION_METADATA_ONLY) == ""


def _notification_with(summary: str, result_line: str) -> str:
    return (
        "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n"
        f"<summary>{summary}</summary>\n<result>{result_line}</result>\n</task-notification>"
    )


def _notification_body_cap(it: jc.Item, cap: int) -> int:
    """The excerpt room `_notification_block` leaves under `cap` (label + pointer reserved)."""
    return cap - len(f"\n{jc._NOTIFICATION_LABEL}\n{jc._format_pointer(it)}".encode("utf-8"))


def _equal_cost_control(notif: jc.Item, id_: str, turn: int) -> jc.Item:
    """An assistant prose item that passes the 80-char gate and costs EXACTLY what `notif`'s
    inline block costs under the 350-B non-owner cap -- so any budget effect it has at a given
    `max_bytes` is the effect the notification's own inline block had before F1b."""
    cost = jc._notification_block(notif, 350)[1]
    room = cost - len(f"-- assistant {id_} --\n".encode("utf-8")) - 1
    text = ("Control: a real finding about the cached transcripts and their full copies. " * 4)[:room]
    ctrl = _item(id_, "assistant", text, turn=turn)
    assert jc._inline_cost(ctrl, 350) == cost
    assert jc._body_chars(text) >= jc._INJECT_MIN_BODY_CHARS
    return ctrl


_TITLE_ONLY_NOTIFICATION = _notification_with('Agent "Fix item extraction" finished', "finding " * 60)


def test_injected_notification_whose_shown_excerpt_is_only_a_title_is_pointed_not_inlined() -> None:
    """TRDD-BLGZTHQ9 F1b: the inline gate measures the RENDERED excerpt. A short summary plus a
    result whose one long line cannot fit the room left after the label and pointer renders as
    the title alone -- measured on fd5cc3e0, 4 of 6 inline notifications were exactly this. The
    full excerpt passes the gate, so the item is still pointed at; it is never shown inline."""
    notif = _item("notif:0", "event", _TITLE_ONLY_NOTIFICATION, turn=1)
    newest = _item("newest:0", "user", "hi", turn=3)
    summary_line, result_line = jc._task_notification_excerpt(_TITLE_ONLY_NOTIFICATION).split("\n")
    body_cap = _notification_body_cap(notif, 350)
    # Precondition 1: only the title fits the cut, and the title alone fails the gate -- while
    # the full excerpt passes it (so the item stays pointer-eligible).
    assert len(summary_line.encode("utf-8")) <= body_cap < len(
        f"{summary_line}\n{result_line}".encode("utf-8"))
    assert jc._body_chars(summary_line) < jc._INJECT_MIN_BODY_CHARS
    assert jc._body_chars(f"{summary_line}\n{result_line}") >= jc._INJECT_MIN_BODY_CHARS
    kw: dict[str, Any] = dict(budget_tokens=8000, header=_H, max_bytes=4000, max_item_bytes=700,
                              non_owner_item_bytes=350)
    # Precondition 2: the room is not the reason -- an item costing exactly the notification's
    # inline block IS shown inline at this budget (as the notification was before F1b).
    ctrl = _equal_cost_control(notif, "ctrl:0", turn=1)
    ctrl_doc = jc.compose([ctrl, newest], {"ctrl:0": _scores(0.9), "newest:0": _scores(0.9)}, **kw)
    assert "ctrl:0" in _shown_ids(ctrl_doc, [ctrl])[0]

    items = [notif, newest]
    doc = jc.compose(items, {it.id: _scores(0.9) for it in items}, **kw)

    inline, pointed = _shown_ids(doc, items)
    assert "notif:0" not in inline
    assert "notif:0" in pointed


def test_injected_notification_label_calls_a_heading_only_result_summary() -> None:
    """TRDD-BLGZTHQ9 F1b: the label is a claim about what is shown. A summary long enough to pass
    the gate on its own, and a result cut down to its bare `ADVERSARIAL-REVIEW` heading (fd5cc3e0
    `f396cd9b`/`a0d1f47f`), is labelled "(excerpt: summary)" -- a heading is not a result. The
    constant label claimed "(excerpt: summary and result)" here."""
    summary = ("Agent \"Re-render the four cached transcripts and compare the full copies byte "
               "for byte against the committed baseline\" finished")
    text = _notification_with(summary, "ADVERSARIAL-REVIEW\n\n" + "finding " * 60)
    items = [
        _item("notif:0", "event", text, turn=1),
        _item("newest:0", "user", "hi", turn=2),
    ]
    excerpt = jc._task_notification_excerpt(text)
    shown = jc._truncate_prefix_bytes(excerpt, _notification_body_cap(items[0], 350))
    # Precondition: the cut keeps the summary and the heading, and nothing of the finding.
    assert shown.rstrip().endswith("<result>ADVERSARIAL-REVIEW")
    assert jc._body_chars(shown) >= jc._INJECT_MIN_BODY_CHARS  # so it is still shown inline
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    inline, _ = _shown_ids(doc, items)
    assert "notif:0" in inline
    assert "(excerpt: summary)" in doc
    assert "(excerpt: summary and result)" not in doc


def test_injected_notification_label_calls_a_surviving_heading_and_finding_summary_and_result() -> None:
    """TRDD-BLGZTHQ9 F1b: the label is a claim about what is shown. A summary that passes the
    gate on its own, plus a result whose one-word heading (`ADVERSARIAL-REVIEW`) is followed by a
    real finding of >= 80 non-whitespace chars, both survive the cut when there is room for the
    whole excerpt -- the label must still say "(excerpt: summary and result)", not drop "result"
    just because the result STARTS with a bare heading line."""
    summary = ("Agent \"Re-render the four cached transcripts and compare the full copies byte "
               "for byte against the committed baseline\" finished")
    finding = "finding " * 15
    assert jc._body_chars(finding) >= 100
    text = _notification_with(summary, "ADVERSARIAL-REVIEW\n\n" + finding)
    items = [
        _item("notif:0", "event", text, turn=1),
        _item("newest:0", "user", "hi", turn=2),
    ]
    excerpt = jc._task_notification_excerpt(text)
    # Precondition: room enough that the whole excerpt is shown, not a truncated prefix.
    assert len(excerpt.encode("utf-8")) <= _notification_body_cap(items[0], 2000)
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=8000,
                     max_item_bytes=2000, non_owner_item_bytes=2000)

    inline, _ = _shown_ids(doc, items)
    assert "notif:0" in inline
    notif_block = doc.split("-- event notif:0 --\n", 1)[1].split("\n[[elided id=notif:0 ", 1)[0]
    assert notif_block.endswith("(excerpt: summary and result)")


def test_injected_title_only_notification_frees_its_bytes_for_the_next_candidate() -> None:
    """TRDD-BLGZTHQ9 F1b: a notification dropped to pointer-only gives its inline bytes back.
    Here a higher-scored title-only notification used to take the non-owner slot ahead of `work:0`,
    and the room could not hold both; now `work:0` -- a real work record -- is shown inline."""
    notif = _item("notif:0", "event", _TITLE_ONLY_NOTIFICATION, turn=1)
    work = _item("work:0", "assistant", ("Step 1: re-rendered the cached transcripts, compared the "
                                          "full copies byte for byte, and all matched. " * 3).strip(),
                 turn=2)
    newest = _item("newest:0", "user", "hi", turn=3)
    kw: dict[str, Any] = dict(budget_tokens=8000, header=_H, max_bytes=780, max_item_bytes=700,
                              non_owner_item_bytes=350)
    # Precondition: at this budget an item costing exactly the notification's inline block, and
    # outranking `work:0` the same way, leaves no room for `work:0` -- the pre-F1b situation.
    ctrl = _equal_cost_control(notif, "ctrl:0", turn=1)
    ctrl_items = [ctrl, work, newest]
    ctrl_doc = jc.compose(ctrl_items, {"ctrl:0": _scores(0.95), "work:0": _scores(0.5),
                                       "newest:0": _scores(0.9)}, **kw)
    ctrl_inline, _ = _shown_ids(ctrl_doc, ctrl_items)
    assert "ctrl:0" in ctrl_inline and "work:0" not in ctrl_inline

    items = [notif, work, newest]
    doc = jc.compose(items, {"notif:0": _scores(0.95), "work:0": _scores(0.5),
                             "newest:0": _scores(0.9)}, **kw)

    inline, pointed = _shown_ids(doc, items)
    assert len(doc.encode("utf-8")) <= 780
    assert "notif:0" not in inline and "notif:0" in pointed
    assert "work:0" in inline


def test_injected_long_newest_message_leaves_room_for_three_non_owner_items() -> None:
    """Amendment S4: a 1,500-B newest owner message used to be shown whole (its 1,500-B cap)
    next to an 800-B newest decision item, leaving too little of a 3,900-B room for the
    non-owner floor. The newest message is now capped at 35% of the available bytes (here
    ~1,200 B, a verbatim prefix plus a pointer), the decision item becomes a reserved decision
    pointer because both together exceed 50% of the room, and three informative non-owner
    items fit -- with no backstop stage running."""
    newest_text = "please finish the injected selection and re-render every transcript. " * 22
    assert 1450 <= len(newest_text) <= 1550
    items = [
        _item("dec:0", "user", "decision: the holdout transcript is never used to tune. " * 14,
              turn=10),
        *(
            _item(f"work{i}:0", "assistant",
                  f"Step {i}: compared the baseline and after renders for every transcript. " * 4,
                  turn=20 + i)
            for i in range(4)
        ),
        _item("newest:0", "user", newest_text, turn=30),
    ]
    scores = {it.id: _scores(0.9, decision=it.id == "dec:0") for it in items}
    doc = jc.compose(items, scores, budget_tokens=80000, header=_H, max_bytes=3900,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert len(doc.encode("utf-8")) <= 3900
    assert jc._DIGEST_TRUNCATED_NOTE not in doc and jc._MINIMAL_FIXED_LINE not in doc
    inline, pointed = _shown_ids(doc, items)
    assert newest_text not in doc
    newest_body = doc.split("-- user newest:0 --\n", 1)[1].split("\n[[elided id=newest:0 ", 1)[0]
    assert jc.DEFAULT_INJECT_ITEM_BYTES < len(newest_body) <= int(3900 * 0.35)
    assert "dec:0" not in inline and "dec:0" in pointed
    assert sum(1 for i in inline if i.startswith("work")) >= jc._NON_OWNER_FLOOR


# --- TRDD-D7RLXAN1: owner and assistant prose since the last compaction, verbatim, never scored ---
# Owner directive (2026-09-24): "assistant prose and user prose (the messages exchanges) should be
# all kept intact". Enforced in code: prose never becomes a scored item.


def _jsonl(tmp_path: Path, records: list[dict[str, Any]], name: str = "t.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _user(uuid: str, text: str) -> dict[str, Any]:
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}}


def _assistant(uuid: str, text: str) -> dict[str, Any]:
    return {"type": "assistant", "uuid": uuid,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _tool_pair(use_uuid: str, result_uuid: str, tool_id: str, result: str) -> list[dict[str, Any]]:
    return [
        {"type": "assistant", "uuid": use_uuid, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "uuid": result_uuid, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": result}]}},
    ]


def _boundary(uuid: str, anchor: str, preserved: list[str]) -> dict[str, Any]:
    """The real shape (fd5cc3e0, 2026-09-24): `type: system`, `subtype: compact_boundary`,
    `compactMetadata.preservedMessages.{anchorUuid, allUuids}`."""
    return {"type": "system", "subtype": "compact_boundary", "uuid": uuid,
            "compactMetadata": {"trigger": "auto", "preservedMessages": {
                "anchorUuid": anchor, "allUuids": preserved}}}


def _summary(uuid: str, text: str) -> dict[str, Any]:
    return {"type": "user", "uuid": uuid, "isCompactSummary": True,
            "isVisibleInTranscriptOnly": True, "message": {"role": "user", "content": text}}


def test_window_pairs_each_boundary_to_its_own_summary_by_anchor_uuid(tmp_path: Path) -> None:
    """TRDD-D7RLXAN1 test 2 (advisor finding D): the window records the LAST boundary, its
    preserved uuids, and the summary whose uuid is that boundary's anchorUuid -- not "the last
    isCompactSummary line seen" (the stray after s2 below), and never a stale earlier summary
    when a boundary's own summary never landed (session killed between the two lines)."""
    path = _jsonl(tmp_path, [
        _user("u0", "first owner message"),
        _boundary("b1", "s1", ["u0"]),
        {"type": "attachment", "uuid": "x1", "attachment": {"type": "date"}},
        _summary("s1", "SUMMARY ONE"),
        _user("u1", "second owner message"),
        _boundary("b2", "s2", ["u1", "names-no-line"]),
        _summary("s2", "SUMMARY TWO"),
        _summary("sx", "A STRAY SUMMARY PAIRED TO NO BOUNDARY"),
        _user("u2", "third owner message"),
    ])
    window = jc.ConversationWindow()
    items = _ei(path, window=window)
    assert [it.id for it in items] == ["u0:0", "u1:0", "u2:0"]  # neither line is ever an item
    assert window.summary == "SUMMARY TWO"
    assert window.preserved_uuids == frozenset({"u1", "names-no-line"})
    assert window.boundary_turn == 2

    killed = _jsonl(tmp_path, [
        _user("u0", "a"), _boundary("b1", "s1", []), _summary("s1", "OLD SUMMARY"),
        _user("u1", "b"), _boundary("b2", "s2", []),
    ], name="killed.jsonl")
    window2 = jc.ConversationWindow()
    _ei(killed, window=window2)
    assert window2.summary is None
    assert window2.boundary_turn == 2


def test_window_summary_survives_a_lone_surrogate_and_reaches_compose(tmp_path: Path) -> None:
    """TRDD-DQXMND59 stage 3, item G follow-up (adversarial review finding B): `window.summary`
    is set directly from `_tool_result_text` in `extract_items` -- it is NOT an `Item`, so
    `Item.__post_init__`'s sanitization (stage 1) never touched it, and `compose()` writes it
    straight into the final document. A lone (unpaired) UTF-16 surrogate in Claude Code's own
    `isCompactSummary` text therefore used to reach `compose()` un-sanitized and raise
    `UnicodeEncodeError` on its first `.encode("utf-8")`. Fails without the
    `jsonl_walk.drop_lone_surrogates` call at the point `window.summary` is set."""
    path = _jsonl(tmp_path, [
        _user("u0", "first owner message"),
        _boundary("b1", "s1", []),
        _summary("s1", "before \ud83d after"),
        _user("u1", "second owner message"),
    ])
    window = jc.ConversationWindow()
    items = _ei(path, window=window)

    assert window.summary is not None
    assert window.summary.encode("utf-8")  # must not raise UnicodeEncodeError
    assert "�" in window.summary

    conversation, scored = jc.split_conversation(items, window)
    doc = jc.compose(scored, {}, budget_tokens=8000,
                      header={"transcript_path": str(path), "session_key": "s"},
                      conversation=conversation, conversation_summary=window.summary)
    assert "�" in doc  # reaches the final document, sanitized -- never dropped, never raw


def test_split_conversation_drops_unpreserved_pre_boundary_prose_only(tmp_path: Path) -> None:
    """TRDD-D7RLXAN1 test 3: conversation = live owner/assistant/control messages (after the
    boundary, or preserved across it); scored = every tool and event item, pre-boundary ones
    included. Only unpreserved pre-boundary prose is in neither -- the summary stands in for it.
    Also pins the turn/boundary alignment (the card's "most likely way it is wrong")."""
    path = _jsonl(tmp_path, [
        _user("pu", "pre-boundary owner message"),
        _assistant("pa", "pre-boundary assistant reply"),
        *_tool_pair("ptu", "ptr", "t1", "pre-boundary tool output"),
        _user("keep", "preserved owner message"),
        _boundary("b", "s", ["keep", "ptu"]),
        _summary("s", "THE SUMMARY"),
        _user("nu", "post-boundary owner message"),
        _assistant("na", "post-boundary assistant reply"),
        *_tool_pair("ntu", "ntr", "t2", "post-boundary tool output"),
        _user("nc", "resume"),
    ])
    window = jc.ConversationWindow()
    items = _ei(path, window=window)
    conversation, scored = jc.split_conversation(items, window)

    assert [it.id for it in conversation] == ["keep:0", "nu:0", "na:0", "nc:0"]
    assert [it.kind for it in conversation] == ["user", "user", "assistant", "control"]
    assert [it.id for it in scored] == ["ptr:0", "ntr:0"]
    assert {it.id for it in items} - {it.id for it in conversation + scored} == {"pu:0", "pa:0"}
    assert window.summary == "THE SUMMARY"
    # No boundary at all: every message is live.
    no_boundary, _ = jc.split_conversation(items, jc.ConversationWindow())
    assert [it.id for it in no_boundary] == ["pu:0", "pa:0", "keep:0", "nu:0", "na:0", "nc:0"]


def test_only_the_bare_heartbeat_reply_is_dropped_a_reply_with_content_is_kept(
    tmp_path: Path,
) -> None:
    """TRDD-D7RLXAN1 (acceptance (a) on the real b2bf5b7b transcript): `is_heartbeat_reply` also
    matches "janitor heartbeat" plus up to two lines -- 9 real replies with content ("The live
    account is ...") vanished from the full copy that way. Only the exact bare reply carries
    nothing; every other assistant message is conversation, kept verbatim."""
    with_content = "janitor heartbeat\nThe rotation outlook is better than I feared."
    path = _jsonl(tmp_path, [
        _assistant("bare", "janitor heartbeat"),
        _assistant("said", with_content),
    ])
    items = _ei(path)
    assert [(it.id, it.kind, it.text) for it in items] == [("said:0", "assistant", with_content)]


def test_boundary_as_the_last_walked_entry_leaves_only_preserved_prose(tmp_path: Path) -> None:
    """TRDD-D7RLXAN1 (advisor finding D): a boundary as the LAST line -- no summary yet, no
    post-boundary prose. `boundary_turn == len(items)`, the conversation is the preserved prose
    only, and an injected render with no owner message in it still works."""
    path = _jsonl(tmp_path, [
        _user("u1", "owner asks something"),
        _assistant("a1", "assistant answers"),
        *_tool_pair("tu", "tr", "t1", "tool output"),
        _boundary("b", "s", ["a1"]),
    ])
    window = jc.ConversationWindow()
    items = _ei(path, window=window)
    assert window.boundary_turn == len(items)
    assert window.summary is None
    conversation, scored = jc.split_conversation(items, window)
    assert [it.id for it in conversation] == ["a1:0"]
    assert [it.id for it in scored] == ["tr:0"]

    doc = jc.compose(scored, {"tr:0": _scores(0.9)}, budget_tokens=8000, header=_H,
                     max_bytes=5000, max_item_bytes=700, non_owner_item_bytes=350,
                     full_context_path="/abs/full.md", conversation=conversation)
    assert doc.splitlines()[0].startswith("READ FIRST: /abs/full.md holds every message")
    assert "-- assistant a1:0 --\nassistant answers" in doc
    assert "owner asks something" not in doc


def test_full_render_contains_every_live_message_verbatim_in_order() -> None:
    """TRDD-D7RLXAN1 test 4: the full (`--out`) copy carries Claude Code's summary, then every
    conversation message byte for byte, in order, uncapped -- none of them scored. A control
    input is labelled "user" (the owner's words), not by its internal kind."""
    conversation = [
        _item(f"m{i}:0", "user" if i % 2 == 0 else "assistant",
              f"message {i} line one\n  indented   line two  with spaces\n\nline four of {i}\n"
              + "long " * 200, turn=i)
        for i in range(30)
    ] + [_item("c:0", "control", "resume", turn=30)]
    tools = [_item("t:0", "tool", "Bash(ls)\nfile.txt", turn=31)]
    doc = jc.compose(tools, {"t:0": _scores(0.9)}, budget_tokens=8000, header=_H,
                     conversation=conversation,
                     conversation_summary="CLAUDE CODE SUMMARY\nsecond line")

    summary_at = doc.index("CLAUDE CODE SUMMARY\nsecond line")
    assert doc.index(jc._CONVERSATION_HEADING) < summary_at < doc.index("## Kept items")
    last = summary_at
    for it in conversation:
        assert doc.count(it.text) == 1, it.id
        at = doc.index(it.text)
        assert at > last, f"{it.id} out of order"
        last = at
    assert "-- user c:0 --\nresume" in doc
    assert last < doc.index("## Kept items")


def test_injected_render_starts_with_read_first_and_shows_the_newest_run() -> None:
    """TRDD-D7RLXAN1 test 5: the injected copy's FIRST line is READ FIRST, naming the full copy
    and counting what is shown; the messages shown are one contiguous newest run (the owner's
    newest message inside it, then older ones while the share lasts), the oldest absent."""
    conversation = [_item(f"m{i}:0", "user" if i % 2 == 0 else "assistant",
                          f"exchange {i:02d} " + "x" * 280, turn=i) for i in range(40)]
    tools = [_item(f"t{i}:0", "tool", f"Bash(ls {i})\nresult {i} " + "y" * 150, turn=40 + i)
             for i in range(5)]
    doc = jc.compose(tools, {it.id: _scores(0.9) for it in tools}, budget_tokens=8000,
                     header=_H, max_bytes=5000, max_item_bytes=700, non_owner_item_bytes=350,
                     full_context_path="/abs/full.md", conversation=conversation)

    first = doc.splitlines()[0]
    assert first.startswith("READ FIRST: /abs/full.md holds every message since the last "
                            "compaction verbatim (40 messages; ")
    match = re.search(r"; (\d+) shown below\)", first)
    assert match is not None
    shown = int(match.group(1))
    blocks = re.findall(r"^-- (?:user|assistant) m(\d+):0 --$", doc, re.M)
    assert len(blocks) == shown and 2 < shown < 40
    assert sorted(int(b) for b in blocks) == list(range(40 - shown, 40))
    assert "exchange 39 " in doc and "exchange 00 " not in doc
    assert len(doc.encode("utf-8")) <= 5000


def test_injected_render_keeps_newest_owner_message_behind_long_assistant_tail() -> None:
    """TRDD-D7RLXAN1 test 6: one owner message, then ten 2 KB assistant replies. The owner's
    message survives whole, the newest replies follow as verbatim prefixes, and an explicit
    marker counts the replies in between that only the full copy has."""
    owner_text = "OWNER-INSTRUCTION: fix the login flow and keep the old API " + "o" * 60
    conversation = [_item("owner:0", "user", owner_text, turn=0)] + [
        _item(f"a{i}:0", "assistant", f"ASSISTANT-{i} " + "z" * 2000, turn=1 + i)
        for i in range(10)]
    tools = [_item(f"t{i}:0", "tool", f"Bash(ls {i})\nresult {i} " + "y" * 150, turn=20 + i)
             for i in range(5)]
    doc = jc.compose(tools, {it.id: _scores(0.9) for it in tools}, budget_tokens=8000,
                     header=_H, max_bytes=5000, max_item_bytes=700, non_owner_item_bytes=350,
                     full_context_path="/abs/full.md", conversation=conversation)

    assert f"-- user owner:0 --\n{owner_text}" in doc
    marker = re.search(r"\[(\d+) messages between these are only in the full copy\]", doc)
    assert marker is not None and 1 <= int(marker.group(1)) < 10
    assert "ASSISTANT-9 " in doc and "ASSISTANT-0 " not in doc
    assert len(doc.encode("utf-8")) <= 5000


def test_injected_render_never_exceeds_max_bytes_with_100kb_of_prose() -> None:
    """TRDD-D7RLXAN1 test 7: the exchanges block is fixed text measured before
    `_select_injected` runs, so `max_bytes` still holds with 100 KB of prose -- at a normal
    room and at a pathological one (where the minimal fallback takes the owner's newest message
    from the conversation, since no owner item is in `items` any more)."""
    conversation = [_item(f"m{i}:0", "user" if i % 3 == 0 else "assistant",
                          f"p{i} " + "w" * 1000, turn=i) for i in range(100)]
    tools = [_item(f"t{i}:0", "tool", f"Bash(ls {i})\nresult {i} " + "y" * 150, turn=100 + i)
             for i in range(10)]
    for max_bytes in (5000, 600):
        doc = jc.compose(tools, {it.id: _scores(0.9) for it in tools}, budget_tokens=8000,
                         header=_H, max_bytes=max_bytes, max_item_bytes=700,
                         non_owner_item_bytes=350, full_context_path="/abs/full.md",
                         conversation=conversation)
        assert len(doc.encode("utf-8")) <= max_bytes, max_bytes
        if jc._MINIMAL_FIXED_LINE in doc:
            assert "m99:0" in doc  # the newest owner message, from the conversation


def test_injected_render_still_shows_three_tool_items_beside_exchanges() -> None:
    """TRDD-D7RLXAN1 test 8: the exchanges take at most their share, so the tool/event items
    Jev kept still reach the `_NON_OWNER_FLOOR` (3) -- what the session DID -- beside them."""
    conversation = [_item(f"m{i}:0", "user" if i % 2 == 0 else "assistant",
                          f"p{i} " + "w" * 1000, turn=i) for i in range(40)]
    tools = [_item(f"t{i}:0", "tool", f"Bash(cmd {i})\nresult line {i}: " + "r" * 120,
                   turn=100 + i) for i in range(20)]
    doc = jc.compose(tools, {it.id: _scores(0.9) for it in tools}, budget_tokens=8000,
                     header=_H, max_bytes=6000, max_item_bytes=700, non_owner_item_bytes=350,
                     full_context_path="/abs/full.md", conversation=conversation)

    assert jc._EXCHANGES_HEADING in doc
    assert len(re.findall(r"^-- tool t\d+:0 --$", doc, re.M)) >= jc._NON_OWNER_FLOOR
    assert len(doc.encode("utf-8")) <= 6000
