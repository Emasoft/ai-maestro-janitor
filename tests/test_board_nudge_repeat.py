"""W4IZA704: an unchanged board with a `dev` card re-nudges every 1800 s, at most 4 times.

A card in `dev` claims work in flight; a session that idled over it must hear again, but a
long-lived `dev` card makes the condition permanently true, so the repeat count is the only
bound. A `todo`-only board keeps the once-only behaviour. Real dispatch phase, real tmp
project and state dir; time is moved by rewriting the stamp, never by sleeping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

from test_board_nudge_lease import _fire  # type: ignore[import-not-found]  # noqa: E402
from test_dispatch_phases import (  # type: ignore[import-not-found]  # noqa: E402,F401
    _import_dispatch,
    _make_user_idle,
    _write_trdd,
    env_isolation,
)

_STAMP = "keep-going-board-nudge-stamp.json"
_AGE = 1801


def _setup(env_isolation: dict, column: str):  # noqa: F811 -- the imported fixture
    dispatch = _import_dispatch()
    import state

    state.init_state()
    _make_user_idle(state, ago_s=3700)
    _write_trdd(env_isolation["project"], "REPEAT01", column)
    return dispatch, state


def _age_stamp(state, seconds: int) -> None:
    """Pretend the last board nudge was `seconds` ago."""
    path = state.state_dir() / _STAMP
    stamp = json.loads(path.read_text(encoding="utf-8"))
    stamp["nudged_at"] -= seconds
    path.write_text(json.dumps(stamp), encoding="utf-8")


def test_unchanged_dev_board_is_quiet_immediately_after_the_first_nudge(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """No repeat storm: a second fire right after the first stays quiet."""
    dispatch, _ = _setup(env_isolation, "dev")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    assert _fire(dispatch, monkeypatch, "s") == ""


def test_unchanged_dev_board_repeats_after_1800s_and_points_at_the_next_card(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """After 1801 s the same dev board nudges again, and the nudge says to pull the next card."""
    dispatch, state = _setup(env_isolation, "dev")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    _age_stamp(state, _AGE)
    out = _fire(dispatch, monkeypatch, "s")
    assert out.startswith("[janitor-resume]")
    assert "trddgrep next" in out


def test_repeats_stop_after_four_and_a_signature_change_rearms(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """Four repeats, then quiet 1801 s later; a new card changes the signature and emits again."""
    dispatch, state = _setup(env_isolation, "dev")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    for _ in range(4):
        _age_stamp(state, _AGE)
        assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    _age_stamp(state, _AGE)
    assert _fire(dispatch, monkeypatch, "s") == ""
    _write_trdd(env_isolation["project"], "REPEAT02", "dev")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")


def test_todo_only_board_never_repeats(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """Without a dev card the once-only behaviour stays: 1801 s later it is still quiet."""
    dispatch, state = _setup(env_isolation, "todo")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    _age_stamp(state, _AGE)
    assert _fire(dispatch, monkeypatch, "s") == ""


def test_stamp_without_nudged_at_does_not_repeat_at_once(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """An old-format stamp (no nudged_at) gets nudged_at=now written and stays quiet."""
    dispatch, state = _setup(env_isolation, "dev")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    path = state.state_dir() / _STAMP
    stamp = json.loads(path.read_text(encoding="utf-8"))
    del stamp["nudged_at"], stamp["repeats"]
    path.write_text(json.dumps(stamp), encoding="utf-8")
    assert _fire(dispatch, monkeypatch, "s") == ""
    assert "nudged_at" in json.loads(path.read_text(encoding="utf-8"))



def _exhaust_cap(dispatch, monkeypatch, state) -> None:
    """First nudge plus the 4 allowed repeats, then confirm the board is quiet."""
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    for _ in range(dispatch._BOARD_NUDGE_MAX_REPEATS):
        _age_stamp(state, _AGE)
        assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    _age_stamp(state, _AGE)
    assert _fire(dispatch, monkeypatch, "s") == ""


def test_signature_change_after_the_cap_resets_the_repeat_count(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """Cap, then a new card, then an unchanged fire 1801 s on repeats again (count was reset to 0)."""
    dispatch, state = _setup(env_isolation, "dev")
    _exhaust_cap(dispatch, monkeypatch, state)
    _write_trdd(env_isolation["project"], "REPEAT02", "dev")
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    assert json.loads((state.state_dir() / _STAMP).read_text(encoding="utf-8"))["repeats"] == 0
    _age_stamp(state, _AGE)
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")


def test_newer_user_prompt_after_the_cap_resets_the_repeat_count(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """Cap, then the owner types (newer prompt epoch): nudged again, count 0, and it repeats later."""
    dispatch, state = _setup(env_isolation, "dev")
    _exhaust_cap(dispatch, monkeypatch, state)
    _make_user_idle(state, ago_s=3000)  # a newer prompt epoch than the one stamped, still idle
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")
    assert json.loads((state.state_dir() / _STAMP).read_text(encoding="utf-8"))["repeats"] == 0
    _age_stamp(state, _AGE)
    assert _fire(dispatch, monkeypatch, "s").startswith("[janitor-resume]")


def test_pending_agent_branch_does_not_carry_the_pull_next_card_hint(
    env_isolation: dict, monkeypatch  # noqa: F811
) -> None:
    """With a stalled pending agent the nudge is emitted but the zero-agent hint is absent."""
    import time

    import pending_agents
    from test_dispatch_phases import _touch_transcript  # type: ignore[import-not-found]

    dispatch, state = _setup(env_isolation, "dev")
    transcript = state.state_dir() / "agent-stalled.jsonl"
    old = time.time() - 20 * 60
    _touch_transcript(transcript, mtime=old, tool_use=False)
    pending_agents.add("agent-stalled", description="stuck worker", transcript=str(transcript), now=int(old))
    out = _fire(dispatch, monkeypatch, "s")
    assert out.startswith("[janitor-resume]")
    assert "trddgrep next" not in out
