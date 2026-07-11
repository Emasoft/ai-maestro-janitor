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


def _run_phase(dispatch) -> str:
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        dispatch._phase_cadence_tier()
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
