"""Tests for scripts/lib/jev_compaction.py (TRDD-RAEGS1D5 card 3, part A)."""

from __future__ import annotations

import json
import re
import sys
import threading
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

def _src_seg_id(a: int) -> str:
    # The pre-commit privacy scan (ssh-user-host rule) reads a literal "0 AT 1-10" ID as an ssh user-at-host pair; this helper keeps such literals out of modified lines. Synthetic fixture IDs only.
    return f"src:0@{a}-{a + 9}"


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


def test_keep_if_relevance_passes() -> None:
    """TRDD-R9UXOSR5: relevance alone decides `kept` -- the old "or decision passes" second
    gate is retired with the decision question, and only `:rel` keys are ever sent."""
    items = [
        _item("i0:0", "tool", "the build is green", 0),
        _item("i1:0", "tool", "always use tabs, never spaces", 1),
        _item("i2:0", "tool", "irrelevant progress noise", 2),
    ]

    def answer(state: Any, questions: Any, key: Any) -> float:
        # Keys are "<ref>:rel" (one question per item); the state.items ref is the part
        # before the ":". No ":dec" question exists any more -- assert that below.
        assert str(key).endswith(":rel")
        ref = str(key).split(":", 1)[0]
        item_text = ""
        if isinstance(state, dict):
            for entry in state.get("items", []):
                if entry.get("ref") == ref:
                    item_text = entry.get("text", "")
        return 0.9 if "build" in item_text else 0.1

    client = FakeJevClient(answer)
    scores = jc.score_items(items, "digest: fixing the build", client)

    assert scores["i0:0"].kept is True   # passes on relevance
    assert scores["i1:0"].kept is False  # below threshold, nothing else can rescue it
    assert scores["i2:0"].kept is False  # below threshold


def test_budget_ordering_drops_lowest_first_oldest_among_equals() -> None:
    # The `budget_tokens` admission is one flat priority fill over every kept item
    # (TRDD-R9UXOSR5: the owner-share stage on top of it went with the decision question --
    # no "user" item is ever a scored candidate any more, so all four items are "tool").
    # (protected, score, turn) descending, highest first: c (turn=2), b (turn=1), a (turn=0)
    # -- all at 0.6 -- then low (0.4, the lowest score, regardless of being the newest).
    # Each 100 tokens against a 200 budget: c and b fill it exactly; a and low do not fit.
    items = [
        _item("a:0", "tool", "aaaa", turn=0, tokens=100),
        _item("b:0", "tool", "bbbb", turn=1, tokens=100),
        _item("c:0", "tool", "cccc", turn=2, tokens=100),
        _item("low:0", "tool", "llll", turn=3, tokens=100),
    ]
    scores = {
        "a:0": jc.Scores(relevance=0.6, oversized=False, kept=True, ),
        "b:0": jc.Scores(relevance=0.6, oversized=False, kept=True, ),
        "c:0": jc.Scores(relevance=0.6, oversized=False, kept=True, ),
        "low:0": jc.Scores(relevance=0.4, oversized=False, kept=True, ),
    }
    doc = jc.compose(items, scores, budget_tokens=200,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- tool c:0 --" in doc
    assert "-- tool b:0 --" in doc
    assert "-- tool a:0 --" not in doc
    assert "-- tool low:0 --" not in doc
    assert "id=a:0" in doc
    assert "id=low:0" in doc


def test_oversized_never_inlined() -> None:
    items = [_item("o:0", "assistant", "oversized text", turn=0, tokens=999999)]
    # kept=True on purpose: compose() must refuse to inline it anyway (the spec's own
    # invariant, not just something score_items happens to enforce upstream).
    scores = {"o:0": jc.Scores(relevance=1.0, oversized=True, kept=True,
                                )}
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
    scores = {"o:0": jc.Scores(relevance=1.0, oversized=True, kept=True,
                                )}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    for line in body_lines[:20]:
        assert line in doc
    for line in body_lines[20:]:
        assert line not in doc


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
        "u0:0": jc.Scores(relevance=0.6, oversized=False, kept=True, ),
        "u1:0": jc.Scores(relevance=0.6, oversized=False, kept=True, ),
        "u2:0": jc.Scores(relevance=0.6, oversized=False, kept=True, ),
        "t0:0": jc.Scores(relevance=0.9, oversized=False, kept=True, ),
    }
    doc = jc.compose(items, scores, budget_tokens=120,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "-- tool t0:0 --" in doc, "a highly relevant non-owner item must survive a budget owner items alone exceed"
    assert "-- user u2:0 --" in doc, "the newest owner message is still guaranteed"


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
        "big:0": jc.Scores(relevance=0.95, oversized=False, kept=True,
                            ),
        "small:0": jc.Scores(relevance=0.6, oversized=False, kept=True,
                              ),
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
    scores = {"p:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                                )}
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
        it.id: jc.Scores(relevance=(i / n), oversized=False, kept=False,
                          )
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
    scores = {"only:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                                   )}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert "more items not listed" not in doc
    assert "pointers expand with:" in doc


def test_max_bytes_backstop_evicts_by_priority_not_chronology() -> None:
    """Review finding, card 5 content-fit (TRDD-RAEGS1D5): the `max_bytes` backstop must
    evict kept items by the SAME `evict_key` priority the `budget_tokens` eviction already
    uses, never bare chronological order. TRDD-R9UXOSR5: `decision_passed` is gone, so the
    discriminating pair is now score-vs-turn -- the NEWEST item has the LOWEST score and is
    evicted FIRST (priority order), where chronology would evict the oldest first; the oldest
    item (same high score as the two middle items) goes SECOND. Four items, budget_tokens
    generous (so the first eviction pass keeps all four); `max_bytes` tight enough that the
    backstop must run."""
    low = _item("newest-low:0", "tool", "newest, lowest relevance", turn=3, tokens=5)
    others = [
        _item(f"high-{i}:0", "tool", f"background text {i}", turn=i, tokens=5)
        for i in range(3)
    ]
    items = [*others, low]
    scores = {
        low.id: jc.Scores(relevance=0.5, oversized=False, kept=True),
        **{it.id: jc.Scores(relevance=0.9, oversized=False, kept=True) for it in others},
    }
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s", "digest": "z" * 300}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header, max_bytes=640)
    assert len(doc.encode("utf-8")) <= 640
    # evict_key = (protected, score, turn) ascending: the newest-but-lowest item goes first,
    # then the oldest among the 0.9-equals -- chronological eviction would drop "high-0" AND
    # "high-1" first, leaving "high-2" + "newest-low" shown instead.
    assert "-- tool newest-low:0 --" not in doc
    assert "-- tool high-0:0 --" not in doc
    assert "-- tool high-1:0 --" in doc
    assert "-- tool high-2:0 --" in doc




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
        "newest:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                               ),
        "dec:0": jc.Scores(relevance=0.6, oversized=False, kept=True,
                            ),
        "rel1:0": jc.Scores(relevance=0.5, oversized=False, kept=True,
                             ),
        "rel2:0": jc.Scores(relevance=0.5, oversized=False, kept=True,
                             ),
    }
    scores.update({
        it.id: jc.Scores(relevance=0.7, oversized=False, kept=True,
                          )
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
        "newest:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                               ),
        "dec:0": jc.Scores(relevance=0.6, oversized=False, kept=True,
                            ),
        "rel1:0": jc.Scores(relevance=0.5, oversized=False, kept=True,
                             ),
        "rel2:0": jc.Scores(relevance=0.5, oversized=False, kept=True,
                             ),
    }
    scores.update({
        it.id: jc.Scores(relevance=0.7, oversized=False, kept=True,
                          )
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
    injected copy's items against the 8,000-token `budget_tokens` gate and then appended ALL
    of them to `kept_order_list` regardless of the injected render's own (much smaller)
    `max_bytes` -- so the coarse byte BACKSTOP, not any admission pass, decided what survived,
    and on every real transcript it evicted down to the exact non-owner floor (3) even when
    the byte budget had room for more (aabd8b0c reached 4/6/4 before this regression). Same
    item shape as the sibling `test_non_owner_floor_holds_in_injected_mode_too` above (which
    pins the floor itself at a TIGHT `max_bytes=1120` -> exactly 3 tools) -- loosened here to
    `max_bytes=1800` (measured: the render is 1732 bytes, fitting BEFORE any backstop stage
    ever runs -- `compose()` returns at its own `len(doc) <= max_bytes` early-return, so the
    backstop never touches this document at all). TRDD-R9UXOSR5: the owner items that used to
    share the kept-item section live in `conversation` now (never scored), so "more than the
    floor" is all about the tools.
    Review finding (TRDD-AW4XD53Q): this specific fixture does NOT by itself discriminate the
    pre-fix code from the fix -- verified directly by running it against a scratch copy of the
    pre-fix eviction-only backstop, which produces the identical result here. This test pins
    the CURRENT correct behaviour (room allows more than the floor -> more than the floor is
    kept); the actual regression proof against the historical bug is the cached-real-pickle
    re-render in that task's own report, not this synthetic fixture."""
    conv = [
        _item("newest:0", "user", "hi there", turn=20),
        _item("dec:0", "user", "policy decision text", turn=0),
        _item("rel1:0", "user", "owner background one " * 5, turn=1),
        _item("rel2:0", "user", "owner background two " * 5, turn=2),
    ]
    tools = [
        _item(f"tool{i}:0", "tool", f"tool output number {i} " * 10, turn=10 + i, tokens=5)
        for i in range(6)
    ]
    scores = {it.id: _scores(0.7) for it in tools}
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(tools, scores, budget_tokens=8000, header=header,
                     max_bytes=1800, max_item_bytes=700, conversation=conv)

    doc_bytes = len(doc.encode("utf-8"))
    assert doc_bytes <= 1800
    assert doc_bytes < 1800, "must fit with room to spare -- proof admission alone did the work"
    tool_count = sum(1 for i in range(6) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count > jc._NON_OWNER_FLOOR, (
        f"expected more than the floor ({jc._NON_OWNER_FLOOR}) non-owner items, got {tool_count}"
    )
    # The owner messages render verbatim in their own section, never scored.
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
    scores = {"newest:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                                     )}
    scores.update({
        it.id: jc.Scores(relevance=0.7, oversized=False, kept=True,
                          )
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
    scores = {"newest:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                                     )}
    scores.update({
        it.id: jc.Scores(relevance=0.7, oversized=False, kept=True,
                          )
        for it in tools
    })
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s"}
    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=900, max_item_bytes=700)

    assert len(doc.encode("utf-8")) <= 900
    tool_count = sum(1 for i in range(2) if f"-- tool tool{i}:0 --" in doc)
    assert tool_count == 2, f"expected both non-owner items (below the floor), got {tool_count}"
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
    scores = {items[0].id: jc.Scores(relevance=1.0, oversized=False, kept=True,
                                      )}
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
        "trace:0": jc.Scores(relevance=0.55, oversized=False, kept=True,
                              ),
        "plain:0": jc.Scores(relevance=0.95, oversized=False, kept=True,
                              ),
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
        it = _item(_src_seg_id(a), "tool", f"segment at {a}", turn=turn, tokens=100)
        return jc.Item(it.id, it.kind, it.text, it.tokens, it.ts, it.turn, protected=True)

    items = [
        _protected_seg(1, 0), _protected_seg(11, 1), _protected_seg(21, 2),
        _item("o1:0", "tool", "other result one", turn=3, tokens=100),
        _item("o2:0", "tool", "other result two", turn=4, tokens=100),
        _item("o3:0", "tool", "other result three", turn=5, tokens=100),
    ]
    scores = {
        _src_seg_id(1): jc.Scores(relevance=0.5, oversized=False, kept=True,
                                   ),
        _src_seg_id(11): jc.Scores(relevance=0.5, oversized=False, kept=True,
                                    ),
        _src_seg_id(21): jc.Scores(relevance=0.5, oversized=False, kept=True,
                                    ),
        "o1:0": jc.Scores(relevance=0.6, oversized=False, kept=True,
                           ),
        "o2:0": jc.Scores(relevance=0.65, oversized=False, kept=True,
                           ),
        "o3:0": jc.Scores(relevance=0.7, oversized=False, kept=True,
                           ),
    }
    doc = jc.compose(items, scores, budget_tokens=300,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    kept_ids = {
        m.group(1) for m in re.finditer(r"^-- \S+ (\S+) --$", doc, re.MULTILINE)
    }
    src_kept = {i for i in kept_ids if i.startswith("src:0@")}
    assert len(src_kept) == 1, f"expected exactly one segment of one source item, got {src_kept}"
    assert src_kept == {_src_seg_id(1)}  # earliest turn among the tied-score segments
    assert kept_ids == {_src_seg_id(1), "o3:0", "o2:0"}  # 3 DISTINCT source items, not 3 segments


def test_protected_boost_winner_is_chosen_among_kept_segments_only() -> None:
    # Adversarial review of the per-source cap: `score_items` scores an oversized item
    # relevance=1.0/decision=1.0 with kept=False, so picking the source's boosted segment from
    # ALL items made the oversized segment win -- and, never being kept, it left the source's
    # one KEPT segment unboosted, losing to a merely higher-scoring plain item. Here only one
    # of the two fits the budget; the kept protected segment must win it.
    def _protected_seg(a: int, turn: int, tokens: int) -> jc.Item:
        it = _item(_src_seg_id(a), "tool", f"segment at {a}", turn=turn, tokens=tokens)
        return jc.Item(it.id, it.kind, it.text, it.tokens, it.ts, it.turn, protected=True)

    items = [
        _protected_seg(1, 0, 5000),
        _protected_seg(11, 1, 100),
        _item("o1:0", "tool", "other result one", turn=2, tokens=100),
    ]
    scores = {
        _src_seg_id(1): jc.Scores(relevance=1.0, oversized=True, kept=False,
                                   ),
        _src_seg_id(11): jc.Scores(relevance=0.5, oversized=False, kept=True,
                                    ),
        "o1:0": jc.Scores(relevance=0.7, oversized=False, kept=True,
                           ),
    }
    doc = jc.compose(items, scores, budget_tokens=150,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    assert f"-- tool {_src_seg_id(11)} --" in doc
    assert "-- tool o1:0 --" not in doc
    assert f"-- tool {_src_seg_id(1)} --" not in doc  # oversized: never inlined


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
        it.id: jc.Scores(relevance=0.9, oversized=False, kept=True,
                          )
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
    # per batch, and that call's state carries each item's text exactly ONCE. TRDD-R9UXOSR5:
    # one question per item -- "<ref>:rel" only, no "<ref>:dec".
    items = [_item("i0:0", "tool", "distinctive-marker-text", turn=0)]
    client = FakeJevClient.constant(0.9)
    jc.score_items(items, "digest", client)

    assert len(client.calls) == 1  # ONE request, not two
    call = client.calls[0]
    assert call.state_text().count("distinctive-marker-text") == 1
    # The single relevance question travels in that one request.
    assert len(call.questions) == 1
    assert {k.rsplit(":", 1)[1] for k in call.questions} == {"rel"}


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
    scores = {"k:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                                )}
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
    scores = {"k:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                                )}
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


def test_decision_question_never_asked_at_all() -> None:
    """TRDD-R9UXOSR5: the DECISION question is retired. No request `score_items` sends may
    carry a `:dec` key, whatever the item's kind -- one relevance question per item, and the
    Scores it returns carry no decision fields at all."""
    items = [
        _item("u:0", "user", "policy: always use tabs", turn=0),
        _item("e:0", "event", "a task notification's report text", turn=1),
    ]
    client = FakeJevClient.constant(0.9)
    scores = jc.score_items(items, "digest", client)

    # One question per item, always ":rel"; no ":dec" key anywhere in any request.
    dec_key_count = sum(1 for call in client.calls for k in call.questions if k.endswith(":dec"))
    rel_key_count = sum(1 for call in client.calls for k in call.questions if k.endswith(":rel"))
    assert dec_key_count == 0
    assert rel_key_count == 2  # both items still get scored for relevance

    assert scores["u:0"].kept is True  # 0.9 relevance passes on its own
    assert scores["e:0"].kept is True
    assert not hasattr(scores["u:0"], "decision")  # the field is gone, not merely 0.0
    assert not hasattr(scores["u:0"], "decision_passed")


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
        "blocked:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                                 blocked=True),
        "skipped:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                                ),
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"})
    lines = doc.splitlines()
    blocked_idx = next(i for i, ln in enumerate(lines) if "id=blocked:0" in ln)
    skipped_idx = next(i for i, ln in enumerate(lines) if "id=skipped:0" in ln)
    assert lines[blocked_idx + 1] == "unscored (provider firewall)"
    # An ordinary below-threshold item gets no such note right after its pointer line.
    assert lines[skipped_idx + 1] != "unscored (provider firewall)"


def test_score_items_parallel_overlaps_requests() -> None:
    """Card 3 (TRDD-CC0CZLMO): jevctx's own `scorer.py` fans batches out on a
    `ThreadPoolExecutor` (`scorer.py:149-154`); ours must too, or a large transcript's serial
    for-loop exceeds both compaction-lane timeouts (the bug this card fixes -- measured: a
    49 MB transcript took 168 s on HEAD, over the 60 s sync AND the 120 s detached timeouts).
    160 non-"user" items pack 32-per-batch (card 5's non-"user" batch size) into 5 batches.
    Asserts OVERLAP with a `threading.Barrier(2)`: the first two requests only proceed once both
    are in flight, so a real pool passes at any host load while a serial executor raises
    BrokenBarrierError after the timeout (TRDD-KJAFABDU: a wall-clock ratio, then a 0.2 s sleep
    window, both still missed at host load 100+; a barrier needs no timing)."""
    items = [_item(f"i{i}:0", "assistant", f"text {i}", turn=i, tokens=10) for i in range(160)]

    def max_in_flight(workers: int, barrier: threading.Barrier | None) -> int:
        lock = threading.Lock()
        counts = {"now": 0, "max": 0, "calls": 0}
        inner = FakeJevClient.constant(0.9)

        class _CountingClient:
            def ask(self, state: Any, questions: Any) -> dict[str, Any]:
                with lock:
                    counts["now"] += 1
                    counts["max"] = max(counts["max"], counts["now"])
                    counts["calls"] += 1
                    meet = barrier is not None and counts["calls"] <= 2
                if meet:
                    assert barrier is not None
                    barrier.wait()
                with lock:
                    counts["now"] -= 1
                return inner.ask(state, questions)

        jc.score_items(items, "digest", _CountingClient(), max_workers=workers)
        return counts["max"]

    assert max_in_flight(1, None) == 1
    assert max_in_flight(8, threading.Barrier(2, timeout=10)) >= 2


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
        it.id: jc.Scores(relevance=(i / n), oversized=False, kept=False,
                          )
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
    scores = {"q:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                                )}
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
    scores = {seg_id: jc.Scores(relevance=0.0, oversized=False, kept=False,
                                 )}
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
    scores = {"b:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                                )}
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
        it.id: jc.Scores(relevance=0.9, oversized=False, kept=True,
                          )
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
    kept_scores = {kept[0].id: jc.Scores(relevance=0.9, oversized=False,
                                          kept=True, )}
    elided = [
        _item(f"e{i}:0", "assistant", f"elided background text number {i} " * 3, turn=i + 1,
              tokens=5)
        for i in range(30)
    ]
    elided_scores = {
        it.id: jc.Scores(relevance=(i / 30), oversized=False, kept=False,
                          )
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
    scores = {"o:0": jc.Scores(relevance=1.0, oversized=True, kept=True,
                                )}
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
                      max_item_bytes=700)
    assert "id=o:0" in doc  # still pointed at -- just never previewed
    for line in body_lines[1:]:  # line 0 legitimately survives as the pointer's own summary
        assert line not in doc





def test_inject_mode_byte_cap_holds_through_the_full_degrade_chain() -> None:
    """Requirement 5: the `max_bytes` cap is a hard guarantee in injected mode too, down to a
    budget tight enough to force every degrade step in turn (pointer eviction, then kept-item
    eviction -- per-item truncation already applied at render time -- then digest truncation,
    and the conversation exchanges give way too) -- and the fixed "pointers expand with"
    trailer, the model's only way back to everything elided, must still survive even this
    squeeze.

    TRDD-R9UXOSR5 re-pin: the "guaranteed newest owner item" this fixture used to carry in
    `items` is gone with the decision question -- owner prose reaches the injected copy only
    through `conversation` (`_select_exchanges`), never as a scored candidate, so there is no
    guaranteed kept slot to exclude from the stages. The fixture: 4 Jev-kept tool items, 10
    below-threshold items with informative text (pointer-eligible), a 900-byte digest and 8
    exchange messages. `max_bytes=1200` (measured) empties every pointer, evicts all four
    kept items, truncates the digest, and drops the exchange block -- 1200-1300 all fire the
    chain; at 1600 the exchange block and a full (untruncated) digest fit again, which pins
    the two states apart."""
    header = {"transcript_path": "/tmp/t.jsonl", "session_key": "s", "digest": "z" * 900}
    conv = [_item(f"c{i}:0", "user", f"note {i} " * 8, turn=i) for i in range(8)]
    items = [
        *[_item(f"keep{i}:0", "tool", f"kept tool body number {i} " * 8, turn=i, tokens=5)
          for i in range(4)],
        *[_item(f"e{i}:0", "assistant", f"elided {i} informative text for its pointer line " * 2,
                turn=100 + i, tokens=5) for i in range(10)],
    ]
    scores = {f"keep{i}:0": _scores(0.9) for i in range(4)}
    scores.update({f"e{i}:0": _scores(0.1, kept=False) for i in range(10)})

    doc = jc.compose(items, scores, budget_tokens=8000, header=header,
                     max_bytes=1200, max_item_bytes=700, conversation=conv)
    assert len(doc.encode("utf-8")) <= 1200
    assert "pointers expand with:" in doc
    # The full chain actually fired, not just the byte bound: every pointer dropped to the
    # count line, every kept item evicted, the digest truncated, the exchange block gone.
    assert "[[elided id=" not in doc.split("\n## Elided\n", 1)[1]
    assert _count_line_n(doc) == 14
    assert not [line for line in doc.splitlines() if line.startswith("-- tool")]
    assert jc._DIGEST_TRUNCATED_NOTE in doc

    doc2 = jc.compose(items, scores, budget_tokens=8000, header=header,
                      max_bytes=1600, max_item_bytes=700, conversation=conv)
    assert len(doc2.encode("utf-8")) <= 1600
    assert "-- user c7:0 --" in doc2  # the newest exchange, verbatim, in its own section
    assert jc._DIGEST_TRUNCATED_NOTE not in doc2
def test_inject_mode_newest_owner_message_capped_and_nonuser_items_survive() -> None:
    """Orchestrator rebalance (2026-09-23), re-pinned for TRDD-R9UXOSR5: the OWNER SHARE
    admission tier and its ~40% ceiling went with the decision question -- owner prose is
    never a scored candidate any more (`split_conversation` keeps it out of `items`), and it
    reaches the injected copy only through the `conversation` section, whose newest owner
    message is capped at `NEWEST_OWNER_ITEM_BYTES` (1500). What must still hold: 19 shorter
    owner messages + one ~1,900-byte newest message in `conversation`, 20 high-relevance
    tool items in `items`. Four things:

    1. the newest owner message survives as exactly its 1500-byte verbatim prefix, never
       the full text and never the smaller 700-byte `max_item_bytes`;
    2. every KEPT item (tool, the only scored kind) respects the general 700-byte cap;
    3. the document fits `max_bytes`;
    4. at least 3 tool items are inline -- the owner prose does not crowd them out."""
    newest_owner_text = "owner instruction " * 100  # ~1,900 bytes, no internal newline
    conv = [
        _item(f"u{i}:0", "user", f"short owner note number {i}", turn=i) for i in range(19)
    ] + [_item("u19:0", "user", newest_owner_text, turn=19)]
    tool_items = [
        _item(f"t{i}:0", "tool", ("tool output line " * 29) + f" id{i}", turn=100 + i, tokens=5)
        for i in range(20)
    ]
    scores = {it.id: _scores(0.95) for it in tool_items}
    doc = jc.compose(tool_items, scores, budget_tokens=80000, header=_H,
                     max_bytes=6000, max_item_bytes=700, conversation=conv)

    assert len(doc.encode("utf-8")) <= 6000

    # (1) the newest owner message: present as exactly its own first 1500 bytes (cut at a
    # line boundary or UTF-8-safe, per `_truncate_prefix_bytes`), never the full ~1900-byte
    # text, and never truncated down to the smaller 700-byte general cap either.
    newest_prefix = jc._truncate_prefix_bytes(newest_owner_text, jc.NEWEST_OWNER_ITEM_BYTES)
    assert newest_prefix in doc
    assert newest_owner_text not in doc
    smaller_prefix = jc._truncate_prefix_bytes(newest_owner_text, jc.DEFAULT_INJECT_ITEM_BYTES)
    assert len(smaller_prefix) < len(newest_prefix)
    assert "-- user u19:0 --" in doc

    # (2) every kept item respects the general 700-byte cap.
    kept_section = doc.split("## Kept items\n", 1)[1].split("\n\n## Elided", 1)[0]
    import re as _re
    for block in _re.split(r"\n(?=-- \w+ [^\n]+ --\n)", kept_section):
        m = _re.match(r"-- (\w+) ([^\n]+) --\n", block)
        if not m:
            continue
        body = block[m.end():].split("\n[[elided", 1)[0]
        assert len(body.encode("utf-8")) <= jc.DEFAULT_INJECT_ITEM_BYTES, (
            f"{m.group(2)} exceeded the general per-item cap"
        )

    # (4) non-user items are not crowded out.
    tool_headers = [line for line in doc.splitlines() if line.startswith("-- tool t")]
    assert len(tool_headers) >= 3, f"expected >=3 tool items, got {len(tool_headers)}"
def test_non_owner_item_bytes_caps_non_owner_items_smaller_than_owner_items() -> None:
    # TRDD-RAEGS1D5 (jev newest+3, task 2): `non_owner_item_bytes`, when given alongside
    # `max_item_bytes`, caps ONLY items whose `kind != "user"` -- an owner item beyond the
    # guaranteed slot still uses the general (bigger) `max_item_bytes`, unaffected by the
    # smaller non-owner cap. "owner2:0" (an owner item, NOT the guaranteed newest) proves the
    # former; "reply:0" proves the latter. TRDD-BLGZTHQ9: the truncated non-owner item is an
    # ASSISTANT item now -- a TOOL/EVENT item over its cap is never shown as a prefix at all,
    # only as a pointer ("tool:0"; a non-notification "event" behaves the same way, see
    # test_injected_event_item_over_its_cap_is_a_pointer_when_room_is_too_small). "assistant"/"control"
    # are conversation kinds -- never scored, never a kept item in production (see
    # `_CONVERSATION_KINDS`) -- so this fixture keeps using "assistant" here purely to exercise
    # the general prefix-truncation path independently of the tool/event carve-out.
    #
    # TRDD-SK490HKU: `max_bytes=1800` pins the room tight enough that the second fill pass
    # cannot afford "tool:0" WHOLE (~625 B) alongside the two owner items and the capped
    # reply -- with no `max_bytes` at all the room is unbounded, and an unbounded room means a
    # Jev-kept over-cap tool item is always admitted whole (see
    # test_injected_tool_item_over_its_cap_is_shown_whole_when_the_room_holds_it),
    # exactly what this fixture exists to rule OUT so the cap mechanics stay testable alone.
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
        it.id: jc.Scores(relevance=0.9, oversized=False, kept=True,
                          )
        for it in items
    }
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_item_bytes=500, non_owner_item_bytes=100, max_bytes=1800,
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
    # as before this parameter existed. TRDD-BLGZTHQ9: an ASSISTANT item, because a tool/event
    # item over the cap is now pointer-only and so could not show which cap applied.
    reply_text = "r" * 600
    items = [_item("reply:0", "assistant", reply_text, turn=0, tokens=10)]
    scores = {"reply:0": jc.Scores(relevance=0.9, oversized=False, kept=True,
                                    )}
    doc = jc.compose(
        items, scores, budget_tokens=8000,
        header={"transcript_path": "/tmp/t.jsonl", "session_key": "s"},
        max_item_bytes=500,
    )
    assert reply_text[:500] in doc
    assert reply_text[:501] not in doc


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
    `transcript_path` (150+ chars here) is embedded in the trailer -- the rendered document
    must NEVER exceed `max_bytes`, and the newest owner message must appear whenever there is
    genuinely enough room for it. TRDD-R9UXOSR5: the owner message reaches `compose()` through
    `conversation` (never scored); at 200 the fixed skeleton alone overflows, so the terminal
    `_render_minimal_fallback` carries a truncated prefix of it; at 2000/6000 the ordinary
    render shows it whole; at 800 the ordinary render fits with the long path in its trailer
    but has no room for the exchange block or any kept item -- the cap holds, no prose."""
    newest_owner_text = "THE NEWEST OWNER MESSAGE CONTENT " * 3  # 99 bytes, no newline
    owner = _item("u-newest:0", "user", newest_owner_text, turn=50)
    conv = [owner]
    filler = [
        _item(f"a{i}:0", "tool", f"filler tool output line {i} " * 20, turn=i, tokens=5)
        for i in range(10)
    ]
    items = filler
    scores = {it.id: _scores(0.5) for it in filler}
    header = {"transcript_path": _LONG_TRANSCRIPT_PATH, "session_key": "s"}  # no digest

    for max_bytes in (1, 50, 200, 800, 2000, 6000):
        doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                         max_bytes=max_bytes, max_item_bytes=700, conversation=conv)
        assert len(doc.encode("utf-8")) <= max_bytes, f"max_bytes={max_bytes} overflowed"

    # Below the fixed skeleton's own cost (measured: ~620 bytes for this path with nothing
    # kept), there is no room for anything at all -- `""` is correct, not a bug.
    tiny_doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                          max_bytes=1, max_item_bytes=700, conversation=conv)
    assert tiny_doc == ""

    # At 200 bytes the fixed skeleton still does not fit -- this exercises the terminal
    # minimal-fallback stage specifically -- yet a truncated prefix of the newest owner
    # message still comes through, with its id still reachable.
    mid_doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                         max_bytes=200, max_item_bytes=700, conversation=conv)
    assert "THE NEWEST" in mid_doc
    assert "u-newest:0" in mid_doc

    # At 2000/6000 the ordinary render (not the fallback) has room for the message whole.
    for max_bytes in (2000, 6000):
        doc = jc.compose(items, scores, budget_tokens=80000, header=header,
                         max_bytes=max_bytes, max_item_bytes=700, conversation=conv)
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
        item.id: jc.Scores(relevance=0.9, oversized=False, kept=True,
                            ),
        elided.id: jc.Scores(relevance=0.1, oversized=False, kept=False,
                              ),
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
        kept.id: jc.Scores(relevance=0.9, oversized=False, kept=True,
                            ),
        **{
            it.id: jc.Scores(relevance=0.1, oversized=False, kept=False,
                              )
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
        "instr:0": jc.Scores(relevance=0.6, oversized=False, kept=True,
                              ),
        "resume:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                               ),
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
        "resume:0": jc.Scores(relevance=0.0, oversized=False, kept=False,
                               ),
        "tool:0": jc.Scores(relevance=0.5, oversized=False, kept=True,
                             ),
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


def _scores(rel: float, *, kept: bool = True) -> jc.Scores:
    return jc.Scores(relevance=rel, oversized=False, kept=kept)


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


def test_select_injected_reserves_floor_before_the_pointer_tier() -> None:
    """The fill order on hand-made exact costs (available=700): the non-owner floor first
    (3 x 150, score order), then the remaining non-owner items while they fit -- the 4th
    (150 inline) fits (600 <= 700), the 5th does not (750 > 700) and becomes a pointer
    (660 <= 700). TRDD-R9UXOSR5: the guaranteed-owner slot and the decision-pointer reserve
    the old fill order interleaved here are retired -- every candidate is now the same tier."""
    def cand(id_: str, kind: jc.ItemKind, turn: int, score: float, inline: int, pointer: int,
             ) -> jc._InjectCandidate:
        return jc._InjectCandidate(id=id_, kind=kind, turn=turn, score=score,
                                   inline_cost=inline, pointer_cost=pointer,
                                   pointer_eligible=True)

    cands = [
        *(cand(f"n{i}", "tool", 10 + i, 0.9 - i / 10, 150, 60) for i in range(5)),
    ]
    sel = jc._select_injected(cands, available=700, max_pointers=12)

    assert sel.kept == ["n0", "n1", "n2", "n3"]
    assert sel.pointers == ["n4"]  # the one that no longer fits inline
    assert sel.hidden == 0
    costs = {c.id: c for c in cands}
    total = (sum(costs[i].inline_cost or 0 for i in sel.kept)
             + sum(costs[i].pointer_cost for i in sel.pointers))
    assert total == 660


def test_injected_tool_item_over_its_cap_is_a_pointer_when_room_is_too_small() -> None:
    """TRDD-BLGZTHQ9: a tool result over `non_owner_item_bytes` used to render as a 350-B
    verbatim prefix plus a pointer -- a few lines of a diff for 3-4x the bytes of the pointer,
    whose preview already says what it is. It is now never a prefix. TRDD-SK490HKU: "over the
    cap" no longer means "pointer, unconditionally" -- the second fill pass admits an over-cap,
    Jev-kept item WHOLE when the room holds its exact cost (see the sibling `..._when_the_room_
    holds_it` test); this fixture pins the OTHER half, room too small for `big:0` (829 B) even
    though `small:0` (which fits the ordinary 350-B cap) is still shown whole beside it."""
    big_text = "".join(f"-    old line {i} of the patched function\n" for i in range(20))
    small_text = "commit 8a623a28: fix the injected selection, all 194 tests green"
    items = [
        _item("big:0", "tool", big_text, turn=1),
        _item("small:0", "tool", small_text, turn=2),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=1000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert "-- tool big:0 --" not in doc
    assert "old line 1 of" not in doc  # not even the first lines as a prefix
    assert "[[elided id=big:0 " in doc.split("\n## Elided\n", 1)[1]
    assert f"-- tool small:0 --\n{small_text}\n" in doc


def test_injected_tool_item_over_its_cap_is_shown_whole_when_the_room_holds_it() -> None:
    """TRDD-SK490HKU (advisor report 20260925_054459, item 1): the second fill pass spends
    leftover room on a Jev-kept, over-cap tool item WHOLE, never a prefix (TRDD-BLGZTHQ9 still
    holds -- see the sibling `..._when_room_is_too_small` test for the case it does NOT fit).
    Same fixture as that test, a room large enough (4,000 B) for `big:0` (829 B) whole too."""
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

    assert f"-- tool big:0 --\n{big_text}\n" in doc  # whole, not a prefix
    assert f"-- tool small:0 --\n{small_text}\n" in doc
    assert "[[elided id=big:0 " not in doc


def test_injected_second_pass_whole_admission_is_exact_to_the_byte() -> None:
    """TRDD-SK490HKU: the exactness invariant `_select_injected`'s own docstring promises now
    also covers the second fill pass -- `max_bytes` at exactly a single over-cap tool item's
    whole cost shows it whole; one byte less drops it to a pointer, with no backstop stage
    (no truncated-prefix marker) -- the one check that fails if the selection (`whole_cost`)
    and the render (`relaxed_cap`) ever disagree, per advisor report 20260925_054459 item (1)
    point 3. 1163 is the exact boundary for this fixture (measured, not derived from an
    unconstrained render's own byte length): `_select_injected`'s `available` is sized off a
    PESSIMISTIC "every item hidden" count line (the monotone-fit comment above `baseline` in
    `compose`), so a doc rendered under no cap at all is shorter than the `max_bytes` its own
    selection actually needed -- reusing that shorter length as `max_bytes` would under-fill."""
    big_text = "".join(f"-    old line {i} of the patched function\n" for i in range(20))
    items = [
        _item("big:0", "tool", big_text, turn=1),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    kwargs: dict[str, Any] = {"budget_tokens": 8000, "header": _H, "max_item_bytes": 700,
                              "non_owner_item_bytes": 350}
    exact = 1163

    doc = jc.compose(items, scores, max_bytes=exact, **kwargs)
    assert f"-- tool big:0 --\n{big_text}\n" in doc

    tight = jc.compose(items, scores, max_bytes=exact - 1, **kwargs)
    assert f"-- tool big:0 --\n{big_text}\n" not in tight
    assert "-- tool big:0 --" not in tight  # not even a truncated prefix
    assert "[[elided id=big:0 " in tight.split("\n## Elided\n", 1)[1]


def test_injected_second_pass_admits_the_highest_scored_whole_item_first() -> None:
    """TRDD-SK490HKU (advisor report 20260925_054459, item 1 point 2, "score-descending" over
    "smallest-first" -- consistent with steps 2 and 5): two over-cap tool items of equal size,
    room enough for exactly one WHOLE -- the higher-scored one is admitted, the lower-scored
    one stays a pointer, regardless of which was declared first."""
    text_hi = "".join(f"-    old line {i} of function A\n" for i in range(20))
    text_lo = "".join(f"-    old line {i} of function B\n" for i in range(20))
    items = [
        _item("hi:0", "tool", text_hi, turn=1),
        _item("lo:0", "tool", text_lo, turn=2),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {"hi:0": _scores(0.95), "lo:0": _scores(0.5), "newest:0": _scores(0.9)}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=1200,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert f"-- tool hi:0 --\n{text_hi}\n" in doc  # higher score: admitted whole
    assert "-- tool lo:0 --" not in doc  # lower score: still a pointer, no prefix either
    assert "[[elided id=lo:0 " in doc.split("\n## Elided\n", 1)[1]


def test_injected_second_pass_leaves_max_elided_pointers_capping_the_rest() -> None:
    """TRDD-SK490HKU: the second fill pass and `max_elided_pointers` are two separate limits on
    two separate things -- how many over-cap items fit WHOLE (byte-bounded, step 6b) vs how many
    of the REST get an ordinary pointer at all (count-bounded, step 7). Six Jev-kept, over-cap
    tool items and a room that fits exactly four whole: the two left over are still subject to
    `max_elided_pointers=2` (both get one here, at the limit; a `max_elided_pointers` of e.g. 1
    would additionally have to fall back to the "N more items not listed" count line for the
    sixth) -- rewritten because the pre-fix pointer-only design left this cap with nothing else
    to prove in the injected copy for THIS item shape (review of this fix, advisor turn 2)."""
    tool_items = [
        _item(f"tool{i}:0", "tool", f"result number {i}: " + ("x" * 500), turn=1 + i)
        for i in range(6)
    ]
    newest = _item("newest:0", "user", "hi", turn=100)
    items = [*tool_items, newest]
    scores = {it.id: _scores(0.9 - i * 0.01) for i, it in enumerate(tool_items)}
    scores["newest:0"] = _scores(0.9)
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=3000,
                     max_item_bytes=700, non_owner_item_bytes=350, max_elided_pointers=2)

    whole = [it.id for it in tool_items if f"-- tool {it.id} --\n" in doc]
    assert whole == ["tool0:0", "tool1:0", "tool2:0", "tool3:0"]  # highest score first
    elided_section = doc.split("\n## Elided\n", 1)[1]
    pointer_ids = re.findall(r"\[\[elided id=(tool\d:0) ", elided_section)
    assert pointer_ids == ["tool4:0", "tool5:0"]  # exactly `max_elided_pointers`, none hidden
    assert "more items not listed" not in doc


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



def test_injected_selection_is_exact_at_the_byte_boundary() -> None:
    """TRDD-BLGZTHQ9 exactness, re-pinned for TRDD-R9UXOSR5 (the decision-pointer fixture the
    old version used is retired with the question): the render is the fixed lines plus the
    exact cost of every selected item, so a `max_bytes` equal to the render shows the whole
    selection (12 inline `work` items + the over-cap `big` as a pointer), and ONE byte less
    costs exactly one inline slot -- the last-selected, lowest-priority `work0:0` becomes a
    pointer and `big`'s pointer moves into the count line -- with no backstop stage running
    (no digest-truncation note, no minimal fallback)."""
    newest = _item("newest:0", "user", "carry on", turn=50)
    work = [_item(f"work{i}:0", "tool", _WORK.format(i=i), turn=30 + i, tokens=5)
            for i in range(12)]
    big = _item("big:0", "tool", "B" * 1500, turn=45)  # over its 350-B cap: pointer-only
    items = [*work, big]
    scores = {it.id: _scores(0.9) for it in items}
    kwargs: dict[str, Any] = {"budget_tokens": 8000, "header": _H, "max_item_bytes": 700,
                              "non_owner_item_bytes": 350, "conversation": [newest]}

    full = jc.compose(items, scores, max_bytes=2350, **kwargs)
    inline, pointed = _shown_ids(full, items)
    assert inline == {f"work{i}:0" for i in range(12)}
    assert pointed == {"big:0"}
    exact = len(full.encode("utf-8"))
    assert exact <= 2350

    tight = jc.compose(items, scores, max_bytes=exact - 1, **kwargs)
    tight_inline, tight_pointed = _shown_ids(tight, items)
    assert inline - tight_inline == {"work0:0"}  # exactly one inline slot lost
    assert {"work0:0"} <= tight_pointed  # and it is recoverable as a pointer
    assert len(tight.encode("utf-8")) <= exact - 1
    assert jc._DIGEST_TRUNCATED_NOTE not in tight and jc._MINIMAL_FIXED_LINE not in tight
    assert _count_line_n(tight) == 1
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


def test_injected_event_item_over_its_cap_is_a_pointer_when_room_is_too_small() -> None:
    """TRDD-BLGZTHQ9 extension: the fix for an over-cap "tool" item (see
    `test_injected_tool_item_over_its_cap_is_a_pointer_when_room_is_too_small`) did not cover
    every other non-owner kind -- an `event` item that is NOT a `<task-notification>` (e.g. a
    cross-session peer message) took the generic `render()` branch with no `kind` guard at all
    and was cut to a truncated prefix plus a pointer, 4 real instances measured on a live
    transcript (reports/compaction-replacement/20260925_025424+0200-trdd-dqxmnd59-v3-gaps-
    closed.md). It is never a prefix now. TRDD-SK490HKU: the sibling `..._when_the_room_holds_
    it` test pins the OTHER half -- room enough admits `big:0` WHOLE instead of a pointer; this
    fixture keeps the room too small (1,600 B against `big:0`'s 1,786-B whole cost)."""
    big_text = "".join(
        f"peer message line {i}: a real cross-session update about the shared task\n"
        for i in range(20)
    )
    small_text = ("peer: short update, all clear -- the shared task finished green, "
                  "nothing else pending on this side")
    items = [
        _item("big:0", "event", big_text, turn=1),
        _item("small:0", "event", small_text, turn=2),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=1600,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert "-- event big:0 --" not in doc
    assert "peer message line 1" not in doc  # not even the first lines as a prefix
    assert "[[elided id=big:0 " in doc.split("\n## Elided\n", 1)[1]
    assert f"-- event small:0 --\n{small_text}\n" in doc


def test_injected_event_item_over_its_cap_is_shown_whole_when_the_room_holds_it() -> None:
    """TRDD-SK490HKU: same fixture as `..._when_room_is_too_small`, a room large enough (4,000
    B) for `big:0` (1,786 B whole cost) to be admitted whole by the second fill pass -- the
    event-kind counterpart of `test_injected_tool_item_over_its_cap_is_shown_whole_when_the_
    room_holds_it`, proving the pass is not accidentally tool-only."""
    big_text = "".join(
        f"peer message line {i}: a real cross-session update about the shared task\n"
        for i in range(20)
    )
    small_text = ("peer: short update, all clear -- the shared task finished green, "
                  "nothing else pending on this side")
    items = [
        _item("big:0", "event", big_text, turn=1),
        _item("small:0", "event", small_text, turn=2),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {it.id: _scores(0.9) for it in items}
    doc = jc.compose(items, scores, budget_tokens=8000, header=_H, max_bytes=4000,
                     max_item_bytes=700, non_owner_item_bytes=350)

    assert f"-- event big:0 --\n{big_text}\n" in doc  # whole, not a prefix
    assert f"-- event small:0 --\n{small_text}\n" in doc
    assert "[[elided id=big:0 " not in doc


def test_injected_over_cap_tool_and_event_items_out_render_is_byte_identical() -> None:
    """TRDD-BLGZTHQ9 extension: the pointer-only fix is injected-only (`max_item_bytes is not
    None`) -- `--out` (`max_item_bytes=None`, no `max_bytes`) must keep showing every item whole,
    unaffected by this change, for both the "tool" kind the original card covered and the "event"
    kind this extension adds."""
    big_tool = "".join(f"-    old line {i} of the patched function\n" for i in range(20))
    big_event = "".join(
        f"<cross-session-message from=\"peer\">line {i} of a long peer message</cross-session-message>\n"
        for i in range(20)
    )
    items = [
        _item("big_tool:0", "tool", big_tool, turn=1),
        _item("big_event:0", "event", big_event, turn=2),
        _item("newest:0", "user", "hi", turn=3),
    ]
    scores = {it.id: _scores(0.9) for it in items}

    doc = jc.compose(items, scores, budget_tokens=8000, header=_H)

    assert f"-- tool big_tool:0 --\n{big_tool}\n" in doc
    assert f"-- event big_event:0 --\n{big_event}\n" in doc


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
        "oversz:0": jc.Scores(relevance=0.9, oversized=True, kept=True,
                              ),
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



def test_injected_long_newest_message_leaves_room_for_the_non_owner_floor() -> None:
    """Amendment S4's subject, re-pinned for TRDD-R9UXOSR5: a ~1,500-byte newest owner message
    used to compete with the non-owner floor for a 3,900-byte room (the old 35% cap
    `_INJECT_NEWEST_OWNER_SHARE` went with the decision question -- the owner message is a
    `conversation` exchange now, never a scored item). What must hold: the newest owner
    message renders verbatim, capped at `NEWEST_OWNER_ITEM_BYTES` or shrunk to its share of
    the room by `_select_exchanges`, while the non-owner floor still fits beside it -- at
    `max_bytes=3900` the message renders at its full 1,500-byte cap with all four work items
    inline; at 2600 it is shrunk to ~1,110 bytes and the floor still holds."""
    newest_text = "please finish the injected selection and re-render every transcript. " * 22
    assert 1450 <= len(newest_text) <= 1550
    conv = [_item("newest:0", "user", newest_text, turn=30)]
    work = [_item(f"work{i}:0", "tool", _WORK.format(i=i), turn=10 + i, tokens=5)
            for i in range(4)]
    items = work
    scores = {it.id: _scores(0.9) for it in work}

    doc = jc.compose(items, scores, budget_tokens=80000, header=_H, max_bytes=3900,
                     max_item_bytes=700, non_owner_item_bytes=350, conversation=conv)
    assert len(doc.encode("utf-8")) <= 3900
    assert jc._DIGEST_TRUNCATED_NOTE not in doc and jc._MINIMAL_FIXED_LINE not in doc
    newest_body = doc.split("-- user newest:0 --\n", 1)[1].split("\n[[elided id=newest:0 ", 1)[0]
    assert len(newest_body) <= jc.NEWEST_OWNER_ITEM_BYTES
    inline, pointed = _shown_ids(doc, items)
    assert not pointed
    assert len(inline) >= jc._NON_OWNER_FLOOR

    tight = jc.compose(items, scores, budget_tokens=80000, header=_H, max_bytes=2600,
                       max_item_bytes=700, non_owner_item_bytes=350, conversation=conv)
    assert len(tight.encode("utf-8")) <= 2600
    tight_newest = tight.split("-- user newest:0 --\n", 1)[1].split("\n[[elided id=newest:0 ",
                                                                    1)[0]
    assert len(tight_newest) < len(newest_body)  # shrunk with the room, not evicted
    tight_inline, _ = _shown_ids(tight, items)
    assert len(tight_inline) >= jc._NON_OWNER_FLOOR
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

    conversation, scored, _pre_boundary = jc.split_conversation(items, window)
    doc = jc.compose(scored, {}, budget_tokens=8000,
                      header={"transcript_path": str(path), "session_key": "s"},
                      conversation=conversation, conversation_summary=window.summary)
    assert "�" in doc  # reaches the final document, sanitized -- never dropped, never raw


def test_compose_sanitizes_every_str_parameter_at_one_boundary() -> None:
    """TRDD-DQXMND59 stage 3b item B: `compose()` used to trust each str-shaped source to have
    sanitized its own lone surrogates BEFORE reaching it (`Item.__post_init__` for item text,
    the `window.summary` call site for the conversation summary) -- but `header`'s own string
    values (`transcript_path`, `session_key`, `digest`) and `full_context_path` had no such
    guard at all, since neither is an `Item`. A lone (unpaired) UTF-16 surrogate in ANY of
    `header`'s values, `full_context_path`, or `conversation_summary` used to reach a bare
    `.encode("utf-8")`/f-string downstream and raise `UnicodeEncodeError`. Fails on HEAD (before
    the entry-point sanitization this item adds) for every one of these parameters; passes
    after, with each replaced by U+FFFD in the final document -- never silently dropped."""
    lone = "before \ud83d after"
    doc = jc.compose(
        [], {}, budget_tokens=8000,
        header={"transcript_path": lone, "session_key": lone, "digest": lone},
        full_context_path=lone, conversation=[], conversation_summary=lone,
    )
    assert doc.encode("utf-8")  # must not raise UnicodeEncodeError
    assert "\ud83d" not in doc
    assert doc.count("�") >= 4  # transcript_path, session_key, digest, full_context_path/summary


def test_split_conversation_drops_unpreserved_pre_boundary_prose_only(tmp_path: Path) -> None:
    """TRDD-D7RLXAN1 test 3, extended by TRDD-350W5II2: conversation = live owner/assistant/
    control messages (after the boundary, or preserved across it); scored = LIVE tool and event
    items only -- a pre-boundary one not itself preserved by uuid is dropped from `scored` too
    (350W5II2: `is_live` now gates tool/event items the same way it already gated prose), and
    counted in `pre_boundary` rather than silently vanishing. Only unpreserved pre-boundary prose
    and unpreserved pre-boundary tool/event items are in neither list -- the summary stands in
    for the prose, `expand <id>` still reaches the tool/event item by uuid. Also pins the
    turn/boundary alignment (the card's "most likely way it is wrong")."""
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
    conversation, scored, pre_boundary = jc.split_conversation(items, window)

    assert [it.id for it in conversation] == ["keep:0", "nu:0", "na:0", "nc:0"]
    assert [it.kind for it in conversation] == ["user", "user", "assistant", "control"]
    # "ptr:0" (the pre-boundary tool result) is dropped: its OWN entry uuid ("ptr") was never
    # preserved -- only "ptu" (the tool_use half) was, and preservation is checked against the
    # item's own id, not its paired entry. Fails on HEAD, where `scored` kept it regardless.
    assert [it.id for it in scored] == ["ntr:0"]
    assert pre_boundary == 1
    assert {it.id for it in items} - {it.id for it in conversation + scored} == {
        "pu:0", "pa:0", "ptr:0",
    }
    assert window.summary == "THE SUMMARY"
    # No boundary at all: every message is live, `pre_boundary` is 0.
    no_boundary, no_boundary_scored, no_boundary_pre = jc.split_conversation(
        items, jc.ConversationWindow()
    )
    assert [it.id for it in no_boundary] == ["pu:0", "pa:0", "keep:0", "nu:0", "na:0", "nc:0"]
    assert [it.id for it in no_boundary_scored] == ["ptr:0", "ntr:0"]
    assert no_boundary_pre == 0


def test_pre_boundary_tool_item_is_not_scored_or_rendered_a_live_one_is(tmp_path: Path) -> None:
    """TRDD-350W5II2 test 1: a pre-boundary tool item never reaches `score_items` (it is absent
    from `scored`, the only list `score_items` is called on -- see `jev_compact.py::cmd_compact`)
    and its text never reaches `compose()`'s output; a live (post-boundary) one is both scored
    and rendered. Fails on HEAD, where `scored` (and so the composed doc) carried both."""
    path = _jsonl(tmp_path, [
        *_tool_pair("ptu", "ptr", "t1", "PRE BOUNDARY TOOL TEXT"),
        _user("keep", "owner message"),
        _boundary("b", "s", ["keep"]),
        _summary("s", "THE SUMMARY"),
        *_tool_pair("ntu", "ntr", "t2", "POST BOUNDARY TOOL TEXT"),
    ])
    window = jc.ConversationWindow()
    items = _ei(path, window=window)
    conversation, scored, pre_boundary = jc.split_conversation(items, window)

    scored_ids = {it.id for it in scored}
    assert "ptr:0" not in scored_ids  # never sent to Jev
    assert "ntr:0" in scored_ids
    assert pre_boundary == 1

    doc = jc.compose(scored, {"ntr:0": _scores(0.9)}, budget_tokens=8000, header=_H,
                     conversation=conversation, conversation_summary=window.summary)
    assert "PRE BOUNDARY TOOL TEXT" not in doc  # not rendered -- not even as a pointer
    assert "POST BOUNDARY TOOL TEXT" in doc


def test_no_boundary_scores_every_tool_and_event_item_as_before(tmp_path: Path) -> None:
    """TRDD-350W5II2 test 2: a session that was never compacted (no `compact_boundary` line at
    all) has `window.boundary_turn is None`, so `is_live` is True unconditionally -- every
    tool/event item is scored exactly like before this change, and `pre_boundary` is 0."""
    path = _jsonl(tmp_path, [
        _user("u1", "owner message"),
        _assistant("a1", "assistant reply"),
        *_tool_pair("tu1", "tr1", "t1", "tool output one"),
        *_tool_pair("tu2", "tr2", "t2", "tool output two"),
    ])
    window = jc.ConversationWindow()
    items = _ei(path, window=window)
    assert window.boundary_turn is None
    conversation, scored, pre_boundary = jc.split_conversation(items, window)
    assert [it.id for it in scored] == ["tr1:0", "tr2:0"]
    assert pre_boundary == 0


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
    conversation, scored, pre_boundary = jc.split_conversation(items, window)
    assert [it.id for it in conversation] == ["a1:0"]
    # TRDD-350W5II2: "tr:0" is the pre-boundary tool result and its own uuid ("tr") was never
    # preserved (only "a1" was) -- dropped from `scored`, counted in `pre_boundary`. Fails on
    # HEAD, where `scored` still kept every pre-boundary tool item.
    assert [it.id for it in scored] == []
    assert pre_boundary == 1

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



_STATUS_REPLY = "janitor heartbeat\n1 background worker running; newest activity under 1 min ago"


def _status_conversation() -> list[jc.Item]:
    return [_item("owner:0", "user", "OWNER ask", turn=0),
            _item("real:0", "assistant", "REAL WORK NOTE alpha", turn=1)] + [
        _item(f"s{i}:0", "assistant", _STATUS_REPLY, turn=2 + i) for i in range(9)]


def test_select_exchanges_caps_heartbeat_status_run_in_the_injected_view() -> None:
    """TRDD-U119W52S: 9 consecutive status replies must not push a real work note out of the
    injected exchanges -- only the newest 2 are shown and `shown` matches the blocks."""
    conversation = _status_conversation()
    cap = jc.DEFAULT_INJECT_ITEM_BYTES

    def cost(it: jc.Item, c: int) -> int:
        return len(jc._exchange_block(it, c).encode("utf-8")) + 1

    marker = len(f"[{len(conversation)} messages between these are only in the full copy]"
                 .encode("utf-8")) + 1
    budget = (cost(conversation[0], jc.NEWEST_OWNER_ITEM_BYTES) + marker
              + cost(conversation[1], cap) + 2 * cost(conversation[-1], cap))
    blocks, shown = jc._select_exchanges(conversation, budget)
    joined = "\n".join(blocks)

    assert "REAL WORK NOTE alpha" in joined
    assert joined.count(_STATUS_REPLY) == 2
    assert shown == sum(1 for b in blocks if b.startswith("-- "))


def test_full_render_keeps_every_heartbeat_status_reply() -> None:
    """TRDD-U119W52S: the cap is for the injected view only; the full copy stays verbatim."""
    doc = jc.compose([], {}, budget_tokens=8000, header=_H, conversation=_status_conversation())
    assert doc.count(_STATUS_REPLY) == 9
