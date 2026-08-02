"""Burn-rate-aware proactive rotation — the PURE decision layer (TRDD-FQXBURNR).

The 2026-07-17 incident (parent TRDD-H7NVKSAX): the live account read "5h=61–63% — within
limits" every minute right up to a hard 429, and the rotated-to account then burned 6%/min.
A utilization THRESHOLD cannot see either failure mode:

  (a) FAST BURN — the wall arrives minutes after a below-threshold reading;
  (b) an EFFECTIVE CAP below 100% — real 429s land while /usage still reads ~60%.

This module answers both with zero new telemetry, from the samples `cmd_auto` already sees
on its 60 s beat:

  * a bounded per-(account, window) ring of `(ts, util%)` samples → a recent SLOPE →
    projected minutes-to-wall; rotate when the live account's wall is inside the horizon
    even though the threshold has not tripped;
  * on a DEBOUNCED live 429 (the reactive trigger — a real limit, not an endpoint
    throttle), the last recently-sampled util% becomes an observed EFFECTIVE-CAP sample;
    the near-limit bar for that account drops to `min(configured, learned_cap − margin)`;
  * alternate SELECTION consults the same rings so rotation never lands on an account
    that will wall within the horizon itself (composing with drain-first, which is
    unchanged — this only FILTERS the candidate list, never re-orders it).

Everything here is PURE — no I/O, no clocks, no keychain (R16 untouched: the inputs are
the read-only usage numbers the caller already holds). FAIL-OPEN is the load-bearing
contract: with no samples, too few samples, a flat/declining slope, stale samples, or no
learned caps, every function returns its neutral value and `cmd_auto` behaves EXACTLY as
the pure threshold did — byte-for-byte, which the tests pin.

State lives inside the rotator's existing `state.json` under two new keys
(`usage_samples`, `learned_caps`), both bounded here (ring caps), so the no-unbounded-
append invariant (TRDD-7IUTRX29 S4) holds by construction.
"""

from __future__ import annotations

import os

# Ring bounds. 12 samples at the 60 s tick ≈ a 12-minute slope window — long enough to
# smooth one noisy reading, short enough that the 6%/min incident shape trips within
# 2–3 samples. Caps keep state.json bounded per (account, window).
SAMPLE_KEEP = int(os.environ.get("ROTATOR_BURN_SAMPLE_KEEP", "12"))
CAP_KEEP = int(os.environ.get("ROTATOR_BURN_CAP_KEEP", "5"))

# A sample older than this is DEAD for slope purposes: a 5h window resets underneath the
# ring, and a slope computed across a reset points down (harmless, fail-open) or bridges
# unrelated regimes (misleading). 30 min also bounds how long a learned-cap source
# reading may predate its 429.
SAMPLE_MAX_AGE_S = int(os.environ.get("ROTATOR_BURN_SAMPLE_MAX_AGE_S", "1800"))

# Rotate when the live account's projected wall is inside this horizon (minutes).
ROTATE_HORIZON_MIN = float(os.environ.get("ROTATOR_ROTATE_HORIZON_MIN", "15"))

# The learned cap is applied minus this safety margin (percentage points).
LEARNED_CAP_MARGIN = float(os.environ.get("ROTATOR_LEARNED_CAP_MARGIN", "5"))

# The effective threshold never drops below this floor — a corrupted/absurd cap sample
# (say 12%) must not turn every tick into a rotation. Below ~50% utilization a "cap" is
# far likelier bad data than a real entitlement edge.
EFFECTIVE_FLOOR_PCT = float(os.environ.get("ROTATOR_BURN_EFFECTIVE_FLOOR_PCT", "50"))


def record_sample(samples: list, ts: float, util: float | None, keep: int = SAMPLE_KEEP) -> list:
    """Append one `(ts, util%)` reading to a ring, returning the new ring (bounded, sorted
    arrival order). `None` util (unknown) records nothing — unknown never becomes data.
    Non-monotonic timestamps (clock step, replayed state) drop the OLDER prefix rather
    than poison the slope."""
    if util is None:
        return list(samples)
    out = [s for s in samples if isinstance(s, (list, tuple)) and len(s) == 2 and s[0] < ts]
    out.append([float(ts), float(util)])
    return out[-max(1, keep):]


def slope_pct_per_min(samples: list, now: float, max_age_s: int = SAMPLE_MAX_AGE_S) -> float | None:
    """Least-squares slope of the FRESH samples, in %/minute. None (⇒ fail-open) when
    fewer than 3 fresh samples, when they span under 2 minutes (two ticks of noise are
    not a trend), or when the slope is flat/declining (a window reset or idle account —
    there is no wall to project)."""
    fresh = [(t, u) for t, u in samples if now - t <= max_age_s]
    if len(fresh) < 3:
        return None
    t0 = fresh[0][0]
    xs = [(t - t0) / 60.0 for t, _ in fresh]
    ys = [u for _, u in fresh]
    if xs[-1] - xs[0] < 2.0:
        return None
    n = float(len(fresh))
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return slope if slope > 0 else None


def minutes_to_wall(
    samples: list, now: float, cap_pct: float = 100.0, max_age_s: int = SAMPLE_MAX_AGE_S
) -> float | None:
    """Projected minutes until the account's util reaches `cap_pct` at the RECENT slope.
    None (fail-open) whenever the slope is (see `slope_pct_per_min`) unprojectable or the
    latest fresh sample is already unknown. Already at/over the cap projects 0."""
    fresh = [(t, u) for t, u in samples if now - t <= max_age_s]
    if not fresh:
        return None
    last_util = fresh[-1][1]
    if last_util >= cap_pct:
        return 0.0
    slope = slope_pct_per_min(samples, now, max_age_s)
    if slope is None:
        return None
    return (cap_pct - last_util) / slope


def record_cap_sample(caps: list, samples: list, now: float, keep: int = CAP_KEEP) -> list:
    """On a CONFIRMED (debounced) live 429, record the last recently-sampled util% as an
    observed effective-cap sample. The 429 response itself carries no util — the ring's
    freshest reading is the best available 'where the wall actually was'. No fresh
    sample ⇒ nothing recorded (never learn from stale data)."""
    fresh = [(t, u) for t, u in samples if now - t <= SAMPLE_MAX_AGE_S]
    if not fresh:
        return list(caps)
    out = [c for c in caps if isinstance(c, (int, float))]
    out.append(float(fresh[-1][1]))
    return out[-max(1, keep):]


def effective_switch_at(configured: float, caps: list, margin: float = LEARNED_CAP_MARGIN) -> float:
    """The near-limit bar for one (account, window): the configured threshold, lowered to
    `min(observed caps) − margin` when 429s have shown the real wall sits below it —
    floored at EFFECTIVE_FLOOR_PCT so one absurd sample cannot make every reading 'near'.
    No caps ⇒ the configured value unchanged (fail-open)."""
    vals = [c for c in caps if isinstance(c, (int, float))]
    if not vals:
        return configured
    return max(EFFECTIVE_FLOOR_PCT, min(configured, min(vals) - margin))


def projected_near(
    samples: list, caps: list, now: float, horizon_min: float = ROTATE_HORIZON_MIN
) -> bool:
    """The FAST-BURN gate for the LIVE account: True when the projected wall — at the
    LEARNED cap when one exists, else 100% — is inside the horizon. False on any missing
    input (fail-open: the threshold gate alone decides, exactly as before this module)."""
    cap = effective_switch_at(100.0, caps, margin=0.0) if caps else 100.0
    m = minutes_to_wall(samples, now, cap_pct=cap)
    return m is not None and m <= horizon_min


def candidate_walls_soon(
    samples: list, caps: list, now: float, horizon_min: float = ROTATE_HORIZON_MIN
) -> bool:
    """The SELECTION filter: True when an alternate's own recent slope projects ITS wall
    inside the horizon — rotating onto it buys minutes, not a session. Sparse history
    (alternates are only probed while a rotation is being considered) ⇒ False, fail-open:
    an unknown candidate is still a candidate, exactly as before this module."""
    return projected_near(samples, caps, now, horizon_min)


# ---------- state.json plumbing (pure dict-shaping; the caller owns load/save) ----------


def account_rings(state: dict, email: str) -> dict:
    """The `{window: ring}` dict for one account, from `state['usage_samples']`.
    Missing/malformed ⇒ fresh empty dict (corrupt state degrades to fail-open, never
    raises — matching the rotator's corruption-recovery posture)."""
    root = state.get("usage_samples")
    per = root.get(email) if isinstance(root, dict) else None
    return per if isinstance(per, dict) else {}


def account_caps(state: dict, email: str) -> dict:
    root = state.get("learned_caps")
    per = root.get(email) if isinstance(root, dict) else None
    return per if isinstance(per, dict) else {}


def store_rings(state: dict, email: str, rings: dict) -> None:
    state.setdefault("usage_samples", {})
    if isinstance(state["usage_samples"], dict):
        state["usage_samples"][email] = rings


def store_caps(state: dict, email: str, caps: dict) -> None:
    state.setdefault("learned_caps", {})
    if isinstance(state["learned_caps"], dict):
        state["learned_caps"][email] = caps


def observe(state: dict, email: str, now: float, fh: float | None, sd: float | None) -> None:
    """Record one tick's `(5h, 7d)` readings for `email` into the state dict, bounded.
    The ONE mutation helper the wiring calls on every 200 probe (live or alternate)."""
    rings = account_rings(state, email)
    rings["5h"] = record_sample(rings.get("5h", []), now, fh)
    rings["7d"] = record_sample(rings.get("7d", []), now, sd)
    store_rings(state, email, rings)


def observe_wall(state: dict, email: str, now: float) -> None:
    """Record a CONFIRMED 429 as effective-cap samples for `email` (per window, from each
    ring's freshest reading). Called once per debounced live 429."""
    rings = account_rings(state, email)
    caps = account_caps(state, email)
    for w in ("5h", "7d"):
        caps[w] = record_cap_sample(caps.get(w, []), rings.get(w, []), now)
    store_caps(state, email, caps)


def live_burn_verdict(
    state: dict,
    email: str,
    now: float,
    *,
    horizon_min: float = ROTATE_HORIZON_MIN,
) -> str | None:
    """The whole live-account fast-burn/learned-cap decision in one call: a short human
    reason string when the account should be rotated AWAY despite the threshold not
    tripping, else None. Reads only the state dict — pure given its inputs."""
    rings = account_rings(state, email)
    caps = account_caps(state, email)
    for w in ("5h", "7d"):
        samples = rings.get(w, [])
        if projected_near(samples, caps.get(w, []), now, horizon_min):
            m = minutes_to_wall(
                samples, now,
                cap_pct=effective_switch_at(100.0, caps.get(w, []), margin=0.0) if caps.get(w) else 100.0,
            )
            return f"{w} wall projected in ~{m:.0f} min (recent burn slope)"
        fresh = [(t, u) for t, u in samples if now - t <= SAMPLE_MAX_AGE_S]
        if fresh and caps.get(w):
            configured = 100.0  # the caller's threshold gate already ran; this is the CAP bar
            bar = effective_switch_at(configured, caps[w])
            if bar < configured and fresh[-1][1] >= bar:
                return f"{w}={fresh[-1][1]:.0f}% ≥ learned cap bar {bar:.0f}% (observed 429s below the configured threshold)"
    return None
