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
    - ``frozen``           → ``esc_nudge`` — ESC-ONLY, NO command typed (TRDD-P7WU40G9).
      ``frozen`` means the session is RATE-LIMITED and sitting in Claude Code's
      "Retrying in Xm" retry-watchdog state, which BLOCKS the input line. Typing a
      slash-command there is the 2026-07-18 disaster: the retry-wait buffers the
      keystrokes, the command TEXT accumulates on the one input line
      (``/janitor-arm/janitor-arm/janitor-arm…``), and when the wait finally breaks the
      buffer flushes into a flood that blocks the session and burns tokens. The ONLY
      correct recovery is ESC (the unwedge) with NOTHING typed: ESC breaks the
      retry-wait, and the session's OWN ``rate-limited.flag → [janitor-resume]`` path
      resumes the work. No hard-restart escalation: killing a rate-limited process
      would discard its in-flight work — the crash-loop guard pages a human instead.
    - ``healthy`` / ``unarmed`` → None  (never poke a working or opted-out session —
      ``include_hard`` NEVER changes this)
    - ``dead``             → ``relaunch`` with ``include_hard`` (no kill — type
      ``claude --continue`` into the surviving pane), else None (A5 unwired view)

    ``include_hard`` (TRDD-56d24c02 increment 2) only names the ``dead``→``relaunch``
    rung — the DAEMON gates execution on ``fleet_restart.hard_restart_enabled()``
    (DEFAULT-OFF dry-run) + ``is_killable``, so this stays pure policy.
    """
    if diagnosis == "cron_dead":
        return "rearm"
    if diagnosis == "version_mismatch":
        return "reload"
    if diagnosis == "frozen":
        return "esc_nudge"  # ESC-only; the flood-safe recovery for a rate-limited session
    if diagnosis == "dead" and include_hard:
        return "relaunch"
    return None


def injection_is_hard(diagnosis: str) -> bool:
    """Hard/soft policy for a gentle recovery injection (TRDD-0GPQROC1). PURE.

    True (ESC-interrupt first) ONLY for ``frozen``: a rate-limited session is stuck in
    the retry-watchdog wait — the ESC IS the unwedge (``frozen`` now injects ESC and
    NOTHING else; see ``action_for``). Every other injectable diagnosis (``cron_dead``,
    ``version_mismatch``) targets a LIVE, possibly mid-work session where only the
    heartbeat or the plugin code is stale; typing without ESC enqueues the command to
    run at the turn boundary, so no in-flight work is lost (user directive 2026-07-10).
    """
    return diagnosis == "frozen"


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
