"""The ONE actuator: read the pane, ask the policy table, type, verify (TRDD-N954KWUC, P3).

Phase 1 gave the janitor a screen READER (`pane_state`), Phase 2 a pure DECIDER
(`pane_policy`). This module is the adapter that joins them to the real keystroke sender and
replaces every scattered `fleet_inject.fire(...)` call the daemon used to make:

    read (PaneState) -> plan (the policy table) -> execute (type, re-read, require, retry)

`fleet_inject.fire` is called from HERE AND NOWHERE ELSE (acceptance box 2 of the TRDD):
`grep -n "fleet_inject.fire" scripts/daemon.py scripts/lib/fleet_restart.py
scripts/lib/fleet_scan.py` now returns nothing. That is the whole point — an actuator that
does not first read the screen is exactly the shape of every mis-typed keystroke the owner
reported ("the janitor script seems blind and does not check what is in the terminal before
giving the commands", 2026-09-02).

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it never changes HOW `fleet_inject` types. A
step's `keys` is mapped back to the exact builder the call site used before —
`build_esc_plan` for `"ESC"`, `build_submit_plan` for `"Enter"`, and for a command the
caller's OWN already-built plan when it has one (`command_plan`). Only the DECISION moved.

ONE EXCEPTION, and it is not byte-for-byte: on the wedge path `_rung` deliberately sets
`esc_first=False` on the command that follows a queue flush (the flush already proved the
field empty, so an ESC there would interrupt the fresh turn). `build_command_plan` BRANCHES on
that flag — `if session and cli and not esc_first` picks the `aimaestro` channel — so a
terminal carrying BOTH an aimaestro identity and a tmux pane now sends the ESC on tmux and the
command on aimaestro, where before P3 one plan carried both on tmux. Whether that split is
desirable is a real question (the server channel is synchronous and has a meaningful exit
code, which the keystroke channels do not); what is NOT acceptable is claiming fidelity this
path does not have. Reachability is narrow — the instance must be non-`server_owned` and still
have `aimaestro_session`/`aimaestro_cli` populated.

"Fired" means the screen changed the way we expected AND the sender accepted the plan
(Proposal §3). A step whose `Expect` is verifiable is re-read until it converges; a step that
is not verifiable (an intermediate flush ESC, or any keystroke into a pane with no read-back
channel) is reported as `unverified`, never as proof.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import fleet_inject
import pane_state
import user_intent
from pane_policy import Event, Expect, Outcome, OutcomeStatus, Step, execute, plan

if TYPE_CHECKING:
    from pane_state import PaneState

__all__ = [
    "Event", "Expect", "NOT_TYPABLE", "NO_READBACK", "Outcome", "OutcomeStatus", "RESUMED", "Step", "act",
    "build_step_plan",
    "presence_blocked_now", "resume_after_esc",
]

# How long to wait for the terminal to REPAINT before re-reading it. Must exceed the plans'
# own `delay_s` (fleet_inject builds them with 2.0 s): the osascript/tmux child sleeps that
# long before sending, so a shorter settle would re-read the PRE-keystroke frame and report a
# false "did not converge". Only verifiable steps pay it — `Expect.ANY` steps never re-read.
_SETTLE_S = 3.0

# The pane's OWN project ledger. Written next to that project's other janitor logs so a
# session can see what was typed INTO IT without reading the machine-wide daemon log (which
# is per-project-invisible, and which `janitor-per-project-channeling` forbids leaking).
# TRDD-UA4FAX67's `unblock-when` predicate greps this file for `rotation unwedge: ok`.
_LEDGER_REL = Path(".janitor") / "logs" / "pane-policy.log"


def presence_blocked_now() -> bool:
    """Machine-wide HID presence gate (Proposal §4). True while the human is at the keyboard.

    A None reading (cannot tell) is NOT blocking — the same fail-open direction every other
    presence check in this codebase takes; the individual steps that must never be deferred
    (an ESC into a wedge, whose input line is already blocked to the human) carry
    `presence_deferrable=False` and never consult this at all.
    """
    hid = user_intent.hid_idle_seconds()
    return hid is not None and hid <= user_intent.USER_PRESENT_IDLE_S


def channel_has_readback(terminal: dict) -> bool:
    """True iff this pane can be read back AT ALL — i.e. a `None` from `pane_state.read`
    means "the read FAILED this beat", not "reading is impossible here".

    Mirrors `fleet_scan.capture_pane_text`'s own dispatch, which is the primitive
    `pane_state.read` calls: it reads a tmux pane or an iTerm session and NOTHING else. The
    ai-maestro CLI, wtype and xdotool are write-only channels (`fleet_inject._readback_identity`
    returns None for all three), and they are the ONLY case where an absent `PaneState` may
    still authorize a keystroke. A tmux/iTerm pane that did not answer is a pane we can
    normally see and currently cannot — and `capture_pane_text` returns None there on purpose
    when the iTerm channel is TCC-denied, precisely so that no injection fires.
    """
    return bool(terminal.get("tmux_pane", "").strip() or terminal.get("iterm_session_id", "").strip())


def build_step_plan(terminal: dict, step: Step, *, submit_ref: dict | None, fallback: dict | None) -> dict | None:
    """Map one `Step` back to the `fleet_inject` plan its call site would have built.

    A command step is REBUILT from `(step.keys, step.esc_first)` rather than reusing the
    caller's plan object. `build_command_plan` is pure and deterministic, so for a step that
    kept the caller's `esc_first` the rebuild is byte-identical — and for a step that
    FOLLOWS a queue flush it is the only correct thing: the caller's plan bakes in
    `esc_first=True`, and firing it after the flush proved the field empty would land two more
    ESCs on a clear prompt, opening the rewind menu the next Enter could select in.

    `fallback` is used only when the rebuild is impossible because the caller kept no terminal
    identity at all (`fleet_restart.fire_restart(terminal=None)`); there the step is always the
    blind one-shot carrying the caller's own law, so its plan is the right one to fire.
    """
    if step.keys == "ESC":
        return fleet_inject.build_esc_plan(terminal)
    if step.keys == "Enter":
        # Enter ALONE — never re-types the command, so it cannot concatenate onto a line
        # someone is editing. Needs a reference plan only to resolve the same channel.
        ref = submit_ref if submit_ref is not None else fallback
        return fleet_inject.build_submit_plan(terminal, ref) if ref is not None else None
    built = fleet_inject.build_command_plan(terminal, step.keys, esc_first=step.esc_first)
    if built is None and fallback is not None and fallback.get("command") == step.keys:
        return fallback
    return built


def _append_ledger(project_dir: str | None, message: str) -> None:
    """Append ONE line to the PANE's own project ledger. Silently skips when the pane has no
    known project dir (an instance the fleet scan could not root) — a ledger is evidence, not
    a gate, so a missing one must never stop a recovery. A write fault is swallowed for the
    same reason: an unwritable log must not crash the daemon beat."""
    if not project_dir:
        return
    path = Path(project_dir) / _LEDGER_REL
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")
    except OSError:
        pass  # a ledger fault must never break the beat


def act(
    terminal: dict,
    event: Event,
    *,
    state: PaneState | None = None,
    read_pane: bool = True,
    fail_open: bool = False,
    command: str | None = None,
    esc_first: bool = False,
    unattended: bool = False,
    command_plan: dict | None = None,
    submit_ref: dict | None = None,
    project_dir: str | None = None,
    log: Callable[[str], None] | None = None,
    presence_blocked: Callable[[], bool] | None = None,
    settle_s: float = _SETTLE_S,
    retries: int = 3,
) -> Outcome:
    """Read `terminal`'s pane, ask the policy table what `event` authorizes there, and run it.

    `state` lets a caller hand in a `PaneState` it ALREADY read this beat — the capture
    budget (Proposal §5) is one osascript per pane per beat, and every migrated site that
    reads the pane for its own guard passes that same read in here rather than taking a
    second one. `read_pane=False` skips the read entirely (the caller knows the pane is
    unreadable, e.g. a relaunch target with no terminal identity at all).

    `command_plan` is the caller's own already-built plan. It is the FALLBACK for a command
    step whose plan cannot be rebuilt (no terminal identity at all), NOT the normal path — see
    `build_step_plan` for why reusing a caller's `esc_first=True` plan after a queue flush is
    a hazard rather than a fidelity win.

    Returns the `Outcome`; `DONE` means every step converged AND every plan was accepted by
    `fleet_inject.fire`. A step that fired into a channel that could not be built (a `None`
    plan) can never be DONE, even on an unverifiable step — otherwise "fired" would again
    mean "we called a function", the exact honesty bug TRDD-3VW434Q8 fixed inside `fire`.
    """
    if state is None and read_pane:
        state = pane_state.read(terminal)

    def _log(message: str) -> None:
        line = f"pane-policy: {event.value} {message}"
        if log is not None:
            log(line)
        _append_ledger(project_dir, line)

    # Law 1: a blind one-shot is authorized ONLY by a channel with no read-back BY
    # CONSTRUCTION. A readable pane that did not answer this beat gets nothing — typing into
    # a pane we normally see and currently cannot is the 2026-09-02 incident on another path.
    #
    # `fail_open` is the ONE sanctioned exception, and it exists because Law 1 has a direction:
    # it makes an unreadable pane get NOTHING, which is the safe answer for a keystroke that
    # STARTS work and the dangerous one for a keystroke that STOPS it. The kill switch and
    # `/janitor-disarm` must reach every session even on the beat their panes cannot be read —
    # a stop that silently does not arrive is exactly the failure the switch exists to prevent,
    # and it fails machine-wide the moment pane capture does. Callers on a stop path opt in;
    # nothing else may, because for them Law 1's default is the correct one.
    blind_ok = not (read_pane and channel_has_readback(terminal))
    if state is None and not blind_ok and fail_open:
        _log("readable channel could not be read — firing blind anyway (stop path, fail-open)")
        blind_ok = True
    if state is None and not blind_ok:
        _log("skipped — readable channel could not be read")
        return Outcome(status=OutcomeStatus.NOOP, steps_done=0, observed=("unreadable",))

    # TRDD-ECHOKVZC: the TARGET session's own hooks publish a pane -> transcript mapping
    # (`user_intent.record_pane_transcript`); consult it before typing INTO that pane. Without
    # this, `act` has no transcript of its own and can never call `recently_interrupted`, so
    # the wedge-recovery ESC bypassed the 300s user-interrupt cooldown every other injector
    # honours (two sessions sharing a cooldown is exactly the bug class the pane-keyed mapping
    # avoids -- see `recently_interrupted`'s docstring on why there is no project-wide guess).
    # Exempt ONLY `Event.STOP_FLAG` -- the kill-switch/`/janitor-disarm` path, which must reach
    # the pane even inside a cooldown (a stop that silently does not arrive is the failure that
    # path exists to prevent). Keyed on the EVENT, not on `fail_open`: `fail_open` only means
    # "type blind into an unreadable pane" (Law 1, above) -- a future non-stop call site that
    # sets it for an unrelated reason must not silently inherit this cooldown exemption too.
    # A missing mapping fails OPEN (types anyway) -- a caller with no known target transcript
    # has nothing to defer for.
    #
    # Ceilings, deliberately accepted (TRDD-ECHOKVZC review):
    #   1. A session's mapping exists only from its FIRST prompt onward (SessionStart carries
    #      no `transcript_path`) -- a wedge in the very first turn is ungated.
    #   2. The mapping persists until the pane id is reused. Two sub-cases (review finding):
    #      (a) the old transcript file is GONE -- `pane_transcript_path`/`recently_interrupted`
    #      fail OPEN on the missing file, costing one stat/read, never a stuck cooldown.
    #      (b) the pane was handed to a NEW session before that session's own first-prompt hook
    #      overwrote the mapping (still pointing at the OLD session's real, still-on-disk
    #      transcript) -- an interrupt the OLD session logged there can wrongly defer a
    #      keystroke meant for the NEW one. This is a real gap, deliberately left open: the
    #      failure direction is an EXTRA deferral, never an extra injection (the same
    #      fail-toward-safe direction as every other gate in this module), and closing it needs
    #      a session identity in the mapping -- new stamp semantics the TRDD's own "Design
    #      (chosen)" section rules out.
    #   3. The Stop-hook write (`on-stop-token-meter.py`) is belt-and-braces; the
    #      UserPromptSubmit write (`on-prompt-submit-user-mem.py`) is the load-bearing one --
    #      it is the hook that fires BEFORE the very turn whose ESC this gate defers.
    if event is not Event.STOP_FLAG and project_dir:
        tp = user_intent.pane_transcript_path(project_dir, terminal)
        if tp is not None:
            # MUST pass `state_dir` explicitly: `recently_interrupted` otherwise defaults it to
            # `state.state_dir()`, this PROCESS's own project (the daemon's), not the TARGET
            # pane's project -- see `target_state_dir`'s docstring for the bug this closes
            # (coordinator review finding, TRDD-ECHOKVZC): without it `_is_self_sent_echo` globs
            # the WRONG project's `self-send.*.stamps.json` and never recognises a self-sent
            # `/janitor-resume` echoed into the TARGET pane, misreading it as "the user is back."
            age = user_intent.recently_interrupted(
                project_dir, transcript_path=tp, state_dir=user_intent.target_state_dir(project_dir)
            )
            if age is not None:
                _log(f"deferred — target session interrupted {int(age)}s ago (user-interrupt cooldown)")
                return Outcome(status=OutcomeStatus.NOOP, steps_done=0, observed=("interrupt-cooldown",))

    steps = plan(state, event, command=command, esc_first=esc_first, unattended=unattended, blind_ok=blind_ok)
    if not steps:
        # TRDD-FKY3NXB8: `plan()` stays PURE (module docstring) and cannot log itself, so this
        # is the one place with both the STATE that explains a NO_HEADROOM decline and I/O
        # already in scope. Only the population worth measuring: an idle pane holding text
        # that is NOT the janitor's own `/model` vocabulary (that case now clears + switches,
        # see `_at_idle`) -- a human draft deferred forever otherwise reads as a silent no-op.
        if (
            event is Event.NO_HEADROOM
            and state is not None
            and state.input_field.kind is pane_state.InputFieldKind.TEXT
        ):
            _log(f"deferred — idle field holds foreign text {(state.input_field.text or '')[:40]!r}")
        return Outcome(status=OutcomeStatus.NOOP, steps_done=0, observed=())

    accepted: list[bool] = []
    crumb_ids: dict[str, str] = {}  # TRDD-9ORKPQCX: command text -> its one crumb id (see _type)

    def _type(step: Step) -> None:
        step_plan = build_step_plan(terminal, step, submit_ref=submit_ref, fallback=command_plan)
        # TRDD-9ORKPQCX: leave the machine-typed crumb in the state dir of the project that OWNS
        # THE TARGET PANE (`project_dir`, never this daemon's own `state.state_dir()`), right
        # BEFORE fire(): the fleet iTerm path bypasses terminal_trigger.inject_until_sent, and the
        # target's UserPromptSubmit hook must not mint consent or presence for this keystroke.
        # ONE crumb per command text per act() call (`crumb_ids`), rewritten before every attempt,
        # exactly as inject_until_sent does: a fresh id per attempt would leave an orphan crumb
        # on every retype, and each orphan silently eats one real owner command of the same text
        # within the 2 h TTL. Without a `project_dir` the target is unknown and NOTHING is
        # guessed (no default to the caller's own state dir).
        if project_dir and step_plan and step_plan.get("command"):
            text = step_plan["command"]
            user_intent.note_machine_typed(
                text, user_intent.target_state_dir(project_dir), crumb_ids.setdefault(text, uuid.uuid4().hex)
            )
        accepted.append(fleet_inject.fire(step_plan))

    def _read() -> PaneState | None:
        time.sleep(settle_s)
        return pane_state.read(terminal)

    outcome = execute(
        steps,
        read=_read,
        type_keys=_type,
        log=_log,
        presence_blocked=presence_blocked if presence_blocked is not None else presence_blocked_now,
        retries=retries,
    )
    # `accepted` is the ONLY place in this system that knows a keystroke actually landed, so
    # carry it out in the Outcome instead of leaving callers to infer it from `status`. A
    # caller cannot: `execute` returns FAILED both when we pressed a live pane that stayed
    # wedged (retry later is pointless — we already tried) and when every press went into a
    # channel `build_step_plan` could not build (retry later is exactly right — nothing was
    # sent). `_rotation_esc_pass` stamps a once-per-rotation dedupe on this distinction, and
    # stamping the second case would cost that pane its unwedge for the whole rotation window.
    touched = any(accepted)
    if outcome.status is OutcomeStatus.DONE and not all(accepted):
        return Outcome(status=OutcomeStatus.FAILED, steps_done=outcome.steps_done, observed=outcome.observed, touched=touched)
    return Outcome(status=outcome.status, steps_done=outcome.steps_done, observed=outcome.observed, touched=touched)



# How long fleet_inject.build_esc_plan sleeps BEFORE it sends its ESC. resume_after_esc starts
# reading only after this plus the settle, or it would re-read the PRE-ESC frame and mistake
# "the ESC has not landed yet" for "nothing was restored". Taken from fleet_inject so the wait
# cannot drift from the plan it follows.
_ESC_PLAN_DELAY_S = fleet_inject.ESC_PLAN_DELAY_S

# Pane states in which the post-ESC composer may be typed into: a quiet prompt. API_ERROR is
# included because the red banner stays in the last rows after the ESC aborts the retry; the
# composer under it is just as free. WORKING is handled separately (the session recovered by
# itself); everything else (a dialog, the Rewind picker, compacting, a wedge that survived, no
# input box visible) is a screen we must not type into.
_RESUME_TYPABLE_KINDS = frozenset({pane_state.StatusKind.IDLE, pane_state.StatusKind.API_ERROR})

# The token resume_after_esc puts in Outcome.observed ONLY when the resume was typed, read
# back as exactly the command, and submitted. The daemon keys its resume_sent marker on it.
RESUMED = "resumed"
# Put in Outcome.observed when the pane could not be typed into at all (a dialog, a wedge that
# survived the ESC, an unreadable frame). The daemon does NOT count such an outcome as a failed
# resume try: nothing was attempted, so it must not burn the retry budget.
NOT_TYPABLE = "not-typable"
# Put in Outcome.observed when the channel has no read-back, so the resume cannot be verified
# and only the ESC was sent.
NO_READBACK = "esc-only-no-readback"


def resume_after_esc(
    terminal: dict,
    command: str,
    *,
    project_dir: str | None = None,
    log: Callable[[str], None] | None = None,
    presence_blocked: Callable[[], bool] | None = None,
    settle_s: float | None = None,
    after_esc: bool = True,
) -> Outcome:
    """The second half of `esc_nudge_resume` (TRDD-RJJGXPIK): the ESC has ALREADY been sent
    (by `act`, with every policy gate); settle, look at the composer, make it empty, and only
    then type `command` and submit it. With `after_esc=False` (the retry pass: the ESC was sent
    on an earlier beat) no ESC-plan wait is added and `touched` reports only what this call
    itself fired.

    WHY the field is read instead of assumed empty (measured live on Claude Code 2.1.323,
    mods-expert-developer report reports_dev/mods-expert-developer/20261113_171403+0100-
    liveness-mod.md, "Live measurements"; reproduced live by the TRDD-RJJGXPIK round-2 run):
    ESC aborts the turn and PUTS THE INTERRUPTED PROMPT BACK IN THE COMPOSER. Typing straight
    after the ESC therefore submitted `say hiresume` (the old fused type+Enter plan), and a
    caller that waits for an empty field would stall forever. The sequence, each step read
    back after `settle_s`:

      1. read the composer. Text there (or queued messages) is the restored prompt: send
         Esc Esc, which CC documents as "clear the draft, saved to history" on a NON-empty
         prompt (it is rewind only on an EMPTY one — see claude-code-esc-input-semantics).
         The Esc Esc is only ever sent against a field just read as non-empty.
      2. re-read; the field must now be EMPTY. If it is not, STOP: log it and type nothing.
         No loop — a draft that survives Esc Esc is not ours to fight. Because that Esc Esc
         may have OPENED the Rewind picker on a misread-empty field (measured live: the picker
         is what Esc Esc does on an empty prompt), a failure here sends ONE plain ESC, which
         cancels the picker and is a no-op on a quiet prompt.
      3. type `command` WITHOUT Enter, re-read, and require the field to show EXACTLY
         `command` (input-injection rule 3). Anything else: STOP, no Enter.
      4. Enter alone, then a last read that must no longer show the command sitting there.

    No read-back channel (wtype / xdotool / ai-maestro CLI) cannot satisfy steps 1-3, so it
    gets the ESC only — what `esc_nudge` always did (`NO_READBACK` in `observed`). A human at
    the keyboard defers before anything is cleared or typed (rule 2: stop, no cleanup).

    The restored prompt's TEXT is never logged — it is whatever the user last typed and may
    hold a secret; only its length is.

    `Outcome.observed` holds `RESUMED` iff the resume was submitted, `NOT_TYPABLE` when the
    screen could not be typed into.
    """
    settle = _SETTLE_S if settle_s is None else settle_s
    observed: list[str] = []
    fired_any = after_esc  # the ESC the caller sent already touched the pane

    def _log(message: str) -> None:
        line = f"pane-policy: esc_resume {message}"
        if log is not None:
            log(line)
        _append_ledger(project_dir, line)

    def _out(status: OutcomeStatus, steps: int) -> Outcome:
        return Outcome(status=status, steps_done=steps, observed=tuple(observed), touched=fired_any)

    def _fire(plan: dict | None) -> bool:
        nonlocal fired_any
        fired_any = True
        return fleet_inject.fire(plan)

    def _read(extra_wait_s: float = 0.0) -> PaneState | None:
        time.sleep(settle + extra_wait_s)
        state = pane_state.read(terminal)
        observed.append(state.input_field.kind.value if state is not None else "unreadable")
        return state

    def _fail_after_clear(steps: int, state: PaneState | None) -> Outcome:
        """A failure that FOLLOWED the Esc Esc: close any Rewind picker it may have opened."""
        if state is not None and state.status.kind is not pane_state.StatusKind.WORKING:
            _log("sending one plain ESC to close a Rewind picker the Esc Esc may have opened")
            _fire(fleet_inject.build_esc_plan(terminal, delay_s=0.0, esc_count=1))
        return _out(OutcomeStatus.FAILED, steps)

    if not channel_has_readback(terminal):
        _log("WARNING no read-back channel — the ESC was sent, `resume` NOT typed (cannot be verified)")
        observed.append(NO_READBACK)
        return _out(OutcomeStatus.DONE, 1)

    state = _read(_ESC_PLAN_DELAY_S if after_esc else 0.0)
    if state is None:
        _log("composer unreadable — `resume` NOT typed")
        observed.append(NOT_TYPABLE)
        return _out(OutcomeStatus.FAILED, 1)
    if state.status.kind is pane_state.StatusKind.WORKING:
        _log("session is already working — `resume` not needed")
        observed.append("working")
        return _out(OutcomeStatus.DONE, 1)
    if state.status.kind not in _RESUME_TYPABLE_KINDS:
        _log(f"pane shows {state.status.kind.value} — `resume` NOT typed")
        observed.append(NOT_TYPABLE)
        return _out(OutcomeStatus.FAILED, 1)

    gate = presence_blocked if presence_blocked is not None else presence_blocked_now
    if state.input_field.kind is not pane_state.InputFieldKind.EMPTY:
        if gate():
            _log("composer holds text and a human is at the keyboard — deferred, nothing cleared")
            return _out(OutcomeStatus.DEFERRED, 1)
        draft_len = len(state.input_field.text or "")
        _log(f"composer holds a restored prompt ({draft_len} chars) — Esc Esc to clear it")
        # delay_s=0: the settle below already covers the two ESCs and their 0.6 s gaps.
        if not _fire(fleet_inject.build_esc_plan(terminal, delay_s=0.0, esc_count=2)):
            _log("the Esc Esc plan was not accepted — `resume` NOT typed")
            return _out(OutcomeStatus.FAILED, 2)
        state = _read()
        if state is None or state.input_field.kind is not pane_state.InputFieldKind.EMPTY:
            _log("composer is still not empty after Esc Esc — `resume` NOT typed, not retrying")
            return _fail_after_clear(2, state)
        if state.status.kind not in _RESUME_TYPABLE_KINDS:
            _log(f"pane shows {state.status.kind.value} after Esc Esc — `resume` NOT typed")
            observed.append(NOT_TYPABLE)
            return _fail_after_clear(2, state)
    elif gate():
        _log("a human is at the keyboard — `resume` deferred")
        return _out(OutcomeStatus.DEFERRED, 1)

    if project_dir:
        # Same machine-typed crumb `act._type` leaves (TRDD-9ORKPQCX): the target session's own
        # UserPromptSubmit hook must not read this keystroke as the owner's consent or presence.
        user_intent.note_machine_typed(command, user_intent.target_state_dir(project_dir), uuid.uuid4().hex)
    if not _fire(fleet_inject.build_type_text_plan(terminal, command)):
        _log(f"typing {command!r} was not accepted — Enter NOT sent")
        return _out(OutcomeStatus.FAILED, 3)
    state = _read()
    shown = (state.input_field.text or "").strip() if state is not None else None
    if state is None or state.input_field.kind is not pane_state.InputFieldKind.TEXT or shown != command:
        _log(f"composer reads {len(shown) if shown is not None else 0} chars, expected exactly {command!r} — Enter NOT sent")
        return _out(OutcomeStatus.FAILED, 3)
    if not _fire(fleet_inject.build_enter_plan(terminal)):
        _log("the Enter plan was not accepted")
        return _out(OutcomeStatus.FAILED, 4)
    state = _read()
    if state is not None and state.input_field.kind is pane_state.InputFieldKind.TEXT and (state.input_field.text or "").strip() == command:
        _log(f"{command!r} is still sitting in the composer after Enter")
        return _out(OutcomeStatus.FAILED, 4)
    observed.append(RESUMED)
    _log(f"ok — {command!r} submitted")
    return _out(OutcomeStatus.DONE, 4)
