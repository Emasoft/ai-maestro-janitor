"""Session-liveness detection primitives (TRDD-dccb0b8a, Phase 1).

The janitor's self-recovery loop fires a fresh turn via an in-session cron when a
turn dies from a rate-limit / server throttle. On Claude Code builds that
downgrade the heartbeat cron to session-only, that cron can die WITH the session
— leaving it frozen indefinitely. This is the observed 2026-06-20→21 ~20h
freeze: a SERVER throttle ("not your usage limit") killed the turn at 23:19, the
in-session cron was already gone, and nothing OUTSIDE the session could re-fire
it, so the transcript sat silent for 19h50m until a human intervened.

These PURE functions decide, from facts the daemon can gather from OUTSIDE a
session, whether that session is FROZEN-AND-STUCK (needs an external wake) versus
merely IDLE (no pending work — leave it alone) versus RECOVERING (progressing on
its own — leave it alone). No I/O: the daemon gathers the inputs and performs the
recovery injection in separate layers. Keeping the decision pure is what makes
"never poke a healthy session" a TESTED property rather than a hope — injecting
keystrokes into a working session would corrupt real work, so the false-positive
cost is high and the gate must be conservative.
"""

from __future__ import annotations

from collections.abc import Mapping


def capture_terminal_identity(env: Mapping[str, str]) -> dict[str, str]:
    """Extract the stable terminal-pane identifiers the daemon needs to inject
    recovery into THIS session from OUTSIDE, from the session's own environment.

    PURE: returns only the keys that are PRESENT and non-empty, so the daemon can
    choose an injection backend by what is available (``iterm_session_id`` →
    iTerm osascript; ``tmux_pane`` → ``tmux send-keys``). The SESSION must record
    this because a detached daemon cannot read another session's environment, and
    ``TMUX_PANE`` / ``ITERM_SESSION_ID`` do not propagate to arbitrary
    subprocesses — only a process the session itself spawns at start sees them.
    """
    out: dict[str, str] = {}
    for env_key, out_key in (
        ("ITERM_SESSION_ID", "iterm_session_id"),
        ("TMUX_PANE", "tmux_pane"),
        ("TERM_PROGRAM", "term_program"),
    ):
        val = (env.get(env_key) or "").strip()
        if val:
            out[out_key] = val
    return out


def is_session_frozen(
    *,
    transcript_mtime: int,
    rate_limited_since: int | None,
    flag_present: bool,
    now: int,
    heartbeat_interval_s: int,
    freeze_factor: int,
    grace_s: int = 120,
) -> bool:
    """True iff a session is FROZEN-AND-STUCK and needs an external wake.

    The STUCK signal is a rate-limit flag that the session's OWN heartbeat should
    have cleared but didn't, with no transcript progress since — distinguishing a
    genuinely stuck session from one that is merely idle (no flag) or recovering
    (transcript advanced after the flag).

    Frozen iff ALL hold:
      * ``flag_present`` and ``rate_limited_since`` is set — the session recorded
        a rate-limit/throttle and has not cleared it;
      * the flag is OLDER than ``freeze_factor`` heartbeat intervals — a healthy
        session clears it within one heartbeat, so a stale flag means the
        in-session recovery (the cron) is not running. The factor gives the
        session several heartbeats to self-recover before we ever intervene;
      * the transcript has NOT advanced past the flag (+ ``grace_s`` for the
        death-burst writes around the rate-limit) — any progress AFTER the flag
        means the session recovered or is actively working, so we must NOT poke
        it. This is the load-bearing safety clause.
    """
    if not flag_present or rate_limited_since is None:
        return False  # no stuck signal — idle or healthy, never poke
    if (now - rate_limited_since) <= freeze_factor * max(1, heartbeat_interval_s):
        return False  # too fresh — give the in-session cron its chance first
    if transcript_mtime > rate_limited_since + max(0, grace_s):
        return False  # progress after the flag → recovered / actively working
    return True


def recovery_cooldown_ok(last_attempt: int | None, now: int, cooldown_s: int) -> bool:
    """True iff enough time has elapsed since the last wake attempt on this
    session. Prevents injection storms: wake once, then wait a full cooldown for
    it to take effect before trying again (or escalating a tier)."""
    if last_attempt is None:
        return True
    return (now - last_attempt) >= max(0, cooldown_s)


def escalation_tier(attempts: int) -> int:
    """Map prior FAILED wake attempts to a recovery TIER (1..3):
      * 1 — ESC + a re-arm nudge (dismiss any modal, kick a fresh turn);
      * 2 — re-arm the in-session cron explicitly (a typed ``/janitor-arm``);
      * 3 — last resort: relaunch the claude process in the pane.
    Two attempts per tier before escalating, capped at 3 so the ladder never
    loops past the nuclear option."""
    if attempts < 0:
        attempts = 0
    return min(1 + attempts // 2, 3)


# The recovery ladder (TRDD-324223a6): gentlest → nuclear. Each successive FAILED
# wake escalates one rung; a rung that succeeds (the session makes progress)
# resets the count to 0. "1 is not enough" — ESC+nudge is only the FIRST rung; a
# hard freeze (dead process, corrupted config) needs the heavier rungs.
RECOVERY_LADDER: tuple[str, ...] = (
    "esc_nudge",      # 1 — inject ESC (dismiss any modal) + kick a fresh turn
    "rearm",          # 2 — /janitor-arm: restore the heartbeat cron
    "reload",         # 3 — /reload-plugins: pick up an auto-update's new hooks
    "update",         # 4 — ensure latest plugin version, then nudge again
    "relaunch",       # 5 — claude --continue in the SAME pane (resume transcript)
    "force_restart",  # 6 — external kill of the stuck pid + claude --continue
    "resurrect",      # 7 — background claude that kills+relaunches the stuck one
)

# Rungs that kill/replace the claude process — bounded by the crash-loop guard so
# the guardian can never enter a restart storm.
NUCLEAR_RUNGS: frozenset[str] = frozenset({"relaunch", "force_restart", "resurrect"})


def recovery_action_for(attempt: int) -> str:
    """The recovery action for the Nth (0-based) consecutive failed wake. Walks
    ``RECOVERY_LADDER`` and CLAMPS to the last rung, so sustained failure stays at
    the nuclear option (bounded by ``crash_loop_tripped``) rather than wrapping
    back to a gentle no-op that would never recover a hard freeze."""
    if attempt < 0:
        attempt = 0
    return RECOVERY_LADDER[min(attempt, len(RECOVERY_LADDER) - 1)]


def is_nuclear_rung(action: str) -> bool:
    """True iff ``action`` kills/replaces the claude process (subject to the
    crash-loop guard)."""
    return action in NUCLEAR_RUNGS


def crash_loop_tripped(nuclear_attempts_in_window: int, max_in_window: int) -> bool:
    """True iff the nuclear rungs have fired too many times in the guard window —
    PAUSE the ladder for this session and page a human instead of a kill/relaunch
    storm. This is the ONE place auto-recovery yields to a human: precisely
    because recovery ITSELF is looping (a persistent, un-self-fixable fault)."""
    return nuclear_attempts_in_window >= max(1, max_in_window)


# Fleet guardianship (TRDD-324223a6): the janitor must guard EVERY claude instance
# that ever armed it — re-arming a dead cron, reloading a version-mismatch, running
# the freeze ladder — from OUTSIDE, regardless of terminal environment. The ONLY
# instance it never touches is one the USER deliberately unarmed. These two pure
# functions are the decision core; the daemon gathers the booleans (from each
# instance's state-dir + the process table) and dispatches the recovery.

# Per-instance janitor-health diagnoses, most-severe / most-actionable first.
DIAGNOSES: tuple[str, ...] = (
    "unarmed",           # user opted out — NEVER touch
    "dead",              # process/pane gone — a keystroke can't reach it
    "frozen",            # rate-limited + no transcript progress — the freeze ladder
    "version_mismatch",  # loaded an older plugin version than cached — reload/update
    "cron_dead",         # armed but the heartbeat stopped firing — re-arm
    "healthy",           # dispatch firing recently — no action
)

# Diagnosis → the recovery the daemon applies. None = leave the instance alone.
_DIAGNOSIS_RECOVERY: dict[str, str | None] = {
    "unarmed": None,
    "healthy": None,
    "frozen": "ladder",            # run recovery_action_for() (the 7-rung escalation)
    "version_mismatch": "reload",  # inject /reload-plugins (+ ensure update)
    "cron_dead": "rearm",          # inject /janitor-arm to restore the heartbeat
    "dead": "relaunch",            # gated nuclear: claude --continue in the pane
}


def diagnose_instance(
    *,
    deliberately_unarmed: bool,
    pane_alive: bool,
    frozen: bool,
    version_stale: bool,
    dispatch_stale: bool,
) -> str:
    """Classify ONE armed claude instance's janitor health from pre-gathered
    boolean facts (the daemon computes each from the instance's state-dir + the
    process table; the freeze/version/staleness comparisons live in their own
    tested helpers so this stays a pure precedence table).

    Precedence is load-bearing — the most severe / most-actionable wins, and the
    two "never touch" verdicts (`unarmed`, `healthy`) are what keep the guardian
    from disrupting a session the user opted out of or one that is working fine.
    """
    if deliberately_unarmed:
        return "unarmed"           # the user opted out — sacrosanct, never touch
    if not pane_alive:
        return "dead"              # gone — keystroke recovery is impossible
    if frozen:
        return "frozen"            # rate-limited + stuck — the freeze ladder
    if version_stale:
        return "version_mismatch"  # running old code (the 'version mismatch' error)
    if dispatch_stale:
        return "cron_dead"         # armed but the heartbeat died — re-arm it
    return "healthy"


def recovery_for_diagnosis(diagnosis: str) -> str | None:
    """The recovery action for a diagnosis, or None to leave the instance alone
    (`unarmed` / `healthy`). Unknown diagnoses are treated as 'leave alone' —
    fail safe: we never invent an action for a state we don't recognize."""
    return _DIAGNOSIS_RECOVERY.get(diagnosis)
