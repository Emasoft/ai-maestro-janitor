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

CC-watchdog interaction (TRDD-FVO2KSSO): CC 2.1.196 ships a default-on stream
idle-watchdog (~5 min; disable via CLAUDE_ENABLE_STREAM_WATCHDOG=0) that
aborts+retries a stalled turn, and CC 2.1.199's CLAUDE_CODE_RETRY_WATCHDOG raises
the default retry count to 300 and lifts the 15 cap on CLAUDE_CODE_MAX_RETRIES
(the sanctioned unattended-session knob). The janitor's freeze-detection is thus
a COMPLEMENT / second line of defense — it recovers a HARD freeze (dead process,
corrupted config) that CC's own turn-level watchdog cannot — not the sole
recovery path.
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


def rate_limit_flag_is_stale(flag_mtime: int | None, now: int, max_age_s: int) -> bool:
    """True iff a `rate-limited.flag` is old enough to be litter rather than a rate limit.

    Only `dispatch.py` clears the flag, and dispatch runs only from a live heartbeat cron.
    A project whose cron died therefore can NEVER clear its own flag — the loop is closed
    by construction, and 17 of 35 projects on this machine held one, up to 50 days old
    (janitor#77 item 4). A stale flag makes `diagnose_instance` read a merely-quiet session
    as `frozen`, which walks the ladder toward rung 6 `force_restart` (a kill) instead of
    the gentle `rearm` that `cron_dead` earns.

    Age is the flag's own mtime because the StopFailure hook `touch()`es it on EVERY
    turn-ending API error. So a session that is genuinely rate-limited right now keeps its
    flag fresh for as long as the limit lasts, and is never swept — while a session that
    has not hit an API error in `max_age_s` is not rate-limited by any definition.

    `max_age_s <= 0` disables the sweep (never stale). An unreadable mtime is not stale:
    we never delete what we cannot assess.
    """
    if flag_mtime is None or max_age_s <= 0:
        return False
    return (now - flag_mtime) >= max_age_s


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
    loops past the hard-restart option."""
    if attempts < 0:
        attempts = 0
    return min(1 + attempts // 2, 3)


# The recovery ladder (TRDD-324223a6): gentlest → hard-restart. Each successive FAILED
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
HARD_RUNGS: frozenset[str] = frozenset({"relaunch", "force_restart", "resurrect"})


def recovery_action_for(attempt: int) -> str:
    """The recovery action for the Nth (0-based) consecutive failed wake. Walks
    ``RECOVERY_LADDER`` and CLAMPS to the last rung, so sustained failure stays at
    the hard-restart option (bounded by ``crash_loop_tripped``) rather than wrapping
    back to a gentle no-op that would never recover a hard freeze."""
    if attempt < 0:
        attempt = 0
    return RECOVERY_LADDER[min(attempt, len(RECOVERY_LADDER) - 1)]


def is_hard_rung(action: str) -> bool:
    """True iff ``action`` kills/replaces the claude process (subject to the
    crash-loop guard)."""
    return action in HARD_RUNGS


def crash_loop_tripped(hard_attempts_in_window: int, max_in_window: int) -> bool:
    """True iff the hard-restart rungs have fired too many times in the guard window —
    PAUSE the ladder for this session and page a human instead of a kill/relaunch
    storm. This is the ONE place auto-recovery yields to a human: precisely
    because recovery ITSELF is looping (a persistent, un-self-fixable fault)."""
    return hard_attempts_in_window >= max(1, max_in_window)


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
    "dead": "relaunch",            # gated hard-restart: claude --continue in the pane
}


def diagnose_instance(
    *,
    deliberately_unarmed: bool,
    pane_alive: bool,
    transcript_stale: bool,
    rate_limited: bool,
    version_stale: bool,
) -> str:
    """Classify ONE armed claude instance's janitor health from pre-gathered
    boolean facts (the daemon computes each from the instance's state-dir +
    transcript + the process table; this stays a pure precedence table).

    The pivotal signal is ``transcript_stale`` — the session's ``.jsonl``
    transcript has NOT advanced within the liveness window. A healthy session's
    transcript advances on EVERY heartbeat (the cron fires a turn, which is
    recorded) AND continuously while it works — so a stale transcript means
    NEITHER is happening: the heartbeat is dead and no work is in flight.

    This is deliberately NOT ``dispatch.log``: dispatch.log is written only on
    NOTABLE events (errors, resumes, pauses), never on a silent heartbeat fire,
    so a quiet-but-healthy session would falsely look cron-dead. And it is not a
    new heartbeat stamp: the broken/zombie instances run an OLD janitor that never
    writes one. EVERY claude instance writes its transcript on every turn — so the
    transcript is the one liveness signal that is both reliable AND works on the
    legacy instances we must rescue. A fresh transcript is therefore the
    false-positive guard: a busy session (continuous tool-call appends) and an
    idle-but-cron-firing session (a heartbeat turn every few minutes) both keep it
    fresh, and neither is ever flagged.
    """
    if deliberately_unarmed:
        return "unarmed"           # the user opted out — sacrosanct, never touch
    if not pane_alive:
        return "dead"              # gone — keystroke recovery is impossible
    if not transcript_stale:
        return "healthy"           # transcript advancing = working OR heartbeat-firing; never touch
    if rate_limited:
        return "frozen"            # stuck + a rate-limit flag = the freeze → ladder
    if version_stale:
        return "version_mismatch"  # stuck on old code → reload
    return "cron_dead"             # stuck, no rate-limit = a dead heartbeat → re-arm


def recovery_for_diagnosis(diagnosis: str) -> str | None:
    """The recovery action for a diagnosis, or None to leave the instance alone
    (`unarmed` / `healthy`). Unknown diagnoses are treated as 'leave alone' —
    fail safe: we never invent an action for a state we don't recognize."""
    return _DIAGNOSIS_RECOVERY.get(diagnosis)


def normalize_tty(raw: str) -> str:
    """Normalize a TTY name to a comparable key (the device basename, e.g.
    ``ttys003``). `ps -o tty=` reports ``s003`` (no ``tty`` prefix) on macOS,
    while `lsof` and iTerm report ``/dev/ttys003`` — all three must compare equal
    so a claude process's controlling TTY matches its terminal's TTY. Empty / no
    controlling tty (``?``, ``-``) returns ``""``."""
    t = (raw or "").strip()
    if not t or t in ("?", "??", "-"):
        return ""
    if t.startswith("/dev/"):
        t = t[len("/dev/"):]
    if t.startswith("s") and not t.startswith("tty"):  # ps drops the 'tty' prefix
        t = "tty" + t
    return t


def resolve_terminal_for_tty(
    tty: str, *, iterm_by_tty: dict[str, str], tmux_by_tty: dict[str, str]
) -> dict[str, str]:
    """Resolve a process's terminal-injection identity from its (normalized) TTY,
    using OS-gathered lookups — WITHOUT relying on the session having recorded its
    own id. This is the load-bearing fleet-rescue path: the broken/zombie
    instances run an OLD janitor that never wrote ``terminal-identity.json``, so
    the only way to reach them is to map their live TTY to a terminal the daemon
    can drive. Returns ``{tmux_pane?, iterm_session_id?}`` — tmux first (the
    cleanest external channel) but both kept when a TTY resolves in both."""
    out: dict[str, str] = {}
    if not tty:
        return out
    pane = tmux_by_tty.get(tty)
    if pane:
        out["tmux_pane"] = pane
    sid = iterm_by_tty.get(tty)
    if sid:
        out["iterm_session_id"] = sid
    return out
