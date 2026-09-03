"""Daemon fleet-stop beat (TRDD-ME8V2YJF) — task_fleet_stop end-to-end decision test.

Real global-state I/O (isolated dir) + real flag setters, but the fleet scan, the
channel builder, and the FIRE are stubbed so the test never spawns a process or types
a keystroke. Pins: opt-in-off is inert, flag-none clears stamps, a set flag injects
the stop command into every OTHER session (never self/daemon/user-active), dedupe,
no-stamp-on-fire-failure, and the soft/hard ESC policy (soft everywhere EXCEPT a
frozen target, whose wedged turn would never dequeue a soft command).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
fleet_scan = importlib.import_module("fleet_scan")
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pane_frames"


def _inst(
    pid: int,
    *,
    active: bool = False,
    command: str = "claude",
    diagnosis: str = "healthy",
) -> object:
    return fleet_scan.Instance(
        pid=pid, command=command, tty=f"ttys{pid:03d}", project_root=f"/proj/{pid}",
        terminal={"tmux_pane": f"%{pid}"}, diagnosis=diagnosis, recovery=None,
        dispatch_age_s=None, active=active, transcript_age_s=10,
    )


def _has_esc(calls: list[dict]) -> list[bool]:
    """Does each fired plan CONTAIN an ESC — the soft/hard switch, observed in the KEYSTROKES.

    PRESENCE, not position. The predicate is `any(...)` over the step list, so
    an ESC emitted AFTER the command would read the same as one emitted before it. Today the two
    coincide — `build_tmux_steps` appends its `HARD_INTERRUPT_ESC_COUNT` `Escape` steps under
    `if esc_first:` BEFORE the loop that types the commands, and its own docstring calls the
    sequence "an OPTIONAL leading ESC, then each command" — so the assertions pass for the
    right reason — but nothing here would catch a builder that moved the ESC after the command,
    which is the "an ESC into a clear field interrupts the fresh turn" hazard `pane_policy._rung`
    warns about. Pinning the order needs an index comparison, not an `any`; it is worth doing the
    day a builder makes that mistake plausible, and saying so is worth more than a name that
    quietly claims it already happened.

    These tests used to read `plan["esc_first"]`, a key the `_wire` stub put on its OWN synthetic
    dict. TRDD-N954KWUC P3 routes fleet-stop through the policy table, which REBUILDS the plan
    with the real `fleet_inject.build_command_plan` (the caller's plan is only a fallback for a
    terminal that cannot be rebuilt) — so the stub's marker key never reaches `fire` and the
    assertion was pinning which dict object travelled, not what got typed.

    The policy is unchanged and still observable: a hard stop emits an `Escape` step ahead of the
    command, a soft one does not. Reading the steps tests the behaviour instead of the plumbing,
    and it keeps working the next time the plan's shape changes.

    Reads BOTH plan shapes and RAISES on a third, rather than answering False. `steps` is the
    tmux/wtype/xdotool shape; the iTerm branch carries an `osascript` string with the ESC baked
    into it and no `steps` at all. A bare `.get("steps", [])` would report "no ESC" there — which
    fails `test_frozen_target_is_hard` loudly (fine) but makes `test_healthy_target_is_soft` pass
    for the wrong reason: not because no ESC was sent, but because the helper cannot see ESCs on
    that channel. A soft-stop assertion that CANNOT fail is worse than no assertion, because the
    thing it guards is "we do not interrupt a live turn". Every `_inst` here builds
    `terminal={"tmux_pane": ...}`, so tmux is all this file exercises today; the iTerm arm is
    untaken but NOT dead — it is what makes the branch already correct on the day a fixture
    carrying a real `iterm_session_id` appears.

    `build_command_plan` returns four channels, and the `steps` arm covers three of them, not
    just tmux: tmux emits `send-keys … Escape`, wtype `-k Escape`, xdotool `key Escape` — the
    same literal token in all three (verified in `terminal_trigger`: `wtype -k Escape` at :942,
    `xdotool key Escape` at :971). The fourth is `aimaestro`, which returns `{channel, command,
    argv}` with NEITHER key and so hits the raise. That is deliberate but should not read as a
    mystery — and the reason is NOT "aimaestro is only chosen for soft sends". `build_command_plan`
    returns an aimaestro plan from TWO places: the soft branch (`session and cli and not
    esc_first`), and a HARD-INTENT FALL-THROUGH taken when there is no tmux pane and no iTerm id,
    on the grounds that an enqueue ignoring the requested ESC still beats UNREACHABLE. So an
    aimaestro plan can answer a hard request; what is invariant is that it carries NO ESC either
    way. That is read from the payload, not inferred from the branch: `aimaestro_command_argv`
    returns `[cli, "session", "command", <session>, "--newline", "--", <command>]` — no ESC, no
    interrupt flag, and no `esc_first` parameter to take one, because the RPC has no raw-ESC
    primitive and typing into a mid-turn agent enqueues regardless of intent.

    Whoever first adds an `aimaestro_session`/`aimaestro_cli` fixture should therefore append
    `False` for it — correct, since the question this helper asks is "did the plan LEAD WITH AN
    ESC", not "was a hard stop intended" — and should know that a `False` there may be a hard
    stop that silently could not deliver its ESC, which is a fact about the channel worth its own
    test rather than a line in this one. The raise exists for a genuinely NEW shape.

    The iTerm predicate is `character id 27`, not `Escape` — measured, not assumed. AppleScript
    sends a raw ESC as `write text (character id 27) without newline`
    (`terminal_trigger.iterm_esc_lines`), so the word "Escape" appears in a HARD iTerm plan
    exactly never; keying on it would report every iTerm stop as soft and reintroduce the vacuous
    assertion one layer down.

    These tests are the only coverage of `pane_actuate.act`'s `fail_open` (verified repo-wide:
    the only other mention is the `daemon.py` fleet-stop call site that passes it). `_wire` stubs
    the capture seam with an IDLE frame (see the note there — leaving it unstubbed made these
    tests depend on the developer's live tmux server), so `_rung`'s wedge branch correctly does
    not fire on an idle pane and `esc_first` reaches the command step directly, which is what
    `test_frozen_target_is_hard` pins.
    """
    out: list[bool] = []
    for c in calls:
        if "steps" in c:
            # A step is a list of argv tokens (`['RUN','tmux','send-keys','-t','%41','Escape']`),
            # so this is a membership test on that list, not a substring test on a string.
            out.append(any("Escape" in step for step in c["steps"]))
        elif "osascript" in c:
            # NOT `"Escape" in ...`: AppleScript sends a raw ESC as
            # `write text (character id 27) without newline` (`terminal_trigger.iterm_esc_lines`),
            # so the word "Escape" appears in a hard iTerm plan exactly never — measured. Keying
            # on it would have reported every iTerm stop as SOFT, which is the vacuous-assertion
            # bug this helper exists to prevent, reintroduced one layer down.
            #
            # And this predicate DISCRIMINATES, which is the half that is easy to skip: measured
            # against a real `iterm_session_id`, a hard plan contains `character id 27` twice
            # (`HARD_INTERRUPT_ESC_COUNT == 2`) and a soft plan contains it zero times. Presence
            # is enough; the count is not asserted, so raising that constant does not touch this.
            out.append("character id 27" in c["osascript"])
        else:
            raise AssertionError(f"unknown plan shape, cannot read the soft/hard policy: {sorted(c)}")
    return out


class _Fire:
    def __init__(self, result: bool = True) -> None:
        self.calls: list[dict] = []
        self.result = result

    def __call__(self, plan: dict) -> bool:
        self.calls.append(plan)
        return self.result


def _wire(monkeypatch, tmp_path, *, fleet, enabled=True, fire_ok=True, plan: str | None = "ok"):
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED", "1" if enabled else "0")
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda *, now: fleet)
    monkeypatch.setattr(daemon.gs, "daemon_pid", lambda: 2)
    monkeypatch.setattr(daemon.os, "getpid", lambda: 1)

    def _plan(terminal, command, *, esc_first):
        # Carry esc_first into the fired plan so the tests can pin the soft/hard policy
        # (soft by default per TRDD-0GPQROC1; hard ONLY for a frozen target).
        if plan is None:
            return None
        return {"channel": "tmux", "command": command, "esc_first": esc_first}

    monkeypatch.setattr(daemon.fleet_restart, "command_injection_plan", _plan)
    # Stub the capture SEAM. It used to be left unstubbed, on the belief that a tmux pane like
    # `%41` cannot exist so the read returns None and `act` proceeds blind. That belief is
    # wrong twice over. `act`'s Law 1 is `blind_ok = not (read_pane and
    # channel_has_readback(terminal))`, and every `_inst` here carries a `tmux_pane` — so the
    # channel HAS read-back, a None read is "readable pane that did not answer", and `act`
    # returns NOOP typing nothing. And the read is a REAL `tmux` shell-out against the
    # developer's own server, so what these tests asserted depended on that machine's live pane
    # list and on whether the call beat its timeout under load.
    #
    # Measured 2026-09-03: all 10 passed in isolation and 6 failed inside the full suite with
    # `fire.calls == []` — the signature of the NOOP above. A frozen idle frame makes the route
    # deterministic and closer to production than the blind path ever was: `act` parses a real
    # state, `_rung`'s wedge branch correctly does not fire on an idle pane, and `esc_first`
    # reaches the command step exactly as the soft/hard assertions below require.
    monkeypatch.setattr(
        daemon.fleet_scan,
        "capture_pane_text",
        lambda _terminal: (_FIXTURES / "synthetic-idle-empty-field.txt").read_text(encoding="utf-8"),
    )
    fire = _Fire(fire_ok)
    monkeypatch.setattr(daemon.fleet_inject, "fire", fire)
    return fire


def test_inert_when_opt_in_off(monkeypatch, tmp_path) -> None:
    """With the opt-in off, the beat fires nothing even though a disarm flag is set."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(10)], enabled=False)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert fire.calls == []


def test_no_flag_clears_stamps(monkeypatch, tmp_path) -> None:
    """No fleet-stop flag → the beat clears any stamps and fires nothing."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(10)])
    gs.record_fleet_injection(10, "disarm", now=1)
    daemon.task_fleet_stop()
    assert fire.calls == []
    assert gs.fleet_injections_seen() == set()


def test_disarm_injects_all_others(monkeypatch, tmp_path) -> None:
    """A disarm flag injects /janitor-disarm into every clean OTHER session and stamps."""
    fleet = [_inst(1), _inst(2), _inst(40, active=True), _inst(41), _inst(42)]
    fire = _wire(monkeypatch, tmp_path, fleet=fleet)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    fired_cmds = {c["command"] for c in fire.calls}
    assert fired_cmds == {"/janitor-disarm"}
    # only 41 + 42: 1=self, 2=daemon, 40=user-active
    assert len(fire.calls) == 2
    assert gs.fleet_injections_seen() == {"41:disarm", "42:disarm"}


def test_dedupe_skips_already_injected(monkeypatch, tmp_path) -> None:
    """An already-stamped (pid, flag) is not re-fired on the next beat."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41), _inst(42)])
    gs.set_kill_switch("d")
    gs.record_fleet_injection(41, "disarm", now=1)
    daemon.task_fleet_stop()
    assert len(fire.calls) == 1
    assert gs.fleet_injections_seen() == {"41:disarm", "42:disarm"}


def test_a_stale_pause_flag_injects_NOTHING(monkeypatch, tmp_path) -> None:
    """The retired pause flag must not drive a fleet-wide injection.

    Pause is gone (owner directive 2026-07-31) and `/janitor-pause` no longer exists, so a host
    still carrying the flag would otherwise have every session in the fleet typed at with a
    command that does not resolve — a fleet-wide error loop driven by dead state.
    """
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)])
    cd = gs.control_dir()
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "global-pause.flag").write_text("{}", encoding="utf-8")
    daemon.task_fleet_stop()
    assert fire.calls == [], f"a retired flag still injected: {fire.calls}"


def test_no_stamp_on_fire_failure(monkeypatch, tmp_path) -> None:
    """A failed fire records NO stamp, so the next beat retries that session."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)], fire_ok=False)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert len(fire.calls) == 1
    assert gs.fleet_injections_seen() == set()


def test_unreachable_channel_skipped(monkeypatch, tmp_path) -> None:
    """A session with no resolvable channel (plan None) is skipped, not stamped."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)], plan=None)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert fire.calls == []
    assert gs.fleet_injections_seen() == set()


def test_healthy_target_is_soft(monkeypatch, tmp_path) -> None:
    """A live (non-frozen) session gets the stop ENQUEUED — no ESC, so its in-flight
    turn finishes first (TRDD-0GPQROC1)."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)])
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert _has_esc(fire.calls) == [False]


def test_frozen_target_is_hard(monkeypatch, tmp_path) -> None:
    """A FROZEN session gets an ESC first: its wedged turn never ends, so a soft command
    would sit in the input queue forever while the fire is stamped as delivered — the
    stop would never actually run and the cron would keep billing turns."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41, diagnosis="frozen")])
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert _has_esc(fire.calls) == [True]


def test_cron_dead_target_is_soft(monkeypatch, tmp_path) -> None:
    """cron_dead is a LIVE session with only a dead heartbeat — still soft."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41, diagnosis="cron_dead")])
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert _has_esc(fire.calls) == [False]
