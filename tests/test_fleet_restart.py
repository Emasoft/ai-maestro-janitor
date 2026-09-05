"""Tests for the hard-restart recovery rung (TRDD-56d24c02 / A5).

The two kill rungs (force_restart, resurrect) were RETIRED — TRDD-56d24c02, executed by
TRDD-V07NFXS9 — leaving `relaunch` as the sole hard-restart rung. It never kills a
process, so the keystroke `fleet_inject.fire` is monkeypatched and no real process is ever
touched. What is proven here is the SAFETY CONTROL FLOW — default-off dry-run, and
`is_killable`'s own refusal gate (kept per TRDD-56d24c02's decision even though this
module no longer calls it).

The channel-resolution tests (TRDD-ME8V2YJF follow-up) prove `_command_plan`'s
fallback order for the two NEW channels (ai-maestro CLI, Linux GUI wtype/xdotool)
without touching the unchanged tmux/iTerm behaviour — pure dict-in/plan-out, no
subprocess, no network.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_restart as fn  # type: ignore[import-not-found]  # noqa: E402


class _KillableKwargs(TypedDict):
    """Shape of `is_killable`'s kwargs (TypedDict, PEP 692) — a bare `dict(...)` mixing
    int/str/bool values infers a single union value type, so `**base` broadcasts that
    union against every keyword parameter regardless of which key actually supplies it."""

    pid: int
    command: str
    active: bool
    diagnosis: str
    self_pid: int
    daemon_pid: int


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
    base: _KillableKwargs = {
        "pid": 4242,
        "command": "claude --foo",
        "active": False,
        "diagnosis": "frozen",
        "self_pid": 10,
        "daemon_pid": 20,
    }
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
    assert tmux["channel"] == "tmux" and tmux["command"].startswith("claude --continue")
    iterm = fn.build_relaunch({"iterm_session_id": "ttys4:4C4A-9B7"})
    assert iterm is not None and iterm["channel"] == "iterm"
    assert "claude --continue" in iterm["osascript"]
    assert fn.build_relaunch({}) is None                        # nowhere safe to type
    assert fn.build_relaunch({"tmux_pane": "-X"}) is None        # malformed pane rejected


def test_relaunch_can_actually_proceed_unattended() -> None:
    """A relaunch REPLAYS the user's own launch flags, so it comes back able to PROCEED.

    A rung only ever fires at an ALREADY-unattended wedged session, so a relaunch that comes
    back up and then parks on a permission prompt has not recovered it — the process is
    running again (so the scanner reads it healthy) while the session is as stuck as before.
    The plugin must not SHIP a permission bypass to achieve that (CPV flags the literal
    CRITICAL, correctly): it mirrors whatever the user launched with, so a session started
    unattended relaunches unattended, and one started interactively does not.
    """
    launched = "claude --add-dir /tmp --dangerously-skip-permissions"
    plan = fn.build_relaunch({"tmux_pane": "%7"}, command=fn.with_resume(launched))
    assert plan is not None
    cmd = plan["command"]

    assert "--add-dir /tmp" in cmd  # every user flag survives, not just the ones we'd guess
    assert "--dangerously-skip-permissions" in cmd
    assert "--continue" in cmd  # …and the transcript is still resumed


def test_the_plugin_ships_no_permission_bypass_invocation() -> None:
    """No janitor source may spell a `claude … --dangerously-skip-permissions` invocation.

    The tripwire for the regression that shipped on 2026-07-29: the relaunch line was
    hardcoded WITH the bypass, and CPV's security gate failed the publish CRITICAL. It was
    right to. Obfuscating the string to slip past the scanner would hide a real capability
    while keeping it working — strictly worse than the finding. The only honest fix is the
    one implemented: mirror the user's argv, ship nothing.

    It matches CPV's own shape — the flag on a line that INVOKES claude — rather than any
    mention of the flag. Banning the mention outright would forbid documenting WHY this
    module mirrors instead of hardcoding, and that WHY is the thing that stops the next
    author from "helpfully" adding the flag back.
    """
    invocation = re.compile(r"\bclaude\b[^\n]*--dangerously-skip-permissions")
    root = Path(__file__).resolve().parent.parent / "scripts"
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if invocation.search(p.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"permission-bypass invocation shipped in: {offenders}"


def test_with_resume_guarantees_the_transcript_is_resumed() -> None:
    """`with_resume` adds `--continue` only when no resume flag is already present.

    The failure this prevents is SILENT and total: most sessions are launched as a bare
    `claude`, so a verbatim replay starts an EMPTY session in the recovered pane. The
    process is running (the scanner reads it healthy) while hours of transcript are gone —
    worse than not recovering. An existing `--resume <id>` is left alone: it targets one
    specific session and `--continue` would fight it.
    """
    assert fn.with_resume("claude") == "claude --continue"
    assert fn.with_resume("claude --model opus") == "claude --model opus --continue"
    assert fn.with_resume("claude --continue") == "claude --continue"
    assert fn.with_resume("claude --resume abc123") == "claude --resume abc123"
    assert fn.with_resume("claude -c") == "claude -c"
    assert fn.with_resume("   ") == ""  # whitespace is not a command


def test_argv_is_claude_matches_the_executable_not_the_line() -> None:
    """The replay guard matches argv[0]'s basename, never a substring of the whole line.

    A session whose FLAGS merely mention the word (`--add-dir ~/Code/claude-plugins`) is not
    a claude launch. A substring test would let a recycled pid — or a doctored
    `terminal-identity.json` — turn recovery into arbitrary command execution in the user's
    own pane, which is the whole reason this guard exists.
    """
    assert fn.argv_is_claude("claude --continue")
    assert fn.argv_is_claude("/opt/homebrew/bin/claude --model opus")
    assert not fn.argv_is_claude("bash -c 'claude --continue'")
    assert not fn.argv_is_claude("rm -rf ~/Code/claude-plugins")
    assert not fn.argv_is_claude("")
    assert not fn.argv_is_claude("claude --add-dir 'unbalanced")  # unparseable ⇒ refuse


def test_relaunch_command_ladder_live_then_recorded_then_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """live argv → recorded argv → `claude --continue`, and a non-claude line is skipped.

    The recorded rung is not a nicety: rung 5 fires on a `dead` instance whose pid is
    ALREADY GONE, so there is no live command line left to read. Without the recording that
    rung has nothing to mirror and every user flag is lost.
    """
    state = tmp_path / ".janitor" / "state"
    state.mkdir(parents=True)
    ident = state / "terminal-identity.json"
    ident.write_text(json.dumps({"argv": "claude --model opus"}), encoding="utf-8")

    # No pid to read ⇒ the recorded argv is used, resume-guaranteed.
    assert fn.relaunch_command(0, str(tmp_path)) == "claude --model opus --continue"

    # A live pid outranks the recording — it is current, with no staleness risk.
    monkeypatch.setattr(fn, "live_cmdline", lambda pid: "claude --add-dir /tmp --continue")
    assert fn.relaunch_command(4242, str(tmp_path)) == "claude --add-dir /tmp --continue"

    # A live line that is NOT claude (recycled pid) falls through to the recording.
    monkeypatch.setattr(fn, "live_cmdline", lambda pid: "python -m http.server")
    assert fn.relaunch_command(4242, str(tmp_path)) == "claude --model opus --continue"

    # Nothing recorded at all ⇒ the minimum that still resumes a transcript.
    assert fn.relaunch_command(0, str(tmp_path / "elsewhere")) == "claude --continue"
    assert fn.relaunch_command(0, None) == "claude --continue"

    # A garbage recording is "no recording", never a crash and never a replayed line.
    ident.write_text("{ not json", encoding="utf-8")
    assert fn.relaunch_command(0, str(tmp_path)) == "claude --continue"
    ident.write_text(json.dumps({"argv": "sudo rm -rf /"}), encoding="utf-8")
    assert fn.relaunch_command(0, str(tmp_path)) == "claude --continue"


def test_build_relaunch_stays_pure_and_falls_back_on_an_empty_command() -> None:
    """`build_relaunch` takes the command as DATA and defaults to the safe minimum.

    Purity is the module contract — a plan must be inspectable and dry-runnable. Resolving
    the argv inside the builder would mean a `ps` call fires merely from BUILDING a plan,
    including in `--dry-run`.
    """
    relaunch = fn.build_relaunch({"tmux_pane": "%7"})
    assert relaunch is not None and "claude --continue" in relaunch["command"]
    assert fn.build_relaunch({}) is None


def test_fire_restart_dry_run_when_disabled_touches_nothing(monkeypatch) -> None:
    """With the opt-in OFF, fire_restart types NOTHING and reports DRY_RUN. This is the
    default production posture."""
    fired: list = []
    monkeypatch.setattr(fn.fleet_inject, "fire", lambda p: fired.append(p) or True)
    plan = fn.build_relaunch({"tmux_pane": "%1"})
    out = fn.fire_restart(plan, enabled=False)
    assert out == "DRY_RUN:relaunch"
    assert fired == []      # absolutely nothing fired


def test_fire_restart_relaunch_fires_the_keystroke(monkeypatch) -> None:
    """relaunch (dead pane, no live pid) fires the keystroke plan when enabled."""
    monkeypatch.setattr(fn.fleet_inject, "fire", lambda p: True)
    plan = fn.build_relaunch({"tmux_pane": "%2"})
    out = fn.fire_restart(plan, enabled=True)
    assert out == "FIRED:relaunch"


def test_fire_restart_safe_on_none_and_unknown() -> None:
    """A None plan or an unknown rung is a safe no-op string, never an exception. The two
    former kill rungs (force_restart, resurrect) were RETIRED — TRDD-56d24c02, executed by
    TRDD-V07NFXS9 — so a plan naming either now surfaces as an unknown rung, never fires."""
    assert fn.fire_restart(None, enabled=True) == "NO_PLAN"
    assert fn.fire_restart({"rung": "bogus"}, enabled=True) == "UNKNOWN_RUNG:bogus"
    assert fn.fire_restart({"rung": "force_restart"}, enabled=True) == "UNKNOWN_RUNG:force_restart"
    assert fn.fire_restart({"rung": "resurrect"}, enabled=True) == "UNKNOWN_RUNG:resurrect"


def test_command_plan_prefers_tmux_then_iterm_then_aimaestro_then_linux_gui() -> None:
    """Channel priority, most-direct first: tmux -> iterm -> aimaestro -> linux-gui.
    Each lower-priority identity is present but never chosen while a higher one is."""
    terminal_all = {
        "tmux_pane": "%3", "iterm_session_id": "tty:4C4A-9B7",
        "aimaestro_session": "agent-x", "aimaestro_cli": "/bin/aimaestro-agent.sh",
        "linux_gui_channel": "wtype",
    }
    plan = fn.command_injection_plan(terminal_all, "/janitor-arm", esc_first=True)
    assert plan is not None and plan["channel"] == "tmux"

    no_tmux = dict(terminal_all)
    del no_tmux["tmux_pane"]
    plan = fn.command_injection_plan(no_tmux, "/janitor-arm", esc_first=True)
    assert plan is not None and plan["channel"] == "iterm"

    aimaestro_only = {
        "aimaestro_session": "agent-x", "aimaestro_cli": "/bin/aimaestro-agent.sh",
        "linux_gui_channel": "xdotool",
    }
    plan = fn.command_injection_plan(aimaestro_only, "/janitor-arm", esc_first=True)
    assert plan is not None
    assert plan["channel"] == "aimaestro"
    assert plan["argv"] == [
        "/bin/aimaestro-agent.sh", "session", "command", "agent-x",
        "--newline", "--", "/janitor-arm",
    ]

    gui_only = {"linux_gui_channel": "xdotool"}
    plan = fn.command_injection_plan(gui_only, "/janitor-arm", esc_first=True)
    assert plan is not None
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
    assert plan is not None
    assert plan["channel"] == "wtype"
    assert ["RUN", "wtype", "/compact"] in plan["steps"]
    assert fn.command_injection_plan({"linux_gui_channel": "bogus"}, "/x", esc_first=True) is None


def test_command_plan_none_when_nothing_resolves() -> None:
    """An empty terminal identity never guesses a channel."""
    assert fn.command_injection_plan({}, "/janitor-arm", esc_first=True) is None
