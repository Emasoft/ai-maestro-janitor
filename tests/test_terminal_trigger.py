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

import json
import os
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
    # Hermetic dispatch: clear any ai-maestro agent signals so the API path is only
    # taken by tests that explicitly opt in (and isn't inherited from the host env).
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        monkeypatch.delenv(var, raising=False)


def _spy_aimaestro_cli(tmp_path, agents_payload):
    """Write a spy `aimaestro-agent.sh` (issue #42 — the janitor now shells out to
    the CLI, not the HTTP API). `list --json` prints `agents_payload`; `session
    command …` records its argv to a log. A REAL executable the janitor invokes —
    no mocks. Returns (cli_path, calls_log)."""
    agents_file = tmp_path / "agents.json"
    agents_file.write_text(json.dumps(agents_payload))
    log = tmp_path / "cli-calls.log"
    cli = tmp_path / "aimaestro-agent.sh"
    cli.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "list" ]; then cat "{agents_file}"; exit 0; fi\n'
        f'if [ "$1" = "session" ] && [ "$2" = "command" ]; then '
        f'printf "%s\\n" "$*" >> "{log}"; exit 0; fi\n'
        "exit 0\n"
    )
    cli.chmod(0o755)
    return cli, log


# --- build_tmux_steps (pure) -----------------------------------------------

def test_build_tmux_steps_sequence():
    # Hard default (esc_first=True): TWO leading Escapes (one clears a running tool, one ends
    # the turn on this CC build — HARD_INTERRUPT_ESC_COUNT) then the single command.
    steps = tt.build_tmux_steps("%3", ["/compact"])
    assert steps == [
        ["RUN", "tmux", "send-keys", "-t", "%3", "Escape"],
        ["SLEEP", "0.6"],
        ["RUN", "tmux", "send-keys", "-t", "%3", "Escape"],
        ["SLEEP", "0.6"],
        ["RUN", "tmux", "send-keys", "-t", "%3", "-l", "/compact"],
        ["RUN", "tmux", "send-keys", "-t", "%3", "Enter"],
    ]


def test_build_tmux_steps_hard_sends_two_escapes():
    # Regression guard (TRDD-L87BQ2Y9): a HARD interrupt sends HARD_INTERRUPT_ESC_COUNT (=2)
    # ESCs — one cancels a running tool, the second ends the turn. A single ESC left a
    # self-triggered /compact enqueued behind the still-alive turn (user-observed 2026-07-01).
    steps = tt.build_tmux_steps("%3", ["/compact"])
    escapes = [i for i, s in enumerate(steps) if s[-1] == "Escape"]
    assert len(escapes) == tt.HARD_INTERRUPT_ESC_COUNT == 2
    first_literal = next(i for i, s in enumerate(steps) if "-l" in s)
    assert all(i < first_literal for i in escapes), "every ESC precedes the command literal-send"


def test_build_tmux_steps_sends_command_literally():
    # `-l` precedes the command so `/reload-plugins` is literal text, not a key name.
    steps = tt.build_tmux_steps("%12", ["/reload-plugins"])
    literal = [s for s in steps if "-l" in s][0]
    assert literal[-2:] == ["-l", "/reload-plugins"]


def test_build_tmux_steps_accepts_bare_string_not_per_char():
    # A bare command STRING must be treated as ONE command, NOT iterated char-by-char.
    # Direct callers (fleet_inject / fleet_restart) pass a single string; a str is a
    # Sequence[str] of characters, so without normalization this would send one
    # keystroke per character. Regression guard for that footgun.
    steps = tt.build_tmux_steps("%5", "/janitor-arm")
    literals = [s[-1] for s in steps if "-l" in s]
    assert literals == ["/janitor-arm"], "a bare string must send exactly ONE literal command"
    assert ["RUN", "tmux", "send-keys", "-t", "%5", "-l", "/janitor-arm"] in steps


def test_build_tmux_steps_soft_omits_escape():
    # SOFT (esc_first=False): NO leading Escape — the command is typed while the agent
    # is mid-turn and Claude Code enqueues it until the turn ends. Just type + Enter.
    steps = tt.build_tmux_steps("%3", ["/compact"], esc_first=False)
    assert steps == [
        ["RUN", "tmux", "send-keys", "-t", "%3", "-l", "/compact"],
        ["RUN", "tmux", "send-keys", "-t", "%3", "Enter"],
    ]
    assert not any("Escape" in s for s in steps), "soft mode must never send ESC"


def test_build_tmux_steps_multi_command_enqueues_both_no_esc():
    # SOFT --handoff: both commands typed back-to-back (no ESC), each submitted with
    # Enter and separated by a settle so the input queue registers them in order.
    steps = tt.build_tmux_steps("%3", ["/janitor-write-handoff", "/compact"], esc_first=False)
    literals = [s[-1] for s in steps if "-l" in s]
    assert literals == ["/janitor-write-handoff", "/compact"], "both commands, in order"
    assert not any("Escape" in s for s in steps), "soft multi-command must never send ESC"
    assert [s for s in steps if s[0] == "SLEEP"], "a settle between the two enqueued commands"


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
    # Hard default: the plan carries an `ESC+` prefix (the interrupt) then the command.
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("TMUX_PANE", "%5")
    out = tt.send_self_command("/compact", delay_s=2.0, dry_run=True)
    assert out == "DRY_RUN:tmux:%5:ESC+/compact@2.0s"


def test_tmux_soft_dry_run_omits_esc(monkeypatch):
    # SOFT: no `ESC+` prefix — the command enqueues instead of interrupting.
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("TMUX_PANE", "%5")
    out = tt.send_self_command("/compact", delay_s=2.0, esc_first=False, dry_run=True)
    assert out == "DRY_RUN:tmux:%5:/compact@2.0s"


def test_tmux_soft_multi_command_dry_run(monkeypatch):
    # SOFT --handoff shape: a command LIST, no ESC, joined by `+` in the plan.
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("TMUX_PANE", "%5")
    out = tt.send_self_command(
        ["/janitor-write-handoff", "/compact"], delay_s=2.0, esc_first=False, dry_run=True
    )
    assert out == "DRY_RUN:tmux:%5:/janitor-write-handoff+/compact@2.0s"


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
    command must show up in the pane. Proves the detached-child send path works.

    OPT-IN ONLY (TRDD-K3WQ7XM9 FIX A): this spawns a REAL tmux server. Production's
    `build_tmux_steps` targets the DEFAULT socket (`tmux send-keys -t <pane>`, no `-L`),
    so an isolated private-socket E2E can't exercise the real send path — and a
    default-socket server would attach to / flood the user's own tmux (it became a
    keystroke flood-host on 2026-07-08). So it is SKIPPED unless JANITOR_TEST_REAL_TMUX=1,
    guaranteeing the publish gate never spawns a tmux server."""
    if os.environ.get("JANITOR_TEST_REAL_TMUX") != "1":
        pytest.skip("real-tmux E2E disabled by default (spawns a server on the DEFAULT socket); "
                    "opt in with JANITOR_TEST_REAL_TMUX=1")
    session = f"janitor-tt-pytest-{os.getpid()}"
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


def test_ai_maestro_cli_send_end_to_end(monkeypatch, tmp_path):
    """Inside an ai-maestro agent: send_self_command resolves the agent's tmux
    session via `aimaestro-agent.sh list --json` and types the command via
    `aimaestro-agent.sh session command <tmux> --newline -- <cmd>` (issue #42 —
    decoupled from the server API). Real spy CLI, no mocks."""
    wd = str(tmp_path)
    agents = [{"id": "a1", "workingDirectory": wd, "session": {"tmuxSessionName": "agent-sess-1"}}]
    cli, log = _spy_aimaestro_cli(tmp_path, agents)
    _force(monkeypatch, "iterm")                        # terminal kind irrelevant — CLI wins
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)         # matches the listed workingDirectory
    out = tt.send_self_command("/compact")
    assert out == "FIRED:aimaestro"
    assert "session command agent-sess-1 --newline -- /compact" in log.read_text()


def test_ai_maestro_cli_multi_command_types_each_in_order(monkeypatch, tmp_path):
    """A command LIST (soft --handoff) types each command via its own CLI call, in
    order. The frozen CLI has no raw-ESC primitive, so esc_first is moot here."""
    wd = str(tmp_path)
    agents = [{"id": "a1", "workingDirectory": wd, "session": {"tmuxSessionName": "sess-h"}}]
    cli, log = _spy_aimaestro_cli(tmp_path, agents)
    _force(monkeypatch, "iterm")
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)
    out = tt.send_self_command(["/janitor-write-handoff", "/compact"], esc_first=False)
    assert out == "FIRED:aimaestro"
    calls = log.read_text().splitlines()
    assert "session command sess-h --newline -- /janitor-write-handoff" in calls[0]
    assert "session command sess-h --newline -- /compact" in calls[1]


def test_ai_maestro_cli_dry_run_does_not_send(monkeypatch, tmp_path):
    wd = str(tmp_path)
    agents = [{"workingDirectory": wd, "session": {"tmuxSessionName": "sess-x"}}]
    cli, log = _spy_aimaestro_cli(tmp_path, agents)
    _force(monkeypatch, "iterm")
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)
    out = tt.send_self_command("/compact", dry_run=True)
    assert out == "DRY_RUN:aimaestro:sess-x:/compact"
    assert not log.exists()   # the `session command` step never ran


def test_ai_maestro_cli_failure_falls_back_to_tmux(monkeypatch, tmp_path):
    """In-agent but the CLI fails (server down → `list` exits non-zero) → the
    ai-maestro send returns None and the call falls through to the local tmux
    keystroke send (agents run in tmux)."""
    cli = tmp_path / "aimaestro-agent.sh"
    cli.write_text("#!/usr/bin/env bash\nexit 1\n")     # every subcommand fails (server unreachable)
    cli.chmod(0o755)
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    monkeypatch.setenv("TMUX_PANE", "%5")
    out = tt.send_self_command("/compact", dry_run=True)
    assert out == "DRY_RUN:tmux:%5:ESC+/compact@2.0s"


def test_not_in_agent_skips_cli(monkeypatch, tmp_path):
    # No agent flags → the ai-maestro path is never attempted (a present CLI must NOT matter).
    cli = tmp_path / "aimaestro-agent.sh"
    cli.write_text("#!/usr/bin/env bash\nexit 0\n")
    cli.chmod(0o755)
    _force(monkeypatch, "iterm")                              # _force clears agent flags
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    assert tt.send_self_command("/compact") == tt.USE_ITERM_PATH
