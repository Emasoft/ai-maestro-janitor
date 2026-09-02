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

import re
from collections.abc import Mapping

# TRDD-WKTD5JTC — the CC retry-watchdog wedge signature. CAUSE-AGNOSTIC on purpose (owner
# incident 2026-07-24): the wedge fires for a 429 ("429 Rate limited · Retrying in 0s ·
# attempt 5/300") AND for a session-limit throttle ("Session limit reached · Retrying in
# 2m 50s (2:10pm) · attempt 1/300") — same UI wedge, different cause. Keying on "429" or
# "rate limit" MISSES the session-limit wedge, so the only invariant is the shape itself:
# "Retrying in <duration>" followed somewhere on the same view by "attempt N/M". Cause
# words are optional context the daemon may log, never part of the match.
_RETRY_WEDGE_RE = re.compile(r"retrying\s+in\b.*\battempt\s+(\d+)\s*/\s*\d+", re.IGNORECASE | re.DOTALL)


def is_retry_wedge(text: str) -> bool:
    """True iff `text` (a captured pane frame) shows the CC retry-watchdog wedge signature.

    PURE. Keys ONLY on the invariant shape `Retrying in … attempt N/M` — never on `429` /
    `rate limit`, which a cause-specific regex would miss the session-limit wedge. This
    alone is NOT sufficient to declare a pane wedged: a STATIC display of this exact text
    (e.g. this very TRDD file, which quotes the wedge line verbatim, shown in a pane) would
    match every poll forever. The advance-across-polls guard (`retry_wedge_state_update`)
    is what turns a signature match into a genuine wedge diagnosis — see there.
    """
    return _RETRY_WEDGE_RE.search(text or "") is not None


def retry_wedge_attempt(text: str) -> int | None:
    """The `attempt N` number from a captured pane frame, or None when the wedge signature
    is absent. PURE. This is the ONLY thing that can distinguish a genuinely-retrying pane
    from one merely displaying the string: the countdown/spinner/statusline clock all change
    every poll too, so "nothing else on the frame changes" is not a usable heuristic — only
    the attempt counter's own trajectory (advancing vs static) tells the two apart."""
    m = _RETRY_WEDGE_RE.search(text or "")
    return int(m.group(1)) if m else None


# A Claude Code input-box border: a full row of box-drawing dashes. Two of them frame the
# input line; the status/queue block sits directly ABOVE the upper one.
_INPUT_BOX_BORDER_RE = re.compile(r"^\s*[─━—-]{20,}\s*$")
# How many non-empty rows above the upper border may hold the status block: the spinner /
# retry line, `(ctrl+b to run in background)`, and a few queued `❯ cmd` rows. Measured on
# this host 2026-09-02: the wedge sat 1 row above the border (one queued command between).
_STATUS_BLOCK_ROWS = 8
# Without an input box in the frame (a bare tmux pane, a capture cut short) fall back to the
# bottom rows of whatever was captured.
_TAIL_FALLBACK_ROWS = 12


def retry_wedge_attempt_at_tail(text: str) -> int | None:
    """The retry-wedge attempt number from a pane frame's STATUS block, or None. PURE.

    The rotation-ESC pass (TRDD-NACCL0CB) cannot use the advance-across-polls guard: a
    weekly-window wall shows `Retrying in 5h … attempt 1/5` and that attempt number does not
    move for five hours, so "advanced" can never come true there. Its guard is POSITIONAL,
    anchored on Claude Code's own chrome rather than a row count (a plain "last N rows"
    window was reviewed and rejected: on this host assistant prose reaches within a dozen rows
    of the bottom, and this repo's own replies quote the wedge line verbatim):

    - the input box is the pair of dash borders at the bottom; the status block (spinner or
      retry line, queued `❯ cmd` rows) is the few rows directly above the UPPER border, and
      conversation content is above that;
    - a real retry line starts at column 0 with its glyph (`✻ Fable limit reached · …`);
      assistant prose is indented under its `⏺` marker, so a quoted wedge line is indented.

    So: the FIRST column-0 row matching the wedge signature within `_STATUS_BLOCK_ROWS` rows
    above the upper border counts; anything indented or higher up does not.
    """
    rows = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    borders = [i for i, r in enumerate(rows) if _INPUT_BOX_BORDER_RE.match(r)]
    if len(borders) >= 2:
        top = borders[-2]
        window = rows[max(0, top - _STATUS_BLOCK_ROWS):top]
    else:
        window = rows[-_TAIL_FALLBACK_ROWS:]
    for row in reversed(window):
        if row[:1].isspace():
            continue  # indented = conversation content, never Claude Code's own status row
        m = _RETRY_WEDGE_RE.search(row)
        if m:
            return int(m.group(1))
    return None


def retry_wedge_state_update(
    *, prev: Mapping[str, object] | None, current_attempt: int | None
) -> tuple[dict[str, object] | None, bool]:
    """Advance the persisted retry-wedge episode state by ONE poll and decide whether THIS
    poll counts as wedged. PURE (TRDD-WKTD5JTC, advisor correction #3).

    Returns ``(new_state, wedged)`` — ``new_state`` is what the caller persists for the NEXT
    poll (``None`` clears it: the signature is gone, the episode is over); ``wedged`` is True
    only once genuine progress (an attempt-number ADVANCE) has been observed — the ONLY guard
    against a pane that STATICALLY displays the string (a naive substring/regex-only match
    would self-trigger on this very TRDD file's own quoted wedge line, which never advances).

    ``current_attempt`` is None when this poll's pane text does not match the wedge signature
    at all (``is_retry_wedge`` false) — the episode is over, clear state, never wedged.

    A DECREASE vs the persisted attempt starts a NEW episode (the earlier one ended — broke,
    or the turn resumed and a fresh retry began later) rather than being treated as
    regression; the new episode's baseline resets ``confirmed`` to False, so IT must advance
    at least once before it counts either.

    A TIE (same attempt as the last poll) is not progress by itself, but it does not cancel
    an ALREADY-confirmed episode either: CC's backoffs (observed up to 2m50s) can exceed the
    ~2 min heartbeat interval, so two consecutive polls legitimately land on the same number
    while the episode is still genuinely wedged — "keep polling", not "reset to unconfirmed".
    """
    if current_attempt is None:
        return None, False
    prev_attempt = prev.get("attempt") if prev else None
    prev_confirmed = bool(prev.get("confirmed")) if prev else False
    if not isinstance(prev_attempt, int) or current_attempt < prev_attempt:
        return {"attempt": current_attempt, "confirmed": False}, False
    if current_attempt > prev_attempt:
        return {"attempt": current_attempt, "confirmed": True}, True
    return {"attempt": current_attempt, "confirmed": prev_confirmed}, prev_confirmed


# PUBLIC: both dispatch.py's alarm and fleet_scan's flag stamp import these, so they are
# part of this module's surface, not internals. See `latest_iterm_rearm_epoch` for why the
# parser and its inputs must have exactly one home.
ITERM_REARM_LOG_NAMES = ("daemon.log", "daemon.log.1")
ITERM_REARM_EVIDENCE_WINDOW_S = 6 * 3600  # peer-measured: rescues landed 1-4h before a false alarm


# Every log line that PROVES the iTerm Apple Event channel answered. Both are positive
# evidence, and leaving the second one out is what made a healthy channel age into looking
# dead (janitor#261, measured on this host: 15 BUSY vs 9 FIRED — the UNCOUNTED outcome is the
# MORE COMMON one).
#
# Why BUSY counts: to report "the input field is busy" the daemon had to READ the pane, which
# requires the Apple Event to have come back. A denied or hung event produces neither line.
# Counting only `FIRED rearm` measured "did the guardian have work to do recently", not "does
# the channel work" — and on a healthy fleet it usually has no work, so the evidence age grew
# without bound while nothing was wrong. Seven consecutive fires were misread that way.
_ITERM_CHANNEL_EVIDENCE = (
    "FIRED rearm → iterm",       # the guardian resolved the channel AND injected
    "INPUT FIELD BUSY on iterm",  # the guardian READ the pane and declined to inject
)


def latest_iterm_rearm_epoch(log_text: str) -> int | None:
    """The epoch of the newest line PROVING the iTerm channel answered, or None. PURE.

    THE single parser for this line — `dispatch.py`'s alarm and `fleet_scan`'s flag stamp
    both call it. It lives here because this module OWNS the semantics of that line: it is
    written by the session-liveness recovery path, so a change to its wording or timestamp
    format is a change to this module's own output.

    Previously duplicated verbatim in both callers and "kept in sync by comment, not by
    import". That is the failure this consolidation removes: if the log line or the
    `%Y-%m-%dT%H:%M:%S%z` stamp ever changes, one copy would be updated and the other would
    silently return None forever — the flag's `rearm_evidence_age_s` going permanently
    absent while the alarm's own parse kept working, so nothing would look broken.

    Malformed timestamps are skipped, never fatal — a log line we cannot date is not
    evidence in either direction.
    """
    import datetime as _dt  # noqa: PLC0415 -- local: keeps module import cost off the hot path

    latest: int | None = None
    for line in log_text.splitlines():
        if not line.startswith("[") or not any(m in line for m in _ITERM_CHANNEL_EVIDENCE):
            continue
        try:
            stamp = line[1 : line.index("]")]
            epoch = int(_dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z").timestamp())
        except (ValueError, IndexError):
            continue
        if latest is None or epoch > latest:
            latest = epoch
    return latest


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
    "server_owned",      # an ai-maestro harness agent a LIVE server owns — NEVER touch (TRDD-PZLVT2RN)
    "dead",              # process/pane gone — a keystroke can't reach it
    "retry_wedged",      # CC's own retry-watchdog wedge (no flag) — ESC-only, ranked above frozen
    "frozen",            # rate-limited + no transcript progress — the freeze ladder
    "version_mismatch",  # loaded an older plugin version than cached — reload/update
    "cron_dead",         # armed but the heartbeat stopped firing — re-arm
    "healthy",           # dispatch firing recently — no action
)

# Diagnosis → the recovery the daemon applies. None = leave the instance alone.
_DIAGNOSIS_RECOVERY: dict[str, str | None] = {
    "unarmed": None,
    "server_owned": None,          # the ai-maestro server owns this agent's continuity — hands off
    "healthy": None,
    "retry_wedged": "esc_retry",   # OWN esc-only recovery (TRDD-WKTD5JTC advisor #1) — NEVER "ladder":
                                    # "ladder" walks to force_restart (a KILL) at attempts>=3 under
                                    # include_hard=True, and a retry-wedge must never kill at any
                                    # attempt count. fleet_recovery.action_for maps this to esc_nudge
                                    # UNCONDITIONALLY (see there) — this string is only the "is this
                                    # diagnosis actionable at all" marker, never invoked directly.
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
    server_owned: bool = False,
    retry_wedged: bool = False,
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
    if server_owned:
        # An ai-maestro harness agent whose LIVE server owns Family-A continuity
        # (TRDD-PZLVT2RN / janitor#100: "neither touches the other's agents"). Checked
        # BEFORE dead/frozen on purpose: even a stuck harness agent is the SERVER's to
        # recover — two principals actuating one pane is the corruption the split
        # prevents. The decision of WHO is server-owned is
        # harness_backend.instance_is_server_owned (override + tag + cache); this table
        # only ranks it.
        return "server_owned"
    if not pane_alive:
        return "dead"              # gone — keystroke recovery is impossible
    if not transcript_stale:
        return "healthy"           # transcript advancing = working OR heartbeat-firing; never touch
    if retry_wedged:
        # Ranked ABOVE frozen (TRDD-WKTD5JTC design §2): a pane can show BOTH the wedge
        # signature and a stale rate-limited.flag (e.g. a prior window's flag that never got
        # swept), and the ESC-only recovery is identical in shape either way — but retry_wedged
        # must win the ROUTING so its OWN esc-only entry is consulted (never "ladder", which
        # would eventually escalate frozen's hard rung — a kill this diagnosis must never reach).
        return "retry_wedged"
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
