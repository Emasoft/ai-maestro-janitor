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
caller's OWN already-built plan when it has one (`command_plan`), so each site's channel
selection and its `esc_first` law survive byte-for-byte. Only the DECISION moved.

"Fired" means the screen changed the way we expected AND the sender accepted the plan
(Proposal §3). A step whose `Expect` is verifiable is re-read until it converges; a step that
is not verifiable (an intermediate flush ESC, or any keystroke into a pane with no read-back
channel) is reported as `unverified`, never as proof.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import fleet_inject
import pane_state
import user_intent
from pane_policy import Event, Expect, Outcome, OutcomeStatus, Step, execute, plan

if TYPE_CHECKING:
    from pane_state import PaneState

__all__ = ["Event", "Expect", "Outcome", "OutcomeStatus", "Step", "act", "build_step_plan", "presence_blocked_now"]

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
    blind_ok = not (read_pane and channel_has_readback(terminal))
    if state is None and not blind_ok:
        _log("skipped — readable channel could not be read")
        return Outcome(status=OutcomeStatus.NOOP, steps_done=0, observed=("unreadable",))

    steps = plan(state, event, command=command, esc_first=esc_first, unattended=unattended, blind_ok=blind_ok)
    if not steps:
        return Outcome(status=OutcomeStatus.NOOP, steps_done=0, observed=())

    accepted: list[bool] = []

    def _type(step: Step) -> None:
        accepted.append(fleet_inject.fire(build_step_plan(terminal, step, submit_ref=submit_ref, fallback=command_plan)))

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
