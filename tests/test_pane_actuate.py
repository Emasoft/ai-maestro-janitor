"""Tests for the Phase-3 actuator adapter (TRDD-N954KWUC): one test per migrated
`fleet_inject.fire` call site, feeding a REAL fixture frame plus that site's event and
asserting the exact keystroke sequence handed to the `fleet_inject` seam — plus, per site,
that a wrong post-state stops the sequence.

`pane_state.parse` is NEVER mocked: the frames come from `tests/fixtures/pane_frames/` and
travel through the real `fleet_scan.capture_pane_text` -> `pane_state.read` -> `parse` chain,
with only the capture PRIMITIVE (genuine I/O — an osascript/tmux read of a live pane) and
`fleet_inject.fire` (which would type into the developer's real terminals) replaced.

`build_step_plan` is spied on, not stubbed: the real `fleet_inject` builders still run, so the
plan each keystroke would actually fire is asserted alongside the keystroke itself.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_inject  # type: ignore[import-not-found]  # noqa: E402
import fleet_scan  # type: ignore[import-not-found]  # noqa: E402
import pane_actuate as pa  # type: ignore[import-not-found]  # noqa: E402
import pane_state as ps  # type: ignore[import-not-found]  # noqa: E402

_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"
_TMUX = {"tmux_pane": "%5"}
# A channel with NO read-back BY CONSTRUCTION — the only case law 1 lets act blind.
_WRITE_ONLY = {"linux_gui_channel": "wtype"}


def _frames(monkeypatch, *names: str | None) -> None:
    """Feed REAL fixture frames (or None = unreadable pane) to the capture primitive, in
    order; the last one repeats for every further read. Everything downstream — `read`,
    `parse`, the whole classification — is the production code."""
    seq: list[str | None] = [None if n is None else (_FIXTURES / n).read_text(encoding="utf-8") for n in names]
    remaining = list(seq)

    def _capture(_terminal):
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    monkeypatch.setattr(fleet_scan, "capture_pane_text", _capture)


def _seam(monkeypatch, *, accepted: bool = True) -> list[tuple[str, dict | None]]:
    """Record `(keystroke, plan)` for every step the adapter actuates. The REAL
    `build_step_plan` still runs, so the recorded plan is the one that would have been fired."""
    fired: list[tuple[str, dict | None]] = []
    real = pa.build_step_plan

    def _spy(terminal, step, *, submit_ref, fallback):
        built = real(terminal, step, submit_ref=submit_ref, fallback=fallback)
        fired.append((step.keys, built))
        return built

    monkeypatch.setattr(pa, "build_step_plan", _spy)
    monkeypatch.setattr(fleet_inject, "fire", lambda plan: accepted and plan is not None)
    return fired


def _act(event, **kw):
    """`act` with the test-only knobs pinned: no settle sleep, no presence gate."""
    kw.setdefault("terminal", _TMUX)
    terminal = kw.pop("terminal")
    return pa.act(terminal, event, settle_s=0.0, presence_blocked=lambda: False, **kw)


def _keys(fired) -> list[str]:
    return [k for k, _ in fired]


# ---------------------------------------------------------------------------------------
# Site: daemon._rotation_esc_pass  (Event.ROTATION_LANDED)
# ---------------------------------------------------------------------------------------


def test_rotation_landed_presses_once_and_stops_when_the_wedge_clears(monkeypatch) -> None:
    """A wedge with one queued command carries a 2-press budget, but the budget is a CEILING:
    the re-read after the first press shows the wedge gone, so the second press — the one that
    would land on an already-clear prompt and open the rewind menu — is never sent."""
    _frames(monkeypatch, "real-wedged-fable-limit.txt", "synthetic-idle-empty-field.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.ROTATION_LANDED)
    assert _keys(fired) == ["ESC"]
    assert fired[0][1]["channel"] == "tmux"
    assert fired[0][1]["command"] == ""  # ESC-only: never a typed command
    assert outcome.status is pa.OutcomeStatus.DONE


def test_rotation_landed_spends_the_budget_then_stops_when_the_wedge_never_clears(monkeypatch) -> None:
    """The wrong post-state stops the sequence: the re-read still shows the wedge after every
    press the budget allows, so the outcome is FAILED, not a silent success."""
    _frames(monkeypatch, "real-wedged-fable-limit.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.ROTATION_LANDED, retries=2)
    assert _keys(fired) == ["ESC", "ESC"]  # 1 + queued, and no more
    assert outcome.status is pa.OutcomeStatus.FAILED
    assert outcome.steps_done == 0


# ---------------------------------------------------------------------------------------
# Site: daemon.task_session_liveness recovery rung  (Event.RECOVERY_RUNG)
# ---------------------------------------------------------------------------------------


def test_recovery_rung_soft_command_fires_the_plan_the_site_would_have_built(monkeypatch) -> None:
    """A soft rung at an idle pane types its one command, and the plan fired equals the
    site's OWN pre-built plan — the rebuild is byte-identical because `build_command_plan` is
    pure and the step carries the caller's `esc_first`."""
    _frames(monkeypatch, "synthetic-idle-empty-field.txt", "synthetic-working-spinner.txt")
    fired = _seam(monkeypatch)
    site_plan = fleet_inject.build_command_plan(_TMUX, "/janitor-arm", esc_first=False)
    outcome = _act(
        pa.Event.RECOVERY_RUNG, command="/janitor-arm", esc_first=False, command_plan=site_plan
    )
    assert _keys(fired) == ["/janitor-arm"]
    assert fired[0][1] == site_plan
    assert outcome.status is pa.OutcomeStatus.DONE


def test_a_hard_rung_keeps_its_leading_esc_but_a_flushed_one_drops_it(monkeypatch) -> None:
    """`esc_first` rides on the command step ONLY when no flush preceded it. After a flush has
    PROVEN the field empty, re-sending the caller's `esc_first=True` plan would land more ESCs
    on a clear prompt — the over-press that opens the rewind menu."""
    hard = pa.plan(
        ps.parse((_FIXTURES / "synthetic-idle-empty-field.txt").read_text(encoding="utf-8")),
        pa.Event.RECOVERY_RUNG,
        command="/janitor-arm",
        esc_first=True,
    )
    assert [s.esc_first for s in hard] == [True]
    wedged = pa.plan(
        ps.parse((_FIXTURES / "real-wedged-fable-limit.txt").read_text(encoding="utf-8")),
        pa.Event.RECOVERY_RUNG,
        command="/janitor-arm",
        esc_first=True,
    )
    assert [s.keys for s in wedged] == ["ESC", "/janitor-arm"]
    assert wedged[1].esc_first is False


def test_recovery_rung_soft_command_refuses_a_wedged_pane(monkeypatch) -> None:
    """TRDD-NACCL0CB, the incident: a soft command typed at the retry line only joins the
    queue behind it, and every queued command later costs the human one more ESC."""
    _frames(monkeypatch, "real-wedged-session-limit.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.RECOVERY_RUNG, command="/janitor-arm", esc_first=False)
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP


def test_recovery_rung_esc_only_at_a_wedge_uses_the_wedge_esc_law(monkeypatch) -> None:
    """`esc_nudge` carries no command (TRDD-P7WU40G9). At a wedge it becomes the same
    1 + queued flush budget, gated on the wedge clearing — and stops as soon as it does."""
    _frames(monkeypatch, "real-wedged-fable-limit.txt", "real-calm-working.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.RECOVERY_RUNG, command=None, esc_first=True)
    assert _keys(fired) == ["ESC"]
    assert outcome.status is pa.OutcomeStatus.DONE


def test_recovery_rung_stops_when_the_pane_lands_on_a_human_decision(monkeypatch) -> None:
    """Wrong post-state: the command was typed but the pane came back showing a permission
    dialog, so `IDLE_OR_WORKING` never holds and the rung reports FAILED."""
    _frames(monkeypatch, "synthetic-idle-empty-field.txt", "synthetic-awaiting-permission.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.RECOVERY_RUNG, command="/janitor-arm", esc_first=False, retries=2)
    assert _keys(fired) == ["/janitor-arm"]
    assert outcome.status is pa.OutcomeStatus.FAILED


# ---------------------------------------------------------------------------------------
# Site: daemon._resume_wake_pass  (Event.RESUME_WAKE)
# ---------------------------------------------------------------------------------------


def test_resume_wake_types_the_slash_command_at_an_idle_pane(monkeypatch) -> None:
    _frames(monkeypatch, "synthetic-idle-empty-field.txt", "synthetic-working-spinner.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.RESUME_WAKE, command="/janitor-resume")
    assert _keys(fired) == ["/janitor-resume"]
    assert fired[0][1]["command"] == "/janitor-resume"
    assert outcome.status is pa.OutcomeStatus.DONE


def test_resume_wake_never_types_over_a_pending_human_decision(monkeypatch) -> None:
    """The 2026-07-17 failure shape: a rate-limited session that is ALSO holding an approval
    dialog must not be typed into. No steps, so the caller stamps no coverage and dispatch
    keeps the cron as the trigger."""
    _frames(monkeypatch, "synthetic-awaiting-permission.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.RESUME_WAKE, command="/janitor-resume")
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP


# ---------------------------------------------------------------------------------------
# Site: daemon._fire_fleet_stop  (Event.STOP_FLAG)
# ---------------------------------------------------------------------------------------


def test_stop_flag_hard_flushes_the_wedge_before_typing_the_stop_command(monkeypatch) -> None:
    """A frozen stop target: the ESC IS the unwedge, and the table turns the site's single
    `esc_first` plan into the wedge's own flush, requiring an EMPTY field before the stop
    command is typed at all — and the command that follows carries NO further ESC."""
    _frames(
        monkeypatch,
        "real-wedged-fable-limit.txt",
        "synthetic-idle-empty-field.txt",
        "synthetic-working-spinner.txt",
    )
    fired = _seam(monkeypatch)
    outcome = _act(
        pa.Event.STOP_FLAG,
        command="/janitor-disarm",
        esc_first=True,
        command_plan=fleet_inject.build_command_plan(_TMUX, "/janitor-disarm", esc_first=True),
    )
    assert _keys(fired) == ["ESC", "/janitor-disarm"]
    # The command plan fired is the ESC-FREE one, not the caller's esc_first=True plan.
    assert fired[1][1] == fleet_inject.build_command_plan(_TMUX, "/janitor-disarm", esc_first=False)
    assert outcome.status is pa.OutcomeStatus.DONE


def test_stop_flag_hard_plus_command_is_refused_at_a_live_turn(monkeypatch) -> None:
    """Law 2's boundary: "interrupt this turn AND type at it" is a stale diagnosis overriding
    a screen that says work is happening. The soft enqueue and the ESC-only nudge stay; this
    does not."""
    _frames(monkeypatch, "synthetic-working-spinner.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.STOP_FLAG, command="/janitor-disarm", esc_first=True)
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP


def test_stop_flag_soft_still_lands_at_a_working_pane(monkeypatch) -> None:
    """Owner directive 2026-07-10: a machine-wide stop is a SOFT enqueue that lands at the
    session's turn boundary, so a live turn must not block it (TRDD-0GPQROC1)."""
    _frames(monkeypatch, "synthetic-working-spinner.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.STOP_FLAG, command="/janitor-pause", esc_first=False)
    assert _keys(fired) == ["/janitor-pause"]
    assert outcome.status is pa.OutcomeStatus.DONE


def test_stop_flag_reports_failed_when_the_sender_rejects_the_plan(monkeypatch) -> None:
    """"Fired" must mean delivered, never "we called a function" (TRDD-3VW434Q8): a sender
    that refuses the plan turns a converged sequence back into FAILED."""
    _frames(monkeypatch, "synthetic-working-spinner.txt")
    _seam(monkeypatch, accepted=False)
    outcome = _act(pa.Event.STOP_FLAG, command="/janitor-pause", esc_first=False)
    assert outcome.status is pa.OutcomeStatus.FAILED


# ---------------------------------------------------------------------------------------
# Site: daemon.task_session_liveness awaiting-user ESC  (Event.STALE_PROMPT)
# ---------------------------------------------------------------------------------------


def test_stale_prompt_escs_an_unattended_dialog_and_never_answers_it(monkeypatch) -> None:
    """ESC ALONE — it can DISMISS a dialog, never approve or select, so it cannot make the
    wrong choice on the human's behalf. Verified by requiring the dialog to be gone."""
    _frames(monkeypatch, "synthetic-awaiting-model-confirm.txt", "synthetic-idle-empty-field.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.STALE_PROMPT, unattended=True)
    assert _keys(fired) == ["ESC"]
    assert fired[0][1]["command"] == ""
    assert outcome.status is pa.OutcomeStatus.DONE


def test_stale_prompt_without_the_unattended_verdict_types_nothing(monkeypatch) -> None:
    """`unattended` is the caller's measured machine-wide HID idle. Without it, a human may
    be about to answer this very prompt — hands off (the 2026-07-17 lesson)."""
    _frames(monkeypatch, "synthetic-awaiting-model-confirm.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.STALE_PROMPT, unattended=False)
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP


def test_stale_prompt_stops_when_the_dialog_survives_the_esc(monkeypatch) -> None:
    _frames(monkeypatch, "synthetic-awaiting-model-confirm.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.STALE_PROMPT, unattended=True, retries=2)
    assert _keys(fired) == ["ESC"]
    assert outcome.status is pa.OutcomeStatus.FAILED


# ---------------------------------------------------------------------------------------
# Site: daemon field-busy submit  (Event.OWN_COMMAND_UNSUBMITTED)
# ---------------------------------------------------------------------------------------


def test_own_command_unsubmitted_presses_enter_alone(monkeypatch) -> None:
    """Enter ALONE: the command is already in the field and is already ours, so this types no
    new text and cannot concatenate onto a line someone is editing."""
    state = ps.parse((_FIXTURES / "synthetic-idle-text-typed-bypass-off.txt").read_text(encoding="utf-8"))
    assert state.input_field.kind is ps.InputFieldKind.TEXT
    _frames(monkeypatch, "synthetic-idle-text-typed-bypass-off.txt")
    fired = _seam(monkeypatch)
    ref = fleet_inject.build_command_plan(_TMUX, "/janitor-arm", esc_first=False)
    outcome = _act(pa.Event.OWN_COMMAND_UNSUBMITTED, state=state, submit_ref=ref)
    assert _keys(fired) == ["Enter"]
    assert fired[0][1]["command"] == ""  # Enter alone — no text is retyped
    assert outcome.status is pa.OutcomeStatus.DONE


def test_own_command_unsubmitted_refuses_an_already_empty_field(monkeypatch) -> None:
    """The field drained between the caller's read-back and now — the check a blind
    `fire()` could not make."""
    _frames(monkeypatch, "synthetic-idle-empty-field.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.OWN_COMMAND_UNSUBMITTED)
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP


# ---------------------------------------------------------------------------------------
# Site: fleet_restart.fire_restart relaunch / force_restart  (Event.RELAUNCH)
# ---------------------------------------------------------------------------------------


def test_relaunch_types_into_a_pane_with_no_claude_chrome(monkeypatch) -> None:
    """A pane whose claude pid is gone shows a shell prompt: UNKNOWN is the EXPECTED
    classification for a relaunch target, not a parse failure."""
    _frames(monkeypatch, "synthetic-garbage-random-text.txt")
    fired = _seam(monkeypatch)
    site_plan = fleet_inject.build_command_plan(_TMUX, "claude --continue", esc_first=False)
    outcome = _act(pa.Event.RELAUNCH, command="claude --continue", command_plan=site_plan)
    assert _keys(fired) == ["claude --continue"]
    assert fired[0][1] == site_plan
    assert outcome.status is pa.OutcomeStatus.DONE


def test_relaunch_refuses_a_pane_that_still_shows_a_live_claude(monkeypatch) -> None:
    """The check this rung never had: the pid died and the session was already restarted, so
    typing the relaunch line would land `claude --continue` in a live input field."""
    _frames(monkeypatch, "synthetic-idle-empty-field.txt")
    fired = _seam(monkeypatch)
    outcome = _act(pa.Event.RELAUNCH, command="claude --continue")
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP


# ---------------------------------------------------------------------------------------
# The unreadable pane (module law 1) + the capture budget
# ---------------------------------------------------------------------------------------


def test_a_channel_with_no_readback_fires_exactly_one_unverified_shot(monkeypatch) -> None:
    """Three shipping channels have NO pane read-back (ai-maestro CLI, wtype, xdotool). A
    flat no-read-no-keystroke law would make those instances permanently unrecoverable, so
    they still get the ONE keystroke they got before this TRDD — and no more."""
    _frames(monkeypatch, None)
    fired = _seam(monkeypatch)
    assert pa.channel_has_readback(_WRITE_ONLY) is False
    outcome = _act(pa.Event.RECOVERY_RUNG, terminal=_WRITE_ONLY, command="/janitor-arm")
    assert _keys(fired) == ["/janitor-arm"]
    assert outcome.status is pa.OutcomeStatus.DONE
    assert outcome.observed == ("unverified",)  # never claimed as verified


def test_a_readable_channel_that_did_not_answer_types_nothing(monkeypatch) -> None:
    """The other half of law 1, and the reason it is not just "unreadable ⇒ fire blind": a
    tmux/iTerm pane we can normally see and currently cannot may be holding a retry wedge or a
    human's dialog. `capture_pane_text` also returns None there ON PURPOSE when the iTerm
    channel is TCC-denied, precisely so that no injection fires."""
    _frames(monkeypatch, None)
    fired = _seam(monkeypatch)
    logged: list[str] = []
    assert pa.channel_has_readback(_TMUX) is True
    outcome = pa.act(
        _TMUX, pa.Event.RECOVERY_RUNG, command="/janitor-arm",
        settle_s=0.0, presence_blocked=lambda: False, log=logged.append,
    )
    assert fired == []
    assert outcome.status is pa.OutcomeStatus.NOOP
    assert logged == ["pane-policy: recovery_rung skipped — readable channel could not be read"]


def test_a_blind_channel_never_grows_a_multi_step_sequence(monkeypatch) -> None:
    """A queue-flush needs a queued-command COUNT. With no frame there is no count, so the
    blind row refuses the whole rotation sequence rather than guessing one ESC too few."""
    _frames(monkeypatch, None)
    fired = _seam(monkeypatch)
    assert _act(pa.Event.ROTATION_LANDED, terminal=_WRITE_ONLY).status is pa.OutcomeStatus.NOOP
    assert fired == []


def test_the_closed_loop_spends_exactly_one_capture_when_it_converges(monkeypatch) -> None:
    """Proposal §5, the capture budget: the caller's own pre-read is passed in (`state=`), so
    the whole rotation flush costs ONE additional capture — the single re-read that proves the
    wedge gone. Routing a keystroke through the table does not double the osascript cost."""
    reads: list[int] = []
    wedged = (_FIXTURES / "real-wedged-fable-limit.txt").read_text(encoding="utf-8")
    cleared = (_FIXTURES / "synthetic-idle-empty-field.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(
        fleet_scan, "capture_pane_text", lambda _t: (reads.append(1), cleared)[1]
    )
    _seam(monkeypatch)
    pre = ps.parse(wedged)  # the caller's OWN read, handed in — costs this loop nothing
    outcome = _act(pa.Event.ROTATION_LANDED, state=pre)
    assert outcome.status is pa.OutcomeStatus.DONE
    assert len(reads) == 1


# ---------------------------------------------------------------------------------------
# The per-project ledger (TRDD-UA4FAX67 keys its `unblock-when` predicate on this file)
# ---------------------------------------------------------------------------------------

_LEDGER_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}\] pane-policy: (?P<event>\S+) (?P<rest>.+)$"
)


def test_every_step_appends_one_line_under_the_panes_own_project_root(monkeypatch, tmp_path) -> None:
    """One line per executed step, at `<project_root>/.janitor/logs/pane-policy.log`.

    The path is joined onto the PANE'S PROJECT ROOT, never onto `state.log_dir()`: the daemon
    runs with `JANITOR_LOG_DIR` pointing at global state, so a `log_dir()`-relative ledger
    could never satisfy TRDD-UA4FAX67's `log:.janitor/logs/pane-policy.log` predicate. This
    test pins that by setting `JANITOR_LOG_DIR` somewhere else entirely.

    `rotation unwedge: ok` is a CONTRACT — that predicate greps this exact text — so the final
    ROTATION_LANDED label must never be renamed.
    """
    elsewhere = tmp_path / "global-state-logs"
    elsewhere.mkdir()
    monkeypatch.setenv("JANITOR_LOG_DIR", str(elsewhere))
    project = tmp_path / "proj"
    project.mkdir()
    _frames(monkeypatch, "real-wedged-fable-limit.txt", "synthetic-idle-empty-field.txt")
    _seam(monkeypatch)
    outcome = _act(pa.Event.ROTATION_LANDED, project_dir=str(project))
    assert outcome.status is pa.OutcomeStatus.DONE

    ledger = project / ".janitor" / "logs" / "pane-policy.log"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # one per executed step
    parsed = _LEDGER_RE.match(lines[0])
    assert parsed is not None
    assert parsed.group("event") == "rotation_landed"
    assert parsed.group("rest") == "rotation unwedge: ok (observed idle)"
    assert list(elsewhere.rglob("pane-policy.log")) == []  # never under JANITOR_LOG_DIR


def test_no_project_dir_writes_no_ledger(monkeypatch, tmp_path) -> None:
    """A pane the fleet scan could not root has nowhere to write. A ledger is evidence, not a
    gate, so its absence must never stop the recovery."""
    monkeypatch.chdir(tmp_path)
    _frames(monkeypatch, "real-wedged-fable-limit.txt", "synthetic-idle-empty-field.txt")
    _seam(monkeypatch)
    outcome = _act(pa.Event.ROTATION_LANDED, project_dir=None)
    assert outcome.status is pa.OutcomeStatus.DONE
    assert list(tmp_path.rglob("pane-policy.log")) == []
