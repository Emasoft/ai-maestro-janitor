"""Tests for the one-screen-state reader (TRDD-N954KWUC, Phase 1).

"A janitor is supposed to control Claude Code to ensure continuity, but without a smart
script that understands the content of the screen there is no hope of a clean and guaranteed
janitor management of Claude Code." (USER, 2026-09-02.) `pane_state.parse` turns a captured
pane frame into a structured `PaneState`; these tests pin its classification against a fixture
corpus of real pane captures (`tests/fixtures/pane_frames/real-*.txt`, anonymized — the 2026-09-02
21:03 incident, reused/adapted from `tests/test_daemon_rotation_esc.py`'s own frame constants)
plus synthetic frames (`synthetic-*.txt`) for every status not present in a real capture.

Pure-function truth table — real values, no mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pane_state as ps  # type: ignore[import-not-found]  # noqa: E402
import pytest  # noqa: E402

_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"

# (filename, expected status kind, expected input-field kind) — verified by running the
# parser against every fixture and reading its output, not guessed.
_CASES: list[tuple[str, ps.StatusKind, ps.InputFieldKind]] = [
    ("real-wedged-fable-limit.txt", ps.StatusKind.RETRY_WEDGE, ps.InputFieldKind.QUEUED),
    ("real-wedged-session-limit.txt", ps.StatusKind.RETRY_WEDGE, ps.InputFieldKind.EMPTY),
    ("real-wedged-rate-limit-429.txt", ps.StatusKind.RETRY_WEDGE, ps.InputFieldKind.EMPTY),
    ("real-calm-working.txt", ps.StatusKind.WORKING, ps.InputFieldKind.EMPTY),
    ("real-quoted-reply-idle.txt", ps.StatusKind.IDLE, ps.InputFieldKind.EMPTY),
    ("real-prompt-echo-idle.txt", ps.StatusKind.IDLE, ps.InputFieldKind.EMPTY),
    ("synthetic-idle-empty-field.txt", ps.StatusKind.IDLE, ps.InputFieldKind.EMPTY),
    ("synthetic-idle-text-typed-bypass-off.txt", ps.StatusKind.IDLE, ps.InputFieldKind.TEXT),
    ("synthetic-working-spinner.txt", ps.StatusKind.WORKING, ps.InputFieldKind.EMPTY),
    ("synthetic-awaiting-permission.txt", ps.StatusKind.AWAITING_USER, ps.InputFieldKind.EMPTY),
    ("synthetic-awaiting-model-confirm.txt", ps.StatusKind.AWAITING_USER, ps.InputFieldKind.EMPTY),
    ("synthetic-awaiting-ask-user-menu.txt", ps.StatusKind.AWAITING_USER, ps.InputFieldKind.EMPTY),
    ("synthetic-api-error.txt", ps.StatusKind.API_ERROR, ps.InputFieldKind.EMPTY),
    ("synthetic-compacting-with-queued.txt", ps.StatusKind.COMPACTING, ps.InputFieldKind.QUEUED),
    ("synthetic-reloading.txt", ps.StatusKind.RELOADING, ps.InputFieldKind.EMPTY),
    ("synthetic-session-limit-terminal.txt", ps.StatusKind.SESSION_LIMIT, ps.InputFieldKind.EMPTY),
    ("synthetic-agents-running-context-pct.txt", ps.StatusKind.WORKING, ps.InputFieldKind.EMPTY),
    ("synthetic-garbage-random-text.txt", ps.StatusKind.UNKNOWN, ps.InputFieldKind.EMPTY),
    ("synthetic-garbage-empty.txt", ps.StatusKind.UNKNOWN, ps.InputFieldKind.EMPTY),
]


def _frame_names() -> list[str]:
    """Every fixture file actually present, so a missing/renamed fixture fails loudly as a
    collection error rather than silently skipping a case."""
    return sorted(p.name for p in _FIXTURES.glob("*.txt"))


def test_fixture_corpus_matches_the_declared_cases() -> None:
    """Every fixture file on disk has exactly one entry in `_CASES` and vice versa — catches
    an added fixture nobody wrote an expectation for, or a stale expectation for a deleted
    fixture, as a loud failure instead of a silently-skipped file."""
    assert sorted(name for name, _, _ in _CASES) == _frame_names()


def test_fixture_corpus_holds_at_least_five_real_captures() -> None:
    """Acceptance box 1: 'incl. the 5 captured 2026-09-02 21:03' — count the anonymized
    real-* fixtures, not just trust the filename convention exists."""
    real = [n for n in _frame_names() if n.startswith("real-")]
    assert len(real) >= 5, f"only {len(real)} real-* fixtures, need >= 5: {real}"


@pytest.mark.parametrize("name,expected_status,expected_field", _CASES, ids=[c[0] for c in _CASES])
def test_parse_classifies_the_fixture_frame(name: str, expected_status: ps.StatusKind, expected_field: ps.InputFieldKind) -> None:
    """`pane_state.parse` classifies this captured/synthetic frame into the intended status
    and input-field kind."""
    frame = (_FIXTURES / name).read_text()
    state = ps.parse(frame)
    assert state.status.kind == expected_status, f"{name}: status {state.status.kind} != {expected_status}"
    assert state.input_field.kind == expected_field, f"{name}: field {state.input_field.kind} != {expected_field}"


def test_the_fable_limit_wedge_carries_the_full_wedge_detail() -> None:
    """The retry-wedge status carries attempt/total/retry_in/resets_at/scope, not just a
    bare attempt number — the policy table (Phase 2) needs all five to plan the ESC + resume."""
    frame = (_FIXTURES / "real-wedged-fable-limit.txt").read_text()
    status = ps.parse(frame).status
    assert status.attempt == 1
    assert status.total == 5
    assert status.retry_in == "5h"
    assert status.resets_at == "Sep 8 at 5pm"
    assert status.scope == "usage-limit"


def test_the_session_limit_wedge_scope_is_distinguished_from_a_rate_limit_wedge() -> None:
    """Two real captures share the identical wedge SHAPE but different SCOPE text — the
    scope field must not collapse them to the same bucket."""
    session_limit = ps.parse((_FIXTURES / "real-wedged-session-limit.txt").read_text()).status
    rate_limit = ps.parse((_FIXTURES / "real-wedged-rate-limit-429.txt").read_text()).status
    assert session_limit.scope == "session-limit"
    assert rate_limit.scope == "rate-limit"
    assert session_limit.scope != rate_limit.scope


def test_the_queued_command_count_is_read_from_the_status_block_not_guessed() -> None:
    """The real fable-limit wedge frame has exactly ONE queued `❯ /janitor-arm` row above the
    input box; the synthetic compacting frame has two — the count must match each, not just
    report 'some' queue."""
    fable = ps.parse((_FIXTURES / "real-wedged-fable-limit.txt").read_text())
    assert fable.input_field.queued_count == 1
    compacting = ps.parse((_FIXTURES / "synthetic-compacting-with-queued.txt").read_text())
    assert compacting.input_field.queued_count == 2


def test_the_typed_text_field_captures_the_exact_typed_string() -> None:
    """A TEXT input field carries the typed content verbatim (chevron stripped), not just a
    boolean 'has text'."""
    state = ps.parse((_FIXTURES / "synthetic-idle-text-typed-bypass-off.txt").read_text())
    assert state.input_field.text == "run the tests please"


def test_agents_running_counts_the_agent_list_markers() -> None:
    """`◯` is Claude Code's own agent-list-entry glyph (documented in
    `session_liveness._ROW_MARKER_GLYPHS`) — two of them means two background agents."""
    state = ps.parse((_FIXTURES / "synthetic-agents-running-context-pct.txt").read_text())
    assert state.agents_running == 2


def test_context_pct_and_model_and_bypass_are_read_from_the_footer() -> None:
    """The three footer facts a policy row may need to decide whether it's even safe to type:
    remaining context, the active model, and whether bypass-permissions is on."""
    state = ps.parse((_FIXTURES / "synthetic-agents-running-context-pct.txt").read_text())
    assert state.context_pct == 42
    assert state.model == "Sonnet 5 v2.1.300"
    bypass_on = ps.parse((_FIXTURES / "synthetic-idle-empty-field.txt").read_text())
    assert bypass_on.bypass_on is True
    bypass_off = ps.parse((_FIXTURES / "synthetic-idle-text-typed-bypass-off.txt").read_text())
    assert bypass_off.bypass_on is False


def test_a_garbage_frame_never_raises_and_classifies_unknown() -> None:
    """Negative test: text that matches none of Claude Code's own chrome must classify as
    UNKNOWN, never raise — a caller can always call `parse()` without a try/except."""
    for garbage in ("", "asdkjaslkdj\nqwoiuqwoiuq\n", "🎉🎉🎉", "\x00\x01binary-ish\x02"):
        state = ps.parse(garbage)
        assert state.status.kind == ps.StatusKind.UNKNOWN, garbage


def test_parse_never_raises_on_none_like_or_malformed_input() -> None:
    """Negative test: `parse(None)` (a caller forwarding `capture_pane_text`'s own `None`
    result without checking it first) must not raise — `text = frame or ""` is the guard."""
    state = ps.parse(None)  # type: ignore[arg-type]
    assert state.status.kind == ps.StatusKind.UNKNOWN


def test_read_returns_none_when_the_pane_cannot_be_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    """`read()` must forward `capture_pane_text`'s fail-open `None` — never synthesize a
    fake PaneState for an unreadable pane."""
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
    import fleet_scan  # type: ignore[import-not-found]

    monkeypatch.setattr(fleet_scan, "capture_pane_text", lambda terminal: None)
    assert ps.read({"tmux_pane": "%1"}) is None


def test_read_parses_a_successfully_captured_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """`read()` is `capture_pane_text` + `parse` — a successful capture reaches `parse`
    unmodified."""
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
    import fleet_scan  # type: ignore[import-not-found]

    frame = (_FIXTURES / "real-wedged-fable-limit.txt").read_text()
    monkeypatch.setattr(fleet_scan, "capture_pane_text", lambda terminal: frame)
    state = ps.read({"tmux_pane": "%1"})
    assert state is not None
    assert state.status.kind == ps.StatusKind.RETRY_WEDGE
