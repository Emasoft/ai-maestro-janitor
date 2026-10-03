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
LIVE_EXPIRED_GRACE_S = 300  # live token past expiry AND not refreshed for this long
TICK_STALL_S = 600  # no completed rotator tick for this long while claude runs

_ACTIONS = {
    "no-rotation-target": "no spare account to rotate to - run /janitor-capture-all-logins",
    "live-token-expired": "the live login has expired and was not refreshed - run /login",
    "tick-stalled": "the account rotator has stopped ticking - run /janitor-doctor",
    "rotation-stuck": "account rotation is stuck - run /janitor-capture-all-logins",
}


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
    if claude_running:
        st = _read_json(root / "state.json")
        slots = _dict(st.get("slots"))
        exps = {em: _epoch(m.get("expires_at")) for em, m in slots.items() if isinstance(m, dict)}
        if not any(e is not None and e > now for e in exps.values()):
            out["no-rotation-target"] = _ACTIONS["no-rotation-target"]
        # No "live token expired" condition, on purpose: the only expiry the daemon may read is
        # the live account's slot twin, and that goes stale BY DESIGN (the rotator never
        # refreshes the live twin), so it would fire ~8 h after every switch while the real
        # login is fine. The -livebak mirror expiry would be right but needs a keychain read
        # (R2 records no non-secret expiry file), which the daemon must not do.
        if _tick_age(root, now) > TICK_STALL_S:
            out["tick-stalled"] = _ACTIONS["tick-stalled"]
    if (root / "rotation-stuck.json").is_file():
        out["rotation-stuck"] = _ACTIONS["rotation-stuck"]
    return out



def _due(prior: dict, now: float) -> bool:
    # Backoff: 2nd notification after DEBOUNCE_S (1 h), then once per 24 h while it holds.
    last, n = prior.get("last_notified"), prior.get("notified")
    if not isinstance(last, (int, float)) or not isinstance(n, int):
        return True
    return now - last >= (DEBOUNCE_S if n <= 1 else 86400)


def evaluate(
    root: Path,
    *,
    now: float,
    claude_running: bool,
    runner: Optional[Callable[[list[str]], None]] = None,
) -> list[str]:
    """Keep `rotator-alert.json` equal to the live set of conditions (every evaluation), delete
    it when none hold, and notify with a backoff: first occurrence, again after 1 h, then at
    most daily while it holds; any change of the SET of conditions notifies at once. Returns the
    active condition names."""
    active = active_conditions(root, now, claude_running)
    path = root / ALERT_NAME
    prior = _dict(_read_json(path).get("alerts"))
    set_changed = set(prior) != set(active)
    alerts: dict[str, dict] = {}
    for cond, action in active.items():
        p = _dict(prior.get(cond))
        last, n = p.get("last_notified"), p.get("notified")
        if set_changed or _due(p, now):
            if notify.enabled():
                notify._deliver(f"[janitor] {action}", runner=runner)
            last = now
            n = 1 if set_changed or not isinstance(n, int) else n + 1
        alerts[cond] = {
            "first_seen": p.get("first_seen", int(now)),
            "last_notified": int(last) if isinstance(last, (int, float)) else int(now),
            "notified": n if isinstance(n, int) else 1,
            "action": action,
        }
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
