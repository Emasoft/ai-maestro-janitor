"""Out-of-band rotator alarm (TRDD-3OS6AXV3 R4) — the DAEMON's last-resort channel.

Incident 2026-10-03 00:37: the only live login expired with no warning, and every model turn
afterwards just printed "Login expired", so a heartbeat drift line could never be read. The
daemon (alive regardless of any login) therefore raises a desktop notification, and ALSO writes
`rotator-alert.json` so the heartbeat can show the same fact once a turn can run.

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
DEBOUNCE_S = 3600  # re-notify an unchanged condition at most hourly
TICK_STALL_S = 600  # no completed rotator tick for this long while claude runs

_ACTIONS = {
    "no-rotation-target": "no spare account to rotate to - run /janitor-capture-all-logins",
    "tick-stalled": "the account rotator has stopped ticking - run /janitor-doctor",
    "rotation-stuck": "account rotation is stuck - run /janitor-capture-all-logins",
}


REPEAT_S = 86400  # after the 2nd notification, repeat an unchanged condition at most daily
AUTH_FAILED_NAME = "auth-failed.json"  # written by the StopFailure hook on a 401
AUTH_FAILED_TTL_S = 6 * 3600  # the marker expires on its own after 6 h
AUTH_FAILED_ACTION = "the login was rejected (Login expired) - run /login"
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


def _tick_age(root: Path, now: float) -> float:
    # mtime of the stamp the rotator writes ONLY when a tick runs to completion (rotator.py
    # _stamp_tick_completed, atomic os.replace): a skipped or hung tick never moves it.
    try:
        return now - (root / "tick-completed.ts").stat().st_mtime
    except OSError:
        return float("inf")  # never stamped: a tick that ran just before this would have stamped


def active_conditions(root: Path, now: float, claude_running: bool) -> dict[str, str]:
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
        if _tick_age(root, now) > TICK_STALL_S:
            out["tick-stalled"] = _ACTIONS["tick-stalled"]
    if (root / "rotation-stuck.json").is_file():
        out["rotation-stuck"] = _ACTIONS["rotation-stuck"]
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
    return out



def _due(prior: dict, now: float) -> bool:
    # Backoff: 2nd notification after DEBOUNCE_S (1 h), then once per REPEAT_S while it holds.
    last, n = prior.get("last_notified"), prior.get("notified")
    if not isinstance(last, (int, float)) or not isinstance(n, int):
        return True
    return now - last >= (DEBOUNCE_S if n <= 1 else REPEAT_S)


def evaluate(
    root: Path,
    *,
    now: float,
    claude_running: bool,
    runner: Optional[Callable[[list[str]], None]] = None,
) -> list[str]:
    """Keep `rotator-alert.json` equal to the live set of conditions (every evaluation), delete
    it when none hold, and notify with a backoff: first occurrence, again after 1 h, then at
    most daily while it holds; a NEW condition notifies at once. A condition that was active
    within the last DEBOUNCE_S is not new when it reappears: it resumes its old backoff (sessions
    sharing one login flip `auth-failed` on and off, and each flip must not be a banner). The
    recent-state lives in its own file because the alert file is deleted when nothing holds.
    Returns the active condition names."""
    active = active_conditions(root, now, claude_running)
    path = root / ALERT_NAME
    recent_path = root / "rotator-alert-recent.json"
    prior = _dict(_read_json(path).get("alerts"))
    recent = {
        c: _dict(v)
        for c, v in _read_json(recent_path).items()
        if isinstance(v, dict) and now - (_epoch(v.get("t")) or 0) <= DEBOUNCE_S
    }
    alerts: dict[str, dict] = {}
    new = {c for c in active if c not in prior and c not in recent}
    for cond, action in active.items():
        p = _dict(prior.get(cond)) or _dict(recent.get(cond))
        last, n = p.get("last_notified"), p.get("notified")
        if cond in new or _due(p, now):
            if notify.enabled():
                notify._deliver(f"[janitor] {action}", runner=runner)
            last = now
            n = 1 if cond in new or not isinstance(n, int) else n + 1
        alerts[cond] = {
            "first_seen": p.get("first_seen", int(now)),
            "last_notified": int(last) if isinstance(last, (int, float)) else int(now),
            "notified": n if isinstance(n, int) else 1,
            "action": action,
        }
    recent.update({c: {**a, "t": int(now)} for c, a in alerts.items()})
    if recent:
        state.atomic_write(recent_path, json.dumps(recent))
    else:
        recent_path.unlink(missing_ok=True)
    if alerts:
        state.atomic_write(path, json.dumps({"alerts": alerts}))
    else:
        path.unlink(missing_ok=True)
    return list(active)


def drift_line(root: Path, now: float) -> Optional[str]:
    """One drift line for the heartbeat, or None. Merges the daemon's alert file with a
    session-side watchdog for `tick-stalled`: a fully hung daemon writes no file, so any live
    session (this runs only inside one) checks the last-completed-tick stamp itself, one stat."""
    alerts = _dict(_read_json(root / ALERT_NAME).get("alerts"))
    actions = {str(a.get("action", c)) for c, a in alerts.items() if isinstance(a, dict)}
    if (root / "tick-completed.ts").exists() and _tick_age(root, now) > TICK_STALL_S:
        actions.add(_ACTIONS["tick-stalled"])
    if not actions:
        return None
    return state.sanitize_for_drift_line("rotator alert: " + "; ".join(sorted(actions)))
