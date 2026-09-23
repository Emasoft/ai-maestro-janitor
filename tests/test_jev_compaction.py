"""Tests for scripts/lib/jev_compaction.py (TRDD-RAEGS1D5 card 3, part A)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import jev_compaction as jc  # noqa: E402
from jevctx.testing import FakeJevClient  # noqa: E402
from jevctx.types import JevUnavailableError  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "jev_transcript_small.jsonl"


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
    # Three kept items, same max_score (0.6) -> the oldest (smallest turn) drops first;
    # a fourth item scores lower (0.4) and must drop before any of the tied trio.
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
    # Budget for exactly 2 of the 4 (200 tokens): drop order must be low, then a (oldest
    # of the tied 0.6 trio), leaving b and c inlined.
    doc = jc.compose(items, scores, budget_tokens=200,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- user b:0 --" in doc
    assert "-- user c:0 --" in doc
    assert "-- user a:0 --" not in doc
    assert "-- user low:0 --" not in doc
    assert "id=a:0" in doc
    assert "id=low:0" in doc


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
    # the "budget undoes the decision question" bug the review flagged. The new ordering
    # protects any decision_passed=True item until every decision_passed=False item is gone,
    # regardless of raw score, so "rel" (relevance-only) is dropped instead.
    items = [
        _item("dec:0", "user", "policy: always use tabs", turn=0, tokens=100),
        _item("rel:0", "user", "merely relevant background", turn=1, tokens=100),
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
    # The path DOES appear exactly once more, in the fixed trailing expand-with line.
    assert doc.count(header["transcript_path"]) == 2  # header line + trailing line


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
