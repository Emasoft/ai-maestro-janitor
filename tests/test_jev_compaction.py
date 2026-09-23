"""Tests for scripts/lib/jev_compaction.py (TRDD-RAEGS1D5 card 3, part A)."""

from __future__ import annotations

import json
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


def test_budget_eviction_protects_decision_passing_items_last() -> None:
    # "dec" scores LOWER on max(relevance, decision) than "rel" does (0.9 vs 0.95), so the
    # OLD ordering (lowest max_score dropped first) would have evicted "dec" first -- exactly
    # the "budget undoes the decision question" bug the review flagged. "dec" is also now the
    # NEWEST owner message (turn=1 vs "rel"'s turn=0) -- TRDD-RAEGS1D5's owner-share ceiling
    # (see `test_owner_share_ceiling_...` below) guarantees the newest owner message a slot
    # REGARDLESS of decision_passed, so a decision_passed item that is not also the newest can
    # lose a slot to it under a tight-enough budget (see
    # `test_decision_passed_owner_item_wins_second_slot_when_not_newest` for that case) -- this
    # test keeps dec/newest aligned, the common real-world case (the user's latest message is
    # usually where a decision/instruction was just stated), so it still proves the ordering
    # is not a blind "lowest max_score first" sort.
    items = [
        _item("dec:0", "user", "policy: always use tabs", turn=1, tokens=100),
        _item("rel:0", "user", "merely relevant background", turn=0, tokens=100),
    ]
    scores = {
        "dec:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                            decision_passed=True),
        "rel:0": jc.Scores(relevance=0.95, decision=0.0, oversized=False, kept=True,
                            decision_passed=False),
    }
    doc = jc.compose(items, scores, budget_tokens=100,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user dec:0 --" in doc
    assert "-- user rel:0 --" not in doc
    assert "id=rel:0" in doc


def test_decision_passed_owner_item_wins_second_slot_when_not_newest() -> None:
    # TRDD-RAEGS1D5: beyond the guaranteed-newest slot, owner items still compete by
    # (decision_passed, turn) -- an OLDER decision_passed item ("dec_old") outranks a newer,
    # merely-relevant one ("rel_old", higher raw relevance 0.9 vs dec_old's 0.6) for the
    # second slot the 100-token owner share (int(250 * 0.40)) can't hold outright, so both
    # overflow to the leftover-budget pass together -- where decision_passed is still the
    # tie-break that decides which one of them actually fits.
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


def test_guaranteed_owner_slot_prefers_newest_decision_passed_over_newest_plain() -> None:
    # TRDD-RAEGS1D5 (adversarial-review fix): pins the fix made in response to the review's
    # Q1 finding -- an earlier version of this fix guaranteed the tier-1 owner slot to the
    # NEWEST owner item unconditionally, which let a merely-recent, non-decision message
    # ("thanks") outrank an OLDER decision_passed one (a stated constraint) for that one
    # guaranteed slot -- silently reintroducing the "budget undoes the decision question"
    # bug for the narrow case where they are not the same item. The guaranteed slot must go
    # to the newest `decision_passed` owner item when one exists, even if a plainer,
    # genuinely more recent owner message exists.
    items = [
        _item("plain_newest:0", "user", "thanks", turn=1, tokens=100),
        _item("dec_older:0", "user", "policy: always use tabs", turn=0, tokens=100),
    ]
    scores = {
        "plain_newest:0": jc.Scores(relevance=0.5, decision=0.0, oversized=False, kept=True,
                                     decision_passed=False),
        "dec_older:0": jc.Scores(relevance=0.6, decision=0.9, oversized=False, kept=True,
                                  decision_passed=True),
    }
    doc = jc.compose(items, scores, budget_tokens=100,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user dec_older:0 --" in doc
    assert "-- user plain_newest:0 --" not in doc
    assert "id=plain_newest:0" in doc


def test_pointer_format_has_no_path() -> None:
    items = [_item("p:0", "user", "some elided line\nmore", turn=0)]
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
    reachable by id)."""
    n = jc._MAX_ELIDED_POINTERS + 10
    items = [_item(f"e{i}:0", "user", f"text {i}", turn=i, tokens=10) for i in range(n)]
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
    `compose()` caps at `_MAX_ELIDED_POINTERS`)."""
    n = jc._MAX_ELIDED_POINTERS + 5
    items = [_item(f"e{i}:0", "user", f"text {i}", turn=i, tokens=10) for i in range(n)]
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
    to the original first line."""
    first_line = 'said "always use \\tabs\\", never spaces'
    items = [_item("q:0", "user", first_line + "\nmore text", turn=0)]
    scores = {"q:0": jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                decision_passed=False)}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})

    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided id=")]
    assert len(pointer_lines) == 1
    parsed = parse_pointer(pointer_lines[0])
    assert parsed is not None
    assert parsed.summary == first_line


def test_pointer_summary_skips_a_leading_blank_line() -> None:
    """Card 5: the summary is the first NON-EMPTY line (was: the first line, blank or not --
    a leading blank line used to produce an empty preview)."""
    items = [_item("b:0", "user", "\n\n   \nreal first content", turn=0)]
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
