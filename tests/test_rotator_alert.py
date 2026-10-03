"""Out-of-band rotator alarm (TRDD-3OS6AXV3 R4): conditions, notifier argv, debounce, clearing,
the daemon wiring, and the dispatch drift line ahead of the summary-hold gate.

Real temp state throughout. The notifier's argv is captured through `notify._deliver`'s own
runner seam, plus one test that puts a REAL fake `osascript` executable first on PATH. A fake
osascript proves only the argv — whether macOS actually shows the banner from a LaunchAgent is a
manual field check (see the R4 report).
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_ROOT / "scripts"))

import rotator_alert as ra  # type: ignore[import-not-found]  # noqa: E402
from test_dispatch_phases import (  # type: ignore[import-not-found]  # noqa: E402,F401
    _arm_summary_hold,
    _import_dispatch,
    _run_main,
    env_isolation,
)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="the osascript channel is darwin-only")

NOW = 1_800_000_000.0
LIVE = "live.person@example.test"
SPARE = "spare.person@example.test"


def _write_state(root: Path, *, live_exp_s: float, spare_exp_s: float | None) -> None:
    slots = {LIVE: {"expires_at": int(live_exp_s * 1000)}}
    if spare_exp_s is not None:
        slots[SPARE] = {"expires_at": int(spare_exp_s * 1000)}
    (root / "state.json").write_text(json.dumps({"live_email": LIVE, "slots": slots}))


def _fresh_tick(root: Path, now: float = NOW) -> None:
    (root / "tick-completed.ts").write_text(str(now - 30))


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL", raising=False)
    r = tmp_path / "rotator"
    r.mkdir()
    return r


class Runner:
    def __init__(self) -> None:
        self.argvs: list[list[str]] = []

    def __call__(self, argv: list[str]) -> None:
        self.argvs.append(argv)


def test_no_rotation_target_notifies_once_with_the_single_action(root: Path) -> None:
    """No slot has a future expiry: one osascript notification naming the action, no e-mail."""
    _write_state(root, live_exp_s=NOW - 3600, spare_exp_s=NOW - 60)
    _fresh_tick(root)
    run = Runner()
    active = ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    assert "no-rotation-target" in active
    assert run.argvs[0][:2] == ["osascript", "-e"]
    script = run.argvs[0][2]
    assert script.startswith("display notification") and "/janitor-capture-all-logins" in script
    assert "example.test" not in script
    saved = json.loads((root / ra.ALERT_NAME).read_text())
    assert "example.test" not in json.dumps(saved)
    assert saved["alerts"]["no-rotation-target"]["last_notified"] == int(NOW)


def test_healthy_state_raises_nothing(root: Path) -> None:
    """A future-expiry live token, a spare, a fresh tick and no stuck file: no alert, no file."""
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=NOW + 7200)
    _fresh_tick(root)
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=run) == []
    assert run.argvs == [] and not (root / ra.ALERT_NAME).exists()


def test_live_token_expired_needs_the_five_minute_grace(root: Path) -> None:
    """Expired 4 min ago: quiet. Expired 6 min ago and unrefreshed: live-token-expired."""
    _fresh_tick(root)
    _write_state(root, live_exp_s=NOW - 240, spare_exp_s=NOW + 7200)
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=Runner()) == []
    _write_state(root, live_exp_s=NOW - 360, spare_exp_s=NOW + 7200)
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=run) == ["live-token-expired"]
    assert len(run.argvs) == 1 and "/login" in run.argvs[0][-1]


def test_tick_stalled_only_while_claude_runs(root: Path) -> None:
    """No completed tick for 11 min fires with a claude session up, and not without one."""
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=NOW + 7200)
    (root / "tick-completed.ts").write_text(str(NOW - 660))
    assert ra.evaluate(root, now=NOW, claude_running=False, runner=Runner()) == []
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=Runner()) == ["tick-stalled"]


def test_rotation_stuck_file_alerts_even_without_claude(root: Path) -> None:
    """rotation-stuck.json present: alert regardless of the session (it is already a verdict)."""
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=NOW + 7200)
    (root / "rotation-stuck.json").write_text(json.dumps({"kind": "all-exhausted", "detail": SPARE}))
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=False, runner=run) == ["rotation-stuck"]
    assert SPARE not in json.dumps(run.argvs) and SPARE not in (root / ra.ALERT_NAME).read_text()


def test_debounce_is_hourly_per_condition_and_keeps_first_seen(root: Path) -> None:
    """An unchanged condition re-notifies only after an hour; first_seen is preserved."""
    (root / "rotation-stuck.json").write_text("{}")
    run = Runner()
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    ra.evaluate(root, now=NOW + 600, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    ra.evaluate(root, now=NOW + 3601, claude_running=False, runner=run)
    assert len(run.argvs) == 2
    saved = json.loads((root / ra.ALERT_NAME).read_text())["alerts"]["rotation-stuck"]
    assert saved["first_seen"] == int(NOW) and saved["last_notified"] == int(NOW + 3601)


def test_alert_file_is_cleared_when_the_condition_clears(root: Path) -> None:
    """Once nothing holds, rotator-alert.json is removed."""
    stuck = root / "rotation-stuck.json"
    stuck.write_text("{}")
    ra.evaluate(root, now=NOW, claude_running=False, runner=Runner())
    assert (root / ra.ALERT_NAME).exists()
    stuck.unlink()
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=Runner())
    assert not (root / ra.ALERT_NAME).exists()


def test_real_fake_osascript_executable_receives_the_notification(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real executable named osascript first on PATH is invoked through the default runner."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    out = tmp_path / "argv.txt"
    exe = bindir / "osascript"
    exe.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{out}"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    (root / "rotation-stuck.json").write_text("{}")
    ra.evaluate(root, now=NOW, claude_running=False)
    lines = out.read_text().splitlines()
    assert lines[0] == "-e" and lines[1].startswith("display notification")


def test_scheduled_rotator_task_is_the_tick_plus_alarm() -> None:
    """The registered `oauth-rotator-tick` Task runs the beat (tick + alarm), not the bare tick."""
    import daemon  # type: ignore[import-not-found]

    task = {t.name: t for t in daemon._build_tasks()}["oauth-rotator-tick"]
    assert task.fn is daemon.task_oauth_rotator_beat


def test_the_daemon_beat_writes_the_alert_file_for_a_stuck_rotator(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task_oauth_rotator_beat evaluates the alarm after the tick (rotator subprocess stubbed)."""
    import daemon  # type: ignore[import-not-found]

    (root / "opt-in.flag").write_text("")
    (root / "rotation-stuck.json").write_text("{}")
    monkeypatch.setattr(daemon.oauth_supervisor, "_rotator_root", lambda: root)
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    monkeypatch.setattr(daemon, "_run_workload", lambda *a, **k: None)
    monkeypatch.setattr(daemon.notify, "_deliver", lambda *a, **k: None)
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda **_k: [])
    daemon.task_oauth_rotator_beat()
    assert "rotation-stuck" in json.loads((root / ra.ALERT_NAME).read_text())["alerts"]


# ---------- dispatch: the drift line is printed even under a live summary hold ----------


def test_dispatch_prints_the_alert_line_before_a_live_summary_hold(
    env_isolation: dict,  # noqa: F811 -- the imported fixture
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live hold + an alert file: main() returns at the hold but the drift line is out."""
    home = tmp_path / "rot-home"
    home.mkdir()
    (home / "state.json").write_text(json.dumps({"slots": {}}))
    (home / ra.ALERT_NAME).write_text(
        json.dumps({"alerts": {"rotation-stuck": {"first_seen": 1, "last_notified": 1,
                                                  "action": "account rotation is stuck - run /janitor-capture-all-logins"}}})
    )
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    dispatch = _import_dispatch()
    import state

    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    _arm_summary_hold(sd, expires_in_s=900)
    out = _run_main(dispatch)
    assert "rotator alert: account rotation is stuck - run /janitor-capture-all-logins" in out, out
    assert "summary hold" not in out


def test_dispatch_prints_nothing_without_an_alert_file(
    env_isolation: dict,  # noqa: F811 -- the imported fixture
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rotator-alert.json: the phase is silent."""
    home = tmp_path / "rot-home"
    home.mkdir()
    (home / "state.json").write_text(json.dumps({"slots": {}}))
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    dispatch = _import_dispatch()
    import state

    state.state_dir().mkdir(parents=True, exist_ok=True)
    _arm_summary_hold(state.state_dir(), expires_in_s=900)
    assert "rotator alert" not in _run_main(dispatch)
