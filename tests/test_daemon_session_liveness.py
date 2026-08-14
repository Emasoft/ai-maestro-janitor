"""Integration test for the daemon's fleet-guardian task (TRDD-324223a6, A2).

This wires the REAL policy (fleet_recovery), the REAL plan builder
(fleet_inject.build_injection) and the REAL task orchestration together; only two
things are controlled, and both for a hard reason, not convenience:

- ``gather_fleet`` is replaced with a fixed instance list — a genuinely-frozen
  claude session cannot be conjured inside a unit test.
- ``fleet_inject.fire`` is replaced with a recorder — a test MUST NOT actually
  inject ESC + /janitor-arm keystrokes into the developer's real terminals.

Everything between (which diagnosis → which action, reachable vs not, cooldown,
crash-loop give-up, healthy-resets-state) runs for real against an isolated
``JANITOR_GLOBAL_STATE_DIR``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import fleet_scan  # type: ignore[import-not-found]  # noqa: E402


def _inst(
    diagnosis: str, root: str, terminal: dict, *, trailing: int = 0, awaiting: bool = False
) -> "fleet_scan.Instance":
    """A synthetic Instance — only diagnosis/root/terminal matter to the task."""
    return fleet_scan.Instance(
        pid=1, command="claude", tty="ttys1", project_root=root, terminal=terminal,
        diagnosis=diagnosis, recovery=None, dispatch_age_s=None, active=False,
        transcript_age_s=None, trailing_enqueues=trailing, awaiting_user=awaiting,
    )


def _setup(monkeypatch, tmp_path: Path, fleet: list, *, fire: str = "1") -> list:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))   # recovery state
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))   # mirrors the real daemon main()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED", fire)
    # The whole path-resolution chain is @lru_cache'd (log_dir → janitor_root →
    # project_root) — stable in production, but it would otherwise pin the FIRST
    # test's tmp dir for the whole process. Clear the entire chain per test.
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()
    recorded: list = []
    monkeypatch.setattr(daemon.fleet_inject, "fire", lambda plan: bool(recorded.append(plan)) or True)
    # `sweep_stale_rate_limit_s` is the daemon's opt-in stale-flag sweep (janitor#77 item C);
    # the seam accepts and ignores it — these tests inject a fleet, so there are no real roots.
    monkeypatch.setattr(
        daemon.fleet_scan,
        "gather_fleet",
        lambda *, now, sweep_stale_rate_limit_s=None: fleet,
    )
    return recorded


def _log(tmp_path: Path) -> str:
    # the daemon logs to JANITOR_LOG_DIR (set in _setup) → <tmp>/logs/daemon.log
    p = tmp_path / "logs" / "daemon.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_dry_run_detects_but_never_fires(tmp_path, monkeypatch) -> None:
    """With firing OFF the task logs the would-do plan but injects nothing and bumps no
    attempt counter — the detection-before-action mode. It DOES stamp a cooldown (F9): a
    dry run repeated every 120 s used to re-audit forever, and the 1 MB audit trim then
    evicted the real fired/force_restart history in favour of that noise."""
    fleet = [
        _inst("frozen", "/p/proj-a", {"tmux_pane": "%5"}),
        _inst("healthy", "/p/proj-b", {"tmux_pane": "%6"}),
        _inst("unarmed", "/p/proj-c", {"tmux_pane": "%7"}),
    ]
    fired = _setup(monkeypatch, tmp_path, fleet, fire="0")
    daemon.task_session_liveness()
    assert fired == []                                   # dry-run fires nothing
    # frozen (rate-limited) → ESC-only recovery since TRDD-P7WU40G9 (never a typed command).
    assert "session-liveness:DRY would esc_nudge" in _log(tmp_path)
    assert "proj-a" in _log(tmp_path)
    persisted = list((tmp_path / "recovery").glob("*.json"))
    assert len(persisted) == 1                           # only the frozen one is decided
    st = json.loads(persisted[0].read_text(encoding="utf-8"))
    assert "attempts" not in st                          # no attempt consumed
    assert st["last_ts"] and st["last_audit"] == "dry_run:esc_nudge"


def test_fire_recovers_reachable_skips_unreachable(tmp_path, monkeypatch) -> None:
    """Firing ON: a frozen (rate-limited) tmux session is recovered ESC-ONLY (no command) and a
    cron-dead iTerm session is re-armed with /janitor-arm, each on its own channel; a frozen
    session with no resolvable terminal is logged UNREACHABLE and not fired."""
    fleet = [
        _inst("frozen", "/p/proj-a", {"tmux_pane": "%5"}),
        _inst("cron_dead", "/p/proj-b", {"iterm_session_id": "ttys3:4C4A-9B7"}),
        _inst("frozen", "/p/proj-c", {}),               # unreachable
    ]
    fired = _setup(monkeypatch, tmp_path, fleet)
    daemon.task_session_liveness()
    assert sorted(p["channel"] for p in fired) == ["iterm", "tmux"]
    # The frozen tmux session fires ESC-only (command==""); only the cron_dead session types a
    # command (TRDD-P7WU40G9 — a rate-limited session is NEVER typed at).
    assert sorted(p["command"] for p in fired) == ["", "/janitor-arm"]
    assert "UNREACHABLE" in _log(tmp_path)
    # an immediate 2nd beat is blocked by the per-instance cooldown
    fired.clear()
    daemon.task_session_liveness()
    assert fired == []


def _pane(field_body: str) -> str:
    """A minimal real-shaped Claude Code pane capture with `field_body` in the input field."""
    nbsp = " "
    return "some earlier output\n" + "─" * 40 + f"\n❯{nbsp}{field_body}\n" + "─" * 40 + "\n"


def test_field_busy_guard_gates_command_typing_never_esc(tmp_path, monkeypatch) -> None:
    """2026-07-17 incident guard, exercised through the REAL daemon call site:

    (a) an ESC-only plan (frozen/esc_nudge) fires even though the pane's field reads back
        non-empty — ESC cannot approve/select anything, so it is never gated;
    (b) a COMMAND-typing plan (cron_dead/rearm) on a READABLE channel whose field is
        non-empty is REFUSED, never fired;
    (c) the same command plan fires once the field reads back empty;
    (d) the same command plan fires when the channel cannot be read at all (aimaestro CLI —
        write-only), so an unreadable channel is never permanently locked out.
    """
    import fleet_inject

    fleet = [
        _inst("frozen", "/p/proj-a", {"tmux_pane": "%5"}),
        _inst("cron_dead", "/p/proj-b", {"tmux_pane": "%6"}),
    ]
    fired = _setup(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(fleet_inject.terminal_trigger, "read_pane_text", lambda rt: _pane("Allow?"))
    daemon.task_session_liveness()
    # (a) ESC-only still fires despite the busy field.
    assert any(p["channel"] == "tmux" and p["command"] == "" for p in fired)
    # (b) the command-typing plan is refused — nothing typed for proj-b this beat.
    assert not any(p["command"] == "/janitor-arm" for p in fired)
    assert "INPUT FIELD BUSY" in _log(tmp_path)
    st_path = daemon._recovery_state_path(tmp_path / "recovery", "/p/proj-b")
    st = json.loads(st_path.read_text(encoding="utf-8"))
    assert st["last_audit"] == "declined_field_busy:rearm"
    assert "attempts" not in st  # nothing tried — no budget spent (mirrors _decline)

    # (c) once the field reads back empty, the SAME command plan fires (fresh beat: clear
    # the per-instance cooldown state files so this isn't blocked by the earlier decision).
    for f in (tmp_path / "recovery").glob("*.json"):
        f.unlink()
    fired.clear()
    monkeypatch.setattr(fleet_inject.terminal_trigger, "read_pane_text", lambda rt: _pane(""))
    daemon.task_session_liveness()
    assert any(p["command"] == "/janitor-arm" for p in fired)
    assert "INPUT FIELD BUSY" not in _log(tmp_path).split("\n")[-1]

    # (d) an unreadable channel (no tmux/iterm identity — aimaestro CLI shape) stays
    # permissive: the command plan fires even though we cannot prove the field is empty.
    for f in (tmp_path / "recovery").glob("*.json"):
        f.unlink()
    fired.clear()
    fleet2 = [
        _inst(
            "cron_dead", "/p/proj-c",
            {"aimaestro_session": "agent-foo", "aimaestro_cli": "/usr/bin/aimaestro-agent.sh"},
        ),
    ]
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda *, now, sweep_stale_rate_limit_s=None: fleet2)
    monkeypatch.setattr(fleet_inject.terminal_trigger, "read_pane_text", lambda rt: _pane("Allow?"))
    daemon.task_session_liveness()
    assert any(p["command"] == "/janitor-arm" and p["channel"] == "aimaestro" for p in fired)


def test_field_busy_with_our_own_queued_command_submits_it(tmp_path, monkeypatch) -> None:
    """janitor#261: the field is non-empty because WE typed into it, SOFT, and the command
    never ran. Declining there is self-perpetuating — nothing else drains the field, so the
    session that most needs rescuing becomes the one that can never receive it. The daemon
    must instead recognise its OWN command and finish the send with Enter alone.

    No cooldown is stamped on success: the field is now empty, so the next beat should be
    free to run the real recovery rather than wait out a cooldown it did not need to spend.
    """
    import fleet_inject

    fleet = [_inst("cron_dead", "/p/proj-b", {"tmux_pane": "%6"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    # The pane shows EXACTLY the command this plan was about to type — ours, unsubmitted.
    monkeypatch.setattr(
        fleet_inject.terminal_trigger, "read_pane_text", lambda rt: _pane("/janitor-arm")
    )
    daemon.task_session_liveness()

    # Enter ALONE: a plan on the same channel that types no new text.
    assert [p["channel"] for p in fired] == ["tmux"]
    assert fired[0]["command"] == ""
    assert "holds OUR unsubmitted '/janitor-arm'" in _log(tmp_path)
    assert "INPUT FIELD BUSY" not in _log(tmp_path)

    import recovery_audit as ra
    assert "submitted_own_queued_command" in [r["outcome"] for r in ra.load_records()]
    # NO per-instance state file at all ⇒ no cooldown was spent, so the very next beat is
    # free to run the real recovery now that the field has been drained.
    assert not daemon._recovery_state_path(tmp_path / "recovery", "/p/proj-b").exists()


def test_field_busy_with_our_command_that_cannot_be_submitted_declines(
    tmp_path, monkeypatch
) -> None:
    """Same shape, but the Enter cannot be delivered. This beat TRIED and achieved nothing,
    so it must stamp the cooldown like any other no-op decision — auditing without stamping
    would re-decide and re-audit every 120 s forever (the unbounded-audit failure `_decline`
    exists to prevent), and an unsubmittable field persists across beats by definition."""
    import fleet_inject

    fleet = [_inst("cron_dead", "/p/proj-b", {"tmux_pane": "%6"})]
    _setup(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(daemon.fleet_inject, "fire", lambda plan: False)
    monkeypatch.setattr(
        fleet_inject.terminal_trigger, "read_pane_text", lambda rt: _pane("/janitor-arm")
    )
    daemon.task_session_liveness()

    assert "could not submit" in _log(tmp_path)
    st = json.loads(
        daemon._recovery_state_path(tmp_path / "recovery", "/p/proj-b").read_text()
    )
    assert st["last_audit"] == "own_queued_command_unsubmittable:rearm"
    assert st["last_ts"]                # cooldown STAMPED — this beat is not repeated at 120 s
    assert "attempts" not in st         # but no recovery attempt was consumed


def test_crash_loop_alerts_once_then_stays_silent(tmp_path, monkeypatch) -> None:
    """A spent attempt budget (with an elapsed cooldown) trips the crash-loop guard:
    it never fires, alerts a human exactly ONCE, and stays silent thereafter."""
    fleet = [_inst("frozen", "/p/proj-x", {"tmux_pane": "%9"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-x")
    # Seed the spent budget WITH this exact session's identity (pid:tty) — otherwise
    # the identity-stamp guard treats it as a different occupant and correctly resets
    # it (which is itself covered by test_restarted_session_gets_a_fresh_budget below).
    ident = f"{fleet[0].pid}:{fleet[0].tty or ''}"
    sf.write_text(
        json.dumps({"attempts": daemon.fr.MAX_ATTEMPTS, "last_ts": 1, "identity": ident}),
        encoding="utf-8",
    )
    daemon.task_session_liveness()
    assert fired == []
    assert "GIVING UP" in _log(tmp_path)
    assert json.loads(sf.read_text(encoding="utf-8"))["alerted"] is True
    daemon.task_session_liveness()                       # 2nd beat: already alerted
    assert _log(tmp_path).count("GIVING UP") == 1


def test_recovered_instance_resets_its_attempt_budget(tmp_path, monkeypatch) -> None:
    """Once an instance is healthy again, its stale attempt counter is cleared so a
    FUTURE freeze starts with a fresh budget — never inheriting a spent one."""
    fleet = [_inst("healthy", "/p/proj-h", {"tmux_pane": "%1"})]
    _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-h")
    sf.write_text(json.dumps({"attempts": 3, "last_ts": 1}), encoding="utf-8")
    daemon.task_session_liveness()
    assert not sf.exists()


def test_restarted_session_gets_a_fresh_budget(tmp_path, monkeypatch) -> None:
    """A spent/alerted budget left by a PREVIOUS occupant of the same project dir
    (different pid:tty) must NOT be inherited by a freshly-restarted session — the new
    session did nothing wrong and gets a fresh budget, so it IS recovered (audit C3)."""
    fleet = [_inst("frozen", "/p/proj-r", {"tmux_pane": "%2"})]   # identity 1:ttys1
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-r")
    sf.write_text(
        json.dumps({"attempts": daemon.fr.MAX_ATTEMPTS, "last_ts": 1,
                    "alerted": True, "identity": "99999:ttysOLD"}),  # a vanished session
        encoding="utf-8",
    )
    daemon.task_session_liveness()
    assert len(fired) == 1                      # recovered, NOT refused by a stale budget
    st = json.loads(sf.read_text(encoding="utf-8"))
    assert st["identity"] == "1:ttys1"          # budget rebound to the NEW session
    assert st["attempts"] == 1                  # fresh budget (1st attempt), not the old MAX


def test_corrupt_state_file_does_not_crash_the_beat(tmp_path, monkeypatch) -> None:
    """A valid-JSON-but-not-an-object state file (external tampering) degrades to a
    fresh budget for that instance instead of crashing the whole beat (audit C4)."""
    fleet = [_inst("frozen", "/p/proj-c", {"tmux_pane": "%3"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-c")
    sf.write_text("[1, 2, 3]", encoding="utf-8")   # valid JSON, NOT a dict
    daemon.task_session_liveness()                 # must not raise
    assert len(fired) == 1                          # treated as fresh → recovered


def test_an_unreachable_instance_is_not_re_audited_on_every_beat(tmp_path, monkeypatch) -> None:
    """F9: `attempts`/`last_ts` used to be stamped ONLY on a successful fire, so an instance
    we DECIDE about but cannot poke — no injection channel (a plain terminal, VS Code's
    integrated terminal, an ssh session: neither tmux nor iTerm) — never tripped the cooldown.
    It was re-decided and re-audited on every 120 s beat, forever: ~720 identical records per
    day per instance, which then drove the 1 MB audit trim to evict the real
    fired/force_restart history the log exists to preserve.

    Three consecutive beats on an unchanged unreachable instance must record ONCE."""
    import recovery_audit as ra

    fleet = [_inst("frozen", "/p/proj-a", {})]          # {} = no pane → no channel
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    _setup(monkeypatch, tmp_path, fleet, fire="1")

    for _ in range(3):
        daemon.task_session_liveness()

    outcomes = [r["outcome"] for r in ra.load_records()]
    assert outcomes == ["unreachable"], f"re-audited every beat: {outcomes}"


def test_wedged_target_is_never_typed_at_again(tmp_path, monkeypatch) -> None:
    """TRDD-8DR0X08A F2: queued-but-unexecuted commands at the target's transcript
    tail prove typed input is NOT executing there — the beat must not inject (the
    queue would only grow), must spend an attempt (so the budget walks to crash_loop
    instead of looping), and must route to the human channel instead."""
    fleet = [_inst("cron_dead", "/p/proj-w", {"tmux_pane": "%5"}, trailing=2)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    pushes: list = []
    monkeypatch.setattr(
        daemon.notify, "push", lambda **kw: pushes.append(kw) or "PUSHED"
    )
    daemon.task_session_liveness()
    assert fired == []                                    # never typed at
    assert "WEDGED" in _log(tmp_path)
    sf = daemon._recovery_state_path(tmp_path / "recovery", "/p/proj-w")
    st = json.loads(sf.read_text(encoding="utf-8"))
    assert st["attempts"] == 1                            # budget consumed, not reset
    assert st["last_audit"] == "declined_wedged:rearm"
    assert pushes and pushes[0]["code"] == "FLEET-WEDGED"
    assert pushes[0]["project"] == "proj-w"


def test_session_awaiting_a_human_answer_is_never_typed_at(tmp_path, monkeypatch) -> None:
    """TRDD-8IZ8COQ8. A session parked on ExitPlanMode / a permission prompt is waiting
    for a PERSON, but it looks exactly like a dead one — no transcript growth, no cron
    fire, so the diagnosis lands on `cron_dead`. Measured in this repo 2026-07-17: the
    guardian typed `/janitor-arm` into the approval dialog after 33 minutes of silence.
    The beat must decline, spend an attempt, and route to the human channel."""
    fleet = [_inst("cron_dead", "/p/proj-a", {"tmux_pane": "%7"}, awaiting=True)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    pushes: list = []
    monkeypatch.setattr(
        daemon.notify, "push", lambda **kw: pushes.append(kw) or "PUSHED"
    )
    # Deterministic "present-ish" idle reading: above the 20s typing gate (so the
    # beat actually runs) but well below the 1800s unattended-ESC threshold, so
    # this test exercises ONLY the pre-existing decline+notify path — never the
    # ESC-dismiss addition (covered separately below).
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: 600.0)
    daemon.task_session_liveness()
    assert fired == []                                    # never typed at
    assert "AWAITING USER" in _log(tmp_path)
    sf = daemon._recovery_state_path(tmp_path / "recovery", "/p/proj-a")
    st = json.loads(sf.read_text(encoding="utf-8"))
    # 2026-08-02 review fix: the awaiting decline must NOT spend attempts — spending
    # budget for an action never tried is what walked action_for to force_restart,
    # which dispatched before the guard ran. last_ts still advances (cooldown pacing).
    assert st["attempts"] == 0                            # budget NOT spent on a decline
    assert st["last_ts"] > 0
    assert st["last_audit"] == "declined_awaiting_user:rearm"
    assert pushes and pushes[0]["code"] == "FLEET-AWAITING-USER"
    assert pushes[0]["project"] == "proj-a"


def test_awaiting_user_outranks_even_the_esc_first_rungs(tmp_path, monkeypatch) -> None:
    """The ONE place this guard must be stricter than the wedged one. A frozen target's
    rungs are ESC-first, and the wedged check exempts them because the ESC is the unwedge
    — but an ESC into a pending approval DISMISSES the human's decision. Declining is the
    lesser harm, so `awaiting_user` blocks hard rungs too."""
    fleet = [_inst("frozen", "/p/proj-af", {"tmux_pane": "%8"}, trailing=3, awaiting=True)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(daemon.notify, "push", lambda **kw: "PUSHED")
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: 600.0)
    daemon.task_session_liveness()
    assert fired == [], "an ESC would dismiss the pending prompt — must not fire"
    assert "AWAITING USER" in _log(tmp_path)


def test_wedged_short_circuit_exempts_esc_first_rungs(tmp_path, monkeypatch) -> None:
    """A FROZEN target's gentle rungs are ESC-first — the ESC itself is the unwedge
    (the same policy _fire_fleet_stop applies) — so trailing enqueues must NOT block
    them; only soft enqueue-style injections are pointless against a stuck turn."""
    fleet = [_inst("frozen", "/p/proj-f", {"tmux_pane": "%6"}, trailing=3)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    daemon.task_session_liveness()
    assert len(fired) == 1                                # still fired: ESC unwedges


def test_awaiting_user_present_never_esc_dismisses(tmp_path, monkeypatch) -> None:
    """Owner directive 2026-08-11 + the 2026-07-17 incident: a human recently at the
    machine must never have their pending prompt touched — only the pre-existing
    decline+notify path runs, exactly as before this feature."""
    proj = tmp_path / "proj-esc-present"
    fleet = [_inst("cron_dead", str(proj), {"tmux_pane": "%9"}, awaiting=True)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(daemon.notify, "push", lambda **kw: "PUSHED")
    # Present-ish: above the 20s typing gate, well below the 1800s unattended bar.
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: 600.0)
    daemon.task_session_liveness()
    assert fired == [], "the human is present — nothing may be typed, not even ESC"
    ledger = proj / ".janitor" / "state" / "findings-ledger.ndjsonl"
    assert not ledger.exists(), "no dismissal happened, so nothing should be recorded"


def test_awaiting_user_unattended_esc_dismisses_and_records(tmp_path, monkeypatch) -> None:
    """Past the unattended threshold, the guard may ESC-dismiss the stale dialog —
    never answer it — and MUST leave a durable, findable record of what happened."""
    proj = tmp_path / "proj-esc-unattended"
    fleet = [_inst("cron_dead", str(proj), {"tmux_pane": "%10"}, awaiting=True)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(daemon.notify, "push", lambda **kw: "PUSHED")
    # Comfortably unattended: above both the 20s typing gate and the 1800s bar.
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: 5000.0)
    daemon.task_session_liveness()
    assert len(fired) == 1, "exactly one ESC plan must fire for the parked dialog"
    plan = fired[0]
    assert plan["command"] == "", "the plan must be ESC-only — never a typed command"
    ledger = proj / ".janitor" / "state" / "findings-ledger.ndjsonl"
    assert ledger.exists(), "the dismissal must be recorded so a human can learn of it"
    entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert any(e["code"] == "FLEET-AWAITING-DISMISS" for e in entries)


# --- TRDD-WKTD5JTC: the retry-wedge ESC rung, exercised through the REAL daemon path ---

def test_retry_wedged_trailing_enqueues_does_not_decline(tmp_path, monkeypatch) -> None:
    """Advisor correction #2's OTHER half: `injection_is_hard(retry_wedged)` must be True,
    else the `trailing_enqueues` wedged-target short-circuit (daemon.py) declines the ESC
    and pages a human instead of injecting — exactly the failure the advisor flagged. A
    retry-wedged pane commonly HAS trailing enqueues (its own earlier typed nudge queued
    behind the frozen turn), so this must still fire the ESC."""
    proj = tmp_path / "proj-rw"
    fleet = [_inst("retry_wedged", str(proj), {"tmux_pane": "%5"}, trailing=2)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    pushes: list = []
    monkeypatch.setattr(daemon.notify, "push", lambda **kw: pushes.append(kw) or "PUSHED")
    daemon.task_session_liveness()
    assert len(fired) == 1, "the ESC must fire despite trailing enqueues"
    assert fired[0]["command"] == "", "retry_wedged is ESC-only, never a typed command"
    assert "WEDGED" not in _log(tmp_path)
    assert pushes == [], "no human paging — the ESC itself is the recovery"


def test_retry_wedged_writes_rate_limited_flag_before_the_esc(tmp_path, monkeypatch) -> None:
    """TRDD-WKTD5JTC §1b (empirically measured): an ESC that breaks the retry wedge fires
    plain `Stop`, not `on-stop-failure` — nothing else writes rate-limited.flag on this
    path. The daemon must write it itself, BEFORE firing, or the wedge breaks and the
    session then just sits idle with no resume cue — strictly worse than the wedge."""
    proj = tmp_path / "proj-flag"
    proj.mkdir()
    fleet = [_inst("retry_wedged", str(proj), {"tmux_pane": "%9"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    flag = proj / ".janitor" / "state" / "rate-limited.flag"
    since = proj / ".janitor" / "state" / "rate-limited-since.ts"
    assert not flag.exists()
    daemon.task_session_liveness()
    assert len(fired) == 1
    assert flag.is_file(), "rate-limited.flag must exist once the ESC has fired"
    assert since.read_text(encoding="utf-8").strip().isdigit()


def test_retry_wedged_dry_run_writes_no_flag(tmp_path, monkeypatch) -> None:
    """A dry run (firing OFF) must not write the flag either — nothing was actually
    injected, so claiming a rate-limit window would be a lie no ESC ever produced."""
    proj = tmp_path / "proj-dry"
    proj.mkdir()
    fleet = [_inst("retry_wedged", str(proj), {"tmux_pane": "%9"})]
    fired = _setup(monkeypatch, tmp_path, fleet, fire="0")
    daemon.task_session_liveness()
    assert fired == []
    flag = proj / ".janitor" / "state" / "rate-limited.flag"
    assert not flag.exists()


def test_retry_wedged_never_escalates_even_at_max_attempts(tmp_path, monkeypatch) -> None:
    """Advisor correction #1, end-to-end: a retry-wedged instance walked all the way to
    a spent attempt budget still gets ESC-only — it must NEVER reach a kill rung the way
    a `frozen` instance's 'ladder' would at the same attempt count."""
    fleet = [_inst("retry_wedged", "/p/proj-max", {"tmux_pane": "%3"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-max")
    ident = f"{fleet[0].pid}:{fleet[0].tty or ''}"
    sf.write_text(
        json.dumps({"attempts": daemon.fr.MAX_ATTEMPTS - 1, "last_ts": 1, "identity": ident}),
        encoding="utf-8",
    )
    daemon.task_session_liveness()
    assert len(fired) == 1
    assert fired[0]["command"] == "", "still ESC-only at a high attempt count — never a kill"


def test_awaiting_user_unknown_idle_never_esc_dismisses(tmp_path, monkeypatch) -> None:
    """`hid_idle_seconds` returning None means "cannot tell" — fail toward NOT
    touching the pane, same as the typing gate above the loop."""
    proj = tmp_path / "proj-esc-unknown"
    fleet = [_inst("cron_dead", str(proj), {"tmux_pane": "%11"}, awaiting=True)]
    fired = _setup(monkeypatch, tmp_path, fleet)
    monkeypatch.setattr(daemon.notify, "push", lambda **kw: "PUSHED")
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: None)
    daemon.task_session_liveness()
    assert fired == [], "an unknown idle reading must never license an ESC"
    ledger = proj / ".janitor" / "state" / "findings-ledger.ndjsonl"
    assert not ledger.exists()
