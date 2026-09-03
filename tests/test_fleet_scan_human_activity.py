"""`fleet_scan.human_activity_age_from_tail` — TRDD-O7UCNNN2.

A heartbeat cron fire is a real `type: user` prompt (carrying `scheduledFireId`) answered by a
substantive assistant turn, so `substantive_age_from_tail` correctly sees an armed session as
perpetually active. The external-clear lane needs the opposite bias: discount whole heartbeat
turns so an armed session can still be diagnosed idle. These tests pin the separation between
the two functions on synthetic transcript tails — never the real ``~/.claude`` tree.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import fleet_scan as fs  # noqa: E402


def _iso(epoch: int) -> str:
    """A transcript-style UTC timestamp."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _prompt_line(epoch: int, *, scheduled: bool) -> str:
    rec = {
        "type": "user",
        "timestamp": _iso(epoch),
        "message": {"role": "user", "content": "do the thing"},
    }
    if scheduled:
        rec["scheduledFireId"] = "fire-1"
        rec["scheduledTaskId"] = "task-1"
        rec["promptSource"] = "cron"
        rec["userType"] = "external"
    return json.dumps(rec)


def _assistant_line(epoch: int) -> str:
    return json.dumps({"type": "assistant", "timestamp": _iso(epoch), "message": {}})


def _tool_result_line(epoch: int, tid: str = "toolu_1") -> str:
    return json.dumps(
        {
            "type": "user",
            "timestamp": _iso(epoch),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid}]},
        }
    )


def test_human_turn_then_three_heartbeat_turns_gives_the_human_age() -> None:
    """A human prompt followed by three heartbeat turns: `human_activity_age_from_tail` must
    return the human turn's age; `substantive_age_from_tail` (unchanged) must return the newest
    heartbeat turn's age — asserted side by side so the separation is pinned."""
    t0 = 1_784_300_000
    now = t0 + 400
    tail = [
        _prompt_line(t0, scheduled=False),
        _assistant_line(t0 + 5),
        _prompt_line(t0 + 100, scheduled=True),
        _assistant_line(t0 + 105),
        _prompt_line(t0 + 200, scheduled=True),
        _assistant_line(t0 + 205),
        _prompt_line(t0 + 300, scheduled=True),
        _assistant_line(t0 + 305),
    ]

    human_age = fs.human_activity_age_from_tail(tail, now=now, fallback_age=9999)
    sub_age, _trailing = fs.substantive_age_from_tail(tail, now=now, fallback_age=9999)

    assert human_age == now - (t0 + 5), "must ignore all three heartbeat turns"
    assert sub_age == now - (t0 + 305), "substantive age must stay unchanged (liveness signal)"
    assert human_age > sub_age, "the whole point: human idle time exceeds substantive idle time"


def test_all_heartbeat_tail_returns_the_oldest_scheduled_prompt_age() -> None:
    """No human turn anywhere: the tail is exhausted while every turn seen was scheduled, so
    the conservative answer is the OLDEST scheduled prompt's age — "at least this idle"."""
    t0 = 1_784_300_000
    now = t0 + 400
    tail = [
        _prompt_line(t0, scheduled=True),
        _assistant_line(t0 + 5),
        _prompt_line(t0 + 100, scheduled=True),
        _assistant_line(t0 + 105),
    ]

    human_age = fs.human_activity_age_from_tail(tail, now=now, fallback_age=9999)

    assert human_age == now - t0, "must use the OLDEST scheduled prompt, not the newest"


def test_tool_result_records_never_count_as_prompts() -> None:
    """A heartbeat turn's tool_result records (also `type: user`) must not be mistaken for a
    non-scheduled prompt — the whole heartbeat turn, tool results included, is skipped."""
    t0 = 1_784_300_000
    now = t0 + 400
    tail = [
        _prompt_line(t0, scheduled=False),
        _assistant_line(t0 + 5),
        _prompt_line(t0 + 100, scheduled=True),
        _assistant_line(t0 + 101),
        _tool_result_line(t0 + 102),
        _assistant_line(t0 + 105),
    ]

    human_age = fs.human_activity_age_from_tail(tail, now=now, fallback_age=9999)

    assert human_age == now - (t0 + 5), "the tool_result inside the heartbeat turn must not leak"


def test_no_prompt_at_all_falls_back_to_substantive_age() -> None:
    """A tail with no `user` record whatsoever (unknown shape) must degrade to the substantive
    age rather than guess — the same fail-safe bias `substantive_age_from_tail` uses."""
    t0 = 1_784_300_000
    now = t0 + 400
    tail = [_assistant_line(t0), _assistant_line(t0 + 50)]

    human_age = fs.human_activity_age_from_tail(tail, now=now, fallback_age=9999)
    sub_age, _trailing = fs.substantive_age_from_tail(tail, now=now, fallback_age=9999)

    assert human_age == sub_age


def test_instance_defaults_human_active_true() -> None:
    """`human_active` defaults to `True` (busy) so every pre-existing `Instance(...)` call site
    that predates this field stays valid AND conservative — a caller that never learns better
    must not accidentally treat an unscored instance as clear-eligible."""
    inst = fs.Instance(
        pid=1,
        command="claude",
        tty="ttys000",
        project_root="/tmp/proj",
        terminal={},
        diagnosis="ok",
        recovery=None,
        dispatch_age_s=None,
        active=False,
        transcript_age_s=None,
    )
    assert inst.human_active is True
    assert inst.human_age_s is None


def _interrupt_line(epoch: int) -> str:
    """The transcript record Claude Code writes for an ESC interrupt — an ordinary
    `type: user` record with no `scheduledFireId`, so `_is_prompt_record` alone cannot
    tell it apart from a genuine human-typed prompt."""
    return json.dumps({
        "type": "user",
        "timestamp": _iso(epoch),
        "message": {"role": "user", "content": "[Request interrupted by user]"},
    })


def test_interrupt_record_never_counts_as_a_human_turn() -> None:
    """TRDD-L32WC0H7 / F6 derived: the daemon's own `esc_nudge` produces a
    `[Request interrupted by user]` record. `human_activity_age_from_tail` must NOT
    read that as the user coming back — only a real prompt after it counts."""
    t0 = 1_784_300_000
    tail = [
        _prompt_line(t0, scheduled=False),          # a real human prompt, 500s ago
        _assistant_line(t0 + 5),                    # the reply to it, 495s ago
        _interrupt_line(t0 + 400),                   # the daemon's ESC, 100s ago
    ]
    now = t0 + 500
    age = fs.human_activity_age_from_tail(tail, now=now, fallback_age=99999)
    assert age == 495, "the interrupt record must be skipped, not read as fresh activity"


def test_interrupt_record_with_real_reply_still_counts_the_reply() -> None:
    """A real assistant reply AFTER the interrupt record is still substantive activity —
    only the interrupt record ITSELF is excluded, not everything after it."""
    t0 = 1_784_300_000
    tail = [
        _prompt_line(t0, scheduled=False),
        _interrupt_line(t0 + 10),
        _assistant_line(t0 + 20),                    # real work resumed after the ESC
    ]
    now = t0 + 30
    age = fs.human_activity_age_from_tail(tail, now=now, fallback_age=99999)
    assert age == 10, "the assistant turn after the interrupt record is real activity"
