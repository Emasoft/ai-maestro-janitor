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

try:  # conftest is importable by test modules (see its module docstring)
    from conftest import away_home  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — conftest is always on path under pytest
    away_home = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _unattended_home(monkeypatch, tmp_path):
    """Pin HOME to an UNATTENDED presence breadcrumb so every test in this module is
    hermetic w.r.t. whether a real human is at the machine.

    `send_self_command`'s presence gate (`user_intent.injection_allowed`) reads the
    machine-global user-presence breadcrumb under $HOME; unpinned, these tests inherit
    the DEVELOPER's live breadcrumb and return USER_PRESENT whenever whoever ran the
    suite happened to be typing — "a test reporting on the tester, not the code"
    (conftest.py). None of this module's tests exercise the gate itself (that lives in
    test_user_intent.py), so an unattended HOME is the correct isolation — matching the
    sibling reload/resume/reload-skills trigger tests. AM8JD9SG F9-adjacent (pre-existing
    isolation gap surfaced during the ai-maestro audit)."""
    if away_home is not None:
        monkeypatch.setenv("HOME", str(away_home(tmp_path)))


def _force(monkeypatch, kind: str) -> None:
    # terminal_kind() reads JANITOR_FORCE_TERMINAL_KIND live (not cached), so just set it.
    monkeypatch.setenv("JANITOR_FORCE_TERMINAL_KIND", kind)
    # Hermetic dispatch: clear any ai-maestro agent signals so the API path is only
    # taken by tests that explicitly opt in (and isn't inherited from the host env).
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        monkeypatch.delenv(var, raising=False)


def _wait_for_log(log, predicate, timeout_s: float = 5.0) -> str:
    """Poll a spy-CLI log until `predicate(text)` holds (F9: delivery is detached, so
    assertions on the log must wait for the child). Returns the final text either way —
    the caller's assert then produces the real diff on timeout."""
    import time as _time

    deadline = _time.monotonic() + timeout_s
    text = ""
    while _time.monotonic() < deadline:
        text = log.read_text() if log.exists() else ""
        if predicate(text):
            return text
        _time.sleep(0.05)
    return text


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


def test_match_agent_tmux_ambiguous_same_workdir_refuses(tmp_path):
    # AM8JD9SG F5: two ai-maestro agents on the SAME workdir (same specificity, DIFFERENT
    # tmux session) cannot be disambiguated by cwd — the old `len > best` kept the first in
    # list order, routing keystrokes into a coin-flip pane. We now REFUSE (None) so the
    # self-trigger degrades to "ask the user" instead of typing into the wrong agent.
    wd = str(tmp_path)
    agents = [
        {"workingDirectory": wd, "session": {"tmuxSessionName": "agent-A"}},
        {"workingDirectory": wd, "session": {"tmuxSessionName": "agent-B"}},
    ]
    assert tt.match_agent_tmux(agents, [wd]) is None


def test_match_agent_tmux_same_workdir_same_session_is_not_ambiguous(tmp_path):
    # The SAME session listed twice on one workdir has a single unambiguous target — not a
    # tie. Only DIFFERENT sessions at equal specificity are ambiguous.
    wd = str(tmp_path)
    agents = [
        {"workingDirectory": wd, "session": {"tmuxSessionName": "agent-A"}},
        {"workingDirectory": wd, "session": {"tmuxSessionName": "agent-A"}},
    ]
    assert tt.match_agent_tmux(agents, [wd]) == "agent-A"


def test_match_agent_tmux_most_specific_still_wins_over_parent(tmp_path):
    # Regression guard: a broad parent-root agent must NOT make a deeper exact-match agent
    # ambiguous — the deeper (longer) workingDirectory is strictly more specific and wins.
    parent = str(tmp_path)
    child = str(tmp_path / "proj")
    agents = [
        {"workingDirectory": parent, "session": {"tmuxSessionName": "root-agent"}},
        {"workingDirectory": child, "session": {"tmuxSessionName": "proj-agent"}},
    ]
    assert tt.match_agent_tmux(agents, [child]) == "proj-agent"


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
    out = tt.send_self_command("/compact", delay_s=0.0)
    assert out == "FIRED:aimaestro"
    # F9: delivery is DETACHED — poll the spy log for the child's send (≤5 s).
    text = _wait_for_log(log, lambda t: "session command" in t)
    assert "session command agent-sess-1 --newline -- /compact" in text


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
    out = tt.send_self_command(["/janitor-write-handoff", "/compact"], esc_first=False, delay_s=0.0)
    assert out == "FIRED:aimaestro"
    # F9: both sends run in ONE detached child, in order — poll until both landed.
    text = _wait_for_log(log, lambda t: t.count("session command") >= 2)
    calls = text.splitlines()
    assert "session command sess-h --newline -- /janitor-write-handoff" in calls[0]
    assert "session command sess-h --newline -- /compact" in calls[1]


def test_ai_maestro_cli_midlist_failure_never_falls_back_to_retype(monkeypatch, tmp_path):
    """AM8JD9SG F8→F9: command 1 delivered, command 2 fails IN THE DETACHED CHILD. The
    caller already returned FIRED:aimaestro at resolution time, so there is no fallback
    path left that could re-type the whole list (the F8 double-run hazard is structurally
    gone) — the delivered prefix is never duplicated, and the lost tail is recoverable at
    the next fire. The spy fails the SECOND `session command`."""
    wd = str(tmp_path)
    agents = [{"workingDirectory": wd, "session": {"tmuxSessionName": "sess-p"}}]
    agents_file = tmp_path / "agents.json"
    agents_file.write_text(json.dumps(agents))
    log = tmp_path / "cli-calls.log"
    cli = tmp_path / "aimaestro-agent.sh"
    cli.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "list" ]; then cat "{agents_file}"; exit 0; fi\n'
        f'if [ "$1" = "session" ] && [ "$2" = "command" ]; then '
        # Fail the SECOND command: once the log already has a line, exit non-zero.
        f'n=$(wc -l < "{log}" 2>/dev/null || echo 0); '
        f'if [ "$n" -ge 1 ]; then exit 1; fi; '
        f'printf "%s\\n" "$*" >> "{log}"; exit 0; fi\n'
        "exit 0\n"
    )
    cli.chmod(0o755)
    # tmux kind + a valid pane: if the channel regressed to returning None here, the
    # caller would fall back and re-type BOTH commands via tmux — the return value is
    # the no-duplicate proof.
    _force(monkeypatch, "tmux")
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)
    monkeypatch.setenv("TMUX_PANE", "%9")
    out = tt.send_self_command(["/janitor-write-handoff", "/compact"], esc_first=False, delay_s=0.0)
    assert out == "FIRED:aimaestro"
    # Only the FIRST command lands (the second fails in-child, without a re-type). Wait
    # for the child, then hold a beat to prove no second line ever arrives.
    text = _wait_for_log(log, lambda t: t.count("session command") >= 1)
    import time as _time

    _time.sleep(0.3)
    assert log.read_text().count("session command") == 1, text


def test_ai_maestro_cli_send_is_detached_not_inline(monkeypatch, tmp_path):
    """AM8JD9SG F9: the per-command CLI POSTs must NOT run inline — a multi-command send
    used to cost 11-17 s synchronously, blowing the 5 s hooks.json budget of the calling hook.
    With a spy whose `session command` SLEEPS 4 s, `send_self_command` must return before that
    send could possibly have finished (only the bounded `list` runs inline).

    ASSERTS ON STATE, NOT ON ELAPSED TIME (TRDD-7NSRD8OV, category C). This test used to assert
    `elapsed < 3.0`, which flaked under suite load for a reason no timeout knob can fix: on a
    saturated box a genuinely DETACHED send still takes over 3 s to return, so the bound failed
    while the behaviour under test was perfectly correct.

    Simply widening the bound was NOT an option, and that is the whole reason for the redesign:
    an INLINE regression costs ~8 s here (two commands x the 4 s sleep), so any bound loose
    enough to survive load is also loose enough to let the exact regression this guards sail
    through — a green test defending nothing. The marker files decide the same question by
    causality instead of by clock: if delivery were inline, `send_self_command` could only return
    AFTER the sleep, so `done` would necessarily exist by then. Its absence is what proves
    detachment, and that stays true at any load.
    """
    wd = str(tmp_path)
    agents = [{"workingDirectory": wd, "session": {"tmuxSessionName": "sess-slow"}}]
    agents_file = tmp_path / "agents.json"
    agents_file.write_text(json.dumps(agents))
    started = tmp_path / "send-started"
    done = tmp_path / "send-done"
    cli = tmp_path / "aimaestro-agent.sh"
    cli.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "list" ]; then cat "{agents_file}"; exit 0; fi\n'
        'if [ "$1" = "session" ] && [ "$2" = "command" ]; then\n'
        f'  : > "{started}"\n'
        "  sleep 4\n"
        f'  : > "{done}"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    cli.chmod(0o755)
    _force(monkeypatch, "iterm")
    monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    monkeypatch.setenv("AIMAESTRO_CLI", str(cli))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", wd)
    import time as _time

    out = tt.send_self_command(["/janitor-write-handoff", "/compact"], esc_first=False, delay_s=0.0)

    assert out == "FIRED:aimaestro"
    # THE detachment assertion: an inline send would have waited out the 4 s sleep, so `done`
    # would already be on disk the moment we got control back.
    assert not done.exists(), "the send COMPLETED before send_self_command returned — not detached"

    # And prove the send was really dispatched rather than silently skipped — otherwise the
    # assertion above would also pass for a no-op. Generously bounded and poll-based, so it
    # measures completion, never scheduling latency.
    deadline = _time.monotonic() + 60.0
    while _time.monotonic() < deadline and not done.exists():
        _time.sleep(0.1)
    assert done.exists(), "the detached send never ran at all — FIRED was reported for a no-op"


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


# --- TRDD-3T9HQEQ6: the queue-flush ESC loop ahead of `/model opus` ------------------------

_QF_NBSP = " "


def _qf_pane(field: str) -> str:
    """A capture shaped like a real prompt box: box rule, marker + NBSP + field, box rule."""
    return "some earlier output\n" + "─" * 40 + f"\n❯{_QF_NBSP}{field}\n" + "─" * 40 + "\n"


def test_two_queued_commands_need_three_escs_before_model_opus_is_typed(monkeypatch) -> None:
    """A pane whose field still holds queued commands after the first two ESCs (the red
    error line, then one queued command each) only gets its THIRD ESC clearing it — and
    only THEN does `/model opus` get typed."""
    calls: list[str] = []
    monkeypatch.setattr(tt, "_run_steps", lambda steps: calls.extend(" ".join(map(str, s)) for s in steps))
    reads = iter([
        _qf_pane("/janitor-arm"),      # after ESC 1 — one queued command remains
        _qf_pane("/janitor-resume"),   # after ESC 2 — a second queued command remains
        _qf_pane(""),                  # after ESC 3 — clear
        _qf_pane(""),                  # send_verified's own pre-type read
        _qf_pane("/model opus"),       # send_verified's post-type read-back
    ])
    ok, why = tt.send_model_switch_true_error(
        {"kind": "tmux", "pane": "%1"}, "/model opus",
        menu_wait_s=1.0, poll_s=1.0, giveup_s=5.0, sleeper=lambda _s: None,
        reader=lambda _t: next(reads, _qf_pane("/model opus")), is_typing=lambda _t: False,
    )
    assert ok is True, why
    esc_count = sum(1 for c in calls if "Escape" in c)
    assert esc_count == 3, f"exactly 3 ESCs to flush 1 red-line + 2 queued commands: {calls!r}"
    joined = " | ".join(calls)
    last_esc = max(i for i, c in enumerate(calls) if "Escape" in c)
    assert joined.index("/model opus") > joined.index(calls[last_esc]), (
        f"/model opus must be typed only AFTER the queue is flushed: {calls!r}"
    )


def test_a_clean_field_gets_one_esc_then_the_command(monkeypatch) -> None:
    """A field that is already empty still gets its one mandatory ESC (the red error line
    itself), then `/model opus` is typed straight away — no wasted extra ESCs."""
    calls: list[str] = []
    monkeypatch.setattr(tt, "_run_steps", lambda steps: calls.extend(" ".join(map(str, s)) for s in steps))
    reads = iter([
        _qf_pane(""),             # after the single ESC — already clear
        _qf_pane(""),             # send_verified's pre-type read
        _qf_pane("/model opus"),  # send_verified's post-type read-back
    ])
    ok, why = tt.send_model_switch_true_error(
        {"kind": "tmux", "pane": "%1"}, "/model opus",
        menu_wait_s=1.0, poll_s=1.0, giveup_s=5.0, sleeper=lambda _s: None,
        reader=lambda _t: next(reads, _qf_pane("/model opus")), is_typing=lambda _t: False,
    )
    assert ok is True, why
    esc_count = sum(1 for c in calls if "Escape" in c)
    assert esc_count == 1, f"a clean field needs exactly one ESC: {calls!r}"
    assert any("/model opus" in c for c in calls), f"the command must still be typed: {calls!r}"


def test_a_field_still_busy_after_five_escs_types_nothing(monkeypatch) -> None:
    """A pane whose field never clears within the 5-ESC bound must be reported and left
    alone — never typed into, since a queue this deep cannot be safely guessed at."""
    calls: list[str] = []
    monkeypatch.setattr(tt, "_run_steps", lambda steps: calls.extend(" ".join(map(str, s)) for s in steps))
    ok, why = tt.send_model_switch_true_error(
        {"kind": "tmux", "pane": "%1"}, "/model opus",
        menu_wait_s=1.0, poll_s=1.0, giveup_s=5.0, sleeper=lambda _s: None,
        reader=lambda _t: _qf_pane("/janitor-arm"), is_typing=lambda _t: False,
    )
    assert ok is False
    assert why == "queue not cleared after 5 ESC"
    esc_count = sum(1 for c in calls if "Escape" in c)
    assert esc_count == 5, f"exactly 5 ESCs are spent, no more: {calls!r}"
    assert not any("/model opus" in c for c in calls), f"nothing must be typed: {calls!r}"
