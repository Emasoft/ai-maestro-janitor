"""(PaneState, event) -> plan policy table + closed-loop executor (TRDD-N954KWUC, Phase 2).

Phase 1 (`pane_state.py`) turns a captured frame into a structured `PaneState`. This module
is the DECIDER + ACTUATOR half: `plan()` is the ONLY place a keystroke is chosen — a pure
function of `(PaneState, Event)` — and `execute()` runs the plan with a closed loop: type a
step, re-read the pane, require the expected next state before the next step, bounded
retries, STOP on a wrong observed state. "Fired" means "the screen changed the way we
expected", never "osascript spawned" (Proposal §3).

Phase 3 (2026-09-03) migrated every `fleet_inject.fire` call site in `daemon.py` /
`fleet_restart.py` onto this table through the `pane_actuate.act()` adapter — that adapter is
now the ONLY place `fleet_inject.fire` is called from, and it always reads a `PaneState`
first.

Rows encoded here are exactly the ones the 2026-09-02 incident dictates (Proposal §2):
- `retry_wedge` + rotation landed -> ESC x (1 + queued), until the wedge is gone.
- `retry_wedge` + no headroom -> ESC x (1 + queued) until the field is empty, then
  `/model opus`, confirm -- the OWNER-RATIFIED sequence `terminal_trigger
  .send_model_switch_true_error` already types by hand-rolled loop; this is its pure,
  testable, call-site-agnostic shape.
- `awaiting_user` -> never type, for ANY event -- a human decision is pending. (Phase 3 added
  ONE exception, `STALE_PROMPT` + a measured `unattended` verdict: an ESC, which can only
  dismiss, never answer.)
- `working` -> no screen-driven sequence, ever. (Phase 3 law 2 below admits the caller-driven
  soft enqueue and the ESC-only nudge, and refuses hard-plus-command.)
- `idle` + cron dead -> `/janitor-arm`.
- `None`/`unknown` -> never type -- an unreadable or unclassifiable pane is not a green light.

Phase 2 left `PLUGIN_STAGED`/`STOP_FLAG`/`STALE_PROMPT` unencoded because the command to type
(`/janitor-disarm` vs. `/janitor-pause`) and the idle duration that authorizes an ESC into a
human's dialog are EXTERNAL state neither `PaneState` nor `Event` carries. Phase 3 supplies
exactly that, as the promised payload -- keyword-only arguments to `plan()`, never a guess:

- `command` -- the literal the caller already resolved (`fleet_inject.action_to_command`, the
  fleet-stop flag's command, the relaunch line). `None` means an ESC-ONLY rung.
- `esc_first` -- the caller's own hard/soft law (`fleet_recovery.injection_is_hard`). It stays
  a property of the CALLER's plan, not of a separate ESC step, so the adapter fires the very
  `build_command_plan(..., esc_first=True)` the site built before: one atomic osascript, and
  the ai-maestro channel's ESC-less fall-through preserved.
- `unattended` -- the machine-wide HID-idle verdict the caller measured, the ONLY thing that
  authorizes a `STALE_PROMPT` ESC into an `awaiting_user` pane.

Two laws Phase 3 had to state explicitly, because migrating the real call sites made them
load-bearing rather than theoretical:

1. **A channel with NO READ-BACK BY CONSTRUCTION (`blind_ok`) gets AT MOST the one-shot
   actuation it got before this TRDD -- never a sequence, never a verified `Expect`. A
   READABLE channel whose read merely FAILED this beat gets NOTHING.** The distinction is the
   whole law, and conflating the two is a bug in both directions. Three shipping channels
   have no pane read-back at all (the ai-maestro CLI, wtype, xdotool -- see
   `fleet_inject._readback_identity` and `fleet_scan.capture_pane_text`'s own dispatch), so a
   flat "no read, no keystroke" rule would silently make every ai-maestro agent and every
   Linux GUI terminal unrecoverable -- the exact severity inversion `build_command_plan`'s
   docstring records, where the gentle fix was skipped precisely where the violent one landed.
   But a tmux/iTerm pane that simply did not answer this beat is a pane we CAN see and
   currently cannot; typing `/janitor-arm` into it is the 2026-09-02 incident on another path,
   and `fleet_scan.capture_pane_text` returns None there on purpose (a TCC-denied iTerm
   channel declines the read so that no injection fires). So `plan()` refuses `state is None`
   unless the CALLER asserts `blind_ok` -- and only `pane_actuate.act`, which knows the
   channel identity, may assert it. A blind step then carries `Expect.ANY`: we cannot verify
   what we cannot read, and pretending otherwise would be worse than admitting it.
2. **A pane showing `working` still accepts the CALLER-DRIVEN rungs.** A soft enqueue buffers
   to the turn boundary and destroys no in-flight work (TRDD-0GPQROC1, owner directive
   2026-07-10 for the machine-wide stop), and an ESC-only `esc_nudge` is authorized by a
   15-minute-stale transcript the SCREEN cannot see. What `working` still refuses is every
   screen-driven sequence -- the rotation flush, the no-headroom model switch, the cron
   re-arm, the stale-prompt ESC -- because those read the screen for their authority and the
   screen says a turn is live.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

from pane_state import InputFieldKind, PaneState, StatusKind

if TYPE_CHECKING:
    from collections.abc import Sequence


class Event(Enum):
    ROTATION_LANDED = "rotation_landed"
    NO_HEADROOM = "no_headroom"
    CRON_DEAD = "cron_dead"
    PLUGIN_STAGED = "plugin_staged"
    STOP_FLAG = "stop_flag"
    STALE_PROMPT = "stale_prompt"
    # Phase 3 -- one per migrated `fleet_inject.fire` call site. Each carries its payload as
    # keyword arguments to `plan()` (see the module docstring); none of them decides a
    # keystroke on its own.
    RECOVERY_RUNG = "recovery_rung"  # daemon session-liveness ladder (rearm/reload/esc_nudge)
    RESUME_WAKE = "resume_wake"  # daemon rate-limit resume wake (/janitor-resume)
    RELAUNCH = "relaunch"  # fleet_restart rungs 5-6: type the relaunch line into a dead pane
    OWN_COMMAND_UNSUBMITTED = "own_command_unsubmitted"  # Enter alone: finish OUR own send


class Expect(Enum):
    """The post-state a `Step` requires before the next one may fire."""

    ANY = "any"  # NOT VERIFIABLE -- an intermediate queue-flush ESC (verified only at the
    # tail of its own sequence), or a one-shot into a pane with no read-back channel.
    # `execute()` spends NO capture on these: there is no post-state to require.
    WEDGE_GONE = "wedge_gone"
    FIELD_EMPTY = "field_empty"
    MENU_SHOWN = "menu_shown"
    IDLE_OR_WORKING = "idle_or_working"


@dataclass(frozen=True)
class Step:
    keys: str  # "ESC", "Enter", or a literal command to type + submit (e.g. "/model opus")
    expect: Expect
    label: str
    presence_deferrable: bool  # may this step wait out a machine-wide HID-busy gate?
    # How many times this keystroke may be RE-SENT while `expect` is still unmet, each send
    # followed by its own re-read. 1 = send once (the default, and every non-flush step).
    # This is the shape `terminal_trigger.send_model_switch_true_error` ratified for a queue
    # flush: press, LOOK, press again only if it is still needed. A pre-counted burst of ESCs
    # is the wrong shape — over-pressing past an empty prompt is what opens Claude Code's
    # rewind menu, and the next Enter in the sequence would then select in it
    # (`build_esc_only_steps`' own warning).
    repeat_max: int = 1
    # Does the command step carry its own leading ESC (the caller's hard/soft law)? Never set
    # on a step that FOLLOWS a flush: an ESC into an already-clear field interrupts the fresh
    # turn the command is about to start.
    esc_first: bool = False


def satisfied(expect: Expect, state: PaneState | None) -> bool:
    """Does `state` already meet `expect`? An unreadable pane (`None`) satisfies nothing --
    the closed loop must never call an unobservable pane a success."""
    if state is None:
        return False
    if expect is Expect.ANY:
        return True
    if expect is Expect.WEDGE_GONE:
        return state.status.kind != StatusKind.RETRY_WEDGE
    if expect is Expect.FIELD_EMPTY:
        return state.input_field.kind == InputFieldKind.EMPTY
    if expect is Expect.MENU_SHOWN:
        return state.status.kind == StatusKind.AWAITING_USER and state.status.awaiting_kind == "model-confirm"
    if expect is Expect.IDLE_OR_WORKING:
        return state.status.kind in (StatusKind.IDLE, StatusKind.WORKING)
    return False  # pragma: no cover -- Expect is a closed enum; no other member exists


# The cap on a queue flush, mirroring `terminal_trigger._QUEUE_FLUSH_MAX_ESC`: a queue deeper
# than this is REPORTED, never guessed at. Kept as its own constant rather than imported so
# this module stays free of the I/O-carrying `terminal_trigger`; the two are the same law and
# the same number by intent.
_QUEUE_FLUSH_MAX_ESC = 5


def _flush_wedge(state: PaneState, *, final_expect: Expect, final_label: str) -> tuple[Step, ...]:
    """ONE ESC step with a press BUDGET of 1 + queued (capped at `_QUEUE_FLUSH_MAX_ESC`) --
    one press for the retry line itself plus one per queued command (owner 2026-09-02 21:04),
    but re-read between presses and STOPPED the moment the pane satisfies `final_expect`.

    It is deliberately NOT a pre-counted burst of independent ESC steps. `queued_count`
    counts `❯` rows in a window that can legitimately include a past prompt echo
    (`pane_state._parse_input_field`), so a burst can over-press by one -- and an over-press
    onto an ALREADY-EMPTY prompt is exactly what opens Claude Code's rewind menu, which the
    no-headroom row's confirming Enter would then select in
    (`terminal_trigger.build_esc_only_steps`' warning, and the ratified
    `send_model_switch_true_error` loop). Press, LOOK, press again only if still wedged.

    Never presence-deferrable: the input line is already blocked to the human, so there is no
    typing to step on.
    """
    queued = state.input_field.queued_count if state.input_field.kind == InputFieldKind.QUEUED else 0
    return (
        Step(
            keys="ESC",
            expect=final_expect,
            label=final_label,
            presence_deferrable=False,
            repeat_max=min(1 + queued, _QUEUE_FLUSH_MAX_ESC),
        ),
    )


# The CALLER-DRIVEN events: the caller resolved the command and the hard/soft law from state
# this pure table cannot see (a recovery diagnosis, which stop flag is held, a rate-limit
# flag). The table still decides WHETHER and IN WHAT ORDER those keystrokes may land.
_CALLER_DRIVEN = (Event.RECOVERY_RUNG, Event.STOP_FLAG, Event.RESUME_WAKE)


def _rung(
    state: PaneState | None, *, command: str | None, esc_first: bool, label: str
) -> tuple[Step, ...]:
    """A caller-driven rung's steps: its own hard/soft law, plus the command it carries.

    At a pane already showing the retry wedge the ESC count is the WEDGE's own law
    (1 + queued, `_flush_wedge`), so the flush is emitted as explicit steps; anywhere else
    `esc_first` rides on the caller's own plan (the adapter fires it unchanged) and no
    separate ESC step exists. A SOFT command into a wedge is refused outright: it can only
    join the queue behind the retry line, and every queued command later costs the human one
    more ESC (TRDD-NACCL0CB, the incident this whole TRDD comes from).
    """
    if state is not None and state.status.kind == StatusKind.RETRY_WEDGE:
        if not esc_first:
            return ()
        flush = _flush_wedge(
            state,
            final_expect=Expect.FIELD_EMPTY if command else Expect.WEDGE_GONE,
            final_label=f"{label} unwedge",
        )
        if not command:
            return flush
        # The flush already fired this rung's ESCs, and it is NOT presence-deferrable — so
        # the command that completes it must not be either, or a presence gate could leave
        # the sequence half-applied (ESCed but never re-armed). `esc_first=False` is
        # load-bearing: the flush just PROVED the field empty, and an ESC into a clear field
        # interrupts the fresh turn this command is about to start.
        return flush + (
            Step(keys=command, expect=Expect.IDLE_OR_WORKING, label=label, presence_deferrable=False, esc_first=False),
        )
    if not command:
        # An ESC-ONLY rung (`esc_nudge`, TRDD-P7WU40G9): ESC and type nothing. Without
        # `esc_first` there is no keystroke left to send at all.
        if not esc_first:
            return ()
        return (Step(keys="ESC", expect=Expect.ANY, label=f"{label} ESC", presence_deferrable=False),)
    return (
        Step(keys=command, expect=Expect.IDLE_OR_WORKING, label=label, presence_deferrable=True, esc_first=esc_first),
    )


def _submit(state: PaneState) -> tuple[Step, ...]:
    """Enter ALONE, to finish a send of OURS still sitting unsubmitted in the field. An
    EMPTY field means it drained between the caller's read-back and now — nothing to submit,
    which is exactly the check a blind `fire()` could not make. `Expect.ANY` because both
    post-states are correct and indistinguishable here: an idle pane runs the command (field
    empties) while a working one buffers it (the field shows the queued indicator)."""
    if state.input_field.kind == InputFieldKind.EMPTY:
        return ()
    return (
        Step(keys="Enter", expect=Expect.ANY, label="submit our own queued command", presence_deferrable=False),
    )


def _unverified(steps: tuple[Step, ...]) -> tuple[Step, ...]:
    """The same steps with every `Expect` downgraded to `ANY` — for a pane we could not read
    at all. We must not claim to have verified a screen we never saw."""
    return tuple(
        Step(
            keys=s.keys,
            expect=Expect.ANY,
            label=s.label,
            presence_deferrable=s.presence_deferrable,
            repeat_max=1,  # a press budget needs a re-read to spend; blind gets ONE shot
            esc_first=s.esc_first,
        )
        for s in steps
    )


def _blind(event: Event, *, command: str | None, esc_first: bool, unattended: bool) -> tuple[Step, ...]:
    """The NO-READ-BACK-CHANNEL row (law 1 in the module docstring): at most ONE unverified
    keystroke, and only for the events whose pre-TRDD call site fired blind anyway.
    `ROTATION_LANDED` / `NO_HEADROOM` / `CRON_DEAD` are absent on purpose — their sites
    already SKIPPED an unreadable pane, and their sequences need a queue count to be correct.
    `OWN_COMMAND_UNSUBMITTED` is absent because its caller cannot even reach it without a
    readable channel (`fleet_inject.field_holds_our_queued_command`)."""
    if event is Event.STALE_PROMPT and unattended:
        return (Step(keys="ESC", expect=Expect.ANY, label="stale-prompt ESC dismiss", presence_deferrable=False),)
    if event in _CALLER_DRIVEN:
        return _unverified(_rung(None, command=command, esc_first=esc_first, label=event.value))
    if event is Event.RELAUNCH and command:
        return (Step(keys=command, expect=Expect.ANY, label="relaunch", presence_deferrable=False),)
    return ()


def _at_wedge(state: PaneState, event: Event, *, command: str | None, esc_first: bool) -> tuple[Step, ...]:
    if event is Event.ROTATION_LANDED:
        # `rotation unwedge` is a CONTRACT, not a label: TRDD-UA4FAX67's `unblock-when`
        # predicate greps `.janitor/logs/pane-policy.log` for `rotation unwedge: ok`.
        # Renaming it silently breaks that card's wait condition.
        return _flush_wedge(state, final_expect=Expect.WEDGE_GONE, final_label="rotation unwedge")
    if event is Event.NO_HEADROOM:
        flush = _flush_wedge(state, final_expect=Expect.FIELD_EMPTY, final_label="queue-flush for model switch")
        return flush + (
            Step(keys="/model opus", expect=Expect.MENU_SHOWN, label="switch model", presence_deferrable=True),
            Step(keys="Enter", expect=Expect.IDLE_OR_WORKING, label="confirm model switch", presence_deferrable=True),
        )
    if event in _CALLER_DRIVEN:
        return _rung(state, command=command, esc_first=esc_first, label=event.value)
    return ()  # RELAUNCH / STALE_PROMPT / PLUGIN_STAGED: a wedge is a LIVE claude, hands off


def _at_idle(state: PaneState, event: Event, *, command: str | None, esc_first: bool, unattended: bool) -> tuple[Step, ...]:
    if event is Event.CRON_DEAD:
        return (Step(keys="/janitor-arm", expect=Expect.IDLE_OR_WORKING, label="re-arm cron", presence_deferrable=True),)
    if event is Event.STALE_PROMPT and unattended:
        # The caller's `awaiting_user` evidence is the TRANSCRIPT (an unanswered tool_use);
        # the screen may still read idle. ESC anyway — it can only DISMISS, never answer —
        # but with nothing to verify: an ESC at an already-idle pane changes no pixel.
        return (Step(keys="ESC", expect=Expect.ANY, label="stale-prompt ESC dismiss", presence_deferrable=False),)
    if event is Event.OWN_COMMAND_UNSUBMITTED:
        return _submit(state)
    if event in _CALLER_DRIVEN:
        return _rung(state, command=command, esc_first=esc_first, label=event.value)
    return ()


def _at_working(state: PaneState, event: Event, *, command: str | None, esc_first: bool) -> tuple[Step, ...]:
    """Law 2 in the module docstring: only the caller-driven rungs (and finishing our own
    send) may land at a live turn — never a screen-driven sequence.

    HARD-plus-command is refused here even though it is caller-driven: an ESC followed by a
    typed command over a live turn is neither of the two things law 2 defends. A soft enqueue
    buffers to the turn boundary and destroys nothing; an ESC-ONLY nudge is authorized by a
    15-minute-stale transcript the screen cannot show. "Interrupt this turn AND type at it"
    is a stale proxy overriding a screen that says work is happening — the exact shape this
    TRDD exists to kill. The rung falls back to its next beat, when the screen agrees.
    """
    if event is Event.OWN_COMMAND_UNSUBMITTED:
        return _submit(state)
    if event in _CALLER_DRIVEN and not (esc_first and command):
        return _rung(state, command=command, esc_first=esc_first, label=event.value)
    return ()


def plan(
    state: PaneState | None,
    event: Event,
    *,
    command: str | None = None,
    esc_first: bool = False,
    unattended: bool = False,
    blind_ok: bool = False,
) -> tuple[Step, ...]:
    """The ONLY place a keystroke is decided. PURE -- does no I/O, never blocks.

    The keyword payload is state the caller MEASURED and this table cannot see; it never
    substitutes for reading the screen, it only supplies what the screen does not show.

    `blind_ok` asserts that this pane's channel has NO read-back BY CONSTRUCTION, so a
    missing `PaneState` means "reading is impossible here", not "the read failed this beat".
    Only `pane_actuate.act` knows the channel identity, so only it may assert it — DEFAULT
    FALSE, and an absent state without it types nothing at all (law 1).
    """
    if state is None:
        return _blind(event, command=command, esc_first=esc_first, unattended=unattended) if blind_ok else ()
    kind = state.status.kind
    if kind == StatusKind.AWAITING_USER:
        if event is Event.STALE_PROMPT and unattended:
            # The ONE keystroke allowed over a pending human decision, and it is ESC: it can
            # DISMISS the dialog, never approve or select anything, so it cannot make the
            # wrong choice on the human's behalf (the 2026-07-17 incident). `unattended` is
            # the caller's measured machine-wide HID idle — without it, hands off.
            return (
                Step(keys="ESC", expect=Expect.IDLE_OR_WORKING, label="stale-prompt ESC dismiss", presence_deferrable=False),
            )
        return ()  # a human decision is pending -- never type over it, for any other event
    if kind == StatusKind.WORKING:
        return _at_working(state, event, command=command, esc_first=esc_first)
    if kind == StatusKind.RETRY_WEDGE:
        return _at_wedge(state, event, command=command, esc_first=esc_first)
    if kind == StatusKind.IDLE:
        return _at_idle(state, event, command=command, esc_first=esc_first, unattended=unattended)
    if kind == StatusKind.UNKNOWN and event is Event.RELAUNCH and command:
        # A pane whose claude pid is GONE shows a shell prompt: no Claude chrome, so UNKNOWN
        # is the EXPECTED classification here, not a failure to parse. Every other status
        # proves a live claude is on screen — and typing a relaunch line into a live session
        # would land `claude --continue` in its input field.
        return (Step(keys=command, expect=Expect.ANY, label="relaunch", presence_deferrable=False),)
    return ()  # unknown status, or a row this table does not (yet) cover -- never guess


class OutcomeStatus(Enum):
    DONE = "done"
    FAILED = "failed"
    DEFERRED = "deferred"
    NOOP = "noop"


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    steps_done: int
    observed: tuple[str, ...]
    # Did we actually TOUCH the pane — did at least one keystroke reach it?
    #
    # `status` cannot answer that, and the difference is load-bearing: FAILED means the pane
    # never reached the expected state, which happens BOTH when we pressed a live pane that
    # stayed wedged (we spent our attempt) AND when every press went into a channel that could
    # not be built or was refused (we spent nothing). Callers that keep "we already actuated
    # this pane" bookkeeping — a once-per-rotation dedupe, a recovery-attempt counter — MUST
    # key on this, never on `status`: charging an untouched pane suppresses its next attempt,
    # and on the recovery ladder it walks toward the hard, killing rungs for free.
    #
    # Named for what it MEANS rather than for the outcome: "the sequence took effect" is
    # `status`, this is only "we typed and it was accepted". A multi-step plan whose first
    # step lands and whose second does not is still a touched pane — re-running the whole
    # sequence later would re-press an already-flushed queue, which is the over-pressing
    # hazard, not a missed actuation.
    #
    # Each layer states only what it knows: `execute()` sets it from whether it called
    # `type_keys` (its callback returns nothing, so that is the whole truth available to it),
    # and `act()` DOWNGRADES it with the acceptance values `fleet_inject.fire` returned.
    touched: bool = False


def execute(
    steps: Sequence[Step],
    *,
    read: Callable[[], PaneState | None],
    type_keys: Callable[[Step], None],
    log: Callable[[str], None],
    presence_blocked: Callable[[], bool],
    retries: int = 3,
) -> Outcome:
    """Run `steps` with the closed loop Proposal §3 requires: type, re-read, require the
    expected state before the next step, bounded retries, STOP on the first step that never
    converges. `presence_blocked` gates only `presence_deferrable` steps -- an ESC into
    `retry_wedge` is never deferred, since the input line is already blocked to the human.

    ponytail: no settle delay between re-reads here -- the injected `read` owns timing (a
    real caller sleeps for the terminal to repaint before capturing; tests read instantly).
    Add a `settle_s` parameter only if a Phase-3 caller cannot express it in `read`."""
    if not steps:
        return Outcome(status=OutcomeStatus.NOOP, steps_done=0, observed=())
    observed: list[str] = []
    # Whether `type_keys` was ever called. A DONE that claimed `touched=False` would describe an
    # impossible world (every step converged and we never typed), so this layer reports what it
    # knows and lets `act` — the only holder of the acceptance values — downgrade it.
    typed = False
    for i, step in enumerate(steps):
        if step.presence_deferrable and presence_blocked():
            log(f"{step.label}: deferred (observed presence-blocked)")
            return Outcome(status=OutcomeStatus.DEFERRED, steps_done=i, observed=tuple(observed), touched=typed)
        if step.expect is Expect.ANY:
            # Nothing to require, so spend no capture proving a tautology (Proposal §5, the
            # capture budget). This is also what lets a pane with NO read-back channel work
            # at all: `satisfied()` refuses an unreadable pane by design, so a blind step
            # that still read would burn `retries` captures and then report a false failure.
            # A press BUDGET is meaningless without a re-read to spend it against, so an ANY
            # step is always sent exactly once regardless of `repeat_max`.
            type_keys(step)
            typed = True
            observed.append("unverified")
            log(f"{step.label}: ok (observed unverified)")
            continue
        # Press, LOOK, press again only while the budget lasts and the pane still disagrees.
        # `retries` is the patience for ONE press to take effect; `repeat_max` is how many
        # presses this step may spend. A plain step (repeat_max=1) therefore behaves exactly
        # as before: one keystroke, up to `retries` re-reads.
        ok = False
        presses = 0
        for _ in range(max(retries, step.repeat_max)):
            if presses < step.repeat_max:
                type_keys(step)
                typed = True
                presses += 1
            state = read()
            observed.append(state.status.kind.value if state is not None else "unreadable")
            if satisfied(step.expect, state):
                ok = True
                break
        log(f"{step.label}: {'ok' if ok else 'failed'} (observed {observed[-1]})")
        if not ok:
            return Outcome(status=OutcomeStatus.FAILED, steps_done=i, observed=tuple(observed), touched=typed)
    return Outcome(status=OutcomeStatus.DONE, steps_done=len(steps), observed=tuple(observed), touched=typed)
