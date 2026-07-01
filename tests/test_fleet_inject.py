"""Tests for the fleet recovery injector (TRDD-324223a6, GROUP A / A3).

Pure plan-building — no keystrokes are fired (that I/O is the daemon's job, and
firing would inject into real panes). The load-bearing properties: only the
command-typing rungs produce a plan; tmux is preferred over iTerm when both are
present (the ai-maestro-compatible, no-AppleScript path); an iTerm plan is built
ONLY for a UUID that passes the injection-safety gate; and the osascript targets
exactly the stored session, never a broadcast.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_inject as fi  # type: ignore[import-not-found]  # noqa: E402


def test_action_to_command_only_typing_rungs() -> None:
    """The gentle command-typing rungs map to a slash-command; esc_nudge (ESC only)
    and the hard-restart rungs (handled by the daemon) map to None."""
    assert fi.action_to_command("rearm") == "/janitor-arm"
    assert fi.action_to_command("reload") == "/reload-plugins"
    assert fi.action_to_command("update") == "/janitor-arm"
    assert fi.action_to_command("esc_nudge") is None
    assert fi.action_to_command("relaunch") is None
    assert fi.action_to_command("force_restart") is None
    assert fi.action_to_command("resurrect") is None
    assert fi.action_to_command("nonsense") is None


def test_valid_session_id_gates_injection() -> None:
    """A bare hex UUID is accepted; anything that could smuggle AppleScript into the
    osascript string is rejected — the daemon must never build a poisoned script."""
    assert fi.valid_session_id("4C4A6F99-5FDB-4884-950B-79A76FBB737E")
    assert fi.valid_session_id("  abc123-DEF  ")  # trimmed
    assert not fi.valid_session_id('x" then do shell script "rm -rf ~" --')
    assert not fi.valid_session_id("has space")
    assert not fi.valid_session_id("")


def test_iterm_osascript_targets_one_session_with_esc() -> None:
    """The script guards on the exact stored id, sends a raw ESC (interrupt the
    dead turn), then types the command — and never touches a non-matching pane."""
    s = fi.iterm_osascript("UUID-1234", "/janitor-arm", delay_s=2.0)
    assert 'if (id of s) is "UUID-1234" then' in s
    assert s.count("character id 27") == 2  # TWO ESC bytes: one clears the tool, one ends the (frozen) turn
    assert 'write text "/janitor-arm"' in s
    assert s.startswith("delay 2.0")
    # esc_first=False omits the ESC for an idle (non-stuck) target
    assert "character id 27" not in fi.iterm_osascript("U", "/x", esc_first=False)


def test_build_injection_prefers_tmux() -> None:
    """When a tmux pane is present it wins over iTerm — the ai-maestro-compatible
    path that needs no AppleScript and steals no focus. The plan carries the
    literal-send steps and the delay for the detached runner."""
    plan = fi.build_injection(
        {"tmux_pane": "%5", "iterm_session_id": "tty:UUID"}, "rearm", delay_s=1.5
    )
    assert plan is not None
    assert plan["channel"] == "tmux"
    assert plan["command"] == "/janitor-arm"
    assert plan["delay_s"] == 1.5
    assert ["RUN", "tmux", "send-keys", "-t", "%5", "-l", "/janitor-arm"] in plan["steps"]


def test_build_injection_iterm_fallback_strips_tty_prefix() -> None:
    """With no tmux pane, an iTerm plan is built from the '<tty>:<uuid>' identity —
    the tty prefix is stripped and only the UUID is interpolated."""
    plan = fi.build_injection({"iterm_session_id": "ttys003:4C4A-9B7"}, "reload")
    assert plan is not None
    assert plan["channel"] == "iterm"
    assert 'if (id of s) is "4C4A-9B7" then' in plan["osascript"]
    assert 'write text "/reload-plugins"' in plan["osascript"]


def test_build_injection_declines_unreachable_and_noncommand() -> None:
    """No tmux pane + no valid UUID → no plan (don't fire blind). A non-typing
    action → no plan even with a good terminal (esc_nudge/hard-restart aren't injected
    as commands here)."""
    assert fi.build_injection({}, "rearm") is None
    assert fi.build_injection({"iterm_session_id": "not a uuid !!"}, "rearm") is None
    assert fi.build_injection({"tmux_pane": "%9"}, "esc_nudge") is None
    assert fi.build_injection({"tmux_pane": "%9"}, "resurrect") is None


def test_build_injection_rejects_malformed_tmux_pane() -> None:
    """A tmux pane that isn't a bare %<n> (e.g. a leading '-', which tmux would parse
    as a FLAG, or an injection-shaped value) is REJECTED — symmetric with the iTerm
    UUID gate (audit C1). It never reaches the `tmux send-keys` argv."""
    # malformed pane + no iTerm fallback → declined entirely (never an unsafe argv)
    assert fi.build_injection({"tmux_pane": "-X"}, "rearm") is None
    assert fi.build_injection({"tmux_pane": "%5; rm -rf x"}, "rearm") is None
    assert fi.build_injection({"tmux_pane": "session:1.0"}, "rearm") is None
    # malformed pane BUT a valid iTerm id → falls through to the gated iTerm channel,
    # never emitting a tmux plan carrying the bad pane
    plan = fi.build_injection({"tmux_pane": "-X", "iterm_session_id": "ttys9:4C4A-9B7"}, "rearm")
    assert plan is not None and plan["channel"] == "iterm"
    # a well-formed pane still produces a tmux plan
    good = fi.build_injection({"tmux_pane": "%5"}, "rearm")
    assert good is not None and good["channel"] == "tmux"


def test_fire_returns_false_on_spawn_failure(monkeypatch) -> None:
    """A spawn failure (e.g. missing osascript) makes fire() return False — the caller
    logs FIRE-FAILED — instead of letting the OSError escape and crash the whole
    fleet beat through Task.run's blanket handler (audit C2)."""
    def boom(*_a, **_k):
        raise FileNotFoundError("osascript not found")
    monkeypatch.setattr(fi.subprocess, "Popen", boom)
    plan = fi.build_injection({"iterm_session_id": "ttys9:4C4A-9B7"}, "rearm")
    assert plan is not None and plan["channel"] == "iterm"
    assert fi.fire(plan) is False          # no exception escapes; reported as failure


def test_fire_declines_empty_plan() -> None:
    """fire(None) is a safe no-op (a declined plan never raises) and reports that
    nothing was launched."""
    assert fi.fire(None) is False
