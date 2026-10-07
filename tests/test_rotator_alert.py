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
    _stamp(root, now - 30)



def _stamp(root: Path, at: float) -> None:
    p = root / "tick-completed.ts"
    p.write_text(str(int(at)))
    os.utime(p, (at, at))  # the evaluator reads the stamp's mtime


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


def test_stale_slot_twin_never_raises_live_token_expired(root: Path) -> None:
    """The live twin goes stale by design (never refreshed): an expiry 8 h ago must stay quiet."""
    _fresh_tick(root)
    _write_state(root, live_exp_s=NOW - 8 * 3600, spare_exp_s=NOW + 7200)
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=run) == []
    assert run.argvs == [] and not (root / ra.ALERT_NAME).exists()



def test_live_twin_with_future_expiry_is_not_a_rotation_target(root: Path) -> None:
    """The live account's own twin expires later, every spare is expired: still no target."""
    _fresh_tick(root)
    _write_state(root, live_exp_s=NOW + 7200, spare_exp_s=NOW - 60)
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=Runner()) == ["no-rotation-target"]


def test_auth_failed_marker_raises_a_banner_at_once_and_expires(root: Path) -> None:
    """A hook-written marker is an `auth-failed` condition that notifies immediately; it is
    gone after 6 h, and when the live slot expiry moves (a fresh login)."""
    _fresh_tick(root)
    _write_state(root, live_exp_s=NOW + 7200, spare_exp_s=NOW + 7200)
    ra.record_auth_failed(root, "authentication_failed", NOW)
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=run) == ["auth-failed"]
    assert len(run.argvs) == 1 and "/login" in run.argvs[0][2]
    assert "example.test" not in run.argvs[0][2]
    _write_state(root, live_exp_s=NOW + 9000, spare_exp_s=NOW + 7200)
    assert "auth-failed" not in ra.active_conditions(root, NOW + 60, True)
    _write_state(root, live_exp_s=NOW + 7200, spare_exp_s=NOW + 7200)
    assert "auth-failed" in ra.active_conditions(root, NOW + 5 * 3600, True)
    assert "auth-failed" not in ra.active_conditions(root, NOW + 6 * 3600 + 1, True)



def test_tick_stalled_only_while_claude_runs(root: Path) -> None:
    """No completed tick for 11 min fires with a claude session up, and not without one."""
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=NOW + 7200)
    (root / "tick-completed.ts").write_text(str(NOW - 660))
    _stamp(root, NOW - 660)
    assert ra.evaluate(root, now=NOW, claude_running=False, runner=Runner()) == []
    assert ra.evaluate(root, now=NOW, claude_running=True, runner=Runner()) == ["tick-stalled"]


def test_rotation_stuck_file_alerts_even_without_claude(root: Path) -> None:
    """rotation-stuck.json present: alert regardless of the session (it is already a verdict)."""
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=NOW + 7200)
    # TRDD-ZQ3GVI9Q: use a kind the rotator really writes (rotator.py _mark_stuck); the old
    # 'all-exhausted' is never produced, so the test passed on a value production never emits.
    (root / "rotation-stuck.json").write_text(json.dumps({"kind": "no-usable-slot-twin", "detail": SPARE}))
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=False, runner=run) == ["rotation-stuck"]
    assert ra.active_conditions(root, NOW, False)["rotation-stuck"] == ra._ACTIONS["rotation-stuck"]
    assert ra._ACTIONS["rotation-stuck"] in (root / ra.ALERT_NAME).read_text()
    assert SPARE not in json.dumps(run.argvs) and SPARE not in (root / ra.ALERT_NAME).read_text()



def test_stuck_alert_for_all_accounts_maxed_says_wait_not_capture(root: Path) -> None:
    """A stuck marker of kind all-accounts-maxed tells the owner to wait, not to capture logins."""
    (root / "rotation-stuck.json").write_text(
        json.dumps({"kind": "all-accounts-maxed", "detail": "x", "first_seen_epoch": 1, "last_seen_epoch": 1})
    )
    text = ra.active_conditions(root, NOW, False)["rotation-stuck"]
    assert text == "every account is at its usage limit - waiting for a window to reset"
    assert "capture-all-logins" not in text


def test_stuck_alert_for_other_kinds_keeps_the_capture_remedy(root: Path) -> None:
    """Control: no kind, another kind, or a truncated marker keeps the capture-logins text."""
    for content in ("{}", json.dumps({"kind": "no-usable-slot-twin"}), "{\"kind\": \"all-acc"):
        (root / "rotation-stuck.json").write_text(content)
        assert ra.active_conditions(root, NOW, False)["rotation-stuck"] == ra._ACTIONS["rotation-stuck"]


def test_banner_backoff_first_then_hourly_then_daily(root: Path) -> None:
    """Notify at first sight, again after 1 h, then at most once per 24 h; the file updates
    on every evaluation and first_seen is preserved."""
    (root / "rotation-stuck.json").write_text("{}")
    run = Runner()
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    ra.evaluate(root, now=NOW + 600, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    ra.evaluate(root, now=NOW + 3601, claude_running=False, runner=run)
    assert len(run.argvs) == 2
    ra.evaluate(root, now=NOW + 3601 + 7200, claude_running=False, runner=run)
    ra.evaluate(root, now=NOW + 3601 + 80000, claude_running=False, runner=run)
    assert len(run.argvs) == 2  # no 3rd banner inside 24 h of the 2nd
    ra.evaluate(root, now=NOW + 3601 + 86400, claude_running=False, runner=run)
    assert len(run.argvs) == 3
    saved = json.loads((root / ra.ALERT_NAME).read_text())["alerts"]["rotation-stuck"]
    assert saved["first_seen"] == int(NOW) and saved["last_notified"] == int(NOW + 3601 + 86400)



def test_no_spare_account_for_days_gives_a_handful_of_banners(root: Path) -> None:
    """Condition (a) held for 3 days, evaluated every minute: at most 5 banners, not ~72."""
    _write_state(root, live_exp_s=NOW - 3600, spare_exp_s=NOW - 60)
    run = Runner()
    for i in range(3 * 24 * 60):
        t = NOW + i * 60
        _stamp(root, t - 30)
        ra.evaluate(root, now=t, claude_running=True, runner=run)
    assert len(run.argvs) <= 5


def test_a_change_of_the_condition_set_notifies_immediately(root: Path) -> None:
    """A second condition appearing inside the backoff window notifies at once."""
    _write_state(root, live_exp_s=NOW - 3600, spare_exp_s=NOW - 60)
    _fresh_tick(root)
    run = Runner()
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    n = len(run.argvs)
    (root / "rotation-stuck.json").write_text("{}")
    _fresh_tick(root, NOW + 60)
    ra.evaluate(root, now=NOW + 60, claude_running=True, runner=run)
    assert len(run.argvs) > n



def test_a_condition_that_flaps_follows_the_backoff(root: Path) -> None:
    """Active -> notified; cleared; back within DEBOUNCE_S -> NOT notified; gone and back after
    DEBOUNCE_S -> notified (shared-login sessions flip the auth-failed marker on and off)."""
    stuck = root / "rotation-stuck.json"
    run = Runner()
    stuck.write_text("{}")
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    stuck.unlink()
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=run)
    stuck.write_text("{}")
    ra.evaluate(root, now=NOW + 120, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    stuck.unlink()
    ra.evaluate(root, now=NOW + 180, claude_running=False, runner=run)
    ra.evaluate(root, now=NOW + 180 + ra.DEBOUNCE_S + 1, claude_running=False, runner=run)
    stuck.write_text("{}")
    ra.evaluate(root, now=NOW + 180 + ra.DEBOUNCE_S + 2, claude_running=False, runner=run)
    assert len(run.argvs) == 2


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



def test_the_daemon_logs_a_malformed_spare_stale_env_but_still_evaluates(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRDD-B78NJU35: a malformed ROTATOR_SPARE_STALE_AFTER_H leaves one daemon.log line (value
    capped at 32 chars) and the alarm evaluation still runs; a valid value logs nothing."""
    import daemon  # type: ignore[import-not-found]

    (root / "rotation-stuck.json").write_text("{}")
    lines: list[str] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "_rotator_root", lambda: root)
    monkeypatch.setattr(daemon.notify, "_deliver", lambda *a, **k: None)
    monkeypatch.setattr(daemon.state, "log_line", lambda _name, msg: lines.append(msg))
    monkeypatch.setenv("ROTATOR_SPARE_STALE_AFTER_H", "12h" + "x" * 50)
    daemon._evaluate_rotator_alert()
    bad = [m for m in lines if "ROTATOR_SPARE_STALE_AFTER_H" in m]
    assert len(bad) == 1 and "is not a number; using 4 h" in bad[0] and "x" * 40 not in bad[0]
    assert "rotation-stuck" in json.loads((root / ra.ALERT_NAME).read_text())["alerts"]
    lines.clear()
    monkeypatch.setenv("ROTATOR_SPARE_STALE_AFTER_H", "6")
    daemon._evaluate_rotator_alert()
    assert not [m for m in lines if "ROTATOR_SPARE_STALE_AFTER_H" in m]



def test_the_daemon_logs_a_malformed_spare_stale_env_only_when_it_changes(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRDD-B78NJU35: the same bad value logs once, a different one again, valid-then-bad again."""
    import daemon  # type: ignore[import-not-found]

    lines: list[str] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "_rotator_root", lambda: root)
    monkeypatch.setattr(daemon.notify, "_deliver", lambda *a, **k: None)
    monkeypatch.setattr(daemon.state, "log_line", lambda _name, msg: lines.append(msg))

    def evaluate(value: str) -> int:
        monkeypatch.setenv("ROTATOR_SPARE_STALE_AFTER_H", value)
        lines.clear()
        daemon._evaluate_rotator_alert()
        return len([m for m in lines if "ROTATOR_SPARE_STALE_AFTER_H" in m])

    assert evaluate("6") == 0  # valid: resets the remembered value
    assert evaluate("abc") == 1
    assert evaluate("abc") == 0
    assert evaluate("abd") == 1
    assert evaluate("6") == 0
    assert evaluate("abd") == 1


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



def test_dispatch_watchdog_reports_a_hung_daemon_without_an_alert_file(
    env_isolation: dict,  # noqa: F811 -- the imported fixture
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No alert file, but the last completed tick is 11 min old: the session still prints it."""
    import time

    home = tmp_path / "rot-home"
    home.mkdir()
    (home / "state.json").write_text(json.dumps({"slots": {}}))
    _stamp(home, time.time() - 660)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    dispatch = _import_dispatch()
    import state

    state.state_dir().mkdir(parents=True, exist_ok=True)
    _arm_summary_hold(state.state_dir(), expires_in_s=900)
    assert "rotator alert: the account rotator has stopped ticking" in _run_main(dispatch)


def test_dispatch_watchdog_is_quiet_after_a_fresh_completed_tick(
    env_isolation: dict,  # noqa: F811 -- the imported fixture
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tick completed 30 s ago: no watchdog line."""
    import time

    home = tmp_path / "rot-home"
    home.mkdir()
    (home / "state.json").write_text(json.dumps({"slots": {}}))
    _stamp(home, time.time() - 30)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    dispatch = _import_dispatch()
    import state

    state.state_dir().mkdir(parents=True, exist_ok=True)
    _arm_summary_hold(state.state_dir(), expires_in_s=900)
    assert "rotator alert" not in _run_main(dispatch)



def _spare_state(root: Path, *, live_exp_s: float, spares: dict[str, float]) -> None:
    slots = {LIVE: {"expires_at": int(live_exp_s * 1000)}}
    slots.update({name: {"expires_at": int(exp * 1000)} for name, exp in spares.items()})
    (root / "state.json").write_text(json.dumps({"live_email": LIVE, "slots": slots}))


def test_spare_stale_fires_for_one_stale_spare_beside_a_healthy_one(root: Path) -> None:
    """TRDD-B78NJU35: a spare expired > 4 h ago raises spare-stale while a healthy spare keeps
    no-rotation-target silent; the text names the fix and no account."""
    _spare_state(root, live_exp_s=NOW - 36000, spares={SPARE: NOW - 5 * 3600, "healthy-spare": NOW + 3 * 3600})
    _fresh_tick(root)
    active = ra.active_conditions(root, NOW, claude_running=True)
    assert "spare-stale" in active and "no-rotation-target" not in active
    assert "/janitor-capture-all-logins" in active["spare-stale"] and SPARE not in active["spare-stale"]
    # only 3 h past expiry is inside the 4 h grace: no alarm
    _spare_state(root, live_exp_s=NOW, spares={SPARE: NOW - 3 * 3600, "healthy-spare": NOW + 3 * 3600})
    assert "spare-stale" not in ra.active_conditions(root, NOW, claude_running=True)


def test_spare_stale_never_counts_the_live_account(root: Path) -> None:
    """The live account's slot twin goes stale by design - it must not raise spare-stale."""
    _spare_state(root, live_exp_s=NOW - 10 * 3600, spares={"healthy-spare": NOW + 3 * 3600})
    assert "spare-stale" not in ra.active_conditions(root, NOW, claude_running=True)


def test_spare_stale_is_suppressed_by_no_rotation_target(root: Path) -> None:
    """When every spare is expired, no-rotation-target already says it: only that one fires."""
    _spare_state(root, live_exp_s=NOW, spares={SPARE: NOW - 5 * 3600})
    active = ra.active_conditions(root, NOW, claude_running=True)
    assert "no-rotation-target" in active and "spare-stale" not in active


def test_spare_stale_threshold_is_env_tunable(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ROTATOR_SPARE_STALE_AFTER_H moves the hours past expiry."""
    _spare_state(root, live_exp_s=NOW, spares={SPARE: NOW - 2 * 3600, "healthy-spare": NOW + 3 * 3600})
    assert "spare-stale" not in ra.active_conditions(root, NOW, claude_running=True)
    monkeypatch.setenv("ROTATOR_SPARE_STALE_AFTER_H", "1")
    assert "spare-stale" in ra.active_conditions(root, NOW, claude_running=True)



def test_bad_spare_stale_env_falls_back_to_4h_and_keeps_other_conditions(
        root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TRDD-B78NJU35: ROTATOR_SPARE_STALE_AFTER_H="12h" must not raise (the daemon's fail-open
    would drop every alarm): other conditions still report and spare-stale uses the 4 h default."""
    monkeypatch.setenv("ROTATOR_SPARE_STALE_AFTER_H", "12h")
    _spare_state(root, live_exp_s=NOW, spares={SPARE: NOW - 5 * 3600, "healthy-spare": NOW + 3 * 3600})
    (root / "rotation-stuck.json").write_text("{}")
    active = ra.active_conditions(root, NOW, claude_running=True)
    assert "rotation-stuck" in active and "spare-stale" in active  # 5 h > the 4 h fallback


def test_spare_stale_follows_the_due_backoff(root: Path) -> None:
    """spare-stale notifies at first sight, not again within the hour, and again after 1 h."""
    _spare_state(root, live_exp_s=NOW, spares={SPARE: NOW - 5 * 3600, "healthy-spare": NOW + 3 * 3600})
    run = Runner()
    for at, expected in ((NOW, 1), (NOW + 600, 1), (NOW + 3601, 2)):
        _fresh_tick(root, at)  # keep tick-stalled quiet so only spare-stale is counted
        assert "spare-stale" in ra.evaluate(root, now=at, claude_running=True, runner=run)
        assert len(run.argvs) == expected
