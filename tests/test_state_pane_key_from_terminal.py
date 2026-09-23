"""Tests for `state.pane_key_from_terminal`'s iTerm-prefix normalisation (review finding,
TRDD-RAEGS1D5 card 5, 2026-09-23).

The WRITER side (`clear_trigger._persist_resume_state`) keys the per-pane sidecar off
`state.pane_key_from_terminal(terminal)`, where `terminal` can arrive already stripped
(`terminal_trigger.self_terminal()`'s own output, `external_clear.terminal_from_record`'s
`iterm.split(":")[-1]`) OR, from some other hand-built dict, still carrying the raw
`$ITERM_SESSION_ID`-shaped `"w0t1p0:<UUID>"` form. `pane_key_from_terminal` now normalises
BOTH shapes to the identical key, so any writer lands where the reader
(`state.pane_key_from_terminal(terminal_trigger.self_terminal(env))`) looks -- one function,
applied consistently, instead of every call site having to remember to strip first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import state  # noqa: E402
import terminal_trigger  # noqa: E402

_RAW_ITERM = "w0t1p0:04F9A16F-04B3-42A0-9B20-C1E08CFE1D36"
_STRIPPED_ITERM = "04F9A16F-04B3-42A0-9B20-C1E08CFE1D36"


def test_a_raw_and_an_already_stripped_iterm_session_id_yield_the_same_key():
    """A terminal dict carrying the RAW `w0t1p0:<UUID>` form (e.g. hand-built from a stored
    pane record) and one already stripped to the bare UUID must resolve to ONE key."""
    raw_key = state.pane_key_from_terminal({"kind": "iterm", "session_id": _RAW_ITERM})
    stripped_key = state.pane_key_from_terminal({"kind": "iterm", "session_id": _STRIPPED_ITERM})
    assert raw_key == stripped_key == f"iterm-{_STRIPPED_ITERM}"


def test_a_raw_writer_dict_matches_the_readers_self_terminal_computation():
    """The three shapes a real clear can produce -- a writer dict built directly from the raw
    env-shaped string, a writer dict already stripped, and the READER's own
    `pane_key_from_terminal(self_terminal(env))` call -- must all agree on one key."""
    writer_raw = state.pane_key_from_terminal({"kind": "iterm", "session_id": _RAW_ITERM})
    writer_stripped = state.pane_key_from_terminal(
        {"kind": "iterm", "session_id": _STRIPPED_ITERM}
    )
    reader = state.pane_key_from_terminal(
        terminal_trigger.self_terminal({"ITERM_SESSION_ID": _RAW_ITERM})
    )
    assert writer_raw == writer_stripped == reader


def test_tmux_pane_key_computed_on_both_sides_still_agrees():
    """tmux carries no such prefix to strip -- pin that the writer-dict path and the
    reader's `self_terminal(env)` path still compute the identical key for it, on BOTH
    sides, rather than assuming tmux was never at risk."""
    writer = state.pane_key_from_terminal({"kind": "tmux", "pane": "%3"})
    reader = state.pane_key_from_terminal(terminal_trigger.self_terminal({"TMUX_PANE": "%3"}))
    assert writer == reader == "tmux-3"
