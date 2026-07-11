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


def test_rate_limited_promotes_to_fast(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rate-limited.flag is an active-waiting signal → FAST cron."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_TTL_REGIME", "subscription")
    (_state(proj) / "rate-limited.flag").write_text("")
    dispatch = _import_dispatch()
    _run_phase(dispatch)
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/5 * * * *"


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

    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        dispatch.main()
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert (_state(proj) / "desired-cadence.cron").read_text().strip() == "*/30 * * * *"
    assert "[janitor-renew]" in out  # first fire, armed absent → re-arm to SLOW
