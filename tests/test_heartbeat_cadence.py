"""Tests for the TTL-aware heartbeat cadence lib (TRDD-0QQX9H0G, issue #83).

Real, no mocks: tier selection + hysteresis + cron mapping are pure functions
exercised directly; the account-status probe is exercised with REAL subprocess
scripts written to a temp dir (a printing script, a failing script, a garbage
script, a missing binary), never a mock.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import heartbeat_cadence as hc  # noqa: E402

# ---------- raw_tier ----------


def test_raw_tier_active_waiting_is_fast() -> None:
    """Any active-waiting signal → FAST, regardless of recent activity."""
    assert hc.raw_tier(hc.Signals(active_waiting=True, recent_activity=False)) == hc.FAST
    assert hc.raw_tier(hc.Signals(active_waiting=True, recent_activity=True)) == hc.FAST


def test_raw_tier_recent_only_is_mid() -> None:
    """Recent user activity but nothing waiting → MID."""
    assert hc.raw_tier(hc.Signals(active_waiting=False, recent_activity=True)) == hc.MID


def test_raw_tier_idle_is_slow() -> None:
    """Neither signal → SLOW (idle keep-warm)."""
    assert hc.raw_tier(hc.Signals(active_waiting=False, recent_activity=False)) == hc.SLOW


# ---------- commit_tier (hysteresis) ----------


def test_commit_tier_first_fire_commits_raw() -> None:
    """No prior state → commit the raw tier immediately."""
    s = hc.commit_tier(hc.SLOW, None, demote_fires=2)
    assert s.committed_tier == hc.SLOW
    assert s.stable_count == 1


def test_commit_tier_promotes_immediately() -> None:
    """A faster raw tier commits on the SAME fire (no wait)."""
    prev = hc.CadenceState(raw_tier=hc.SLOW, stable_count=5, committed_tier=hc.SLOW)
    s = hc.commit_tier(hc.FAST, prev, demote_fires=2)
    assert s.committed_tier == hc.FAST


def test_commit_tier_demotes_only_after_n_fires() -> None:
    """A slower raw tier demotes only after demote_fires consecutive fires."""
    prev = hc.CadenceState(raw_tier=hc.FAST, stable_count=1, committed_tier=hc.FAST)
    first = hc.commit_tier(hc.SLOW, prev, demote_fires=2)
    assert first.committed_tier == hc.FAST  # not yet — one idle fire
    second = hc.commit_tier(hc.SLOW, first, demote_fires=2)
    assert second.committed_tier == hc.SLOW  # two consecutive → demote


def test_commit_tier_single_idle_fire_does_not_flap() -> None:
    """FAST → one idle fire → FAST again: the committed tier never left FAST."""
    prev = hc.CadenceState(raw_tier=hc.FAST, stable_count=3, committed_tier=hc.FAST)
    idle = hc.commit_tier(hc.SLOW, prev, demote_fires=2)
    assert idle.committed_tier == hc.FAST
    back = hc.commit_tier(hc.FAST, idle, demote_fires=2)
    assert back.committed_tier == hc.FAST


def test_commit_tier_demote_fires_one_demotes_immediately() -> None:
    """demote_fires=1 makes demotion immediate (no hysteresis)."""
    prev = hc.CadenceState(raw_tier=hc.FAST, stable_count=1, committed_tier=hc.FAST)
    s = hc.commit_tier(hc.SLOW, prev, demote_fires=1)
    assert s.committed_tier == hc.SLOW


def test_commit_tier_equal_raw_keeps_committed() -> None:
    """raw == committed leaves the committed tier untouched, counting up."""
    prev = hc.CadenceState(raw_tier=hc.MID, stable_count=1, committed_tier=hc.MID)
    s = hc.commit_tier(hc.MID, prev, demote_fires=2)
    assert s.committed_tier == hc.MID
    assert s.stable_count == 2


# ---------- tier_to_cron ----------


def test_tier_to_cron_slow_ttl_regime() -> None:
    """ttl >= 30 → the tiered slow-TTL crons (FAST keeps */5, SLOW is */30 = 6x cheaper)."""
    assert hc.tier_to_cron(hc.FAST, 60) == "*/5 * * * *"
    assert hc.tier_to_cron(hc.MID, 60) == "*/15 * * * *"
    assert hc.tier_to_cron(hc.SLOW, 60) == "*/30 * * * *"


def test_tier_to_cron_fast_ttl_regime_collapses_to_5min() -> None:
    """ttl < 30 (over-plan credits / api-key) → every tier is */5, no slowdown."""
    for tier in (hc.FAST, hc.MID, hc.SLOW):
        assert hc.tier_to_cron(tier, 5) == "*/5 * * * *"


def test_tier_to_cron_boundary_is_30() -> None:
    """30 min is slow-TTL; 29 is fast-TTL."""
    assert hc.tier_to_cron(hc.SLOW, 30) == "*/30 * * * *"
    assert hc.tier_to_cron(hc.SLOW, 29) == "*/5 * * * *"


def test_tier_to_cron_overrides_apply_in_slow_ttl() -> None:
    """A configured override wins in the slow-TTL regime."""
    ov = {hc.SLOW: "13 * * * *"}
    assert hc.tier_to_cron(hc.SLOW, 60, ov) == "13 * * * *"
    assert hc.tier_to_cron(hc.MID, 60, ov) == "*/15 * * * *"  # untouched tier keeps default


def test_tier_to_cron_overrides_ignored_in_fast_ttl() -> None:
    """Overrides are ignored under a 5-min TTL — a slower cron would kill the cache."""
    ov = {hc.SLOW: "13 * * * *"}
    assert hc.tier_to_cron(hc.SLOW, 5, ov) == "*/5 * * * *"


def test_tier_to_cron_blank_override_falls_through() -> None:
    """An empty-string override is treated as unset."""
    assert hc.tier_to_cron(hc.FAST, 60, {hc.FAST: "  "}) == "*/5 * * * *"


# ---------- probe_account_status (real subprocess) ----------


def _write_script(tmp_path: Path, name: str, body: str) -> str:
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(0o755)
    return str(script)


def test_probe_parses_cache_ttl_minutes(tmp_path: Path) -> None:
    """A real script printing the account-status JSON yields cacheTtl.minutes."""
    cmd = _write_script(tmp_path, "ok.sh", "echo '{\"cacheTtl\":{\"minutes\":60},\"plan\":\"Max 5x\"}'")
    assert hc.probe_account_status(cmd) == 60


def test_probe_none_on_nonzero_exit(tmp_path: Path) -> None:
    """A failing command → None (fail-open)."""
    cmd = _write_script(tmp_path, "fail.sh", "echo '{\"cacheTtl\":{\"minutes\":60}}'; exit 1")
    assert hc.probe_account_status(cmd) is None


def test_probe_none_on_garbage_output(tmp_path: Path) -> None:
    """Non-JSON stdout → None."""
    cmd = _write_script(tmp_path, "garbage.sh", "echo 'not json at all'")
    assert hc.probe_account_status(cmd) is None


def test_probe_none_on_missing_field(tmp_path: Path) -> None:
    """Valid JSON without cacheTtl.minutes → None."""
    cmd = _write_script(tmp_path, "nomin.sh", "echo '{\"plan\":\"Max 5x\"}'")
    assert hc.probe_account_status(cmd) is None


def test_probe_none_on_missing_binary() -> None:
    """A missing executable → None, never an exception."""
    assert hc.probe_account_status("/definitely/not/a/real/binary/xyzzy") is None


def test_probe_none_on_empty_command() -> None:
    """An empty command string disables the probe → None."""
    assert hc.probe_account_status("") is None
    assert hc.probe_account_status("   ") is None


# ---------- resolve_ttl_minutes ----------


def _never(*_a, **_k):  # a probe that must not be called
    raise AssertionError("probe should not have been invoked")


def test_resolve_explicit_subscription_skips_probe() -> None:
    m, write = hc.resolve_ttl_minutes(
        now=1000, regime_config="subscription", cached=None,
        probe_interval=1800, probe=_never, env={},
    )
    assert (m, write) == (60, None)


def test_resolve_explicit_api_key_skips_probe() -> None:
    m, write = hc.resolve_ttl_minutes(
        now=1000, regime_config="api-key", cached=None,
        probe_interval=1800, probe=_never, env={},
    )
    assert (m, write) == (5, None)


def test_resolve_auto_reuses_fresh_cache() -> None:
    """A cache younger than probe_interval is reused; the probe is NOT called."""
    cached = {"minutes": 60, "probed_at": 900, "source": "probe"}
    m, write = hc.resolve_ttl_minutes(
        now=1000, regime_config="auto", cached=cached,
        probe_interval=1800, probe=_never, env={},
    )
    assert m == 60
    assert write is None  # nothing to persist


def test_resolve_auto_reprobes_when_stale() -> None:
    """A cache older than probe_interval → re-probe; the new value is returned + persisted."""
    cached = {"minutes": 60, "probed_at": 0, "source": "probe"}
    m, write = hc.resolve_ttl_minutes(
        now=100000, regime_config="auto", cached=cached,
        probe_interval=1800, probe=lambda: 45, env={},
    )
    assert m == 45
    assert write == {"minutes": 45, "probed_at": 100000, "source": "probe"}


def test_resolve_auto_probe_success_no_cache() -> None:
    m, write = hc.resolve_ttl_minutes(
        now=500, regime_config="auto", cached=None,
        probe_interval=1800, probe=lambda: 60, env={},
    )
    assert m == 60
    assert write == {"minutes": 60, "probed_at": 500, "source": "probe"}


def test_resolve_auto_probe_fail_env_fallback_subscription() -> None:
    """Probe fails, no API key → 60, cached as a fallback (bounds re-probe frequency)."""
    m, write = hc.resolve_ttl_minutes(
        now=500, regime_config="auto", cached=None,
        probe_interval=1800, probe=lambda: None, env={},
    )
    assert m == 60
    assert write == {"minutes": 60, "probed_at": 500, "source": "fallback"}


def test_resolve_auto_probe_fail_env_fallback_api_key() -> None:
    """Probe fails, ANTHROPIC_API_KEY set → 5 (the fallback the env heuristic gives)."""
    m, write = hc.resolve_ttl_minutes(
        now=500, regime_config="auto", cached=None,
        probe_interval=1800, probe=lambda: None, env={"ANTHROPIC_API_KEY": "sk-xxx"},
    )
    assert m == 5
    assert write == {"minutes": 5, "probed_at": 500, "source": "fallback"}


# ---------- state serialization ----------


def test_state_round_trip() -> None:
    s = hc.CadenceState(raw_tier=hc.MID, stable_count=3, committed_tier=hc.FAST)
    assert hc.state_from_dict(hc.state_to_dict(s)) == s


def test_state_from_dict_none_on_malformed() -> None:
    assert hc.state_from_dict(None) is None
    assert hc.state_from_dict({}) is None
    assert hc.state_from_dict({"raw_tier": "bogus", "committed_tier": hc.SLOW}) is None
    assert hc.state_from_dict({"raw_tier": hc.SLOW, "committed_tier": "bogus"}) is None


def test_state_from_dict_bad_count_defaults_to_one() -> None:
    s = hc.state_from_dict({"raw_tier": hc.SLOW, "committed_tier": hc.SLOW, "stable_count": "nope"})
    assert s is not None
    assert s.stable_count == 1
