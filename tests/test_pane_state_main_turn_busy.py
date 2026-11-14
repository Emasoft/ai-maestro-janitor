"""Tests for `pane_state.main_turn_busy` — "is the MAIN turn still running?" (issues #355, #356).

The clear chain used to type `/clear` into a pane whose main turn was still running: the input
field is empty mid-turn, so the injector's "field empty" rule passed, Claude Code QUEUED the
command, and it ran at the next turn boundary — 19 minutes later in #355, after the chain had
given up. `main_turn_busy` is the gate that stops that. It is deliberately NOT `status.kind !=
IDLE`: `StatusKind.WORKING` is also returned for background-agent rows alone (`◯ agent-1 ...`)
while the main turn is idle, and that must not block a clear.

Pure-function truth table over the captured/synthetic frames in `tests/fixtures/pane_frames/` —
real values, no mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pane_state as ps  # type: ignore[import-not-found]  # noqa: E402

_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"

# (fixture, expected verdict). True = main turn busy, False = idle, None = cannot be read.
_CASES: list[tuple[str, bool | None]] = [
    # IDLE prompts: nothing to wait for.
    ("synthetic-idle-empty-field.txt", False),
    ("synthetic-idle-text-typed-bypass-off.txt", False),
    ("real-quoted-reply-idle.txt", False),
    ("real-prompt-echo-idle.txt", False),
    ("real-esc-restored-prompt.txt", False),
    # A finished turn leaves its `done` row on screen; a stale row is not a running turn.
    ("synthetic-done-row-idle.txt", False),
    ("synthetic-stale-glyph-row-then-done-row.txt", False),
    # Background-agent rows only: parse() says WORKING, the main turn is idle.
    ("synthetic-agents-running-context-pct.txt", False),
    # A running main-turn status row.
    ("real-calm-working.txt", True),
    ("synthetic-working-spinner.txt", True),
    # Every other busy status kind.
    ("synthetic-compacting-with-queued.txt", True),
    ("synthetic-reloading.txt", True),
    ("synthetic-awaiting-permission.txt", True),
    ("synthetic-awaiting-model-confirm.txt", True),
    ("synthetic-awaiting-ask-user-menu.txt", True),
    ("real-rewind-picker.txt", True),
    ("synthetic-api-error.txt", True),
    ("real-api-error-400-banner.txt", True),
    ("real-wedged-fable-limit.txt", True),
    ("real-wedged-session-limit.txt", True),
    ("real-wedged-rate-limit-429.txt", True),
    ("synthetic-session-limit-terminal.txt", True),
    # Unreadable: never a verdict.
    ("synthetic-garbage-random-text.txt", None),
    ("synthetic-garbage-empty.txt", None),
]


@pytest.mark.parametrize("name,expected", _CASES, ids=[c[0] for c in _CASES])
def test_main_turn_busy_verdict_for_the_fixture_frame(name: str, expected: bool | None) -> None:
    """`main_turn_busy` gives the intended busy / idle / unreadable verdict for this captured or synthetic frame."""
    assert ps.main_turn_busy((_FIXTURES / name).read_text()) is expected, name


def test_background_agent_rows_alone_are_not_a_busy_main_turn() -> None:
    """`parse` reads agent rows as WORKING, but `main_turn_busy` must still say the main turn is idle."""
    frame = (_FIXTURES / "synthetic-agents-running-context-pct.txt").read_text()
    state = ps.parse(frame)
    assert state.status.kind == ps.StatusKind.WORKING and state.agents_running > 0
    assert ps.main_turn_busy(frame) is False


def test_a_running_row_is_busy_even_when_background_agents_are_also_listed() -> None:
    """Agent rows next to a live main-turn spinner row do not hide the spinner: still busy."""
    working = (_FIXTURES / "real-calm-working.txt").read_text()
    agents = "◯ agent-1: scanning fixtures\n"
    assert ps.main_turn_busy(agents + working) is True


def test_a_stale_done_row_is_idle_and_parse_agrees() -> None:
    """A `done` status row is the leftover of a finished turn: parse says IDLE and so does the gate."""
    frame = (_FIXTURES / "synthetic-done-row-idle.txt").read_text()
    assert ps.parse(frame).status.kind == ps.StatusKind.IDLE
    assert ps.main_turn_busy(frame) is False


def test_only_the_last_status_block_decides() -> None:
    """An older still-running row above a newer `done` row does not make the pane busy (last block wins)."""
    frame = (_FIXTURES / "synthetic-stale-glyph-row-then-done-row.txt").read_text()
    assert "Running scheduled task" in frame
    assert ps.main_turn_busy(frame) is False


def test_empty_and_none_frames_are_unreadable() -> None:
    """An empty capture (or no capture at all) is None — the caller must not read it as idle."""
    assert ps.main_turn_busy("") is None
    assert ps.main_turn_busy(None) is None
