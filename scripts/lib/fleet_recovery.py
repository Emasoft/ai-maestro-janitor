"""Fleet recovery POLICY (TRDD-324223a6, GROUP A / A2) — the PURE decisions the
daemon's ``task_session_liveness`` wraps with I/O: which recovery action to inject
for a diagnosis at a given attempt count, and whether an attempt is allowed right
now (cooldown + crash-loop bounds). No I/O, no firing, no process control.

The daemon walks a COMMAND-TYPING ladder for a stuck session — each action's
injection (``fleet_inject``) sends ESC first, then types the slash-command, so a
bare ESC-nudge is subsumed by ``rearm``. The genuinely-dangerous hard-restart rungs
(relaunch / force_restart / resurrect — killing and respawning a process) are A5:
deliberately NOT wired here. When the gentle ladder is exhausted the guard alerts
a human instead of escalating to a process kill the daemon can't yet do safely.

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

# The command-typing ladder for a FROZEN (stuck) session, gentlest → strongest.
# rearm re-arms the dead in-session cron (the freeze fix); reload picks up a rolled
# plugin; update forces a self-update + re-arm. All three send ESC first.
_FROZEN_LADDER = ("rearm", "reload", "update")


def action_for(diagnosis: str, attempts: int) -> str | None:
    """The recovery action to inject for ``diagnosis`` at this ``attempts`` count,
    or None when the diagnosis is not recoverable by a typed command:

    - ``cron_dead``        → ``rearm``  (the in-session cron died → re-arm it)
    - ``version_mismatch`` → ``reload`` (running stale code → reload the new plugin)
    - ``frozen``           → walk ``_FROZEN_LADDER`` by attempt (rearm→reload→update)
    - ``healthy`` / ``unarmed`` → None  (never poke a working or opted-out session)
    - ``dead``             → None       (no pane to type into → hard-restart A5, not here)
    """
    if diagnosis == "cron_dead":
        return "rearm"
    if diagnosis == "version_mismatch":
        return "reload"
    if diagnosis == "frozen":
        return _FROZEN_LADDER[min(max(attempts, 0), len(_FROZEN_LADDER) - 1)]
    return None


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
