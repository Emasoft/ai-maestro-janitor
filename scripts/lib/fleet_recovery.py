"""Fleet recovery POLICY (TRDD-324223a6, GROUP A / A2) — the PURE decisions the
daemon's ``task_session_liveness`` wraps with I/O: which recovery action to inject
for a diagnosis at a given attempt count, and whether an attempt is allowed right
now (cooldown + crash-loop bounds). No I/O, no firing, no process control.

The daemon walks a COMMAND-TYPING ladder for a stuck session — each action's
injection (``fleet_inject``) sends ESC first, then types the slash-command, so a
bare ESC-nudge is subsumed by ``rearm``. The genuinely-dangerous hard-restart rungs
(relaunch / force_restart / resurrect — killing and respawning a process) are A5
(TRDD-56d24c02): this POLICY names them only when the caller passes
``include_hard=True`` (increment 2, USER-approved 2026-07-08); EXECUTION stays in
the daemon behind ``fleet_restart.hard_restart_enabled()`` + ``is_killable`` — this
module still never fires anything. Without ``include_hard`` the gentle ladder is
the whole ladder and exhaustion alerts a human, exactly as before.

All three gentle rungs are IDEMPOTENT and harmless even if mis-fired on a merely
idle (non-working) session: ESC on a session with no in-flight turn is a no-op, and
``/janitor-arm`` / ``/reload-plugins`` just re-establish the heartbeat. The
load-bearing safety is upstream — ``diagnose_instance`` never classifies a session
whose transcript is advancing as recoverable, so an actively-working session is
never targeted.
"""

from __future__ import annotations

import session_liveness  # noqa: E402  (bare sibling import; lib/ is on sys.path)

# Min seconds between recovery attempts on ONE instance — long enough that a
# re-arm has a full heartbeat interval (~5 min) to take effect, plus margin,
# before the next escalation nudge.
COOLDOWN_S = 900
# Crash-loop guard: after this many attempts on one instance without it recovering,
# STOP poking it and alert a human — recovery itself is looping, which is the one
# situation auto-recovery must yield on.
MAX_ATTEMPTS = 4

def action_for(diagnosis: str, attempts: int, *, include_hard: bool = False) -> str | None:
    """The recovery action to inject for ``diagnosis`` at this ``attempts`` count,
    or None when the diagnosis is not recoverable:

    - ``cron_dead``        → ``rearm``  (the in-session cron died → re-arm it)
    - ``version_mismatch`` → ``reload`` (running stale code → reload the new plugin)
    - ``frozen``           → ``esc_nudge`` UNCONDITIONALLY, at EVERY ``attempts`` value and
      REGARDLESS of ``include_hard`` (TRDD-P7WU40G9; capped by TRDD-L32WC0H7 / F1 derived 1).
      ESC-ONLY, NO command typed. ``frozen`` means the session is RATE-LIMITED and sitting in
      Claude Code's "Retrying in Xm" retry-watchdog state, which BLOCKS the input line. Typing
      a slash-command there is the 2026-07-18 disaster: the retry-wait buffers the keystrokes,
      the command TEXT accumulates on the one input line
      (``/janitor-arm/janitor-arm/janitor-arm…``), and when the wait finally breaks the buffer
      flushes into a flood that blocks the session and burns tokens. ESC breaks the retry-wait
      and the session's OWN ``rate-limited.flag → [janitor-resume]`` resumes the work — with NO
      command to accumulate. It NEVER escalates to ``force_restart``: the `frozen` shape is
      indistinguishable from a static CC retry-watchdog frame (`attempt 1/5` unchanged for
      hours — see ``retry_wedged`` below), so a stall whose cause is unsettled must never reach
      a kill rung. On exhaustion (``gate()`` → ``crash_loop``) the daemon alerts a human, never
      a keystroke.
    - ``healthy`` / ``unarmed`` → None  (never poke a working or opted-out session —
      ``include_hard`` NEVER changes this)
    - ``dead``             → ``relaunch`` with ``include_hard`` (no kill — type
      ``claude --continue`` into the surviving pane), else None (A5 unwired view)
    - ``retry_wedged``     → ``esc_nudge`` UNCONDITIONALLY, at EVERY ``attempts`` value and
      REGARDLESS of ``include_hard`` (TRDD-WKTD5JTC advisor #1). This is CC's own
      retry-watchdog wedge (``Retrying in … attempt N/M`` — no ``rate-limited.flag`` involved
      until the daemon writes one itself, see the caller); it is never a crashed/dead
      process, so escalating to a kill rung — which ``frozen``'s ``"ladder"`` mapping would
      eventually reach — is never correct here. Checked BEFORE the ``frozen`` branch so a
      diagnosis of exactly ``"retry_wedged"`` never falls through to it.

    ``include_hard`` (TRDD-56d24c02 increment 2) only NAMES the hard rungs — the DAEMON gates
    execution on ``fleet_restart.hard_restart_enabled()`` (DEFAULT-OFF dry-run) + ``is_killable``,
    so this stays pure policy.
    """
    if diagnosis == "cron_dead":
        return "rearm"
    if diagnosis == "version_mismatch":
        return "reload"
    if diagnosis == "retry_wedged":
        return "esc_nudge"  # ESC-only, at EVERY attempt, include_hard or not — never escalates
    if diagnosis == "frozen":
        # CAPPED at esc_nudge, unconditionally (TRDD-L32WC0H7 / F1 derived 1): a `frozen`
        # diagnosis is a STALL whose cause is UNSETTLED — it fires on the exact same shape
        # as a static CC retry-watchdog frame (`attempt 1/5` unchanged for hours), which
        # `retry_wedged` above already declines to escalate for the same reason. Escalating
        # to `force_restart` here was reachable via `crash_loop_tripped`'s own budget
        # (attempt 3 < MAX_ATTEMPTS=4) BEFORE the give-up alert ever fired, i.e. a kill could
        # happen on a session no human had been told about yet. Never kill a session whose
        # stall shape has not been confirmed distinct from a benign retry wait; on exhaustion
        # (`gate()` → `crash_loop`) the daemon alerts a human instead — never a keystroke.
        return "esc_nudge"
    if diagnosis == "dead" and include_hard:
        return "relaunch"
    return None


def injection_is_hard(diagnosis: str) -> bool:
    """Hard/soft policy for a gentle recovery injection (TRDD-0GPQROC1). PURE.

    True (ESC-interrupt first) for ``frozen`` and ``retry_wedged``: both are a session stuck
    in Claude Code's retry-watchdog wait — the ESC IS the unwedge, and typing a command would
    only buffer on the retry-blocked input line (TRDD-P7WU40G9). ``retry_wedged``
    (TRDD-WKTD5JTC) must return True here for a second, independent reason: the
    ``trailing_enqueues`` wedged-target short-circuit in ``daemon.py`` declines every
    injection for which this is False, so without it the daemon would notify a human instead
    of ever sending the unwedging ESC. Every other injectable diagnosis (``cron_dead``,
    ``version_mismatch``) targets a LIVE, possibly mid-work session where only the heartbeat
    or the plugin code is stale; typing without ESC enqueues the command to run at the turn
    boundary, so no in-flight work is lost (user directive 2026-07-10).
    """
    return diagnosis in ("frozen", "retry_wedged")


def gate(*, last_ts: int | None, attempts: int, now: int) -> str:
    """Decide whether to attempt recovery on an instance NOW. Returns:

    - ``'crash_loop'`` — the attempt budget is spent (→ the daemon alerts a human
      ONCE and stops poking; checked FIRST so a spent budget always wins),
    - ``'cooldown'``   — the last attempt is too recent (let the prior nudge land),
    - ``'ok'``         — proceed with a recovery attempt.
    """
    if session_liveness.crash_loop_tripped(attempts, MAX_ATTEMPTS):
        return "crash_loop"
    if not session_liveness.recovery_cooldown_ok(last_ts, now, COOLDOWN_S):
        return "cooldown"
    return "ok"
