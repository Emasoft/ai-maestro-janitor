"""Tests for the fleet recovery injector (TRDD-324223a6, GROUP A / A3).

Pure plan-building — no keystrokes are fired (that I/O is the daemon's job, and
firing would inject into real panes). The load-bearing properties: only the
command-typing rungs produce a plan; tmux is preferred over iTerm when both are
present (the ai-maestro-compatible, no-AppleScript path); an iTerm plan is built
ONLY for a UUID that passes the injection-safety gate; and the osascript targets
exactly the stored session, never a broadcast.

The two NEW channels (TRDD-ME8V2YJF follow-up — ai-maestro CLI, Linux GUI
wtype/xdotool) are tested the same way: pure argv building, and `fire()` dispatch
proven via injected/monkeypatched spawn points — never a real subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_inject as fi  # type: ignore[import-not-found]  # noqa: E402


def test_action_to_command_only_typing_rungs() -> None:
    """The gentle command-typing rungs map to a slash-command; esc_nudge (ESC only)
    and the hard-restart rungs (handled by the daemon) map to None."""
    assert fi.action_to_command("rearm") == "/janitor-arm"
    # --force always (user directive 2026-07-10): a mid-use plugin can refuse a
    # plain reload and silently stay on the old cached version.
    assert fi.action_to_command("reload") == "/reload-plugins --force"
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


def test_build_command_plan_tmux_honors_soft() -> None:
    """esc_first=False must reach the tmux steps too (TRDD-0GPQROC1): the old
    always-ESC shortcut silently turned every SOFT intent hard on this channel —
    a mid-turn Claude in tmux is interrupted by ESC exactly like in iTerm."""
    soft = fi.build_command_plan({"tmux_pane": "%5"}, "/janitor-arm", esc_first=False)
    assert soft is not None and soft["channel"] == "tmux"
    assert not any("Escape" in step for step in soft["steps"]), "soft tmux plan must not send ESC"
    hard = fi.build_command_plan({"tmux_pane": "%5"}, "/janitor-arm", esc_first=True)
    assert hard is not None
    assert any("Escape" in step for step in hard["steps"]), "hard tmux plan leads with ESC"


def test_build_injection_soft_reaches_the_plan() -> None:
    """build_injection forwards esc_first (TRDD-0GPQROC1): the daemon passes
    injection_is_hard(diagnosis), so a live cron_dead target gets a soft enqueue
    that preserves its in-flight turn."""
    plan = fi.build_injection({"tmux_pane": "%5"}, "rearm", esc_first=False)
    assert plan is not None
    assert not any("Escape" in step for step in plan["steps"])


def test_build_injection_iterm_fallback_strips_tty_prefix() -> None:
    """With no tmux pane, an iTerm plan is built from the '<tty>:<uuid>' identity —
    the tty prefix is stripped and only the UUID is interpolated."""
    plan = fi.build_injection({"iterm_session_id": "ttys003:4C4A-9B7"}, "reload")
    assert plan is not None
    assert plan["channel"] == "iterm"
    assert 'if (id of s) is "4C4A-9B7" then' in plan["osascript"]
    assert 'write text "/reload-plugins --force"' in plan["osascript"]


def test_build_injection_declines_unreachable_and_hard_rungs() -> None:
    """No tmux pane + no valid UUID → no plan (don't fire blind). A hard-restart rung types no
    command and is not ESC-only → no plan even with a good terminal (the daemon owns those)."""
    assert fi.build_injection({}, "rearm") is None
    assert fi.build_injection({"iterm_session_id": "not a uuid !!"}, "rearm") is None
    assert fi.build_injection({"tmux_pane": "%9"}, "resurrect") is None
    assert fi.build_injection({"tmux_pane": "%9"}, "force_restart") is None


def test_build_injection_esc_nudge_builds_an_esc_only_plan() -> None:
    """THE FLOOD FIX (TRDD-P7WU40G9): `esc_nudge` builds an ESC-ONLY plan on the resolved channel
    — a real plan (NOT None), but one that types NO command (`command == ""`). This is how a
    rate-limited session is recovered without a slash-command accumulating on its retry-blocked
    input line. An unreachable terminal still declines."""
    tmux = fi.build_injection({"tmux_pane": "%9"}, "esc_nudge")
    assert tmux is not None and tmux["channel"] == "tmux" and tmux["command"] == ""
    iterm = fi.build_injection({"iterm_session_id": "ttys3:4C4A-9B7"}, "esc_nudge")
    assert iterm is not None and iterm["channel"] == "iterm" and iterm["command"] == ""
    # ESC-only carries no slash-command anywhere in its payload — the regression that caused the
    # /janitor-arm flood.
    assert "/janitor-arm" not in iterm["osascript"] and "/reload-plugins" not in iterm["osascript"]
    assert fi.build_injection({}, "esc_nudge") is None  # no channel → still declines


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


def test_aimaestro_command_argv_shape() -> None:
    """Pure argv builder: `<cli> session command <session> --newline -- <command>` —
    the frozen ai-maestro CLI interface; no ESC primitive (documented: enqueues
    regardless of hard/soft intent)."""
    argv = fi.aimaestro_command_argv("/home/x/.local/bin/aimaestro-agent.sh", "agent-foo", "/janitor-arm")
    assert argv == [
        "/home/x/.local/bin/aimaestro-agent.sh", "session", "command", "agent-foo",
        "--newline", "--", "/janitor-arm",
    ]


def _aimaestro_plan(command: str = "/janitor-arm") -> dict:
    return {
        "channel": "aimaestro", "command": command,
        "argv": ["cli", "session", "command", "agent-foo", "--newline", "--", command],
    }


def test_fire_aimaestro_runs_the_cli_synchronously_and_bounded(monkeypatch) -> None:
    """The aimaestro channel runs the resolved argv SYNCHRONOUSLY (subprocess.run, not a
    detached Popen) under a bound, and reports DELIVERY (returncode 0), not mere spawn.
    Unlike the keystroke channels it is an RPC with a real exit code (TRDD-3VW434Q8)."""
    calls: list = []

    def fake_run(*a, **k):
        calls.append((a, k))
        return subprocess.CompletedProcess(a[0], 0, stdout="", stderr="")

    monkeypatch.setattr(fi.subprocess, "run", fake_run)
    plan = _aimaestro_plan()
    assert fi.fire(plan) is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == plan["argv"]
    assert kwargs["timeout"] == fi.AIMAESTRO_CLI_TIMEOUT_S   # bounded — never an unbounded wait
    assert kwargs["check"] is False                          # a non-zero exit is data, not an exception


def test_fire_aimaestro_nonzero_exit_is_a_failure(monkeypatch) -> None:
    """THE REGRESSION GUARD (TRDD-3VW434Q8). A non-zero CLI exit — a 403 once ai-maestro
    strict-classifies the inject verb (their #54), a down server, an unauthenticated CLI,
    a stale session name — means the command was NOT delivered, so fire() must report
    False. It previously returned True on spawn, so `_fire_fleet_stop` stamped an
    UNDELIVERED machine-wide stop as delivered and never retried it."""
    monkeypatch.setattr(
        fi.subprocess, "run",
        lambda *a, **_k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="403 Forbidden"),
    )
    assert fi.fire(_aimaestro_plan()) is False


def test_fire_aimaestro_timeout_is_a_failure(monkeypatch) -> None:
    """A CLI that hangs past the bound is UNDELIVERED, not delivered. TimeoutExpired
    subclasses SubprocessError, so the branch's existing guard renders it as False —
    the caller logs FIRE-FAILED and retries next beat."""
    def hang(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="cli", timeout=fi.AIMAESTRO_CLI_TIMEOUT_S)
    monkeypatch.setattr(fi.subprocess, "run", hang)
    assert fi.fire(_aimaestro_plan()) is False


def test_fire_aimaestro_spawn_failure_returns_false(monkeypatch) -> None:
    """An un-spawnable CLI (absent binary) degrades to False rather than letting the
    OSError escape and crash the whole fleet beat through Task.run's blanket handler."""
    def boom(*_a, **_k):
        raise FileNotFoundError("cli not found")
    monkeypatch.setattr(fi.subprocess, "run", boom)
    assert fi.fire(_aimaestro_plan("/x")) is False


def test_fire_wtype_and_xdotool_use_detached_steps(monkeypatch) -> None:
    """The Linux GUI channels (wtype/xdotool) reuse terminal_trigger's detached-step
    runner, exactly like the tmux channel."""
    seen: list = []
    monkeypatch.setattr(
        fi.terminal_trigger, "_fire_detached_steps",
        lambda delay, steps: seen.append((delay, steps)),
    )
    for channel in ("wtype", "xdotool"):
        plan = {"channel": channel, "command": "/x", "delay_s": 2.0, "steps": [["RUN", channel, "/x"]]}
        assert fi.fire(plan) is True
    assert len(seen) == 2
    assert seen[0] == (2.0, [["RUN", "wtype", "/x"]])
    assert seen[1] == (2.0, [["RUN", "xdotool", "/x"]])


# ---------------------------------------------------------------------------
# Gentle/hard rung reachability parity — the severity inversion.
#
# `build_injection` (gentle rungs: rearm/reload/update) used to stop after the
# iterm channel, while `fleet_restart._command_plan` (hard rungs: relaunch /
# force_restart) already walked tmux -> iterm -> aimaestro -> linux-gui. So an
# ai-maestro agent reachable ONLY via the CLI channel, and any Linux GUI
# terminal, was reported UNREACHABLE for a harmless `/janitor-arm`, kept
# escalating, and eventually met a rung that KILLS it. The gentle fix was
# skipped exactly where the violent one landed. These lock the two sets together.
# ---------------------------------------------------------------------------

_AIMAESTRO_TERMINAL = {
    "aimaestro_session": "agent-foo",
    "aimaestro_cli": "/usr/bin/aimaestro-agent.sh",
}
_GUI_TERMINAL = {"linux_gui_channel": "wtype"}


def test_build_injection_reaches_aimaestro_agent() -> None:
    """A gentle rung MUST reach an ai-maestro agent that only the CLI channel can place
    (a nested/managed tmux the raw TTY scan cannot see)."""
    plan = fi.build_injection(_AIMAESTRO_TERMINAL, "rearm")
    assert plan is not None, "gentle rung must not declare an ai-maestro agent unreachable"
    assert plan["channel"] == "aimaestro"
    assert plan["command"] == "/janitor-arm"
    assert plan["argv"] == [
        "/usr/bin/aimaestro-agent.sh", "session", "command", "agent-foo",
        "--newline", "--", "/janitor-arm",
    ]


def test_build_injection_reaches_linux_gui_terminal() -> None:
    """A gentle rung MUST reach a Linux GUI terminal (focused-window, best effort)."""
    plan = fi.build_injection(_GUI_TERMINAL, "reload")
    assert plan is not None
    assert plan["channel"] == "wtype"
    assert plan["command"] == "/reload-plugins --force"
    assert plan["steps"]


def test_build_injection_channel_precedence_unchanged() -> None:
    """Adding the fallbacks must not demote an already-direct channel: tmux still wins
    over iterm, and both still win over aimaestro / linux-gui."""
    both = {
        "tmux_pane": "%3", "iterm_session_id": "DEADBEEF-0000",
        **_AIMAESTRO_TERMINAL, **_GUI_TERMINAL,
    }
    tmux_plan = fi.build_injection(both, "rearm")
    assert tmux_plan is not None and tmux_plan["channel"] == "tmux"
    no_tmux = {k: v for k, v in both.items() if k != "tmux_pane"}
    iterm_plan = fi.build_injection(no_tmux, "rearm")
    assert iterm_plan is not None and iterm_plan["channel"] == "iterm"
    cli_only = {**_AIMAESTRO_TERMINAL, **_GUI_TERMINAL}
    cli_plan = fi.build_injection(cli_only, "rearm")
    assert cli_plan is not None and cli_plan["channel"] == "aimaestro"


def test_build_injection_still_none_when_no_channel() -> None:
    """A genuinely unreachable terminal still declines — the fallbacks must not invent
    a channel out of an empty or bogus identity."""
    assert fi.build_injection({}, "rearm") is None
    assert fi.build_injection({"linux_gui_channel": "bogus"}, "rearm") is None


def test_build_injection_declines_hard_rungs() -> None:
    """The hard rungs type no command and are not ESC-only -> still None, even with a live
    channel resolved (the daemon executes those behind its crash-loop guard)."""
    assert fi.build_injection(_AIMAESTRO_TERMINAL, "force_restart") is None
    assert fi.build_injection(_AIMAESTRO_TERMINAL, "relaunch") is None


def test_esc_only_plan_never_uses_the_aimaestro_channel() -> None:
    """build_esc_plan mirrors build_command_plan MINUS the ai-maestro CLI channel — the CLI has
    no raw-ESC primitive (a managed agent only ENQUEUES), and an ai-maestro agent is server_owned
    and never recovered by this daemon. So an aimaestro-only terminal yields NO esc plan; a tmux
    pane on the same terminal is used instead."""
    assert fi.build_esc_plan(_AIMAESTRO_TERMINAL) is None
    both = fi.build_esc_plan({**_AIMAESTRO_TERMINAL, "tmux_pane": "%7"})
    assert both is not None and both["channel"] == "tmux" and both["command"] == ""


def test_gentle_and_hard_paths_agree_on_every_terminal_shape() -> None:
    """The invariant the inversion violated: for the SAME terminal, the gentle builder
    and the hard builder resolve the SAME channel — including agreeing on None."""
    import fleet_restart as fr  # type: ignore[import-not-found]

    shapes = [
        {"tmux_pane": "%7"},
        {"iterm_session_id": "tty1:DEADBEEF-1234"},
        dict(_AIMAESTRO_TERMINAL),
        dict(_GUI_TERMINAL),
        {"linux_gui_channel": "xdotool"},
        {},
        {"tmux_pane": "-bad"},              # malformed pane -> decline that channel
        {"iterm_session_id": "no;script"},  # malformed uuid -> decline that channel
    ]
    for term in shapes:
        gentle = fi.build_injection(term, "rearm")
        hard = fr._command_plan(term, "/janitor-arm", esc_first=True)
        gentle_ch = gentle["channel"] if gentle else None
        hard_ch = hard["channel"] if hard else None
        assert gentle_ch == hard_ch, f"reachability drift on {term}: {gentle_ch} vs {hard_ch}"


# ---- the iTerm sink must be injection-proof (audit finding 3) ----------------

_UUID = "4C4A9B71-0000-4000-8000-000000000000"


def test_iterm_command_with_a_quote_cannot_escape_the_applescript_string():
    """The iTerm channel builds `write text "<command>"` by interpolation, and it is the ONLY
    channel that does (tmux/wtype/xdotool pass argv or `-l` literal). It used to interpolate
    raw, guarded only by every caller happening to pass a fixed internal literal — while
    build_command_plan / command_injection_plan ADVERTISE themselves as builders for an
    ARBITRARY command. A `"` must be escaped, not close the string."""
    script = fi.iterm_osascript(_UUID, '/x" & (do shell script "touch /tmp/pwned") & "',
                                esc_first=False)
    # The quotes are escaped, so no bare `"` ever terminates the write-text literal early.
    assert '\\"' in script
    assert 'write text "/x\\" & (do shell script \\"touch /tmp/pwned\\") & \\""' in script


def test_iterm_command_with_a_backslash_is_escaped_before_the_quote():
    """Order matters: escaping the quote first would then double-escape its own backslashes."""
    assert 'write text "a\\\\b"' in fi.iterm_osascript(_UUID, "a\\b", esc_first=False)


def test_iterm_command_refuses_a_newline():
    """A newline cannot appear inside an AppleScript string literal, and it would mean typing
    a SECOND, unreviewed command into the user's shell — refuse, never smuggle."""
    with pytest.raises(ValueError, match="single line"):
        fi.iterm_osascript(_UUID, "/janitor-arm\nrm -rf ~", esc_first=False)


def test_a_normal_command_is_unchanged():
    """The escaping must not perturb the fixed internal literals every caller passes today."""
    assert 'write text "/janitor-arm"' in fi.iterm_osascript(_UUID, "/janitor-arm", esc_first=False)


# ---------------------------------------------------------------------------
# AM8JD9SG F10 — SOFT sends to a server-managed pane go THROUGH the server.
# ---------------------------------------------------------------------------


def test_soft_send_prefers_aimaestro_channel_for_server_managed_pane() -> None:
    """A pane that is BOTH tmux-reachable and server-managed: a SOFT send must use the
    server's own channel (the server sees and queues the command) instead of raw
    send-keys typed behind the server's back."""
    both = {"tmux_pane": "%3", **_AIMAESTRO_TERMINAL}
    plan = fi.build_command_plan(both, "/janitor-arm", esc_first=False)
    assert plan is not None and plan["channel"] == "aimaestro"


def test_hard_send_stays_on_tmux_even_for_server_managed_pane() -> None:
    """The ai-maestro channel has no ESC primitive, so a HARD intent (the ESC is the
    point — e.g. a frozen target) must keep the tmux keystroke channel."""
    both = {"tmux_pane": "%3", **_AIMAESTRO_TERMINAL}
    plan = fi.build_command_plan(both, "/janitor-arm", esc_first=True)
    assert plan is not None and plan["channel"] == "tmux"
    assert plan["steps"][0][:2] == ["RUN", "tmux"] or plan["steps"], "tmux steps expected"


def test_hard_send_falls_through_to_aimaestro_when_cli_is_the_only_channel() -> None:
    """Reachability parity survives F10: an aimaestro-ONLY identity still gets the CLI
    channel for a hard intent (an ESC-less enqueue beats UNREACHABLE-then-escalate)."""
    plan = fi.build_command_plan(dict(_AIMAESTRO_TERMINAL), "/janitor-arm", esc_first=True)
    assert plan is not None and plan["channel"] == "aimaestro"
