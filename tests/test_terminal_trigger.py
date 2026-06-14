"""Tests for the terminal-aware self-trigger send-abstraction (TRDD-db169d9e R3).

`send_self_command` dispatches on `state.terminal_kind()`: iTerm / unknown / not-
yet-automated terminals get the `USE_ITERM_PATH` sentinel (the caller's own
osascript fallback), tmux gets a detached delayed `tmux send-keys`. The kind is
pinned via `JANITOR_FORCE_TERMINAL_KIND` so these tests are deterministic
regardless of the host terminal.

The real-tmux test is the end-to-end proof: it drives `send_self_command` against
a live throwaway tmux pane running `cat` and asserts the keystrokes arrive. It is
skipped when tmux isn't installed, and always tears its session down.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402


def _force(monkeypatch, kind: str) -> None:
    # terminal_kind() reads JANITOR_FORCE_TERMINAL_KIND live (not cached), so just set it.
    monkeypatch.setenv("JANITOR_FORCE_TERMINAL_KIND", kind)


# --- build_tmux_steps (pure) -----------------------------------------------

def test_build_tmux_steps_sequence():
    steps = tt.build_tmux_steps("%3", "/compact")
    assert steps == [
        ["RUN", "tmux", "send-keys", "-t", "%3", "Escape"],
        ["SLEEP", "0.6"],
        ["RUN", "tmux", "send-keys", "-t", "%3", "-l", "/compact"],
        ["RUN", "tmux", "send-keys", "-t", "%3", "Enter"],
    ]


def test_build_tmux_steps_sends_command_literally():
    # `-l` precedes the command so `/reload-plugins` is literal text, not a key name.
    steps = tt.build_tmux_steps("%12", "/reload-plugins")
    literal = [s for s in steps if "-l" in s][0]
    assert literal[-2:] == ["-l", "/reload-plugins"]


# --- send_self_command dispatch (forced kind) ------------------------------

def test_iterm_returns_use_iterm_path(monkeypatch):
    _force(monkeypatch, "iterm")
    assert tt.send_self_command("/compact") == tt.USE_ITERM_PATH


def test_unknown_returns_use_iterm_path(monkeypatch):
    _force(monkeypatch, "unknown")
    assert tt.send_self_command("/compact") == tt.USE_ITERM_PATH


def test_apple_terminal_degrades_to_use_iterm_path(monkeypatch):
    # Not yet automated → caller's degrade path (ask the human), not a crash.
    _force(monkeypatch, "apple-terminal")
    assert tt.send_self_command("/compact") == tt.USE_ITERM_PATH


def test_tmux_dry_run_reports_plan(monkeypatch):
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("TMUX_PANE", "%5")
    out = tt.send_self_command("/compact", delay_s=2.0, dry_run=True)
    assert out == "DRY_RUN:tmux:%5:/compact@2.0s"


def test_tmux_bad_pane_degrades(monkeypatch):
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("TMUX_PANE", "not-a-pane")
    assert tt.send_self_command("/compact", dry_run=True) == "NO_AUTO_TERMINAL:tmux"


def test_tmux_missing_pane_degrades(monkeypatch):
    _force(monkeypatch, "tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert tt.send_self_command("/compact", dry_run=True) == "NO_AUTO_TERMINAL:tmux"


# --- payload round-trip (child decode) -------------------------------------

def test_payload_encode_decode_runs_steps(tmp_path):
    # A RUN step that touches a file proves the child decodes + executes the plan.
    marker = tmp_path / "ran.txt"
    steps = [["SLEEP", "0.0"], ["RUN", "touch", str(marker)]]
    payload = tt._encode_payload(0.0, steps)
    assert tt._run_send_payload(payload) == 0
    assert marker.exists()


def test_payload_malformed_returns_nonzero():
    assert tt._run_send_payload("@@@not-base64@@@") == 2


# --- REAL tmux end-to-end (gated on tmux) ----------------------------------

@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_tmux_real_send_delivers_keystrokes(monkeypatch):
    """Drive send_self_command against a live tmux pane running `cat`; the typed
    command must show up in the pane. Proves the detached-child send path works."""
    session = f"janitor-tt-pytest-{__import__('os').getpid()}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-x", "80", "-y", "24", "cat"],
        check=True, timeout=10,
    )
    try:
        panes = subprocess.run(
            ["tmux", "list-panes", "-t", session, "-F", "#{pane_id}"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.split()
        assert panes, "tmux session has no pane"
        pane = panes[0]

        _force(monkeypatch, "tmux")
        monkeypatch.setenv("TMUX_PANE", pane)
        token = "janitortoken98765"
        assert tt.send_self_command(token, delay_s=0.2) == "FIRED:tmux"

        captured = ""
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            captured = subprocess.run(
                ["tmux", "capture-pane", "-t", session, "-p"],
                capture_output=True, text=True, check=True, timeout=10,
            ).stdout
            if token in captured:
                break
            time.sleep(0.15)
        assert token in captured, f"typed command never reached the pane; got:\n{captured!r}"
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], check=False, timeout=10)
