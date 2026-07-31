"""Integration tests for the dynamic cadence dispatch phase (TRDD-0QQX9H0G, #83).

Real I/O, no mocks: each test points CLAUDE_PROJECT_DIR at a tmp dir, seeds the
state files the phase reads, runs dispatch._phase_cadence_tier() in-process, and
asserts the desired-cadence.cron it wrote + whether it emitted [janitor-renew].
HEARTBEAT_TTL_REGIME is forced (subscription / api-key) so the phase never shells
out to the agentlensPro probe — the probe itself is covered in
test_heartbeat_cadence.py.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def proj(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CLAUDE_PROJECT_DIR at a tmp project and reload the state modules."""
    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    for mod in ("dispatch", "state", "global_state"):
        sys.modules.pop(mod, None)
    return project


def _import_dispatch():
    import importlib.util as _u

    spec = _u.spec_from_file_location("janitor_dispatch_cadence_ut", str(_PROJECT_ROOT / "scripts" / "dispatch.py"))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_phase(dispatch, *, budget_cap_slow: bool = False) -> str:
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        dispatch._phase_cadence_tier(budget_cap_slow=budget_cap_slow)
    finally:
        sys.stdout = old
    return buf.getvalue()


def _run_main(dispatch) -> str:
    """Run a WHOLE fire (dispatch.main()) and return its stdout."""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        dispatch.main()
    finally:
        sys.stdout = old
    return buf.getvalue()


def _state(proj: Path) -> Path:
    return proj / ".janitor" / "state"


def test_dynamic_off_is_total_noop(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """heartbeat_cadence_dynamic=false → no files written, no output."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DYNAMIC", "false")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out == ""
    assert not (_state(proj) / "desired-cadence.cron").exists()
    assert not (_state(proj) / "cadence-state.json").exists()


def test_idle_writes_slow_and_emits_renew(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Idle session, subscription regime → SLOW cron; armed absent → [janitor-renew]."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"
    assert out.strip() == "[janitor-renew]"


def test_silent_when_armed_matches_desired(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Once /janitor-arm has recorded armed-cadence.cron == desired, no marker fires."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    (_state(proj) / "armed-cadence.cron").write_text("*/30 * * * *")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out == ""
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"


def test_recent_resume_promotes_to_fast(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A FRESH last-resume.ts stamp is an active-waiting signal → FAST cron.

    The stamp — not rate-limited.flag — is the cadence's view of a resume: the resume
    phases unlink their flag and early-return from main() before this phase ever runs.
    """
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    (_state(proj) / "last-resume.ts").write_text(str(int(time.time())))
    dispatch = _import_dispatch()
    _run_phase(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"


def test_stale_resume_stamp_does_not_hold_fast(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An OLD resume stamp expires → the session is free to demote back to SLOW."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    (_state(proj) / "last-resume.ts").write_text(str(int(time.time()) - 7200))
    dispatch = _import_dispatch()
    _run_phase(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"


def test_rate_limit_fire_stamps_resume_then_next_fire_goes_fast(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """END-TO-END regression guard for the dead-signal bug (TRDD-0QQX9H0G).

    Fire 1: rate-limited.flag → main() emits [janitor-resume] and returns EARLY, having
    unlinked the flag — so the cadence phase never sees it and the fire's output must
    stay clean (no [janitor-renew]). It leaves a last-resume.ts stamp.
    Fire 2: the flag is gone, but the stamp makes the session ACTIVE-WAITING → FAST, so
    the recovery retry loop runs at */5 instead of the idle */30 it would otherwise sit
    at. Before the fix, fire 2 read no signal at all and demoted the session to SLOW.
    """
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    (_state(proj) / "maintenance-mode").write_text("")  # skip chores; cadence still runs
    monkeypatch.setattr(dispatch, "_run_maintenance_detectors", lambda *a, **k: None)
    (_state(proj) / "rate-limited.flag").write_text("")

    out1 = _run_main(dispatch)
    assert "[janitor-resume]" in out1
    assert "rate-limit cleared" in out1
    assert "[janitor-renew]" not in out1  # a recovery fire stays clean
    assert not (_state(proj) / "rate-limited.flag").exists()
    assert (_state(proj) / "last-resume.ts").is_file()
    assert not (_state(proj) / "desired-cadence.cron").exists()  # phase did not run

    out2 = _run_main(dispatch)
    assert "rate-limit cleared" not in out2  # the flag is consumed; no second cue
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"
    assert "[janitor-renew]" in out2  # re-arm to FAST


def test_api_key_regime_all_tiers_5min(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Under the 5-min-TTL regime every tier collapses to */5 (idle here)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "api-key")
    dispatch = _import_dispatch()
    _run_phase(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"


def test_cadence_state_persisted(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The phase persists its hysteresis state for the next fire to read."""
    import json

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    dispatch = _import_dispatch()
    _run_phase(dispatch)
    data = json.loads((_state(proj) / "cadence-state.json").read_text())
    assert data["committed_tier"] == "slow"
    assert data["raw_tier"] == "slow"


def test_demote_hysteresis_holds_fast_one_idle_fire(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeded committed=FAST + one idle fire → stays FAST (demote needs 2 fires)."""
    import json

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    (_state(proj) / "cadence-state.json").write_text(
        json.dumps({"raw_tier": "fast", "stable_count": 1, "committed_tier": "fast"})
    )
    dispatch = _import_dispatch()
    _run_phase(dispatch)  # idle fire (no signals)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"


def test_maintenance_fire_runs_cadence_before_return(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """END-TO-END placement proof: a maintenance-mode dispatch.main() still reaches the
    cadence phase (Phase 1.5a3, before the maintenance early-return), so an idle
    maintenance session demotes to SLOW and re-arms once."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    (st.state_dir() / "maintenance-mode").write_text("")
    # Neutralize the maintenance survival work so the test stays hermetic.
    monkeypatch.setattr(dispatch, "_run_maintenance_detectors", lambda *a, **k: None)
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)

    out = _run_main(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"
    assert "[janitor-renew]" in out  # first fire, armed absent → re-arm to SLOW


# --------------------------------------------------------------------------- #
# issue #89 half 2 — the re-arm DWELL. desired_differs != committed-tier-change:
# even once the tier hysteresis picks a new committed tier, the ACTUAL re-arm
# (a full billed model turn) must not fire again inside the dwell window unless
# this is a genuine tier PROMOTION. Sibling of TRDD-CI6ZTNB9 (half 1, the
# self-exclusion fix, tested above).
# --------------------------------------------------------------------------- #


def _seed_cadence_state(proj: Path, *, raw_tier: str, committed_tier: str, last_rearm_ts: int, stable_count: int = 1) -> None:
    import json

    (_state(proj) / "cadence-state.json").write_text(
        json.dumps(
            {
                "raw_tier": raw_tier,
                "stable_count": stable_count,
                "committed_tier": committed_tier,
                "last_rearm_ts": last_rearm_ts,
            }
        )
    )


def test_dwell_suppresses_demotion_renew_within_window(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A demotion (FAST->SLOW, demote_fires=1 so it commits on this fire) whose last
    re-arm was recent must NOT emit [janitor-renew] — this is exactly the re-arm
    churn issue #89 describes. desired-cadence.cron is still updated (so /janitor-arm
    picks up the right value once the dwell later allows a renew)."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    now = int(time.time())
    _seed_cadence_state(proj, raw_tier="fast", committed_tier="fast", last_rearm_ts=now - 500)
    (_state(proj) / "armed-cadence.cron").write_text("*/5 * * * *")  # armed to the old FAST cron
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out == ""  # dwell (default 1200s) suppresses the renew at only 500s
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"


def test_dwell_allows_demotion_renew_after_window_expires(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The SAME demotion, but the last re-arm is old enough — dwell no longer blocks it."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    now = int(time.time())
    _seed_cadence_state(proj, raw_tier="fast", committed_tier="fast", last_rearm_ts=now - 1300)
    (_state(proj) / "armed-cadence.cron").write_text("*/5 * * * *")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out.strip() == "[janitor-renew]"
    import json

    data = json.loads((_state(proj) / "cadence-state.json").read_text())
    assert data["committed_tier"] == "slow"
    assert data["last_rearm_ts"] > now - 1300  # re-stamped to THIS fire


def test_dwell_bypassed_for_a_genuine_fast_promotion(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PROMOTION (SLOW->FAST via a fresh resume stamp) renews immediately even
    seconds after the last re-arm — recovery latency must never wait on the dwell."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    now = int(time.time())
    _seed_cadence_state(proj, raw_tier="slow", committed_tier="slow", last_rearm_ts=now - 10)
    (_state(proj) / "armed-cadence.cron").write_text("*/30 * * * *")  # armed to the old SLOW cron
    (_state(proj) / "last-resume.ts").write_text(str(now))  # a genuine active-waiting signal
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out.strip() == "[janitor-renew]"
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"


def test_dwell_env_var_zero_disables_the_feature(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DWELL_S=0 restores the pre-dwell
    behavior: every cron divergence renews, even a demotion moments after the
    previous re-arm."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DWELL_S", "0")
    now = int(time.time())
    _seed_cadence_state(proj, raw_tier="fast", committed_tier="fast", last_rearm_ts=now - 5)
    (_state(proj) / "armed-cadence.cron").write_text("*/5 * * * *")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out.strip() == "[janitor-renew]"


def test_dwell_env_var_custom_window_honored(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A short custom dwell (e.g. 60s) lets a re-arm land sooner than the 1200s default."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DWELL_S", "60")
    now = int(time.time())
    _seed_cadence_state(proj, raw_tier="fast", committed_tier="fast", last_rearm_ts=now - 90)
    (_state(proj) / "armed-cadence.cron").write_text("*/5 * * * *")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch)
    assert out.strip() == "[janitor-renew]"  # 90s >= the 60s custom dwell


def test_dwell_state_persists_across_two_suppressed_fires(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE regression this whole half exists to prevent: issue #89's observed
    oscillation (*/15 <-> */5 every fire). Two consecutive fires inside the dwell
    window must BOTH stay silent, and neither may reset the dwell anchor."""
    import json
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    now = int(time.time())
    _seed_cadence_state(proj, raw_tier="fast", committed_tier="fast", last_rearm_ts=now - 100)
    (_state(proj) / "armed-cadence.cron").write_text("*/5 * * * *")
    dispatch = _import_dispatch()

    out1 = _run_phase(dispatch)
    assert out1 == ""
    data1 = json.loads((_state(proj) / "cadence-state.json").read_text())
    assert data1["last_rearm_ts"] == now - 100  # unchanged — no renew happened

    out2 = _run_phase(dispatch)
    assert out2 == ""
    data2 = json.loads((_state(proj) / "cadence-state.json").read_text())
    assert data2["last_rearm_ts"] == now - 100  # still unchanged on the second silent fire


# --------------------------------------------------------------------------- #
# MF4 — the daemon-injectability handshake (TRDD-X07E7HTN, D1 v1). A rate-limit
# resume may DEMOTE off FAST ONLY when the daemon has stamped daemon-wake-covered.ts
# (it injected /janitor-resume into this pane for free). The coverage stamp — not
# active_waiting itself — is the SOLE demotion authority, and it demotes ONLY the
# rate-limit/resume reason. DEFAULT-OFF: absent the opt-in a stamp is ignored.
# --------------------------------------------------------------------------- #


def _fresh_cover(proj: Path) -> None:
    import time

    (_state(proj) / "daemon-wake-covered.ts").write_text(str(int(time.time())))


def test_active_waiting_non_ratelimit_reasons_stay_fast_without_coverage(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE NEGATIVE TEST (MF4): a session active-waiting for a NON-rate-limit reason — a resume
    directive or pending background agents — stays FAST with NO fresh daemon-wake-covered.ts.
    This proves the coverage stamp, NOT active_waiting, authorizes demotion: the stamp demotes
    ONLY the rate-limit/resume reason, never these.

    `keep-going` used to be a third reason here and is gone with the off-switches: the nudge it
    gated is unconditional now, so it would be true of every session and pin the whole fleet FAST.
    """
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_pending_external_agent_count", lambda: 0)

    (sd / "resume-directive.txt").write_text("continue TRDD-X07E7HTN")
    assert dispatch._cadence_active_waiting(sd, now) is True
    (sd / "resume-directive.txt").unlink()

    monkeypatch.setattr(dispatch, "_pending_external_agent_count", lambda: 1)
    assert dispatch._cadence_active_waiting(sd, now) is True


def test_coverage_stamp_never_demotes_a_non_ratelimit_reason(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a FRESH coverage stamp must NOT demote a session waiting on a resume DIRECTIVE: the
    stamp suppresses ONLY the rate-limit/resume reason. A pending directive is an independent FAST
    signal, so a covered session with one is still FAST — this is why the demotion keys on the
    reason, not on active_waiting as a whole."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _state(proj)
    monkeypatch.setattr(dispatch, "_pending_external_agent_count", lambda: 0)
    (sd / "resume-directive.txt").write_text("continue TRDD-X07E7HTN")
    _fresh_cover(proj)
    assert dispatch._cadence_active_waiting(sd, int(time.time())) is True


def test_ratelimit_resume_demotes_only_with_fresh_coverage(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SOLE demotion condition: a recent resume stamp forces FAST UNLESS a FRESH
    daemon-wake-covered.ts proves the daemon owns the wake for free. Stale/absent coverage
    keeps FAST (the cron stays the trigger)."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_pending_external_agent_count", lambda: 0)
    (sd / "last-resume.ts").write_text(str(now))

    assert dispatch._cadence_active_waiting(sd, now) is True  # no coverage → FAST

    (sd / "daemon-wake-covered.ts").write_text(str(now))
    assert dispatch._cadence_active_waiting(sd, now) is False  # fresh coverage → demote

    (sd / "daemon-wake-covered.ts").write_text(str(now - 100_000))
    assert dispatch._cadence_active_waiting(sd, now) is True  # stale coverage → FAST again


def test_coverage_ignored_when_feature_disabled(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEFAULT-OFF preserves today's behavior: a fresh coverage stamp is IGNORED unless the
    opt-in is set, so a rate-limited session stays FAST exactly as before D1 — a stray stamp
    can never silently demote (and under-cover) a session while the feature is disabled."""
    import time

    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", raising=False)
    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_pending_external_agent_count", lambda: 0)
    (sd / "last-resume.ts").write_text(str(now))
    _fresh_cover(proj)
    assert dispatch._cadence_active_waiting(sd, now) is True


def test_phase_demotes_ratelimit_window_with_fresh_coverage(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """END-TO-END: a rate-limited (recent-resume) session with FRESH daemon coverage demotes
    the cron off FAST to the survival floor — the paid FAST poll is redundant because the
    daemon owns the wake. Contrast test_recent_resume_promotes_to_fast (no coverage → FAST)."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DEMOTE_FIRES", "1")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    now = int(time.time())
    (_state(proj) / "last-resume.ts").write_text(str(now))
    (_state(proj) / "daemon-wake-covered.ts").write_text(str(now))
    dispatch = _import_dispatch()
    _run_phase(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"


def test_daemon_feature_on_does_not_disable_cron_resume_fallback(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COMBINED resume+action (TRDD-X07E7HTN, the survival invariant): with the daemon wake
    feature ON and even a fresh coverage stamp present, a rate-limited cron fire STILL emits
    the bare [janitor-resume] and clears the flag. The single-consumer flag means EXACTLY ONE
    resume reaches the model — never lost, never doubled — so the cron fallback is never
    disabled by the daemon path."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    import state as st

    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    (_state(proj) / "rate-limited.flag").write_text("")
    (_state(proj) / "daemon-wake-covered.ts").write_text(str(int(time.time())))  # daemon covering
    out = _run_main(dispatch)
    assert out.count("[janitor-resume]") == 1, "exactly one resume — never lost, never doubled"
    assert not (_state(proj) / "rate-limited.flag").exists(), "single-consumer flag cleared by the cron"


# --------------------------------------------------------------------------- #
# Self-budget SLOW cap (TRDD-ZCODD6YS). `_phase_cadence_tier(budget_cap_slow=True)` clamps
# the committed tier to the SLOW floor even when live signals ask for FAST.
# --------------------------------------------------------------------------- #


def test_budget_cap_slow_pins_slow_even_with_fast_signal(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh last-resume.ts stamp would normally promote to FAST (*/5); with
    budget_cap_slow=True the committed tier is clamped to SLOW (*/30) — the self-budget
    throttle wins over the live promote signal for this fire."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    (_state(proj) / "last-resume.ts").write_text(str(int(time.time())))  # active-waiting → FAST signal
    dispatch = _import_dispatch()
    _run_phase(dispatch, budget_cap_slow=True)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"
    import json

    assert json.loads((_state(proj) / "cadence-state.json").read_text())["committed_tier"] == "slow"


def test_budget_cap_slow_false_leaves_fast(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: the SAME fresh resume stamp WITHOUT the cap promotes to FAST as before —
    proving the cap, not some side effect, is what pins SLOW above."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    (_state(proj) / "last-resume.ts").write_text(str(int(time.time())))
    dispatch = _import_dispatch()
    _run_phase(dispatch, budget_cap_slow=False)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"


def test_budget_cap_slow_noop_when_dynamic_off(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With heartbeat_cadence_dynamic OFF the whole phase is a no-op, so the SLOW cap is
    inert (writes nothing, never errors) — documenting that maintenance is then the only
    effective throttle."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DYNAMIC", "false")
    dispatch = _import_dispatch()
    out = _run_phase(dispatch, budget_cap_slow=True)
    assert out == ""
    assert not (_state(proj) / "desired-cadence.cron").exists()
