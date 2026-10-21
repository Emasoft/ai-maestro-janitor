"""Out-of-band rotator alarm (TRDD-3OS6AXV3 R4) — the DAEMON's last-resort channel.

Incident 2026-10-03 00:37: the only live login expired with no warning, and every model turn
afterwards just printed "Login expired". The daemon (alive regardless of any login) therefore
raises ONE desktop notification per condition episode (USER ruling 2026-10-21: the user is
told, no agent is: rotator and account issues never reach agent context, so there is no
heartbeat drift line and no agent-visible channel). Every active alarm is recorded in
`rotator-alert.json` (diagnostics) and `owner-remediation.json`; the daemon notifies each new
remediation record once through `notify.notify_episode`.

Reads only state.json / rotation-stuck.json / tick-completed.ts — never a credential. The text
names the single action and never a token or an e-mail.
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


REMEDIATION_FRESH_S = 1800  # an owner-remediation record not re-seen for this long is a condition that went away
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
    episode (`notify.notify_episode`). The daemon notifies each fresh record once."""
    path = root / OWNER_REMEDIATION_NAME
    records = _dict(_read_json(path).get("conditions"))
    key = ":".join(p for p in (condition, kind, slot) if p)
    records[key] = {"condition": condition, "kind": kind, "slot": slot, "action": action, "last_seen": int(now)}
    # Bounded file: a record not re-seen for a week is a condition long gone.
    records = {
        k: v for k, v in records.items()
        if isinstance(v, dict) and now - (_epoch(v.get("last_seen")) or 0) <= 7 * 86400
    }
    root.mkdir(parents=True, exist_ok=True)
    state.atomic_write(path, json.dumps({"conditions": records}, sort_keys=True))



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
    runner: Optional[Callable[[list[str]], None]] = None,
) -> Optional[str]:
    """Session-side tick-stalled notification: a hung or dead daemon cannot raise its own alarm,
    so the heartbeat-side detector calls this. It uses the SAME episode key the daemon's
    evaluation uses (condition `tick-stalled`) in the machine-wide notify-sent store, so N
    sessions plus the daemon produce ONE desktop notification per episode. Prints nothing -
    the owner learns of it, no agent reads it. Returns the notify outcome, or None when the
    rotator has ticked recently (or never ticked: no stamp, nothing to compare)."""
    if not (root / "tick-completed.ts").exists() or _tick_age(root, now) <= TICK_STALL_S:
        return None
    return notify.notify_episode(
        condition="tick-stalled", message=_ACTIONS["tick-stalled"], now=now, runner=runner
    )



def evaluate(
    root: Path,
    *,
    now: float,
    claude_running: bool,
    runner: Optional[Callable[[list[str]], None]] = None,
    check_tick: bool = True,
) -> list[str]:
    """Persist active alarms, record each as an owner remediation, and notify the owner once
    per new episode (`notify_new_remediations`). Nothing here reaches an agent."""
    active = active_conditions(root, now, claude_running, check_tick=check_tick)
    stuck_kind = str(_read_json(root / "rotation-stuck.json").get("kind") or "")
    for cond, action in active.items():
        name, kind, slot = _episode_parts(cond, stuck_kind)
        record_owner_remediation(root, name, action, now, kind=kind, slot=slot)
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


