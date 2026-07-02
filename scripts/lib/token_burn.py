"""Pure window burn-rate decision layer (TRDD-OY0W6LX5).

The `window-burn-rate` detector and `/janitor-token-report` both turn a read-only
`/api/oauth/usage` payload (`five_hour`/`seven_day` = `{utilization, resets_at}`) into
the "is this account burning FASTER than its even-pace budget?" verdict. This module is
that shared, PURE decision logic — no I/O, no network, no rotator import — so it is
unit-testable with hand-built usage dicts and the two consumers can never disagree on
what a "burn trip" is.

It composes the pure ratio/projection primitives in `token_baseline` (burn_ratio,
elapsed_fraction_from_reset, projected_exhaustion_epoch) and reuses `token_history.parse_ts`
to turn the payload's ISO `resets_at` into an epoch — so there is ONE definition of a
window's elapsed fraction and ONE definition of a timestamp across the whole feature.
"""

from __future__ import annotations

from datetime import datetime

import token_baseline as tb
import token_history as th

# The two fixed-reset subscription windows, matching token_report.py / token_history.py.
_5H = 5 * 3600
_7D = 7 * 86400

# (report label, payload key, window seconds) for each window we evaluate.
_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("5h", "five_hour", _5H),
    ("7d", "seven_day", _7D),
)


def account_prefix(email: str | None) -> str:
    """The privacy-safe account label for a drift line: the local part of the email only
    (never the full address in a surfaced line). None / empty → "live" (the live account
    whose email the state index has not recorded)."""
    if not email:
        return "live"
    return email.split("@", 1)[0].strip() or "live"


def windows_from_usage(usage: dict, now: int) -> list[dict]:
    """Parse a raw `/api/oauth/usage` payload into per-window burn inputs for `now`.

    Returns one dict `{label, util_pct, resets_at_epoch, window_s, elapsed_fraction,
    burn_ratio, exhaustion_epoch}` per COMPUTABLE window (both `utilization` present AND a
    parseable `resets_at`). A window with a missing/non-numeric utilization or a malformed
    `resets_at` (unparseable ISO) is SKIPPED — a junk sample must never crash or alarm.
    Pure: `now` is a parameter, timestamps come from `token_history.parse_ts`."""
    out: list[dict] = []
    if not isinstance(usage, dict):
        return out
    for wlabel, key, window_s in _WINDOWS:
        w = usage.get(key)
        if not isinstance(w, dict):
            continue
        util = w.get("utilization")
        if not isinstance(util, (int, float)) or isinstance(util, bool):
            continue
        raw_reset = w.get("resets_at")
        resets_at = th.parse_ts(raw_reset) if isinstance(raw_reset, str) else None
        if resets_at is None:  # malformed / absent reset boundary — skip this window
            continue
        util_pct = float(util)
        frac = tb.elapsed_fraction_from_reset(resets_at, window_s, now)
        out.append(
            {
                "label": wlabel,
                "util_pct": util_pct,
                "resets_at_epoch": resets_at,
                "window_s": window_s,
                "elapsed_fraction": frac,
                "burn_ratio": tb.burn_ratio(util_pct, frac),
                "exhaustion_epoch": tb.projected_exhaustion_epoch(resets_at, window_s, util_pct, now),
            }
        )
    return out


def format_burn_line(label: str, window: dict) -> str:
    """Render ONE tripped window as the base drift line (no top-consumer clause — the
    caller appends that only when fleet attribution is available)."""
    util = window["util_pct"]
    frac = window["elapsed_fraction"] or 0.0
    ratio = window["burn_ratio"] or 0.0
    base = f"[window-burn-rate] ⚠ {label} {window['label']} window {util:.0f}% at {frac * 100:.0f}% elapsed — {ratio:.1f}x linear pace"
    exhaustion = window["exhaustion_epoch"]
    resets_at = window["resets_at_epoch"]
    if isinstance(exhaustion, int) and exhaustion < resets_at:
        local = datetime.fromtimestamp(exhaustion).strftime("%m-%d %H:%M")
        hours = (resets_at - exhaustion) / 3600.0
        return f"{base}; projected exhaustion {local} ({hours:.0f}h before reset)."
    return f"{base}."


def evaluate_trips(accounts_usage: list[dict], now: int, ratio: float, min_util: float) -> list[dict]:
    """The pure burn verdict: one trip per (account, window) whose burn ratio ≥ `ratio`.

    `accounts_usage` is `[{"label": <prefix>, "usage": <raw /api/oauth/usage payload>}]`.
    A window is a trip iff its utilization ≥ `min_util` (the floor so a fresh, barely-used
    window never alarms) AND its `burn_ratio` is computable AND ≥ `ratio`. Each trip carries
    a stable `key` (`<label>-<window>`, for per-day dedupe) and the rendered `line`."""
    trips: list[dict] = []
    for acct in accounts_usage:
        if not isinstance(acct, dict):
            continue
        label = acct.get("label") or "live"
        usage = acct.get("usage")
        if not isinstance(usage, dict):
            continue
        for w in windows_from_usage(usage, now):
            if w["util_pct"] < min_util:
                continue
            r = w["burn_ratio"]
            if r is None or r < ratio:
                continue
            trips.append({"key": f"{label}-{w['label']}", "line": format_burn_line(label, w)})
    return trips


def evaluate(accounts_usage: list[dict], now: int, ratio: float, min_util: float) -> list[str]:
    """The detector's pure decision helper: the rendered burn drift lines (no top-consumer
    clause). Thin wrapper over `evaluate_trips` for callers that only need the text."""
    return [t["line"] for t in evaluate_trips(accounts_usage, now, ratio, min_util)]
