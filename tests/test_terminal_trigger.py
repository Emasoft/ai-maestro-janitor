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

import contextlib
import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402


def _force(monkeypatch, kind: str) -> None:
    # terminal_kind() reads JANITOR_FORCE_TERMINAL_KIND live (not cached), so just set it.
    monkeypatch.setenv("JANITOR_FORCE_TERMINAL_KIND", kind)
    # Hermetic dispatch: clear any ai-maestro agent signals so the API path is only
    # taken by tests that explicitly opt in (and isn't inherited from the host env).
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        monkeypatch.delenv(var, raising=False)


@contextlib.contextmanager
def _stub_aimaestro_server(agents_payload):
    """A REAL localhost HTTP server mimicking the ai-maestro API: serves
    GET /api/agents and records POST /api/sessions/<s>/command. No mocks."""
    posts: list[dict] = []

    class _H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - match base signature; silence access logs
            return

        def _json(self, code: int, obj) -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract
            self._json(200, agents_payload) if self.path == "/api/agents" else self._json(404, {})

        def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler contract
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n).decode("utf-8") if n else ""
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            posts.append({"path": self.path, "body": body})
            self._json(200, {"success": True})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", posts
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


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
        # Fragmented in source (per tests/README.md secret-hygiene) — a unique
        # needle to find in the pane, not a credential.
        marker = "janitor" "-needle-" "98765"
        assert tt.send_self_command(marker, delay_s=0.2) == "FIRED:tmux"

        captured = ""
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            captured = subprocess.run(
                ["tmux", "capture-pane", "-t", session, "-p"],
                capture_output=True, text=True, check=True, timeout=10,
            ).stdout
            if marker in captured:
                break
            time.sleep(0.15)
        assert marker in captured, f"typed command never reached the pane; got:\n{captured!r}"
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], check=False, timeout=10)


# --- ai-maestro API send (TRDD-db169d9e R4) --------------------------------

def test_match_agent_tmux_exact(tmp_path):
    wd = str(tmp_path)
    agents = [{"workingDirectory": wd, "session": {"tmuxSessionName": "s1"}}]
    assert tt.match_agent_tmux(agents, [wd]) == "s1"


def test_match_agent_tmux_subdir(tmp_path):
    wd = str(tmp_path)
    sub = str(tmp_path / "a" / "b")
    agents = [{"workingDirectory": wd, "tmuxSessionName": "s2"}]   # top-level tmuxSessionName
    assert tt.match_agent_tmux(agents, [sub]) == "s2"


def test_match_agent_tmux_session_working_dir(tmp_path):
    wd = str(tmp_path)
    agents = [{"session": {"workingDirectory": wd, "tmuxSessionName": "s3"}}]
    assert tt.match_agent_tmux(agents, [wd]) == "s3"


def test_match_agent_tmux_no_match(tmp_path):
    agents = [{"workingDirectory": str(tmp_path / "x"), "session": {"tmuxSessionName": "s"}}]
    assert tt.match_agent_tmux(agents, [str(tmp_path / "y")]) is None


def test_ai_maestro_api_send_end_to_end(monkeypatch, tmp_path):
    """Inside an ai-maestro agent: send_self_command POSTs the command to the
    agent's tmux session resolved via GET /api/agents. Real localhost server."""
    wd = str(tmp_path)
    agents = [{"id": "a1", "workingDirectory": wd, "session": {"tmuxSessionName": "agent-sess-1"}}]
    with _stub_aimaestro_server(agents) as (base, posts):
        _force(monkeypatch, "iterm")                       # terminal kind irrelevant — API wins
        monkeypatch.setenv("AIMAESTRO_AGENT", "1")
        monkeypatch.setenv("AIMAESTRO_API", base)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)        # matches the served workingDirectory
        out = tt.send_self_command("/compact")
        assert out == "FIRED:aimaestro"
    assert len(posts) == 1
    assert posts[0]["path"] == "/api/sessions/agent-sess-1/command"
    assert posts[0]["body"] == {"command": "/compact", "requireIdle": False, "addNewline": True}


def test_ai_maestro_api_dry_run_does_not_post(monkeypatch, tmp_path):
    wd = str(tmp_path)
    agents = [{"workingDirectory": wd, "session": {"tmuxSessionName": "sess-x"}}]
    with _stub_aimaestro_server(agents) as (base, posts):
        _force(monkeypatch, "iterm")
        monkeypatch.setenv("AIMAESTRO_AGENT", "1")
        monkeypatch.setenv("AIMAESTRO_API", base)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)
        out = tt.send_self_command("/compact", dry_run=True)
        assert out == "DRY_RUN:aimaestro:sess-x:/compact"
    assert posts == []


def test_ai_maestro_unreachable_falls_back_to_tmux(monkeypatch):
    """In-agent but the server is unreachable → the API send returns None and the
    call falls through to the local tmux keystroke send (agents run in tmux)."""
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_API", "http://127.0.0.1:1")   # port 1 → connection refused
    monkeypatch.setenv("TMUX_PANE", "%5")
    out = tt.send_self_command("/compact", dry_run=True)
    assert out == "DRY_RUN:tmux:%5:/compact@2.0s"


def test_not_in_agent_skips_api(monkeypatch):
    # No agent flags → API path never attempted (a dead AIMAESTRO_API must NOT matter).
    _force(monkeypatch, "iterm")                              # _force clears agent flags
    monkeypatch.setenv("AIMAESTRO_API", "http://127.0.0.1:1")
    assert tt.send_self_command("/compact") == tt.USE_ITERM_PATH
