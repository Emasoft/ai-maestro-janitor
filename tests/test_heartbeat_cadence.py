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


def test_commit_tier_carries_last_rearm_ts_forward_unchanged() -> None:
    """commit_tier decides which tier WINS, never the re-arm dwell anchor — it
    must carry last_rearm_ts through untouched (issue #89 half 2)."""
    prev = hc.CadenceState(raw_tier=hc.SLOW, stable_count=1, committed_tier=hc.SLOW, last_rearm_ts=12345)
    s = hc.commit_tier(hc.FAST, prev, demote_fires=2)
    assert s.last_rearm_ts == 12345


def test_commit_tier_first_fire_last_rearm_ts_is_zero() -> None:
    """No prior state → last_rearm_ts starts at 0 (never armed under dwell tracking)."""
    s = hc.commit_tier(hc.SLOW, None, demote_fires=2)
    assert s.last_rearm_ts == 0


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
    s = hc.CadenceState(raw_tier=hc.MID, stable_count=3, committed_tier=hc.FAST, last_rearm_ts=555)
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


def test_state_from_dict_missing_last_rearm_ts_defaults_zero() -> None:
    """A pre-dwell (issue #89 half 2) state file has no last_rearm_ts key — it
    must parse with 0 (never armed), not raise or drop the whole state."""
    s = hc.state_from_dict({"raw_tier": hc.SLOW, "committed_tier": hc.SLOW})
    assert s is not None
    assert s.last_rearm_ts == 0


def test_state_from_dict_negative_last_rearm_ts_clamped_to_zero() -> None:
    """A corrupt/negative timestamp must not produce a negative dwell anchor."""
    s = hc.state_from_dict({"raw_tier": hc.SLOW, "committed_tier": hc.SLOW, "last_rearm_ts": -99})
    assert s is not None
    assert s.last_rearm_ts == 0


# ---------- should_emit_renew / stamp_rearm (issue #89 half 2 — re-arm dwell) ----------


def _cs(tier: str, *, last_rearm_ts: int = 0) -> hc.CadenceState:
    return hc.CadenceState(raw_tier=tier, stable_count=1, committed_tier=tier, last_rearm_ts=last_rearm_ts)


def test_should_emit_renew_false_when_cron_matches() -> None:
    """No divergence → never renew, regardless of dwell state."""
    committed = _cs(hc.SLOW, last_rearm_ts=0)
    assert (
        hc.should_emit_renew(
            desired_differs=False, committed=committed, prev=None, now=100000, dwell_s=1200
        )
        is False
    )


def test_should_emit_renew_first_commit_always_renews() -> None:
    """prev=None (the very first commit) is treated as a promotion — always renews,
    matching the pre-dwell behavior for a session's first-ever cadence fire."""
    committed = _cs(hc.SLOW, last_rearm_ts=0)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=None, now=100000, dwell_s=1200
        )
        is True
    )


def test_should_emit_renew_promotion_bypasses_dwell() -> None:
    """A tier PROMOTION (SLOW->FAST) renews immediately even seconds after the last
    re-arm — recovery latency must never wait out a dwell window."""
    prev = _cs(hc.SLOW, last_rearm_ts=99990)
    committed = hc.CadenceState(raw_tier=hc.FAST, stable_count=1, committed_tier=hc.FAST, last_rearm_ts=99990)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=1200
        )
        is True
    )


def test_should_emit_renew_mid_promotion_also_bypasses_dwell() -> None:
    """SLOW->MID (genuine user activity) is a promotion too — not just ->FAST."""
    prev = _cs(hc.SLOW, last_rearm_ts=99990)
    committed = hc.CadenceState(raw_tier=hc.MID, stable_count=1, committed_tier=hc.MID, last_rearm_ts=99990)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=1200
        )
        is True
    )


def test_should_emit_renew_demotion_suppressed_within_dwell() -> None:
    """THE fix: a demotion (FAST->SLOW) within the dwell window does NOT renew —
    this is exactly the churn issue #89 describes (a re-arm every tier flip)."""
    prev = _cs(hc.FAST, last_rearm_ts=99500)
    committed = hc.CadenceState(raw_tier=hc.SLOW, stable_count=1, committed_tier=hc.SLOW, last_rearm_ts=99500)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=1200
        )
        is False
    )  # only 500s since the last re-arm, dwell_s=1200 — still inside the window


def test_should_emit_renew_demotion_allowed_after_dwell_expires() -> None:
    """The SAME demotion, but the last re-arm is now old enough — renews."""
    prev = _cs(hc.FAST, last_rearm_ts=98000)
    committed = hc.CadenceState(raw_tier=hc.SLOW, stable_count=1, committed_tier=hc.SLOW, last_rearm_ts=98000)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=1200
        )
        is True
    )  # 2000s since the last re-arm >= dwell_s=1200


def test_should_emit_renew_same_tier_cron_change_is_dwell_gated() -> None:
    """Same committed tier (e.g. an override env var changed the cron, or the TTL
    regime flipped) is NOT a promotion — it is dwell-gated like a demotion."""
    prev = _cs(hc.MID, last_rearm_ts=99900)
    committed = _cs(hc.MID, last_rearm_ts=99900)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=1200
        )
        is False
    )


def test_should_emit_renew_dwell_disabled_always_renews() -> None:
    """dwell_s<=0 disables the feature entirely — every divergence (that isn't a
    same-fire no-op) renews immediately, matching the pre-dwell behavior."""
    prev = _cs(hc.FAST, last_rearm_ts=99999)
    committed = _cs(hc.SLOW, last_rearm_ts=99999)
    assert (
        hc.should_emit_renew(desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=0)
        is True
    )


def test_should_emit_renew_no_prior_rearm_always_renews() -> None:
    """last_rearm_ts==0 means no re-arm has ever landed — nothing to dwell against,
    so the fire may renew even though it is a demotion vs the prior committed tier."""
    prev = _cs(hc.FAST, last_rearm_ts=0)
    committed = _cs(hc.SLOW, last_rearm_ts=0)
    assert (
        hc.should_emit_renew(
            desired_differs=True, committed=committed, prev=prev, now=100000, dwell_s=1200
        )
        is True
    )


def test_stamp_rearm_sets_timestamp_preserves_tier_fields() -> None:
    s = hc.CadenceState(raw_tier=hc.MID, stable_count=4, committed_tier=hc.FAST, last_rearm_ts=0)
    stamped = hc.stamp_rearm(s, 42424)
    assert stamped.last_rearm_ts == 42424
    assert stamped.raw_tier == hc.MID
    assert stamped.stable_count == 4
    assert stamped.committed_tier == hc.FAST


# ---------- cap_tier (self-budget SLOW clamp, TRDD-ZCODD6YS) ----------


def test_cap_tier_clamps_fast_to_slow() -> None:
    """A FAST committed tier capped at SLOW → committed becomes SLOW; the hysteresis fields
    (raw_tier, stable_count, last_rearm_ts) are preserved untouched."""
    s = hc.CadenceState(raw_tier=hc.FAST, stable_count=3, committed_tier=hc.FAST, last_rearm_ts=999)
    capped = hc.cap_tier(s, hc.SLOW)
    assert capped.committed_tier == hc.SLOW
    assert capped.raw_tier == hc.FAST
    assert capped.stable_count == 3
    assert capped.last_rearm_ts == 999


def test_cap_tier_clamps_mid_to_slow() -> None:
    s = _cs(hc.MID)
    assert hc.cap_tier(s, hc.SLOW).committed_tier == hc.SLOW


def test_cap_tier_noop_on_already_slow() -> None:
    """Capping an already-SLOW state at SLOW returns it UNCHANGED (a no-op, not an error)."""
    s = _cs(hc.SLOW)
    assert hc.cap_tier(s, hc.SLOW) is s


def test_cap_tier_ceiling_mid_leaves_slow_alone_clamps_fast() -> None:
    """The clamp respects _TIER_RANK for any ceiling, not just SLOW: a MID ceiling leaves a
    SLOW state alone and clamps a FAST one to MID."""
    assert hc.cap_tier(_cs(hc.SLOW), hc.MID).committed_tier == hc.SLOW
    assert hc.cap_tier(_cs(hc.FAST), hc.MID).committed_tier == hc.MID
