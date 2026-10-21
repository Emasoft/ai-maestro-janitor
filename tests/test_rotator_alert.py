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
import time
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


def _stuck(root: Path, at: float = NOW, **fields: object) -> None:
    """Write a rotation-stuck marker the way the rotator does: kind plus a last_seen_epoch."""
    payload = {"kind": "no-usable-slot-twin", "detail": SPARE, "first_seen_epoch": int(at), "last_seen_epoch": int(at)}
    payload.update(fields)
    (root / "rotation-stuck.json").write_text(json.dumps(payload))


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
    assert saved["alerts"]["no-rotation-target"]["first_seen"] == int(NOW)


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
    # all-exhausted kind is never produced, so the test passed on a value production never emits.
    _stuck(root, NOW - 10)
    run = Runner()
    assert ra.evaluate(root, now=NOW, claude_running=False, runner=run) == ["rotation-stuck"]
    assert ra.active_conditions(root, NOW, False)["rotation-stuck"] == ra._ACTIONS["rotation-stuck"]
    assert ra._ACTIONS["rotation-stuck"] in (root / ra.ALERT_NAME).read_text()
    assert SPARE not in json.dumps(run.argvs) and SPARE not in (root / ra.ALERT_NAME).read_text()


def test_stuck_alert_for_all_accounts_maxed_says_wait_not_capture(root: Path) -> None:
    """A stuck marker of kind all-accounts-maxed tells the owner to wait, not to capture logins."""
    _stuck(root, NOW, kind="all-accounts-maxed", detail="x")
    text = ra.active_conditions(root, NOW, False)["rotation-stuck"]
    assert text == ra._STUCK_ALL_MAXED_TEXT
    assert "capture-all-logins" not in text


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("all-accounts-maxed", ra._STUCK_ALL_MAXED_TEXT),
        ("no-alternates-configured", "no second account to rotate to - add another paid account"),
        (
            "expired-and-offline",
            "the login expired and the API is unreachable - check the network, then run /login",
        ),
        (
            "identity-unknowable",
            "the live login cannot be identified - start one interactive Claude session, or run /login",
        ),
        ("no-usable-slot-twin", ra._ACTIONS["rotation-stuck"]),
        ("some-new-kind", ra._ACTIONS["rotation-stuck"]),
    ],
)
def test_stuck_alert_text_per_kind(root: Path, kind: str, expected: str) -> None:
    """Each stuck kind a login capture cannot repair names its own remedy; the rest keep the generic text."""
    _stuck(root, NOW, kind=kind)
    text = ra.active_conditions(root, NOW, False)["rotation-stuck"]
    assert text == expected
    if kind in ("no-alternates-configured", "expired-and-offline", "identity-unknowable"):
        assert "capture-all-logins" not in text


def test_stuck_marker_older_than_an_hour_does_not_alert_but_a_fresh_one_does(root: Path) -> None:
    """TRDD-7T4J5T6Z: a marker last seen 2 h ago (recovered or stopped rotator) raises nothing; a fresh one does."""
    _stuck(root, NOW - 7200)
    assert "rotation-stuck" not in ra.active_conditions(root, NOW, False)
    _stuck(root, NOW - 60)
    assert "rotation-stuck" in ra.active_conditions(root, NOW, False)


def test_stuck_marker_without_a_kind_or_unreadable_does_not_alert(root: Path) -> None:
    """TRDD-7T4J5T6Z: a kindless, last_seen-less or truncated marker is not a verdict the rotator wrote."""
    for content in ("{}", json.dumps({"kind": "no-usable-slot-twin"}), "{\"kind\": \"all-acc"):
        (root / "rotation-stuck.json").write_text(content)
        assert "rotation-stuck" not in ra.active_conditions(root, NOW, False)


def test_an_unchanged_condition_notifies_once_and_never_repeats(root: Path) -> None:
    """USER ruling 2026-10-21: a condition already notified is NEVER notified again while it
    holds - not after 1 h, not daily. Over 5 days of evaluations exactly one notification goes
    out, the alert file keeps updating and first_seen is preserved."""
    run = Runner()

    def ev(t: float) -> None:
        _stuck(root, t)  # the live rotator rewrites last_seen_epoch every stuck tick
        ra.evaluate(root, now=t, claude_running=False, runner=run)

    ev(NOW)
    # Evaluated every 10 min for 5 days (the daemon runs every minute; the condition is never
    # absent, so it is never a new episode).
    for t in range(int(NOW) + 600, int(NOW) + 5 * 86400, 600):
        ev(t)
    assert len(run.argvs) == 1
    saved = json.loads((root / ra.ALERT_NAME).read_text())["alerts"]["rotation-stuck"]
    assert saved["first_seen"] == int(NOW) and "last_notified" not in saved


def test_no_spare_account_for_days_gives_one_banner(root: Path) -> None:
    """Condition (a) held for 3 days, evaluated every minute: ONE banner, not ~72."""
    _write_state(root, live_exp_s=NOW - 3600, spare_exp_s=NOW - 60)
    run = Runner()
    for i in range(3 * 24 * 60):
        t = NOW + i * 60
        _stamp(root, t - 30)
        ra.evaluate(root, now=t, claude_running=True, runner=run)
    assert len(run.argvs) == 1


def test_a_change_of_the_condition_set_notifies_immediately(root: Path) -> None:
    """A second condition appearing inside the backoff window notifies at once."""
    _write_state(root, live_exp_s=NOW - 3600, spare_exp_s=NOW - 60)
    _fresh_tick(root)
    run = Runner()
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    n = len(run.argvs)
    _stuck(root, NOW + 60)
    _fresh_tick(root, NOW + 60)
    ra.evaluate(root, now=NOW + 60, claude_running=True, runner=run)
    assert len(run.argvs) > n


def test_a_condition_that_flaps_follows_the_backoff(root: Path) -> None:
    """Active -> notified; cleared; back within DEBOUNCE_S -> NOT notified; gone and back after
    DEBOUNCE_S -> notified (shared-login sessions flip the auth-failed marker on and off)."""
    stuck = root / "rotation-stuck.json"
    run = Runner()
    _stuck(root, NOW)
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    stuck.unlink()
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=run)
    _stuck(root, NOW + 120)
    ra.evaluate(root, now=NOW + 120, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    stuck.unlink()
    ra.evaluate(root, now=NOW + 180, claude_running=False, runner=run)
    ra.evaluate(root, now=NOW + 180 + ra.DEBOUNCE_S + 1, claude_running=False, runner=run)
    _stuck(root, NOW + 180 + ra.DEBOUNCE_S + 2)
    ra.evaluate(root, now=NOW + 180 + ra.DEBOUNCE_S + 2, claude_running=False, runner=run)
    assert len(run.argvs) == 2


def test_alert_file_is_cleared_when_the_condition_clears(root: Path) -> None:
    """Once nothing holds, rotator-alert.json is removed."""
    stuck = root / "rotation-stuck.json"
    _stuck(root, NOW)
    ra.evaluate(root, now=NOW, claude_running=False, runner=Runner())
    assert (root / ra.ALERT_NAME).exists()
    stuck.unlink()
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=Runner())
    assert not (root / ra.ALERT_NAME).exists()


def test_a_second_account_is_its_own_episode_and_neither_repeats(root: Path) -> None:
    """The episode key includes the slot (USER ruling 2026-10-21): a refused capture on account A
    does not silence account B, and neither one is ever notified twice while it holds."""
    run = Runner()
    ra.record_capture_refused(root, "a.person@example.test", "other@example.test", NOW)
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    ra.record_capture_refused(root, "b.person@example.test", None, NOW + 60)
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=run)
    assert len(run.argvs) == 2
    for t in range(int(NOW) + 120, int(NOW) + 5 * 3600, 300):
        ra.evaluate(root, now=t, claude_running=False, runner=run)
    assert len(run.argvs) == 2


def test_a_new_stuck_kind_is_a_new_episode_but_the_same_kind_is_not(root: Path) -> None:
    """Episode key = condition + kind: all-accounts-maxed then expired-and-offline notifies twice."""
    run = Runner()
    _stuck(root, NOW, kind="all-accounts-maxed")
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    _stuck(root, NOW + 60, kind="all-accounts-maxed")
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    _stuck(root, NOW + 120, kind="expired-and-offline")
    ra.evaluate(root, now=NOW + 120, claude_running=False, runner=run)
    assert len(run.argvs) == 2


def test_a_flapping_verdict_is_one_episode_until_absent_longer_than_the_flap_window(root: Path) -> None:
    """A verdict that disappears and returns within the flap window stays ONE episode (one
    notification); after it was absent longer than the window it is a new episode."""
    stuck = root / "rotation-stuck.json"
    run = Runner()
    _stuck(root, NOW)
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    stuck.unlink()
    for t in range(int(NOW) + 60, int(NOW) + 3000, 60):  # absent for 49 min: shorter than the window
        ra.evaluate(root, now=t, claude_running=False, runner=run)
    _stuck(root, NOW + 3000)
    ra.evaluate(root, now=NOW + 3000, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    stuck.unlink()
    # absent for far longer than the flap window plus the record freshness
    for t in range(int(NOW) + 3060, int(NOW) + 3000 + 2 * ra.DEBOUNCE_S + ra.REMEDIATION_FRESH_S, 300):
        ra.evaluate(root, now=t, claude_running=False, runner=run)
    t_back = NOW + 3000 + 2 * ra.DEBOUNCE_S + ra.REMEDIATION_FRESH_S
    _stuck(root, t_back)
    ra.evaluate(root, now=t_back, claude_running=False, runner=run)
    assert len(run.argvs) == 2


def test_the_episode_survives_a_daemon_restart(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second process (a restarted or handed-over daemon) reads the sent-record on disk and does
    not notify the same episode again. Real executables: a fake osascript counts the banners."""
    import subprocess

    bindir = tmp_path / "bin"
    bindir.mkdir()
    out = tmp_path / "banners.txt"
    exe = bindir / "osascript"
    exe.write_text(f'#!/bin/sh\necho banner >> "{out}"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    _stuck(root, NOW)
    ra.evaluate(root, now=NOW, claude_running=False)
    assert out.read_text().count("banner") == 1
    code = (
        "import sys; sys.path[:0] = [sys.argv[1]]; import rotator_alert as ra; "
        "from pathlib import Path; "
        "ra.evaluate(Path(sys.argv[2]), now=float(sys.argv[3]), claude_running=False)"
    )
    subprocess.run(
        [sys.executable, "-I", "-c", code, str(_ROOT / "scripts" / "lib"), str(root), str(NOW + 600)],
        check=True, capture_output=True, timeout=60,
    )
    assert out.read_text().count("banner") == 1


def test_a_detector_record_is_notified_once_by_the_daemon_evaluation(root: Path) -> None:
    """The oauth-login-needed detector only records; the daemon's evaluation notifies each fresh
    record once and ignores a stale or malformed one."""
    run = Runner()
    ra.record_owner_remediation(
        root, "oauth-login-needed", "account x needs a one-time login (expired)", NOW, kind="expired", slot="x@example.test"
    )
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    assert len(run.argvs) == 1 and "one-time login" in run.argvs[0][2]
    for t in range(int(NOW) + 60, int(NOW) + 1500, 60):  # the detector refreshes its record
        ra.record_owner_remediation(
            root, "oauth-login-needed", "account x needs a one-time login (expired)", t, kind="expired", slot="x@example.test"
        )
        ra.evaluate(root, now=t, claude_running=False, runner=run)
    assert len(run.argvs) == 1
    # a record nobody refreshed any more is a condition that went away: never notified again
    stale = NOW + 10 * 86400
    ra.record_owner_remediation(root, "other", "another action", NOW, slot="y")
    (root / ra.OWNER_REMEDIATION_NAME).write_text(
        json.dumps({"conditions": {"junk": "not-a-record", "old": {"condition": "old", "action": "old action", "last_seen": int(NOW)}}})
    )
    ra.evaluate(root, now=stale, claude_running=False, runner=run)
    assert len(run.argvs) == 1


def test_session_side_tick_stalled_shares_the_daemons_episode(root: Path) -> None:
    """A hung or dead daemon cannot notify, so a heartbeat session does - under the SAME episode
    key as the daemon's own evaluation: any number of sessions plus the daemon raise ONE
    notification, and a fresh or absent tick stamp raises none."""
    (root / "opt-in.flag").touch()
    run = Runner()
    assert ra.notify_session_tick_stalled(root, NOW, runner=run) is None  # no stamp at all
    _stamp(root, NOW - 30)
    assert ra.notify_session_tick_stalled(root, NOW, runner=run) is None  # fresh tick
    _stamp(root, NOW - 700)
    for _ in range(5):  # five sessions' heartbeats
        ra.notify_session_tick_stalled(root, NOW + 1, runner=run)
    assert len(run.argvs) == 1 and "janitor-doctor" in run.argvs[0][2]
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=NOW + 7200)
    assert "tick-stalled" in ra.evaluate(root, now=NOW + 60, claude_running=True, runner=run)
    assert len(run.argvs) == 1  # the daemon's own evaluation does not add a second copy


def test_session_side_tick_stalled_is_silent_without_the_opt_in_flag(root: Path) -> None:
    """No opt-in flag means the rotator never ticks on this machine: a stale or missing stamp is
    not a stall, so the session-side watchdog must not raise a false alarm (the daemon gates the
    same way)."""
    run = Runner()
    _stamp(root, NOW - 5000)
    assert ra.notify_session_tick_stalled(root, NOW, runner=run) is None
    assert run.argvs == []


def test_session_side_tick_stalled_is_silent_while_the_server_owns_the_tick(root: Path) -> None:
    """While the ai-maestro server owns the rotator tick its stamp is not ours to judge."""
    (root / "opt-in.flag").touch()
    run = Runner()
    _stamp(root, NOW - 5000)
    assert ra.notify_session_tick_stalled(root, NOW, server_owns_tick=True, runner=run) is None
    assert run.argvs == []
    assert ra.notify_session_tick_stalled(root, NOW, server_owns_tick=False, runner=run) is not None
    assert len(run.argvs) == 1


def test_a_fresh_tick_seen_by_a_session_ends_the_tick_stalled_episode(root: Path) -> None:
    """A fresh stamp is an OBSERVED clear: the next stall, after the flap window, notifies again."""
    from notify import EPISODE_FLAP_S  # type: ignore[import-not-found]

    (root / "opt-in.flag").touch()
    run = Runner()
    _stamp(root, NOW - 700)
    ra.notify_session_tick_stalled(root, NOW, runner=run)
    _stamp(root, NOW + 10)  # the daemon ticked again
    assert ra.notify_session_tick_stalled(root, NOW + 20, runner=run) is None
    later = NOW + 20 + EPISODE_FLAP_S + 1
    _stamp(root, later - 700)
    ra.notify_session_tick_stalled(root, later, runner=run)
    assert len(run.argvs) == 2


def test_a_gap_in_observation_is_not_a_clear_for_the_daemon_conditions(root: Path) -> None:
    """The same unchanged condition re-evaluated hours or days later (sparse callers) never
    notifies a second time: only an observation of the condition GONE ends an episode."""
    _stuck(root, NOW)
    run = Runner()
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    for gap in (2400, 3600 * 3, 3 * 86400):
        _stuck(root, NOW + gap)
        ra.evaluate(root, now=NOW + gap, claude_running=False, runner=run)
    assert len(run.argvs) == 1


def test_an_observed_clear_then_a_return_after_the_flap_window_notifies_again(root: Path) -> None:
    """evaluate observes the stuck marker gone (record deleted, episode ended); the same verdict
    back after the flap window is a new episode, back inside it is not."""
    run = Runner()
    _stuck(root, NOW)
    ra.evaluate(root, now=NOW, claude_running=False, runner=run)
    (root / "rotation-stuck.json").unlink()
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=run)
    assert not [c for c in json.loads((root / ra.OWNER_REMEDIATION_NAME).read_text())["conditions"]]
    back = NOW + 60 + ra.DEBOUNCE_S + 1
    _stuck(root, back)
    ra.evaluate(root, now=back, claude_running=False, runner=run)
    assert len(run.argvs) == 2


def test_a_pass_that_could_not_observe_a_condition_does_not_clear_it(root: Path) -> None:
    """Without a running claude the no-rotation-target check is not made at all: that is a gap in
    observation, not a clear, so the record survives and the return does not renotify."""
    _write_state(root, live_exp_s=NOW + 3600, spare_exp_s=None)
    _fresh_tick(root)
    run = Runner()
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    ra.evaluate(root, now=NOW + 60, claude_running=False, runner=run)
    recs = json.loads((root / ra.OWNER_REMEDIATION_NAME).read_text())["conditions"]
    assert "no-rotation-target" in recs
    _fresh_tick(root, NOW + 60 + ra.DEBOUNCE_S + 1)
    ra.evaluate(root, now=NOW + 60 + ra.DEBOUNCE_S + 1, claude_running=True, runner=run)
    assert len(run.argvs) == 1


def test_concurrent_remediation_writers_lose_no_record(root: Path) -> None:
    """The detector of every session and the daemon thread write owner-remediation.json: the
    read-modify-write is flock-guarded, so 16 writers keep all 16 records."""
    import threading

    def write(i: int) -> None:
        for n in range(5):
            ra.record_owner_remediation(root, "oauth-login-needed", "act", NOW + n, kind="k", slot=f"s{i}")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    recs = json.loads((root / ra.OWNER_REMEDIATION_NAME).read_text())["conditions"]
    assert len(recs) == 16


def test_one_record_per_condition_and_slot_a_new_kind_supersedes_the_old(root: Path) -> None:
    ra.record_owner_remediation(root, "oauth-login-needed", "a", NOW, kind="48h", slot="x@y")
    ra.record_owner_remediation(root, "oauth-login-needed", "b", NOW, kind="24h", slot="x@y")
    ra.record_owner_remediation(root, "oauth-login-needed", "c", NOW, kind="48h", slot="z@y")
    recs = json.loads((root / ra.OWNER_REMEDIATION_NAME).read_text())["conditions"]
    assert set(recs) == {"oauth-login-needed:24h:x@y", "oauth-login-needed:48h:z@y"}



def _auth_records(root: Path) -> dict:
    return json.loads((root / ra.OWNER_REMEDIATION_NAME).read_text())["conditions"]


def test_an_aged_but_present_auth_failed_marker_is_not_a_clear(root: Path) -> None:
    """A marker past its 6 h TTL is not an observation of recovery: the record and the open
    episode survive, so the same failure later does not pop a second banner."""
    _write_state(root, live_exp_s=NOW + 30 * 86400, spare_exp_s=NOW + 30 * 86400)
    ra.record_auth_failed(root, "authentication_failed", NOW)
    run = Runner()
    _fresh_tick(root)
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    later = NOW + 7 * 3600
    _fresh_tick(root, later)
    ra.evaluate(root, now=later, claude_running=True, runner=run)
    assert "auth-failed" in _auth_records(root)
    again = later + ra.DEBOUNCE_S + 1
    ra.record_auth_failed(root, "authentication_failed", again)
    _fresh_tick(root, again)
    ra.evaluate(root, now=again, claude_running=True, runner=run)
    assert len(run.argvs) == 1


def test_an_absent_auth_failed_marker_is_a_clear_and_a_new_failure_notifies_once(root: Path) -> None:
    """The Stop hook removed the marker: observed gone. The record goes and a failure after the
    flap window is a new episode notified exactly once."""
    _write_state(root, live_exp_s=NOW + 30 * 86400, spare_exp_s=NOW + 30 * 86400)
    ra.record_auth_failed(root, "authentication_failed", NOW)
    run = Runner()
    _fresh_tick(root)
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    ra.clear_auth_failed(root)
    ra.evaluate(root, now=NOW + 60, claude_running=True, runner=run)
    assert "auth-failed" not in _auth_records(root)
    again = NOW + 60 + ra.DEBOUNCE_S + 1
    ra.record_auth_failed(root, "authentication_failed", again)
    _fresh_tick(root, again)
    ra.evaluate(root, now=again, claude_running=True, runner=run)
    ra.evaluate(root, now=again + 30, claude_running=True, runner=run)
    assert len(run.argvs) == 2


def test_a_moved_live_account_or_expiry_is_a_clear_for_auth_failed(root: Path) -> None:
    """The live account or its slot expiry moved (a rotation, or a token renewal on the same
    account, which changes live_exp): the marker no longer describes the live login."""
    _write_state(root, live_exp_s=NOW + 30 * 86400, spare_exp_s=NOW + 30 * 86400)
    ra.record_auth_failed(root, "authentication_failed", NOW)
    run = Runner()
    _fresh_tick(root)
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    _write_state(root, live_exp_s=NOW + 9000, spare_exp_s=NOW + 7200)
    ra.evaluate(root, now=NOW + 60, claude_running=True, runner=run)
    assert "auth-failed" not in _auth_records(root)


def test_an_aged_but_present_capture_refused_marker_is_not_a_clear_but_an_absent_one_is(root: Path) -> None:
    """The 6 h cooldown only stops the alarm; the refusal clears when its marker file is gone."""
    _write_state(root, live_exp_s=NOW + 30 * 86400, spare_exp_s=NOW + 30 * 86400)
    ra.record_capture_refused(root, SPARE, "other@example.test", NOW)
    run = Runner()
    _fresh_tick(root)
    ra.evaluate(root, now=NOW, claude_running=True, runner=run)
    later = NOW + 7 * 3600
    _fresh_tick(root, later)
    ra.evaluate(root, now=later, claude_running=True, runner=run)
    assert any(k.startswith("capture-refused") for k in _auth_records(root))
    ra.clear_capture_refused(root, SPARE)
    ra.evaluate(root, now=later + 60, claude_running=True, runner=run)
    assert not any(k.startswith("capture-refused") for k in _auth_records(root))


def test_clear_owner_remediations_only_clears_observed_slots(root: Path) -> None:
    ra.record_owner_remediation(root, "oauth-login-needed", "a", NOW, kind="k", slot="seen@y")
    ra.record_owner_remediation(root, "oauth-login-needed", "b", NOW, kind="k", slot="unseen@y")
    ra.clear_owner_remediations(root, "oauth-login-needed", NOW, observed_slots=frozenset({"seen@y"}))
    assert set(_auth_records(root)) == {"oauth-login-needed:k:unseen@y"}


def test_evaluate_prunes_a_week_old_record_and_ends_its_episode(root: Path) -> None:
    """Backstop: an episode that can never be observed clear would suppress every later
    notification forever. A record not re-seen for 7 days is pruned by a quiet daemon pass and
    its episode cleared, so a new occurrence notifies once."""
    run = Runner()
    ra.record_owner_remediation(root, "oauth-login-needed", "act", NOW, kind="k", slot="s@y")
    ra.notify_new_remediations(root, NOW, runner=run)
    assert len(run.argvs) == 1
    later = NOW + 8 * 86400
    _write_state(root, live_exp_s=later + 3600, spare_exp_s=later + 7200)
    ra.evaluate(root, now=later, claude_running=False, runner=run)
    assert _auth_records(root) == {}
    again = later + ra.DEBOUNCE_S + 1
    ra.record_owner_remediation(root, "oauth-login-needed", "act", again, kind="k", slot="s@y")
    ra.notify_new_remediations(root, again, runner=run)
    assert len(run.argvs) == 2


def test_the_alert_thread_evaluates_once_at_start_before_waiting(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restarted daemon must evaluate at once, not one interval later."""
    import daemon  # type: ignore[import-not-found]

    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    calls: list[bool] = []
    alerter = daemon._RotatorAlertThread(eval_fn=calls.append, interval_s=3600)
    alerter.start()
    try:
        deadline = time.time() + 10
        while not calls and time.time() < deadline:
            time.sleep(0.02)
        assert calls, "no pass at thread start"
        time.sleep(0.3)
        assert len(calls) == 1, "then it must wait the interval, not spin"
    finally:
        alerter.shutdown(5)


def test_the_first_pass_does_not_judge_a_server_owned_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first pass runs before the main loop has published the yield state: the pass must ask
    the same predicate the daemon uses, or a server-owned tick stamp raises a false tick-stalled."""
    import daemon  # type: ignore[import-not-found]

    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    monkeypatch.setattr(daemon.oauth_supervisor, "_server_owns_chores", lambda: True)
    calls: list[bool] = []
    daemon._RotatorAlertThread(eval_fn=calls.append).run_once()
    assert calls == [False]


def test_every_condition_is_recorded_as_an_owner_remediation(root: Path) -> None:
    """tick-stalled included: no condition is agent-visible any more (USER ruling 2026-10-21)."""
    _write_state(root, live_exp_s=NOW + 1000, spare_exp_s=None)
    _stamp(root, NOW - ra.TICK_STALL_S - 1)
    _stuck(root, NOW, kind="all-accounts-maxed")
    ra.evaluate(root, now=NOW, claude_running=True, runner=Runner())
    conditions = json.loads((root / ra.OWNER_REMEDIATION_NAME).read_text())["conditions"]
    assert {"no-rotation-target", "tick-stalled", "rotation-stuck:all-accounts-maxed"} <= set(conditions)


def _patch_alert_thread_world(daemon: object, monkeypatch: pytest.MonkeyPatch, root: Path) -> list[str]:
    """Point the daemon's alert pass at `root` with a rotator that says claude is running; return
    the list the notifier appends to (no real popup)."""
    delivered: list[str] = []

    class _Rot:
        @staticmethod
        def claude_running() -> bool:
            return True

    monkeypatch.setattr(daemon.oauth_supervisor, "_rotator_root", lambda: root)  # type: ignore[attr-defined]
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)  # type: ignore[attr-defined]
    monkeypatch.setattr(daemon.oauth_supervisor, "_rotator_module", lambda: _Rot)  # type: ignore[attr-defined]
    monkeypatch.setattr(daemon.notify, "_deliver", lambda message, **_k: delivered.append(message))  # type: ignore[attr-defined]
    return delivered


def test_a_hung_tick_cannot_suppress_its_own_tick_stalled_alarm(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick thread is blocked inside the tick (hung); the separate alert thread still raises
    tick-stalled. Under the old design the evaluation ran AFTER the tick on the tick thread."""
    import threading

    import daemon  # type: ignore[import-not-found]

    _write_state(root, live_exp_s=time.time() + 3600, spare_exp_s=time.time() + 7200)
    _stamp(root, time.time() - 700)
    delivered = _patch_alert_thread_world(daemon, monkeypatch, root)
    release = threading.Event()
    monkeypatch.setattr(daemon, "task_oauth_rotator_tick", lambda: release.wait(30))
    tick_thread = threading.Thread(target=daemon.task_oauth_rotator_beat, daemon=True)
    tick_thread.start()
    alerter = daemon._RotatorAlertThread(interval_s=0.05)
    alerter.start()
    try:
        deadline = time.time() + 10
        while not delivered and time.time() < deadline:
            time.sleep(0.05)
        assert tick_thread.is_alive(), "the tick must still be hung"
        assert any("stopped ticking" in m for m in delivered), delivered
    finally:
        release.set()
        alerter.shutdown(5)
        tick_thread.join(5)


def test_the_alert_pass_skips_tick_stalled_while_the_server_owns_the_tick(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the ai-maestro server owns the rotator tick its stamp is not ours to judge: the pass
    still runs (the daemon stays the one notifier of every other condition) but raises no
    tick-stalled; once the tick is ours again it does."""
    import daemon  # type: ignore[import-not-found]

    _write_state(root, live_exp_s=time.time() + 3600, spare_exp_s=time.time() + 7200)
    _stamp(root, time.time() - 700)
    _stuck(root, time.time())
    delivered = _patch_alert_thread_world(daemon, monkeypatch, root)
    alerter = daemon._RotatorAlertThread()
    alerter.set_tick_yielded(True)
    alerter.run_once()
    assert len(delivered) == 1 and "stopped ticking" not in delivered[0]  # the stuck verdict only
    alerter.set_tick_yielded(False)
    alerter.run_once()
    assert len(delivered) == 2 and "stopped ticking" in delivered[1]


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
    _stuck(root, NOW)
    ra.evaluate(root, now=NOW, claude_running=False)
    lines = out.read_text().splitlines()
    assert lines[0] == "-e" and lines[1].startswith("display notification")


def test_scheduled_rotator_task_is_the_tick_only() -> None:
    """The registered `oauth-rotator-tick` Task runs the beat, which is the bare tick: the alarm
    lives on its own thread so a hung tick cannot suppress it."""
    import daemon  # type: ignore[import-not-found]

    task = {t.name: t for t in daemon._build_tasks()}["oauth-rotator-tick"]
    assert task.fn is daemon.task_oauth_rotator_beat
    ran: list[str] = []
    orig_tick, orig_eval = daemon.task_oauth_rotator_tick, daemon._evaluate_rotator_alert
    daemon.task_oauth_rotator_tick = lambda: ran.append("tick")  # type: ignore[assignment]
    daemon._evaluate_rotator_alert = lambda *a, **k: ran.append("eval")  # type: ignore[assignment]
    try:
        daemon.task_oauth_rotator_beat()
    finally:
        daemon.task_oauth_rotator_tick, daemon._evaluate_rotator_alert = orig_tick, orig_eval  # type: ignore[assignment]
    assert ran == ["tick"]


def test_the_alert_thread_pass_writes_the_alert_file_for_a_stuck_rotator(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One `_RotatorAlertThread` pass evaluates the alarm (no tick involved) and records the
    owner remediation."""
    import daemon  # type: ignore[import-not-found]

    (root / "opt-in.flag").write_text("")
    _stuck(root, time.time())  # the daemon evaluates at the real clock
    monkeypatch.setattr(daemon.oauth_supervisor, "_rotator_root", lambda: root)
    monkeypatch.setattr(daemon.notify, "_deliver", lambda *a, **k: None)
    daemon._RotatorAlertThread().run_once()
    assert "rotation-stuck" in json.loads((root / ra.ALERT_NAME).read_text())["alerts"]
    assert "rotation-stuck" in (root / ra.OWNER_REMEDIATION_NAME).read_text()


def test_the_daemon_logs_a_malformed_spare_stale_env_but_still_evaluates(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRDD-B78NJU35: a malformed ROTATOR_SPARE_STALE_AFTER_H leaves one daemon.log line (value
    capped at 32 chars) and the alarm evaluation still runs; a valid value logs nothing."""
    import daemon  # type: ignore[import-not-found]

    _stuck(root, time.time())  # the daemon evaluates at the real clock
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


def test_dispatch_excludes_owner_alert_before_a_live_summary_hold(
    env_isolation: dict,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live hold never leaks owner-only rotation telemetry into heartbeat stdout."""
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
    assert _run_main(dispatch) == ""


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


def _plant_runaway_kill(dispatch) -> None:
    """Plant a fresh runaway-kill broadcast: a drift line `main()` prints before the summary-hold
    gate, used as a positive control that the drift-printing stage ran."""
    import runaway_alert  # type: ignore[import-not-found]

    root = dispatch.gs.global_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    runaway_alert.record_kill(
        root,
        runaway_alert.kill_record(pid=4242, name="node", rss_mb=2100, age_s=7200, reason="test", readings="r"),
    )


def _assert_no_old_rotator_drift(out: str) -> None:
    """None of the three prefixes the removed rotator drift line / watchdog used."""
    for old in ("rotator alert:", "stopped ticking", "janitor-doctor"):
        assert old not in out, f"{old!r} found in {out!r}"


def test_dispatch_watchdog_prints_nothing_for_a_hung_daemon_without_an_alert_file(
    env_isolation: dict,  # noqa: F811 -- the imported fixture
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale tick and no alert file print none of the old rotator drift text (TRDD-1J9B7MWO);
    a planted runaway-kill line proves main() reached the drift-printing stage."""
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
    _plant_runaway_kill(dispatch)
    out = _run_main(dispatch)
    assert "pid 4242" in out, out  # positive control: drift lines DO print in this run
    _assert_no_old_rotator_drift(out)


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
    _stuck(root, NOW)
    active = ra.active_conditions(root, NOW, claude_running=True)
    assert "rotation-stuck" in active and "spare-stale" in active  # 5 h > the 4 h fallback


def test_spare_stale_notifies_once_per_episode(root: Path) -> None:
    """spare-stale notifies at first sight and never again while it holds."""
    run = Runner()
    for at in range(int(NOW), int(NOW) + 90000, 600):
        _fresh_tick(root, at)  # keep tick-stalled quiet so only spare-stale is counted
        # the slot expiries move with the clock, so the same condition holds the whole time
        _spare_state(root, live_exp_s=at, spares={SPARE: at - 5 * 3600, "healthy-spare": at + 3 * 3600})
        assert "spare-stale" in ra.evaluate(root, now=at, claude_running=True, runner=run)
        assert len(run.argvs) == 1


# ---------- dispatch: the advisory throttle (TRDD-MMWDSFB4, janitor#342) ----------

_ADV_TEXT = "a spare account has not been refreshed for hours - run /janitor-capture-all-logins to re-capture the stale spare account"
_URGENT_TEXT = "account rotation is stuck - run /janitor-capture-all-logins"
_STALL_TEXT = "the account rotator has stopped ticking - run /janitor-doctor"


def _fire_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(dispatch, rotator home, state module) with a live summary hold so each fire is cheap."""
    home = tmp_path / "rot-home"
    home.mkdir()
    (home / "state.json").write_text(json.dumps({"slots": {}}))
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    dispatch = _import_dispatch()
    import state

    state.state_dir().mkdir(parents=True, exist_ok=True)
    _arm_summary_hold(state.state_dir(), expires_in_s=900)
    return dispatch, home, state


def _set_alerts(home: Path, **conds: tuple[int, str]) -> None:
    """Write rotator-alert.json the way the daemon does: cond -> (last_notified, action)."""
    alerts = {c: {"first_seen": 1, "last_notified": last, "notified": 1, "action": action} for c, (last, action) in conds.items()}
    (home / ra.ALERT_NAME).write_text(json.dumps({"alerts": alerts}))


def test_advisory_never_prints_when_last_notified_advances(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Notification backoff changes remain control-plane-only on every heartbeat."""
    dispatch, home, _ = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"spare-stale": (100, _ADV_TEXT)})
    assert _run_main(dispatch) == ""
    _set_alerts(home, **{"spare-stale": (200, _ADV_TEXT)})
    assert _run_main(dispatch) == ""


def test_rotation_capacity_condition_never_prints(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """A rotation-capacity condition is owner-only despite its former urgent class."""
    dispatch, home, _ = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"rotation-stuck": (100, _URGENT_TEXT)})
    for _ in range(3):
        assert _run_main(dispatch) == ""


def test_rotation_capacity_plus_advisory_never_prints(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Mixed owner-only conditions cannot recreate a heartbeat payload."""
    dispatch, home, _ = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"rotation-stuck": (100, _URGENT_TEXT), "spare-stale": (100, _ADV_TEXT)})
    assert _run_main(dispatch) == ""
    assert _run_main(dispatch) == ""


def test_advisory_text_change_stays_out_of_context(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Changing owner-only prose cannot bypass source-aware exclusion."""
    dispatch, home, _ = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"spare-stale": (100, _ADV_TEXT)})
    assert _run_main(dispatch) == ""
    _set_alerts(home, **{"spare-stale": (100, _ADV_TEXT + " changed")})
    assert _run_main(dispatch) == ""


def test_advisory_clear_and_recurrence_stay_out_of_context(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """A recurrence remains owner-only regardless of prior advisory stamp state."""
    dispatch, home, _ = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"spare-stale": (100, _ADV_TEXT)})
    assert _run_main(dispatch) == ""
    _set_alerts(home)
    assert _run_main(dispatch) == ""
    _set_alerts(home, **{"spare-stale": (100, _ADV_TEXT)})
    assert _run_main(dispatch) == ""


def test_corrupt_advisory_stamp_cannot_leak_owner_text(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Corrupt legacy dedupe state cannot bypass the source-aware exclusion boundary."""
    dispatch, home, state = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"spare-stale": (100, _ADV_TEXT)})
    stamp = state.state_dir() / "rotator-alert-advisory-printed.txt"
    stamp.write_bytes(b"\xff\xfe")
    assert _run_main(dispatch) == ""


def test_tick_stalled_alert_file_and_stale_tick_watchdog_print_nothing(
    env_isolation: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """A present rotator-alert.json plus a stale tick put none of the old rotator drift text in
    the heartbeat (TRDD-1J9B7MWO); the runaway-kill positive control proves drift printing ran."""
    dispatch, home, _ = _fire_setup(tmp_path, monkeypatch)
    _set_alerts(home, **{"tick-stalled": (100, _STALL_TEXT)})
    _stamp(home, time.time() - 660)
    _plant_runaway_kill(dispatch)
    out = _run_main(dispatch)
    assert "pid 4242" in out, out
    _assert_no_old_rotator_drift(out)
