"""A failed TTL probe must not overwrite a measurement with a guess (TRDD-VXFNDHXT).

`probe_account_status` runs `agentlenspro get_account_status`, a network call, against a 5s
bound. Measured on a healthy host: 2.89s / 6.29s / 9.18s across three consecutive runs — so it
fails on latency variance alone, intermittently, with nothing misconfigured.

Before this change every such miss wrote `_env_fallback_minutes` over the cached reading. That
guess returns 60 for a non-API-key session, and `tier_to_cron`'s FAST guard fires only BELOW 30
— so the fallback was exactly the value at which the guard can never trigger (janitor#190). A
session whose real TTL was 5 then ran */15 with a cache dying between fires.

The rule these tests pin: a stale MEASUREMENT outranks a fresh GUESS, and `source:` stays
truthful about which one you are looking at.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import heartbeat_cadence as hc  # type: ignore[import-not-found]  # noqa: E402

NOW = 1_800_000_000
INTERVAL = 1800


def _resolve(cached, probe_result, env=None):
    return hc.resolve_ttl_minutes(
        now=NOW,
        regime_config="auto",
        cached=cached,
        probe_interval=INTERVAL,
        probe=lambda: probe_result,
        env=env if env is not None else {},
    )


# ── the core rule ─────────────────────────────────────────────────────────────────────


def test_a_failed_probe_reuses_the_last_measured_value_instead_of_guessing() -> None:
    """The janitor#190 case: probe times out, a real reading of 5 exists, the guess would be 60."""
    cached = {"minutes": 5, "probed_at": NOW - 9999, "source": "probe"}
    minutes, write = _resolve(cached, None)
    assert minutes == 5, "the measured 5 must survive; 60 would disable the FAST guard"
    assert write is not None and write["source"] == "stale-probe"


def test_reuse_ignores_age_because_probe_interval_bounds_ASKING_not_validity() -> None:
    """A reading from a week ago is still evidence about this account; the interval only says
    how often we re-ask. Expiring it would hand the decision back to the guess."""
    cached = {"minutes": 5, "probed_at": NOW - 7 * 86400, "source": "probe"}
    minutes, _ = _resolve(cached, None)
    assert minutes == 5


def test_a_stale_probe_value_survives_repeated_failures() -> None:
    """Second failure must not degrade `stale-probe` into `fallback` — otherwise the guess wins
    by attrition, one heartbeat later than before.

    `probed_at` must be OLDER than probe_interval in every test that means to reach the probe:
    inside the interval the fresh-cache branch returns first and never probes at all. That
    branch is correct and predates this change — three of these tests failed on first run
    because I set a recent stamp, which asserted against a code path the input never entered."""
    cached = {"minutes": 5, "probed_at": NOW - 9999, "source": "stale-probe"}
    minutes, write = _resolve(cached, None)
    assert minutes == 5
    assert write is not None and write["source"] == "stale-probe"


def test_a_prior_FALLBACK_is_not_reused_because_it_was_never_a_measurement() -> None:
    """Reusing a guess would launder it into permanence — it would look measured forever after."""
    cached = {"minutes": 60, "probed_at": NOW - 9999, "source": "fallback"}
    _, write = _resolve(cached, None, env={"ANTHROPIC_API_KEY": "sk-x"})
    assert write is not None and write["source"] == "fallback"


def test_with_no_cache_at_all_it_still_falls_back() -> None:
    minutes, write = _resolve(None, None, env={"ANTHROPIC_API_KEY": "sk-x"})
    assert minutes == hc._TTL_API_KEY_MIN
    assert write is not None and write["source"] == "fallback"


# ── the paths this must not disturb ───────────────────────────────────────────────────


def test_a_successful_probe_still_wins_over_any_cache() -> None:
    """A cache old enough to re-probe, and the probe succeeds — the live answer must win."""
    cached = {"minutes": 5, "probed_at": NOW - 9999, "source": "probe"}
    minutes, write = _resolve(cached, 60)
    assert minutes == 60
    assert write is not None and write["source"] == "probe"


def test_a_FRESH_cache_short_circuits_without_probing() -> None:
    """Unchanged: inside the interval we neither probe nor write."""
    cached = {"minutes": 60, "probed_at": NOW - 10, "source": "probe"}
    calls: list[int] = []

    def _probe():
        calls.append(1)
        return 5

    minutes, write = hc.resolve_ttl_minutes(
        now=NOW, regime_config="auto", cached=cached, probe_interval=INTERVAL,
        probe=_probe, env={},
    )
    assert (minutes, write, calls) == (60, None, [])


@pytest.mark.parametrize("regime,expected", [("subscription", 60), ("api-key", 5)])
def test_a_pinned_regime_never_probes_or_caches(regime: str, expected: int) -> None:
    minutes, write = hc.resolve_ttl_minutes(
        now=NOW, regime_config=regime, cached=None, probe_interval=INTERVAL,
        probe=lambda: 999, env={},
    )
    assert (minutes, write) == (expected, None)


# ── the consequence that actually matters ─────────────────────────────────────────────


def test_the_reused_measurement_drives_the_FAST_tier_the_guess_would_have_disabled() -> None:
    """The whole point. 5 collapses every tier to */5; 60 lets the ladder reach */30 with a
    cache that dies between fires — which is what janitor#190 measured at ~530k per fire."""
    measured, _ = _resolve({"minutes": 5, "probed_at": NOW - 9999, "source": "probe"}, None)
    guessed = hc._env_fallback_minutes({})

    assert hc.tier_to_cron("slow", measured, {}) == hc._FAST_TTL_CRON
    assert hc.tier_to_cron("slow", guessed, {}) != hc._FAST_TTL_CRON
