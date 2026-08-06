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

# `limits[].group` -> (base label, window seconds). The payload's own grouping is what
# says how long a scoped window is; an unknown group is SKIPPED rather than guessed,
# because `elapsed_fraction` divides by this number and a wrong length silently scales
# every pace and projection derived from it.
_LIMIT_GROUPS: dict[str, tuple[str, int]] = {
    "session": ("5h", _5H),
    "weekly": ("7d", _7D),
}

# Model display names come from the API and end up in a drift line, so they are reduced
# to a conservative charset before ever being formatted (a drift line is parsed
# downstream, and `[`/`]` are its own delimiters).
_MODEL_NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-")


def _model_name(scope: object) -> str:
    """The sanitized `scope.model.display_name` of a `limits[]` entry, or "" when the entry
    is not model-scoped. "" is the discriminator: the `session` / `weekly_all` entries carry
    `scope: null` and merely restate `five_hour` / `seven_day`, so only the scoped ones are
    net-new information."""
    if not isinstance(scope, dict):
        return ""
    model = scope.get("model")
    if not isinstance(model, dict):
        return ""
    raw = model.get("display_name")
    if not isinstance(raw, str):
        return ""
    return "".join(c for c in raw if c in _MODEL_NAME_OK).strip()[:32]


def model_windows_from_usage(usage: dict, now: int) -> list[dict]:
    """Per-window burn inputs for every MODEL-SCOPED limit in the payload's `limits[]`.

    Anthropic moved model-scoped limits OUT of the flat `seven_day_opus` / `seven_day_sonnet`
    fields — verified `null` on every live payload 2026-08-01 — and into a generic `limits[]`
    array whose scoped entries carry `scope.model.display_name`. A model with its own window
    (Fable 5 today) is therefore invisible to any reader that only looks at `five_hour` /
    `seven_day`: it can sit at 90% of its OWN weekly budget while the account's `seven_day`
    reads comfortable. Reading the array rather than a hardcoded model list is what makes a
    newly-scoped model show up on its own.

    Same dict shape as `windows_from_usage` (so both feed one evaluator), labeled
    `<base>/<model>` e.g. `7d/Fable`, plus the API's own `severity` and `is_active` verdicts.
    Pure."""
    out: list[dict] = []
    if not isinstance(usage, dict):
        return out
    limits = usage.get("limits")
    if not isinstance(limits, list):
        return out
    for entry in limits:
        if not isinstance(entry, dict):
            continue
        model = _model_name(entry.get("scope"))
        if not model:
            continue
        group = _LIMIT_GROUPS.get(str(entry.get("group") or ""))
        if group is None:
            continue
        base, window_s = group
        pct = entry.get("percent")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        raw_reset = entry.get("resets_at")
        resets_at = th.parse_ts(raw_reset) if isinstance(raw_reset, str) else None
        if resets_at is None:
            continue
        util_pct = float(pct)
        frac = tb.elapsed_fraction_from_reset(resets_at, window_s, now)
        out.append(
            {
                "label": f"{base}/{model}",
                "util_pct": util_pct,
                "resets_at_epoch": resets_at,
                "window_s": window_s,
                "elapsed_fraction": frac,
                "burn_ratio": tb.burn_ratio(util_pct, frac),
                "exhaustion_epoch": tb.projected_exhaustion_epoch(resets_at, window_s, util_pct, now),
                "severity": entry.get("severity"),
                "is_active": entry.get("is_active"),
            }
        )
    return out


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


def session_is_open(usage: dict, now: int) -> bool | None:
    """Does this account have an OPEN 5h SESSION window right now?

    `True` (a `five_hour` bucket whose `resets_at` is still in the future), `False` (a
    `five_hour` bucket with a null / unparseable / already-past `resets_at` — the API's
    shape for "no session window is running", i.e. the account is IDLE), or `None` when
    the payload does not say (no `five_hour` key at all).

    Load-bearing, because `burn_ratio` and `projected_exhaustion_epoch` are derived from a
    window AVERAGE: extrapolating them forward asserts the account KEEPS SPENDING. An idle
    ALTERNATE (no 5h window, 7d still at 94% from earlier use) consumes nothing, so
    "1.6x linear pace; projected exhaustion in 6h" is simply false — it describes a future
    that cannot happen. Measured on a real payload 2026-08-01: `five_hour = {utilization:
    0.0, resets_at: null}` while `seven_day = 94%`, and that account tripped every fire.

    A definite `False` is the ONLY value that suppresses a trip; `None` fails toward the
    alarm, so a payload-shape change can never silently mute a genuine burn. This cannot
    hide a real one either: a window that is actually burning has, by construction, an open
    session — the request that spends the budget is what opens it."""
    if not isinstance(usage, dict):
        return None
    w = usage.get("five_hour")
    if not isinstance(w, dict):
        return None
    raw_reset = w.get("resets_at")
    resets_at = th.parse_ts(raw_reset) if isinstance(raw_reset, str) else None
    if resets_at is None:
        return False
    return resets_at > now


def window_starts(accounts_usage: list[dict], now: int) -> tuple[int | None, int | None]:
    """The LIVE subscription windows' START epochs `(w5_lo, w7_lo)` — `resets_at − window_s`.

    This is what makes attribution WINDOW-ALIGNED (TRDD-0NRVNDSZ): the user's meter bills a
    FIXED window ending at `resets_at`, so its start is `resets_at − window_s` — NOT the
    trailing `now − window_s`. Walks `accounts_usage` (the `rotator_usage.accounts_usage()`
    shape) preferring the account labeled "live" (its windows are the ones the meter shows),
    then the rest in order; the first parseable window per label wins. Either element is
    None when no account exposes that window (callers then fall back to trailing). Pure."""
    w5_lo: int | None = None
    w7_lo: int | None = None
    ordered = sorted(
        (a for a in accounts_usage if isinstance(a, dict)),
        key=lambda a: a.get("label") != "live",  # live first, stable otherwise
    )
    for acct in ordered:
        usage = acct.get("usage")
        if not isinstance(usage, dict):
            continue
        for w in windows_from_usage(usage, now):
            start = w["resets_at_epoch"] - w["window_s"]
            if w["label"] == "5h" and w5_lo is None:
                w5_lo = start
            elif w["label"] == "7d" and w7_lo is None:
                w7_lo = start
        if w5_lo is not None and w7_lo is not None:
            break
    return (w5_lo, w7_lo)


def format_burn_line(label: str, window: dict, *, live: bool | None = None) -> str:
    """Render ONE tripped window as the base drift line (no top-consumer clause — the
    caller appends that only when fleet attribution is available).

    `live` names WHICH account the line is about: the credential Claude Code is signed in
    as (`True` → "(live)") or a rotator alternate (`False` → "(alternate)"); `None` omits
    the marker. An email prefix alone is NOT enough — a reader who sees a burn line inside
    their own session reasonably assumes it describes THEIR window, and on 2026-08-01 that
    mis-read cost a full debugging session across two agents: the live account was at
    5h 5% / 7d 36% (matching the status line) while the alarming 94% belonged to a
    different, idle account. The line must say whose window it is."""
    util = window["util_pct"]
    who = "" if live is None else (" (live)" if live else " (alternate)")
    frac = window["elapsed_fraction"] or 0.0
    ratio = window["burn_ratio"] or 0.0
    base = f"[window-burn-rate] ⚠ {label}{who} {window['label']} window {util:.0f}% at {frac * 100:.0f}% elapsed — {ratio:.1f}x linear pace"
    exhaustion = window["exhaustion_epoch"]
    resets_at = window["resets_at_epoch"]
    if isinstance(exhaustion, int) and exhaustion < resets_at:
        local = datetime.fromtimestamp(exhaustion).strftime("%m-%d %H:%M")
        hours = (resets_at - exhaustion) / 3600.0
        return f"{base}; projected exhaustion {local} ({hours:.0f}h before reset)."
    return f"{base}."


def evaluate_trips(accounts_usage: list[dict], now: int, ratio: float, min_util: float) -> list[dict]:
    """The pure burn verdict: one trip per (account, window) whose burn ratio ≥ `ratio`.

    `accounts_usage` is `[{"label": <prefix>, "usage": <payload>, "is_live": <bool|None>}]`.
    A window is a trip iff the account has NOT been proven idle (see `session_is_open`) AND
    its utilization ≥ `min_util` (the floor so a fresh, barely-used window never alarms) AND
    its `burn_ratio` is computable AND ≥ `ratio`.

    Each trip carries the rendered `line` and a stable `key` — `<label>-<window>-<reset
    epoch>`. The reset epoch makes the key identify ONE WINDOW INSTANCE, so the caller's
    dedupe re-arms exactly when the window resets rather than on a calendar boundary: a 7d
    window keyed per DAY re-alarms seven times about the same unchanged window, which is
    how a single 94% reading became a recurring alarm."""
    trips: list[dict] = []
    for acct in accounts_usage:
        if not isinstance(acct, dict):
            continue
        label = acct.get("label") or "live"
        usage = acct.get("usage")
        if not isinstance(usage, dict):
            continue
        # An idle account has no burn RATE to be above pace — only a stock level. Reporting
        # a projection for it is a claim about a future it is not moving toward.
        if session_is_open(usage, now) is False:
            continue
        live = acct.get("is_live")
        live = live if isinstance(live, bool) else None
        # Model-scoped windows are evaluated on the SAME terms as the account-wide ones —
        # a model with its own budget (Fable 5 today) can exhaust while `seven_day` still
        # reads comfortable, and that is exactly the early rate-limit this detector exists
        # to catch.
        for w in windows_from_usage(usage, now) + model_windows_from_usage(usage, now):
            if w["util_pct"] < min_util:
                continue
            r = w["burn_ratio"]
            if r is None or r < ratio:
                continue
            trips.append(
                {
                    "key": f"{label}-{w['label']}-{w['resets_at_epoch']}",
                    "line": format_burn_line(label, w, live=live),
                }
            )
    return trips


def evaluate(accounts_usage: list[dict], now: int, ratio: float, min_util: float) -> list[str]:
    """The detector's pure decision helper: the rendered burn drift lines (no top-consumer
    clause). Thin wrapper over `evaluate_trips` for callers that only need the text."""
    return [t["line"] for t in evaluate_trips(accounts_usage, now, ratio, min_util)]


def model_fallback_verdict(
    usage: dict, now: int, *, scoped_high: float, account_headroom: float
) -> dict | None:
    """The MODEL to stop using because its own window is spent while the ACCOUNT is fine.

    PURE. Returns `{model, scoped_label, scoped_util, account_max_util, resets_at_epoch}`
    for the most-exhausted qualifying model-scoped window, or None when no fallback is
    warranted. The three conditions, and why each is load-bearing (TRDD-QE390SJA,
    janitor#222):

      * a model-scoped window at/above `scoped_high` — the thing that actually stops work.
      * EVERY account-wide window (5h, 7d) at or below `account_headroom` — the gate that
        makes "switch model" the right remedy instead of "rotate or wait". Firing on
        ACCOUNT pressure would switch models when the account itself is the constraint,
        which is the mirror of the mistake that evicted the fleet's healthiest account.
      * at least one account-wide window COMPUTABLE — headroom must be PROVEN, never
        assumed. An unreadable payload yields None (do nothing), because acting on
        unproven headroom is how "could not measure" silently becomes "measured fine".

    Measured motivation (2026-08-06): the live account sat at 5h=42% / 7d=60% with the
    Fable scoped window at ~98%. The remedy was `/model opus`; instead the account was
    rotated away from and then disqualified as a return target for ~123h."""
    if not isinstance(usage, dict):
        return None
    account = [w for w in windows_from_usage(usage, now) if isinstance(w.get("util_pct"), (int, float))]
    if not account:
        return None  # headroom unproven → never act
    account_max = max(float(w["util_pct"]) for w in account)
    if account_max > account_headroom:
        return None  # the ACCOUNT is the constraint — rotating/waiting is the remedy
    scoped = [w for w in model_windows_from_usage(usage, now) if float(w["util_pct"]) >= scoped_high]
    if not scoped:
        return None
    worst = max(scoped, key=lambda w: float(w["util_pct"]))
    label = str(worst["label"])
    return {
        "model": label.split("/", 1)[1] if "/" in label else label,
        "scoped_label": label,
        "scoped_util": float(worst["util_pct"]),
        "account_max_util": account_max,
        "resets_at_epoch": worst.get("resets_at_epoch"),
    }


def format_model_fallback_line(verdict: dict, target: str) -> str:
    """The one drift line a fallback emits. Names BOTH numbers, because the whole point is
    that they disagree — a reader who sees only "98%" assumes the account is exhausted."""
    return (
        f"[model-fallback] {verdict['scoped_label']} window at {verdict['scoped_util']:.0f}% "
        f"while the account's worst window is only {verdict['account_max_util']:.0f}% — "
        f"switching to {target} (the account has headroom; rotating would be the wrong remedy)"
    )
