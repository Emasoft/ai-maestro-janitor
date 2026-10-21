"""Out-of-band rotator alarm (TRDD-3OS6AXV3 R4) — the DAEMON's last-resort channel.

Incident 2026-10-03 00:37: the only live login expired with no warning, and every model turn
afterwards just printed "Login expired". The daemon (alive regardless of any login) therefore
raises ONE desktop notification per condition episode (USER ruling 2026-10-21: the user is
told, no agent is: rotator and account issues never reach agent context, so there is no
heartbeat drift line and no agent-visible channel). Every active alarm is recorded in
`rotator-alert.json` (diagnostics) and `owner-remediation.json`; the daemon notifies each new
remediation record once through `notify.notify_episode`.

Reads only state.json / rotation-stuck.json / tick-completed.ts — never a credential. The text
names the single action; a remediation record may carry the affected account e-mail (it is owner-only
state and a desktop notification, never agent context), and never a token.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import notify  # noqa: E402  -- the existing daemon-only desktop notifier
import state  # noqa: E402

ALERT_NAME = "rotator-alert.json"
DEBOUNCE_S = 3600  # flap window: a condition gone longer than this is a NEW episode and notifies again
TICK_STALL_S = 600  # no completed rotator tick for this long while claude runs

_ACTIONS = {
    "no-rotation-target": "no spare account to rotate to - run /janitor-capture-all-logins",
    "tick-stalled": "the account rotator has stopped ticking - run /janitor-doctor",
    "rotation-stuck": "account rotation is stuck - run /janitor-capture-all-logins",
}
# WHY (TRDD-5CCRBM1H): one name for the all-accounts-maxed stuck text, so the test imports it
# instead of repeating the literal and the two cannot drift.
_STUCK_ALL_MAXED_TEXT = "every account is at its usage limit - waiting for a window to reset"
# WHY (TRDD-DM7IJQ1T): a login capture cannot help these kinds, so each names its own remedy.
_STUCK_TEXT = {
    "all-accounts-maxed": _STUCK_ALL_MAXED_TEXT,
    "no-alternates-configured": "no second account to rotate to - add another paid account",
    "expired-and-offline": "the login expired and the API is unreachable - check the network, then run /login",
    "identity-unknowable": "the live login cannot be identified - start one interactive Claude session, or run /login",
}


REMEDIATION_FRESH_S = 1800  # a record not re-seen for this long is not NEWLY notified (an episode ends only on an observed clear, never on this age)
AUTH_FAILED_NAME = "auth-failed.json"  # written by the StopFailure hook on a 401
AUTH_FAILED_TTL_S = 6 * 3600  # the marker expires on its own after 6 h
AUTH_FAILED_ACTION = "the login was rejected (Login expired) - run /login"


# WHY (TRDD-MI018FID): the alert and the oauth-login-needed detector word a stuck rotation from this one table.
def stuck_text(kind: object) -> str:
    """Owner-facing wording for a stuck-rotation kind; unknown kinds get the generic remedy."""
    return _STUCK_TEXT.get(str(kind), _ACTIONS["rotation-stuck"])


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _dict(raw: object) -> dict:
    return raw if isinstance(raw, dict) else {}


def _epoch(raw: object) -> Optional[float]:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw / 1000 if raw > 1e12 else float(raw)


def _remediation_key(condition: str, kind: str, slot: str) -> str:
    return ":".join(p for p in (condition, kind, slot) if p)


def _remediation_lock(root: Path) -> Path:
    return root / (OWNER_REMEDIATION_NAME + ".lock")


REMEDIATION_MAX_AGE_S = 7 * 86400  # a record not re-seen for a week is a condition long gone


def _prune_stale(records: dict, now: float) -> dict:
    """`records` without the ones not re-seen for REMEDIATION_MAX_AGE_S, each pruned record's
    notification episode ended. WHY clear_episode (TRDD-1J9B7MWO): an episode ends only on an
    observed clear, so a record dropped by age alone would leave its episode open and suppress
    every later notification for that condition forever; the backstop makes the worst case one
    repeat a week for a condition that can never be observed clear. Limitation: an episode
    whose record vanished by some other route without clear_episode is not covered (every known
    removal path calls it)."""
    kept: dict = {}
    for k, v in records.items():
        if isinstance(v, dict) and now - (_epoch(v.get("last_seen")) or 0) <= REMEDIATION_MAX_AGE_S:
            kept[k] = v
        elif isinstance(v, dict):
            notify.clear_episode(
                condition=str(v.get("condition") or ""),
                kind=str(v.get("kind") or ""),
                slot=str(v.get("slot") or ""),
                now=now,
            )
    return kept


def prune_stale_remediations(root: Path, now: float) -> None:
    """Age-prune owner-remediation.json under its lock. Called every daemon pass (`evaluate`) so a
    quiet host that records nothing new still prunes."""

    def _update() -> None:
        records = _dict(_read_json(root / OWNER_REMEDIATION_NAME).get("conditions"))
        kept = _prune_stale(records, now)
        if len(kept) != len(records):
            _write_remediations(root, kept)

    if (root / OWNER_REMEDIATION_NAME).exists():
        notify.under_lock(_remediation_lock(root), _update)


def _write_remediations(root: Path, records: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state.atomic_write(root / OWNER_REMEDIATION_NAME, json.dumps({"conditions": records}, sort_keys=True))


def _spare_stale_after_s() -> float:
    """ROTATOR_SPARE_STALE_AFTER_H (hours past expiry, default 4) in seconds. A malformed value
    falls back to 4: raising here would make the daemon's fail-open drop EVERY alarm
    (TRDD-B78NJU35); the daemon logs the fallback via `spare_stale_env_malformed`."""
    if spare_stale_env_malformed() is not None:
        return 4 * 3600.0
    return float(os.environ.get("ROTATOR_SPARE_STALE_AFTER_H", "4")) * 3600


def spare_stale_env_malformed() -> Optional[str]:
    """The raw ROTATOR_SPARE_STALE_AFTER_H when it is set but not a non-negative number, else
    None. The single parse rule: `_spare_stale_after_s` falls back on it and the daemon (which
    has the logger this module lacks) reports it, so a typo leaves a trace (TRDD-B78NJU35)."""
    raw = os.environ.get("ROTATOR_SPARE_STALE_AFTER_H")
    if raw is None:
        return None
    try:
        return raw if not float(raw) >= 0 else None  # NaN and negatives are malformed too
    except ValueError:
        return raw


def _live(st: dict) -> tuple[Optional[str], Optional[float]]:
    """(live account e-mail, its slot twin expiry) from state.json - no credential read."""
    live = st.get("live_email")
    live = live if isinstance(live, str) else None
    slot = _dict(_dict(st.get("slots")).get(live))
    return live, _epoch(slot.get("expires_at"))


def record_auth_failed(root: Path, kind: str, now: float) -> None:
    """Called by the StopFailure hook on an authentication failure: marker for the daemon.
    Holds a timestamp, the error kind and the live account/expiry it was raised under (so a
    rotation clears it) - never a token. The clear on a working login is `clear_auth_failed`."""
    live, live_exp = _live(_read_json(root / "state.json"))
    root.mkdir(parents=True, exist_ok=True)
    state.atomic_write(
        root / AUTH_FAILED_NAME,
        json.dumps({"ts": int(now), "kind": kind, "live_email": live, "live_exp": live_exp}),
    )


def clear_auth_failed(root: Path) -> None:
    """Called by the Stop hook: Claude Code fires Stop only for a turn that ended WITHOUT an
    API error, so a Stop is proof the login works again - the marker is no longer true. (The
    beacon fp is NOT used for this: a re-stamp of a still-dead primary changes it too.)"""
    (root / AUTH_FAILED_NAME).unlink(missing_ok=True)


# WHY (TRDD-JWIGGMH0): owner remediation is control-plane state, not a finding source.
# Desktop delivery may fail or dedupe; this record remains readable by explicit pull diagnostics.
OWNER_REMEDIATION_NAME = "owner-remediation.json"


def record_owner_remediation(
    root: Path, condition: str, action: str, now: float, *, kind: str = "", slot: str = ""
) -> None:
    """Durably record an owner-only remediation without creating agent-context output.
    The record key is condition[:kind][:slot] - the same three parts that make one notification
    episode (`notify.notify_episode`). The daemon notifies each fresh record once.
    One record per (condition, slot): a record of the same condition and slot under ANOTHER kind
    is superseded (the old kind no longer holds - observed), and its episode is cleared.
    The read-modify-write runs under a sidecar flock: the daemon's alert thread and every
    session's detector write this file, and an unlocked update is a lost record."""

    def _update() -> None:
        records = _dict(_read_json(root / OWNER_REMEDIATION_NAME).get("conditions"))
        for old_key, old in list(records.items()):
            old = _dict(old)
            if old.get("condition") == condition and (old.get("slot") or "") == slot and (old.get("kind") or "") != kind:
                del records[old_key]
                notify.clear_episode(condition=condition, kind=str(old.get("kind") or ""), slot=slot, now=now)
        records[_remediation_key(condition, kind, slot)] = {
            "condition": condition, "kind": kind, "slot": slot, "action": action, "last_seen": int(now)
        }
        _write_remediations(root, _prune_stale(records, now))

    root.mkdir(parents=True, exist_ok=True)
    notify.under_lock(_remediation_lock(root), _update)


def clear_owner_remediations(
    root: Path,
    condition: str,
    now: float,
    *,
    keep_slots: frozenset[str] = frozenset(),
    observed_slots: Optional[frozenset[str]] = None,
) -> None:
    """The caller OBSERVED `condition` gone for every slot not in `keep_slots`: delete those
    records and end their notification episodes (`notify.clear_episode`). This - never a gap in
    observation - is what lets a returning condition notify again.
    `observed_slots`, when given, limits the clear to those slots: a slot the caller could not
    read this pass is not observed, so its record and episode must survive (TRDD-1J9B7MWO)."""

    def _update() -> None:
        records = _dict(_read_json(root / OWNER_REMEDIATION_NAME).get("conditions"))
        gone = {
            k: _dict(v) for k, v in records.items()
            if _dict(v).get("condition") == condition and (_dict(v).get("slot") or "") not in keep_slots
            and (observed_slots is None or (_dict(v).get("slot") or "") in observed_slots)
        }
        if not gone:
            return
        for k in gone:
            del records[k]
        _write_remediations(root, records)
        for rec in gone.values():
            notify.clear_episode(
                condition=condition, kind=str(rec.get("kind") or ""), slot=str(rec.get("slot") or ""), now=now
            )

    if (root / OWNER_REMEDIATION_NAME).exists():
        notify.under_lock(_remediation_lock(root), _update)


# WHY a marker file (TRDD-0SU2C2IM): the capture is launched DETACHED, so the launcher never sees
# its exit code; the capture itself knows when it refused (wrong account, nothing clicked), so it
# leaves this marker in the rotator root for the launcher (no launch charged, no relaunch for
# REFUSED_COOLDOWN_S) and for `active_conditions` (the out-of-band alert) to read.
CAPTURE_REFUSED_PREFIX = "capture-refused."
# WHY bounded time and not "until the account changes": the profile's signed-in account is only
# observable by opening Chrome, which is the very launch being suppressed. 6 h caps the cost at one
# visible window per slot per 6 h and the delay after the owner fixes the profile at 6 h.
REFUSED_COOLDOWN_S = 6 * 3600


def _refusal_path(root: Path, email: str) -> Path:
    return root / f"{CAPTURE_REFUSED_PREFIX}{email.replace('/', '_')}.json"


def record_capture_refused(root: Path, email: str, actual: Optional[str], now: float) -> None:
    """Called by slot_capture_browser when it refuses to authorize: profile `email` is signed in
    as `actual` (None = could not be confirmed). Holds names and a timestamp, never a token."""
    root.mkdir(parents=True, exist_ok=True)
    state.atomic_write(
        _refusal_path(root, email),
        json.dumps({"ts": int(now), "target": email, "actual": actual}),
    )


def fresh_refusal(root: Path, email: str, now: float) -> Optional[dict]:
    """The refusal marker for `email` if younger than REFUSED_COOLDOWN_S, else None."""
    marker = _read_json(_refusal_path(root, email))
    ts = _epoch(marker.get("ts"))
    return marker if ts is not None and 0 <= now - ts < REFUSED_COOLDOWN_S else None


def clear_capture_refused(root: Path, email: str) -> None:
    _refusal_path(root, email).unlink(missing_ok=True)


def _tick_age(root: Path, now: float) -> float:
    # mtime of the stamp the rotator writes ONLY when a tick runs to completion (rotator.py
    # _stamp_tick_completed, atomic os.replace): a skipped or hung tick never moves it.
    try:
        return now - (root / "tick-completed.ts").stat().st_mtime
    except OSError:
        return float("inf")  # never stamped: a tick that ran just before this would have stamped


_STUCK_FRESH_S = 3600  # mirrors the oauth-login-needed detector gate and rotator.STUCK_MARKER_FRESH_S

# Daemon-written conditions: only `evaluate` observes them, so only it clears their records.
# The first three are observable only while a Claude session runs; tick-stalled also only while
# the tick is ours to judge.
_DAEMON_CONDITIONS = frozenset(
    {"no-rotation-target", "spare-stale", "tick-stalled", "rotation-stuck", "auth-failed", "capture-refused"}
)
_CLAUDE_GATED_CONDITIONS = frozenset({"no-rotation-target", "spare-stale", "tick-stalled"})


def active_conditions(
    root: Path, now: float, claude_running: bool, *, check_tick: bool = True
) -> dict[str, str]:
    """Condition name -> action text for every alarm that holds right now."""
    out: dict[str, str] = {}
    st = _read_json(root / "state.json")
    live, live_exp = _live(st)
    if claude_running:
        # The live account is NOT a rotation target: its slot twin keeps a future expiry
        # (the rotator never refreshes it) long after the real login died, so counting it hid
        # "no spare" until the wall itself (incident 2026-10-03 00:37).
        slots = _dict(st.get("slots"))
        exps = {
            em: _epoch(m.get("expires_at"))
            for em, m in slots.items()
            if isinstance(m, dict) and em != live
        }
        if not any(e is not None and e > now for e in exps.values()):
            out["no-rotation-target"] = _ACTIONS["no-rotation-target"]
        # WHY (TRDD-B78NJU35): a spare whose slot expiry is long past was never refreshed (the 8 h
        # token + ROTATOR_SPARE_STALE_AFTER_H, default 4, = no refresh for 12 h+), i.e. it is dying
        # silently. Without this the first alarm is the wall. Skipped when no-rotation-target
        # already says it, and the live account is excluded by `exps` above.
        stale_s = _spare_stale_after_s()
        if "no-rotation-target" not in out and any(e is not None and e < now - stale_s for e in exps.values()):
            out["spare-stale"] = (
                "a spare account has not been refreshed for hours - "
                "run /janitor-capture-all-logins to re-capture the stale spare account"
            )
        # No "live token expired" condition, on purpose: the only expiry the daemon may read is
        # the live account's slot twin, and that goes stale BY DESIGN, so it would fire ~8 h
        # after every switch while the real login is fine. The wall itself is reported by
        # `auth-failed` below, written by the session's StopFailure hook.
        # check_tick is False while the ai-maestro server owns the rotator tick: its stamp is not ours to judge.
        if check_tick and _tick_age(root, now) > TICK_STALL_S:
            out["tick-stalled"] = _ACTIONS["tick-stalled"]
    # WHY (TRDD-7T4J5T6Z): only a marker the rotator rewrote within the last hour is a live verdict;
    # one left by a recovered or stopped rotator must not alert forever. Mirrors the detector gate
    # in oauth-login-needed.py.
    stuck = _read_json(root / "rotation-stuck.json")
    stuck_seen = _epoch(stuck.get("last_seen_epoch"))
    if stuck.get("kind") and stuck_seen is not None and now - stuck_seen <= _STUCK_FRESH_S:
        # WHY: a login capture cannot help when every account is at its limit; on 2026-10-05 the
        # generic text sent the owner to /janitor-capture-all-logins for hours (TRDD-QHACQPPG).
        out["rotation-stuck"] = stuck_text(stuck.get("kind"))
    marker = _read_json(root / AUTH_FAILED_NAME)
    ts = _epoch(marker.get("ts"))
    # Normally cleared by the next successful Stop (`clear_auth_failed`); these are backstops:
    # age, or the live account / its slot expiry moved (a rotation rewrites them).
    if (
        ts is not None
        and now - ts <= AUTH_FAILED_TTL_S
        and marker.get("live_email") == live
        and marker.get("live_exp") == live_exp
    ):
        out["auth-failed"] = AUTH_FAILED_ACTION
    # WHY not gated on claude_running: a refused capture means a spare cannot be re-logged in, and
    # the owner is the only one who can fix the profile; nothing else reports it (TRDD-0SU2C2IM).
    for path in sorted(root.glob(f"{CAPTURE_REFUSED_PREFIX}*.json")):
        marker = _read_json(path)
        target = marker.get("target")
        if not isinstance(target, str) or fresh_refusal(root, target, now) is None:
            continue
        actual = marker.get("actual")
        out[f"capture-refused:{target}"] = (
            f"profile {target} is signed in as {actual}; sign it in as {target}"
            if isinstance(actual, str)
            else f"profile {target} could not be confirmed as signed in; sign it in as {target}"
        )
    return out


def _episode_parts(cond: str, stuck_kind: str) -> tuple[str, str, str]:
    """(condition, kind, slot) of an active alarm - the three parts of its notification episode.
    A per-slot alarm (`capture-refused:<email>`) carries its slot; `rotation-stuck` carries the
    stuck kind (a new kind is a new episode, the same kind is the same one)."""
    if cond.startswith("capture-refused:"):
        return "capture-refused", "", cond.split(":", 1)[1]
    if cond == "rotation-stuck":
        return cond, stuck_kind, ""
    return cond, "", ""


def notify_new_remediations(
    root: Path,
    now: float,
    *,
    runner: Optional[Callable[[list[str]], None]] = None,
) -> list[str]:
    """Notify the owner ONCE per episode for every fresh record in owner-remediation.json -
    the records this module AND the oauth-login-needed detector write. The daemon is the only
    caller (USER ruling 2026-10-21: one notification per episode, never one per session).
    A record whose last_seen is older than REMEDIATION_FRESH_S is a condition that went away.
    Returns the keys of the records that actually raised a notification."""
    sent: list[str] = []
    for key, rec in sorted(_dict(_read_json(root / OWNER_REMEDIATION_NAME).get("conditions")).items()):
        rec = _dict(rec)
        seen = _epoch(rec.get("last_seen"))
        cond, action = rec.get("condition"), rec.get("action")
        if not isinstance(cond, str) or not isinstance(action, str) or seen is None:
            continue
        if now - seen > REMEDIATION_FRESH_S:
            continue
        outcome = notify.notify_episode(
            condition=cond,
            kind=str(rec.get("kind") or ""),
            slot=str(rec.get("slot") or ""),
            message=action,
            now=now,
            runner=runner,
        )
        if outcome == notify.PUSHED:
            sent.append(key)
    return sent


def notify_session_tick_stalled(
    root: Path,
    now: float,
    *,
    server_owns_tick: bool = False,
    runner: Optional[Callable[[list[str]], None]] = None,
) -> Optional[str]:
    """Session-side tick-stalled notification: a hung or dead daemon cannot raise its own alarm,
    so the heartbeat-side detector calls this. It uses the SAME episode key the daemon's
    evaluation uses (condition `tick-stalled`) in the machine-wide notify-sent store, so N
    sessions plus the daemon produce ONE desktop notification per episode. Prints nothing -
    the owner learns of it, no agent reads it.

    Gated exactly like the daemon's own alarm, or it is a false alarm: no opt-in flag means the
    rotator never ticks here, and `server_owns_tick` (the ai-maestro server owns the tick, so
    its stamp is not ours to judge) switches the check off. Returns the notify outcome, or None
    when nothing was notified. A tick seen fresh is an OBSERVED clear: it ends the episode."""
    if not (root / "opt-in.flag").is_file() or server_owns_tick:
        return None
    if not (root / "tick-completed.ts").exists():
        return None  # never stamped: nothing to compare, nothing observed
    if _tick_age(root, now) <= TICK_STALL_S:
        notify.clear_episode(condition="tick-stalled", now=now)
        return None
    return notify.notify_episode(
        condition="tick-stalled", message=_ACTIONS["tick-stalled"], now=now, runner=runner
    )


def _clear_observed_gone(
    root: Path, now: float, active_parts: set[tuple[str, str]], claude_running: bool, check_tick: bool
) -> None:
    """End the episode of every daemon condition that was OBSERVED not to hold on this pass.
    A condition this pass could not observe (no claude running; tick not ours to judge) is left
    alone: a gap in observation is not a clear."""
    st = _read_json(root / "state.json")
    live, live_exp = _live(st)
    for rec in _dict(_read_json(root / OWNER_REMEDIATION_NAME).get("conditions")).values():
        name, slot = str(_dict(rec).get("condition") or ""), str(_dict(rec).get("slot") or "")
        if name not in _DAEMON_CONDITIONS or (name, slot) in active_parts:
            continue
        if name in _CLAUDE_GATED_CONDITIONS and not claude_running:
            continue
        if name == "tick-stalled" and not check_tick:
            continue
        # WHY (TRDD-1J9B7MWO): a marker that is merely PRESENT but aged past its TTL / cooldown is
        # not an observation of the condition being gone - age is the absence of a look. Only an
        # absent marker (the Stop hook / a successful capture removed it) or, for auth-failed, a
        # live account or expiry that moved ends the episode; otherwise it would re-notify later.
        if name == "auth-failed":
            if (root / AUTH_FAILED_NAME).exists():
                marker = _read_json(root / AUTH_FAILED_NAME)
                # A state.json that cannot be read is not an observation that the live account moved (TRDD-1J9B7MWO).
                if live is None:
                    continue
                if not marker or (marker.get("live_email") == live and marker.get("live_exp") == live_exp):
                    continue
        elif name == "capture-refused":
            if _refusal_path(root, slot).exists():
                continue
        # rotation-stuck keeps its age-based clear on purpose: the rotator deletes the marker on every
        # successful switch, but a recovery that needed no switch can leave an aged maxed marker behind
        # (rotator.py _mark_stuck/_clear_stuck), so an aged marker may mean recovered; waiting for an
        # observed clear would silence the next weekly all-maxed episode (TRDD-1J9B7MWO).
        else:
            clear_owner_remediations(
                root, name, now, keep_slots=frozenset(s for n, s in active_parts if n == name)
            )
            continue
        clear_owner_remediations(root, name, now, observed_slots=frozenset({slot}))


def evaluate(
    root: Path,
    *,
    now: float,
    claude_running: bool,
    runner: Optional[Callable[[list[str]], None]] = None,
    check_tick: bool = True,
) -> list[str]:
    """Persist active alarms, record each as an owner remediation, end the episode of every
    daemon condition observed gone, and notify the owner once per new episode
    (`notify_new_remediations`). Nothing here reaches an agent."""
    active = active_conditions(root, now, claude_running, check_tick=check_tick)
    stuck_kind = str(_read_json(root / "rotation-stuck.json").get("kind") or "")
    active_parts: set[tuple[str, str]] = set()
    for cond, action in active.items():
        name, kind, slot = _episode_parts(cond, stuck_kind)
        active_parts.add((name, slot))
        record_owner_remediation(root, name, action, now, kind=kind, slot=slot)
    _clear_observed_gone(root, now, active_parts, claude_running, check_tick)
    prune_stale_remediations(root, now)
    path = root / ALERT_NAME
    prior = _dict(_read_json(path).get("alerts"))
    alerts = {
        c: {"first_seen": _dict(prior.get(c)).get("first_seen", int(now)), "action": a}
        for c, a in active.items()
    }
    if alerts:
        state.atomic_write(path, json.dumps({"alerts": alerts}))
    else:
        path.unlink(missing_ok=True)
    notify_new_remediations(root, now, runner=runner)
    return list(active)


