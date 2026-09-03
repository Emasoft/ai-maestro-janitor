"""Tests for the (PaneState, event) -> plan policy table + closed-loop executor
(TRDD-N954KWUC, Phase 2).

Real captured/anonymized frames from `tests/fixtures/pane_frames/` drive every case --
`pane_state.parse` is never mocked, only `plan()`'s downstream `execute()` seams
(`read`/`type_keys`/`log`/`presence_blocked`) are, since those are genuinely I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pane_policy as pp  # type: ignore[import-not-found]  # noqa: E402
import pane_state as ps  # type: ignore[import-not-found]  # noqa: E402
import pytest  # noqa: E402

_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"


def _state(name: str) -> ps.PaneState:
    return ps.parse((_FIXTURES / name).read_text())


# ---------------------------------------------------------------------------------------
# plan() -- exact keystroke sequence per row
# ---------------------------------------------------------------------------------------


def test_retry_wedge_single_queued_item_rotation_landed_gets_a_two_press_budget() -> None:
    """A wedge with one queued command + rotation landing -> ONE ESC step with a press
    BUDGET of 1 + queued, each press followed by a re-read and stopped the moment the wedge
    clears. It is deliberately NOT two independent blind ESC steps: `queued_count` can
    over-count a past prompt echo by one, and an over-press onto an already-clear prompt is
    what opens Claude Code's rewind menu."""
    state = _state("real-wedged-fable-limit.txt")
    assert state.input_field.queued_count == 1
    steps = pp.plan(state, pp.Event.ROTATION_LANDED)
    assert [s.keys for s in steps] == ["ESC"]
    assert steps[0].expect is pp.Expect.WEDGE_GONE
    assert steps[0].repeat_max == 2  # 1 + queued
    assert steps[0].presence_deferrable is False


def test_retry_wedge_no_queue_rotation_landed_gets_a_single_press_budget() -> None:
    """No queued command -> a budget of exactly 1 (the red error line alone)."""
    state = _state("real-wedged-session-limit.txt")
    assert state.input_field.queued_count == 0
    steps = pp.plan(state, pp.Event.ROTATION_LANDED)
    assert [s.keys for s in steps] == ["ESC"]
    assert steps[0].expect is pp.Expect.WEDGE_GONE
    assert steps[0].repeat_max == 1
    assert steps[0].presence_deferrable is False


def test_queue_flush_press_budget_is_capped() -> None:
    """A queue deeper than `_QUEUE_FLUSH_MAX_ESC` is REPORTED, never guessed at — the same
    cap `terminal_trigger.send_model_switch_true_error` ratified."""
    state = _state("real-wedged-fable-limit.txt")
    deep = ps.PaneState(
        input_field=ps.InputField(kind=ps.InputFieldKind.QUEUED, queued_count=40),
        status=state.status,
        agents_running=state.agents_running,
        model=state.model,
        context_pct=state.context_pct,
        bypass_on=state.bypass_on,
    )
    assert pp.plan(deep, pp.Event.ROTATION_LANDED)[0].repeat_max == pp._QUEUE_FLUSH_MAX_ESC


def test_retry_wedge_no_headroom_flushes_then_switches_model_and_confirms() -> None:
    """No-headroom fallback: ESC flush to an EMPTY field, then `/model opus`, then Enter to
    confirm the ask-user menu -- the owner-ratified sequence, purely encoded."""
    state = _state("real-wedged-rate-limit-429.txt")
    steps = pp.plan(state, pp.Event.NO_HEADROOM)
    assert [s.keys for s in steps] == ["ESC", "/model opus", "Enter"]
    assert steps[0].expect is pp.Expect.FIELD_EMPTY
    assert steps[1].expect is pp.Expect.MENU_SHOWN
    assert steps[2].expect is pp.Expect.IDLE_OR_WORKING
    assert steps[0].presence_deferrable is False  # ESC into retry_wedge -- never deferred
    assert steps[1].presence_deferrable is True  # typing a command -- may defer to presence
    assert steps[2].presence_deferrable is True


@pytest.mark.parametrize(
    "event",
    [
        pp.Event.ROTATION_LANDED,
        pp.Event.NO_HEADROOM,
        pp.Event.CRON_DEAD,
        pp.Event.PLUGIN_STAGED,
        pp.Event.STOP_FLAG,
        pp.Event.STALE_PROMPT,
    ],
)
def test_awaiting_user_never_types_for_any_event(event: pp.Event) -> None:
    """A pending human decision blocks EVERY event -- never type over it."""
    state = _state("synthetic-awaiting-model-confirm.txt")
    assert state.status.kind is ps.StatusKind.AWAITING_USER
    assert pp.plan(state, event) == ()


@pytest.mark.parametrize(
    "event",
    [
        pp.Event.ROTATION_LANDED,
        pp.Event.NO_HEADROOM,
        pp.Event.CRON_DEAD,
        pp.Event.PLUGIN_STAGED,
        pp.Event.STOP_FLAG,
        pp.Event.STALE_PROMPT,
    ],
)
def test_working_never_types_for_any_event(event: pp.Event) -> None:
    """A live turn is running -- nothing to inject, for any event."""
    state = _state("synthetic-working-spinner.txt")
    assert state.status.kind is ps.StatusKind.WORKING
    assert pp.plan(state, event) == ()


def test_working_refuses_an_esc_only_rung_because_esc_cancels_the_live_turn() -> None:
    """The owner-reported continuity break (2026-09-03): `esc_nudge` reaches `plan()` as a
    caller-driven RECOVERY_RUNG carrying `command=None`, and the old law admitted it at a
    WORKING pane on the strength of a stale transcript. A session inside one long tool call
    writes no transcript for the whole call, so that proxy goes stale exactly when the screen
    is right — and ESC alone cancels the turn."""
    state = _state("synthetic-working-spinner.txt")
    assert state.status.kind is ps.StatusKind.WORKING
    assert pp.plan(state, pp.Event.RECOVERY_RUNG, command=None) == ()
    assert pp.plan(state, pp.Event.RECOVERY_RUNG, command=None, esc_first=True) == ()


def test_working_still_accepts_a_soft_enqueue_that_types_a_command() -> None:
    """The half of law 2 that must survive: a soft enqueue buffers to the turn boundary and
    destroys nothing, so the cron re-arm and the machine-wide stop still land at a live turn.
    Refusing these too would make the fix above a regression, not a fix."""
    state = _state("synthetic-working-spinner.txt")
    for event in (pp.Event.RECOVERY_RUNG, pp.Event.STOP_FLAG, pp.Event.RESUME_WAKE):
        steps = pp.plan(state, event, command="/janitor-arm")
        assert [s.keys for s in steps] == ["/janitor-arm"], f"{event} must still enqueue"


def test_working_refuses_hard_plus_command_unchanged() -> None:
    """Unchanged by the ESC-only fix, and pinned so a later edit cannot quietly re-admit it."""
    state = _state("synthetic-working-spinner.txt")
    assert pp.plan(state, pp.Event.RECOVERY_RUNG, command="/janitor-arm", esc_first=True) == ()


def test_a_rate_limited_pane_is_never_classified_working_so_the_fix_strands_nothing() -> None:
    """Why refusing the ESC-only rung at WORKING costs the `frozen` recovery nothing: the panes
    that recovery exists for do not present as WORKING. Read from the real captured frames, so
    a parser change that broke this would fail here rather than silently strand the ladder."""
    for name in ("real-wedged-fable-limit.txt", "real-wedged-rate-limit-429.txt",
                 "real-wedged-session-limit.txt", "synthetic-api-error.txt",
                 "synthetic-session-limit-terminal.txt"):
        assert _state(name).status.kind is not ps.StatusKind.WORKING, name


def test_idle_cron_dead_re_arms() -> None:
    state = _state("synthetic-idle-empty-field.txt")
    steps = pp.plan(state, pp.Event.CRON_DEAD)
    assert [s.keys for s in steps] == ["/janitor-arm"]
    assert steps[0].expect is pp.Expect.IDLE_OR_WORKING
    assert steps[0].presence_deferrable is True


def test_idle_non_cron_dead_events_do_nothing() -> None:
    state = _state("synthetic-idle-empty-field.txt")
    for event in (pp.Event.ROTATION_LANDED, pp.Event.NO_HEADROOM, pp.Event.PLUGIN_STAGED, pp.Event.STOP_FLAG):
        assert pp.plan(state, event) == ()


def test_none_state_never_types_without_the_no_readback_assertion() -> None:
    """Law 1: an absent `PaneState` types NOTHING unless the caller asserts the channel has no
    read-back BY CONSTRUCTION. A readable tmux/iTerm pane that merely failed to answer this
    beat must never be typed into — that is the 2026-09-02 incident on another path."""
    for event in pp.Event:
        assert pp.plan(None, event) == ()
        assert pp.plan(None, event, command="/janitor-arm", esc_first=True, unattended=True) == ()


def test_no_readback_channel_gets_exactly_one_unverified_shot() -> None:
    """With `blind_ok` the write-only channels (ai-maestro CLI, wtype, xdotool) still get the
    ONE keystroke they got before this TRDD — and never a sequence, never a verified expect."""
    steps = pp.plan(None, pp.Event.RECOVERY_RUNG, command="/janitor-arm", blind_ok=True)
    assert [s.keys for s in steps] == ["/janitor-arm"]
    assert steps[0].expect is pp.Expect.ANY
    assert steps[0].repeat_max == 1
    # A queue flush needs a queued-command COUNT, which no frame supplied — so it is refused
    # outright rather than guessed one ESC too few.
    assert pp.plan(None, pp.Event.ROTATION_LANDED, blind_ok=True) == ()
    assert pp.plan(None, pp.Event.OWN_COMMAND_UNSUBMITTED, blind_ok=True) == ()


def test_unknown_status_never_types() -> None:
    state = _state("synthetic-garbage-random-text.txt")
    assert state.status.kind is ps.StatusKind.UNKNOWN
    for event in pp.Event:
        assert pp.plan(state, event) == ()


def test_plugin_staged_and_stop_flag_are_not_yet_encoded_by_this_pure_table() -> None:
    """These need external context (which flag, which plugin) that neither PaneState nor
    Event carries -- guessing would reproduce the proxy-decides-blind bug. Documented no-op,
    not a silent gap: covered by the module docstring."""
    idle = _state("synthetic-idle-empty-field.txt")
    assert pp.plan(idle, pp.Event.PLUGIN_STAGED) == ()
    assert pp.plan(idle, pp.Event.STOP_FLAG) == ()


# ---------------------------------------------------------------------------------------
# satisfied()
# ---------------------------------------------------------------------------------------


def test_satisfied_is_false_for_unreadable_pane() -> None:
    for expect in pp.Expect:
        assert pp.satisfied(expect, None) is False


def test_satisfied_any_is_always_true() -> None:
    assert pp.satisfied(pp.Expect.ANY, _state("synthetic-idle-empty-field.txt")) is True
    assert pp.satisfied(pp.Expect.ANY, None) is False  # None still fails first -- no exception


def test_satisfied_wedge_gone_true_once_status_leaves_retry_wedge() -> None:
    wedged = _state("real-wedged-session-limit.txt")
    idle = _state("synthetic-idle-empty-field.txt")
    assert pp.satisfied(pp.Expect.WEDGE_GONE, wedged) is False
    assert pp.satisfied(pp.Expect.WEDGE_GONE, idle) is True


def test_satisfied_field_empty() -> None:
    empty = _state("synthetic-idle-empty-field.txt")
    queued = _state("synthetic-compacting-with-queued.txt")
    assert pp.satisfied(pp.Expect.FIELD_EMPTY, empty) is True
    assert pp.satisfied(pp.Expect.FIELD_EMPTY, queued) is False


def test_satisfied_menu_shown_only_on_model_confirm() -> None:
    menu = _state("synthetic-awaiting-model-confirm.txt")
    ask_user = _state("synthetic-awaiting-ask-user-menu.txt")
    assert pp.satisfied(pp.Expect.MENU_SHOWN, menu) is True
    assert pp.satisfied(pp.Expect.MENU_SHOWN, ask_user) is False


def test_satisfied_idle_or_working() -> None:
    idle = _state("synthetic-idle-empty-field.txt")
    working = _state("synthetic-working-spinner.txt")
    wedged = _state("real-wedged-session-limit.txt")
    assert pp.satisfied(pp.Expect.IDLE_OR_WORKING, idle) is True
    assert pp.satisfied(pp.Expect.IDLE_OR_WORKING, working) is True
    assert pp.satisfied(pp.Expect.IDLE_OR_WORKING, wedged) is False


# ---------------------------------------------------------------------------------------
# execute() -- the closed loop
# ---------------------------------------------------------------------------------------


def _recorder() -> tuple[list[str], Callable[[str], None]]:
    lines: list[str] = []
    return lines, lines.append


def test_execute_noop_on_empty_plan() -> None:
    outcome = pp.execute(
        (), read=lambda: None, type_keys=lambda k: None, log=lambda m: None, presence_blocked=lambda: False
    )
    assert outcome.status is pp.OutcomeStatus.NOOP
    assert outcome.steps_done == 0


def test_execute_runs_the_whole_multi_step_sequence_when_state_converges() -> None:
    """Each step's re-read reports the converged state immediately -- one read per step,
    all satisfied, DONE with every step recorded."""
    idle = _state("synthetic-idle-empty-field.txt")
    typed: list[str] = []
    logs, log = _recorder()
    outcome = pp.execute(
        (pp.Step(keys="/janitor-arm", expect=pp.Expect.IDLE_OR_WORKING, label="re-arm", presence_deferrable=True),),
        read=lambda: idle,
        type_keys=lambda step: typed.append(step.keys),
        log=log,
        presence_blocked=lambda: False,
    )
    assert outcome.status is pp.OutcomeStatus.DONE
    assert outcome.steps_done == 1
    assert typed == ["/janitor-arm"]
    assert logs and "ok" in logs[0]


def test_execute_stops_the_sequence_on_a_wrong_post_state() -> None:
    """A fake reader that keeps returning the UNCHANGED wedged frame -- the step never
    converges, so execute() STOPS after exhausting its retries rather than running on."""
    wedged = _state("real-wedged-session-limit.txt")
    typed: list[str] = []
    outcome = pp.execute(
        pp.plan(wedged, pp.Event.ROTATION_LANDED),  # single ESC, expect=WEDGE_GONE
        read=lambda: wedged,  # never changes -- the wedge never clears
        type_keys=lambda step: typed.append(step.keys),
        log=lambda m: None,
        presence_blocked=lambda: False,
        retries=2,
    )
    assert outcome.status is pp.OutcomeStatus.FAILED
    assert outcome.steps_done == 0  # the one step never satisfied
    assert typed == ["ESC"]  # the keystroke WAS attempted, verification just never passed
    assert len(outcome.observed) == 2  # both retries recorded


def test_execute_spends_the_whole_press_budget_when_the_pane_never_converges() -> None:
    """A 2-press flush budget (queued=1) against a reader that never clears the wedge: each
    press is followed by its own re-read, the budget is spent, and the step FAILS rather than
    the sequence running on."""
    wedged = _state("real-wedged-fable-limit.txt")
    typed: list[str] = []
    outcome = pp.execute(
        pp.plan(wedged, pp.Event.ROTATION_LANDED),
        read=lambda: wedged,
        type_keys=lambda step: typed.append(step.keys),
        log=lambda m: None,
        presence_blocked=lambda: False,
        retries=1,
    )
    assert outcome.status is pp.OutcomeStatus.FAILED
    assert outcome.steps_done == 0
    assert typed == ["ESC", "ESC"]  # both presses of the budget were spent


def test_execute_stops_pressing_the_moment_the_pane_converges() -> None:
    """The budget is a CEILING, not a count: the wedge clears after the first press, so the
    second is never sent — the over-press that would open the rewind menu."""
    wedged = _state("real-wedged-fable-limit.txt")
    idle = _state("synthetic-idle-empty-field.txt")
    typed: list[str] = []
    outcome = pp.execute(
        pp.plan(wedged, pp.Event.ROTATION_LANDED),
        read=lambda: idle,
        type_keys=lambda step: typed.append(step.keys),
        log=lambda m: None,
        presence_blocked=lambda: False,
    )
    assert outcome.status is pp.OutcomeStatus.DONE
    assert typed == ["ESC"]


def test_execute_presence_deferral_blocks_a_deferrable_step() -> None:
    idle = _state("synthetic-idle-empty-field.txt")
    typed: list[str] = []
    outcome = pp.execute(
        pp.plan(idle, pp.Event.CRON_DEAD),  # /janitor-arm, presence_deferrable=True
        read=lambda: idle,
        type_keys=lambda step: typed.append(step.keys),
        log=lambda m: None,
        presence_blocked=lambda: True,
    )
    assert outcome.status is pp.OutcomeStatus.DEFERRED
    assert outcome.steps_done == 0
    assert typed == []  # never typed -- deferred before the keystroke


def test_execute_presence_deferral_never_blocks_a_non_deferrable_esc() -> None:
    """An ESC into `retry_wedge` is never deferred, even when presence_blocked() is True --
    the input line is already blocked to the human, so there is nothing to step on."""
    wedged = _state("real-wedged-session-limit.txt")
    idle = _state("synthetic-idle-empty-field.txt")
    typed: list[str] = []
    outcome = pp.execute(
        pp.plan(wedged, pp.Event.ROTATION_LANDED),
        read=lambda: idle,  # converges immediately once ESCed
        type_keys=lambda step: typed.append(step.keys),
        log=lambda m: None,
        presence_blocked=lambda: True,  # would defer a deferrable step -- must not matter here
    )
    assert outcome.status is pp.OutcomeStatus.DONE
    assert typed == ["ESC"]


def test_execute_unreadable_pane_never_satisfies_and_fails() -> None:
    outcome = pp.execute(
        (pp.Step(keys="ESC", expect=pp.Expect.WEDGE_GONE, label="x", presence_deferrable=False),),
        read=lambda: None,
        type_keys=lambda k: None,
        log=lambda m: None,
        presence_blocked=lambda: False,
        retries=1,
    )
    assert outcome.status is pp.OutcomeStatus.FAILED
    assert outcome.observed == ("unreadable",)
