"""Tests for the hard-restart recovery rungs (TRDD-56d24c02 / A5).

These rungs KILL and RESPAWN processes, so the tests are written so that NONE of
them can ever touch a real process: every kill goes through an injected recorder,
every spawn through an injected recorder, and the keystroke `fleet_inject.fire` is
monkeypatched. What is proven here is the SAFETY CONTROL FLOW — default-off dry-run,
the is_killable refusals, and that a kill happens only when both the opt-in and the
guard agree.

The channel-resolution tests (TRDD-ME8V2YJF follow-up) prove `_command_plan`'s
fallback order for the two NEW channels (ai-maestro CLI, Linux GUI wtype/xdotool)
without touching the unchanged tmux/iTerm behaviour — pure dict-in/plan-out, no
subprocess, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_restart as fn  # type: ignore[import-not-found]  # noqa: E402


def test_hard_restart_disabled_by_default(monkeypatch) -> None:
    """The process-killing rungs are OFF unless explicitly opted in (the inverse of
    the gentle rungs, which are on by default) — killing is irreversible."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", raising=False)
    assert fn.hard_restart_enabled() is False
    for on in ("1", "true", "yes", "on"):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", on)
        assert fn.hard_restart_enabled() is True
    for off in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", off)
        assert fn.hard_restart_enabled() is False


def test_is_killable_refuses_everything_but_a_wedged_claude() -> None:
    """The hard kill-gate: only a genuinely-frozen, non-active, real-claude pid that
    is neither this process nor the daemon may be killed."""
    base = dict(pid=4242, command="claude --foo", active=False, diagnosis="frozen",
                self_pid=10, daemon_pid=20)
    assert fn.is_killable(**base) is True                       # the one allowed case
    assert fn.is_killable(**{**base, "active": True}) is False  # user is WORKING → never
    assert fn.is_killable(**{**base, "command": "vim notes"}) is False   # not a claude pid
    assert fn.is_killable(**{**base, "diagnosis": "healthy"}) is False    # not wedged
    assert fn.is_killable(**{**base, "diagnosis": "dead"}) is False       # no live pid to kill
    assert fn.is_killable(**{**base, "pid": 10}) is False       # == self_pid (the guardian)
    assert fn.is_killable(**{**base, "pid": 20}) is False       # == daemon_pid
    assert fn.is_killable(**{**base, "pid": 0}) is False        # nonsense pid


def test_build_relaunch_types_claude_continue() -> None:
    """relaunch resumes a dead pane by typing `claude --continue` (preserving the
    transcript), via the gated tmux/iTerm channel; None when no channel resolves."""
    tmux = fn.build_relaunch({"tmux_pane": "%7"})
    assert tmux is not None and tmux["rung"] == "relaunch"
    assert tmux["channel"] == "tmux" and tmux["command"] == "claude --continue"
    iterm = fn.build_relaunch({"iterm_session_id": "ttys4:4C4A-9B7"})
    assert iterm is not None and iterm["channel"] == "iterm"
    assert "claude --continue" in iterm["osascript"]
    assert fn.build_relaunch({}) is None                        # nowhere safe to type
    assert fn.build_relaunch({"tmux_pane": "-X"}) is None        # malformed pane rejected


def test_build_force_restart_carries_kill_then_relaunch() -> None:
    """force_restart describes the kill target + an in-pane relaunch; None with no pane
    (the caller then escalates to resurrect)."""
    plan = fn.build_force_restart(9988, {"tmux_pane": "%3"})
    assert plan is not None and plan["rung"] == "force_restart"
    assert plan["kill_pid"] == 9988 and plan["relaunch"]["rung"] == "relaunch"
    assert fn.build_force_restart(9988, {}) is None


def test_build_resurrect_always_builds_and_quotes_cwd() -> None:
    """resurrect is the no-channel last resort: it always builds a detached-spawn plan,
    and shlex-quotes the cwd so a crafted project path can't break the command."""
    plan = fn.build_resurrect(555, "/tmp/weird; rm -rf x")
    assert plan["rung"] == "resurrect" and plan["kill_pid"] == 555
    assert plan["spawn"][:3] == ["tmux", "new-session", "-d"]
    inner = plan["spawn"][-1]
    assert "kill 555" in inner
    assert "'/tmp/weird; rm -rf x'" in inner          # the cwd is single-quoted as ONE arg
    assert "claude --continue" in inner
    # no project root → falls back to $HOME, still a valid plan
    assert fn.build_resurrect(5, None)["spawn"][-1].startswith("kill 5")


def test_fire_restart_dry_run_when_disabled_touches_nothing(monkeypatch) -> None:
    """With the opt-in OFF, fire_restart executes NOTHING — no kill, no spawn, no
    keystroke — and reports DRY_RUN. This is the default production posture."""
    killed: list = []
    spawned: list = []
    def _fire(p):  # list.append() returns None; a def keeps the fire spy truthy cleanly
        spawned.append(p)
        return True
    monkeypatch.setattr(fn.fleet_inject, "fire", _fire)
    plan = fn.build_force_restart(123, {"tmux_pane": "%1"})
    out = fn.fire_restart(plan, enabled=False, killable=True,
                          killer=lambda *a: killed.append(a), spawner=lambda a: spawned.append(a))
    assert out == "DRY_RUN:force_restart"
    assert killed == [] and spawned == []      # absolutely nothing fired


def test_fire_restart_relaunch_needs_no_kill(monkeypatch) -> None:
    """relaunch (dead pane, no live pid) fires the keystroke and never kills."""
    killed: list = []
    monkeypatch.setattr(fn.fleet_inject, "fire", lambda p: True)
    plan = fn.build_relaunch({"tmux_pane": "%2"})
    out = fn.fire_restart(plan, enabled=True, killable=False, killer=lambda *a: killed.append(a))
    assert out == "FIRED:relaunch" and killed == []   # killable irrelevant for relaunch


def test_fire_restart_force_restart_kills_only_when_killable(monkeypatch) -> None:
    """force_restart kills the pid (injected recorder) then relaunches — but ONLY when
    killable; a not-killable verdict refuses without touching the process."""
    monkeypatch.setattr(fn.fleet_inject, "fire", lambda p: True)
    killed: list = []
    plan = fn.build_force_restart(777, {"tmux_pane": "%9"})
    # killable → kills 777 then relaunches
    out = fn.fire_restart(plan, enabled=True, killable=True, killer=lambda pid, sig: killed.append(pid))
    assert out == "FIRED:force_restart" and killed == [777]
    # NOT killable → refuse, never kill
    killed.clear()
    out = fn.fire_restart(plan, enabled=True, killable=False, killer=lambda pid, sig: killed.append(pid))
    assert out == "REFUSED:not-killable:force_restart" and killed == []


def test_fire_restart_resurrect_kills_then_spawns() -> None:
    """resurrect kills the stuck pid then spawns the detached background claude (both
    injected); refuses entirely when not killable."""
    killed: list = []
    spawned: list = []
    plan = fn.build_resurrect(888, "/proj")
    def _spawn(argv):  # list.append() returns None; a def keeps the spawner spy truthy cleanly
        spawned.append(argv)
        return True
    out = fn.fire_restart(plan, enabled=True, killable=True,
                          killer=lambda pid, sig: killed.append(pid),
                          spawner=_spawn)
    assert out == "FIRED:resurrect" and killed == [888] and len(spawned) == 1
    killed.clear()
    spawned.clear()
    out = fn.fire_restart(plan, enabled=True, killable=False,
                          killer=lambda pid, sig: killed.append(pid),
                          spawner=lambda argv: spawned.append(argv))
    assert out == "REFUSED:not-killable:resurrect" and killed == [] and spawned == []


def test_fire_restart_safe_on_none_and_unknown() -> None:
    """A None plan or an unknown rung is a safe no-op string, never an exception."""
    assert fn.fire_restart(None, enabled=True, killable=True) == "NO_PLAN"
    assert fn.fire_restart({"rung": "bogus"}, enabled=True, killable=True) == "UNKNOWN_RUNG:bogus"


def test_command_plan_prefers_tmux_then_iterm_then_aimaestro_then_linux_gui() -> None:
    """Channel priority, most-direct first: tmux -> iterm -> aimaestro -> linux-gui.
    Each lower-priority identity is present but never chosen while a higher one is."""
    terminal_all = {
        "tmux_pane": "%3", "iterm_session_id": "tty:4C4A-9B7",
        "aimaestro_session": "agent-x", "aimaestro_cli": "/bin/aimaestro-agent.sh",
        "linux_gui_channel": "wtype",
    }
    plan = fn.command_injection_plan(terminal_all, "/janitor-arm", esc_first=True)
    assert plan["channel"] == "tmux"

    no_tmux = dict(terminal_all)
    del no_tmux["tmux_pane"]
    plan = fn.command_injection_plan(no_tmux, "/janitor-arm", esc_first=True)
    assert plan["channel"] == "iterm"

    aimaestro_only = {
        "aimaestro_session": "agent-x", "aimaestro_cli": "/bin/aimaestro-agent.sh",
        "linux_gui_channel": "xdotool",
    }
    plan = fn.command_injection_plan(aimaestro_only, "/janitor-arm", esc_first=True)
    assert plan["channel"] == "aimaestro"
    assert plan["argv"] == [
        "/bin/aimaestro-agent.sh", "session", "command", "agent-x",
        "--newline", "--", "/janitor-arm",
    ]

    gui_only = {"linux_gui_channel": "xdotool"}
    plan = fn.command_injection_plan(gui_only, "/janitor-arm", esc_first=True)
    assert plan["channel"] == "xdotool"
    assert ["RUN", "xdotool", "type", "--clearmodifiers", "--", "/janitor-arm"] in plan["steps"]


def test_command_plan_aimaestro_requires_both_session_and_cli() -> None:
    """A partial ai-maestro identity (session without a resolved CLI, or vice versa)
    never builds a plan — fail-open, never guess a channel."""
    assert fn.command_injection_plan({"aimaestro_session": "agent-x"}, "/x", esc_first=True) is None
    assert fn.command_injection_plan(
        {"aimaestro_cli": "/bin/aimaestro-agent.sh"}, "/x", esc_first=True
    ) is None


def test_command_plan_wtype_channel_builds_steps() -> None:
    """The Linux GUI channel dispatches to the matching builder (wtype vs xdotool) by
    the `linux_gui_channel` tag; falls open to None with an unrecognised value."""
    plan = fn.command_injection_plan({"linux_gui_channel": "wtype"}, "/compact", esc_first=True)
    assert plan["channel"] == "wtype"
    assert ["RUN", "wtype", "/compact"] in plan["steps"]
    assert fn.command_injection_plan({"linux_gui_channel": "bogus"}, "/x", esc_first=True) is None


def test_command_plan_none_when_nothing_resolves() -> None:
    """An empty terminal identity never guesses a channel."""
    assert fn.command_injection_plan({}, "/janitor-arm", esc_first=True) is None
