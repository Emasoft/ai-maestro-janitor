"""Tests for the daemon-owned rate-limit RESUME wake (TRDD-X07E7HTN, D1 v1).

The FREE half of the rate-limit recovery: for a non-frozen, injectable, rate-limited
instance the daemon types `/janitor-resume` (soft enqueue) and stamps `daemon-wake-covered.ts`
so that session's cron can leave the paid FAST poll (the MF4 arm handshake, read by dispatch).

Real policy + real per-project `detector.lock`; only two things are seams, both for a hard
reason, not convenience:

- ``gather_fleet`` is replaced with a fixed instance list — a live rate-limited session cannot
  be conjured in a unit test.
- ``fleet_inject.fire`` is replaced with a recorder — a test MUST NOT type ``/janitor-resume``
  into the developer's real terminals.

Everything else (the eligibility gate, the once-per-window dedupe, the coverage stamp, the
single-writer lock) runs for real against an isolated ``JANITOR_GLOBAL_STATE_DIR`` and tmp
project roots. The feature is DEFAULT-OFF, so every test opts in explicitly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import fleet_scan  # type: ignore[import-not-found]  # noqa: E402
import global_state as gs  # type: ignore[import-not-found]  # noqa: E402


def _inst(diagnosis: str, root: Path, terminal: dict, *, trailing: int = 0) -> "fleet_scan.Instance":
    """A synthetic Instance — only diagnosis / root / terminal / trailing matter here."""
    return fleet_scan.Instance(
        pid=1, command="claude", tty="ttys1", project_root=str(root), terminal=terminal,
        diagnosis=diagnosis, recovery=None, dispatch_age_s=None, active=False,
        transcript_age_s=None, trailing_enqueues=trailing,
    )


def _setup(monkeypatch, tmp_path: Path, fleet: list, *, enabled: str = "1", fire: str = "1") -> list:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", enabled)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED", fire)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_SESSION_LIVENESS_ENABLED", "1")
    # The path-resolution chain is @lru_cache'd — clear it so the FIRST test's tmp dir does not
    # pin log_dir for the whole process (mirrors test_daemon_session_liveness).
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()
    recorded: list = []
    monkeypatch.setattr(daemon.fleet_inject, "fire", lambda plan: bool(recorded.append(plan)) or True)
    monkeypatch.setattr(
        daemon.fleet_scan, "gather_fleet",
        lambda *, now, sweep_stale_rate_limit_s=None: fleet,
    )
    return recorded


def _rl(root: Path, *, since: int | None = 1000) -> Path:
    """Seed a project's rate-limited.flag (+ optional since) so the daemon sees a limited pane."""
    sd = root / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "rate-limited.flag").write_text("")
    if since is not None:
        (sd / "rate-limited-since.ts").write_text(str(since))
    return sd


def _resume_fires(recorded: list) -> list:
    return [p for p in recorded if p.get("command") == "/janitor-resume"]


def test_healthy_ratelimited_pane_gets_resume_and_coverage_stamp(tmp_path, monkeypatch) -> None:
    """The happy path: a non-frozen, injectable, rate-limited pane is sent /janitor-resume
    (soft), and the daemon stamps daemon-wake-covered.ts (coverage proof for the demotion) plus
    daemon-resume-wake.ts keyed on the window's `since` (the once-per-window dedupe)."""
    import time

    root = tmp_path / "proj"
    sd = _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    before = int(time.time())
    daemon.task_session_liveness()

    resumes = _resume_fires(fired)
    assert len(resumes) == 1
    assert resumes[0]["channel"] == "tmux"
    assert not any("Escape" in step for step in resumes[0]["steps"]), "the wake is SOFT (no ESC)"
    assert int((sd / "daemon-wake-covered.ts").read_text()) >= before  # coverage proven
    assert int((sd / "daemon-resume-wake.ts").read_text()) == 1000     # dedupe keyed on `since`


def test_feature_off_is_total_noop(tmp_path, monkeypatch) -> None:
    """DEFAULT-OFF: without the opt-in the pass injects nothing and stamps nothing — the cron
    remains the only trigger, exactly as before D1."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], enabled="0")
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (sd / "daemon-wake-covered.ts").exists()
    assert not (sd / "daemon-resume-wake.ts").exists()


def test_frozen_pane_gets_esc_only_never_a_resume_command(tmp_path, monkeypatch) -> None:
    """MF1: a `frozen` (rate-limited, wedged) pane is recovered ONLY by the recovery loop's
    ESC-only esc_nudge; the resume pass SKIPS it (diagnosis != healthy). A command is NEVER
    typed into a frozen pane — that is the flood (TRDD-P7WU40G9) — and no resume coverage is
    stamped for it."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("frozen", root, {"tmux_pane": "%5"})])
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []          # no /janitor-resume into a frozen pane
    assert [p["command"] for p in fired] == [""]  # only the ESC-only nudge from the recovery loop
    assert not (sd / "daemon-wake-covered.ts").exists()


def test_uninjectable_pane_gets_no_coverage_stamp(tmp_path, monkeypatch) -> None:
    """MF4 fail-open: an un-injectable pane (no resolvable terminal — plain / VS Code / ssh)
    cannot prove a wake, so NO coverage is stamped and dispatch keeps that session FAST (the
    cron is its only trigger)."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {})])  # empty terminal
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (sd / "daemon-wake-covered.ts").exists()


def test_server_owned_pane_is_hands_off(tmp_path, monkeypatch) -> None:
    """TRDD-X92VBFNF: a server_owned harness agent's continuity belongs to the ai-maestro
    server — the resume pass never injects into it (diagnosis != healthy)."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("server_owned", root, {"tmux_pane": "%5"})])
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (sd / "daemon-wake-covered.ts").exists()


def test_non_ratelimited_healthy_pane_is_untouched(tmp_path, monkeypatch) -> None:
    """A healthy pane with NO rate-limited.flag is not a wake target — nothing fires, nothing
    is stamped."""
    root = tmp_path / "proj"
    (root / ".janitor" / "state").mkdir(parents=True)  # exists, but no rate-limited.flag
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (root / ".janitor" / "state" / "daemon-wake-covered.ts").exists()


def test_resume_injected_once_per_window_coverage_restamped_each_beat(tmp_path, monkeypatch) -> None:
    """Dedupe: /janitor-resume is injected ONCE per rate-limit window (same `since` → no
    re-inject), but the coverage stamp is RE-STAMPED every beat so dispatch keeps the session
    demoted while the daemon keeps covering it."""
    root = tmp_path / "proj"
    sd = _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])

    daemon.task_session_liveness()  # beat 1: inject + stamp coverage
    assert len(_resume_fires(fired)) == 1
    (sd / "daemon-wake-covered.ts").write_text("1")  # simulate a stale stamp between beats

    daemon.task_session_liveness()  # beat 2: SAME window → no re-inject, but re-stamp coverage
    assert len(_resume_fires(fired)) == 1, "same window → NOT re-injected"
    assert int((sd / "daemon-wake-covered.ts").read_text()) > 1, "coverage re-stamped each beat"


def test_new_rate_limit_window_reinjects(tmp_path, monkeypatch) -> None:
    """A NEW rate-limit window (a new `since`) is a new window → the resume IS re-injected: a
    legitimately-repeated resume must not be swallowed by the dedupe."""
    root = tmp_path / "proj"
    sd = _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])

    daemon.task_session_liveness()
    assert len(_resume_fires(fired)) == 1
    (sd / "rate-limited-since.ts").write_text("2000")  # a NEW limit → a NEW window

    daemon.task_session_liveness()
    assert len(_resume_fires(fired)) == 2, "a new window re-injects /janitor-resume"
    assert int((sd / "daemon-resume-wake.ts").read_text()) == 2000


def test_dry_run_injects_nothing_and_stamps_no_coverage(tmp_path, monkeypatch) -> None:
    """FLEET_RECOVERY_ENABLED=0 (dry-run): the pass logs but injects nothing and stamps NO
    coverage — an unproven wake must never demote a session (dispatch keeps it FAST)."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], fire="0")
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (sd / "daemon-wake-covered.ts").exists()


def test_wedged_pane_with_queued_command_is_skipped(tmp_path, monkeypatch) -> None:
    """A queued-but-unexecuted command at the pane tail (trailing_enqueues) means a soft inject
    would only pile up (the 'janitor keeps printing commands' wedge) — the pass skips entirely
    and stamps no coverage."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"}, trailing=1)])
    daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (sd / "daemon-wake-covered.ts").exists()


def test_resume_wake_skips_when_detector_lock_held(tmp_path, monkeypatch) -> None:
    """MF3 single-writer: while the per-project detector.lock is held (by the cron, or a
    concurrent beat), the resume pass SKIPS — no inject, no stamp — so the daemon and the cron
    never race / double-write / corrupt dedupe."""
    root = tmp_path / "proj"
    sd = _rl(root)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    with gs.detector_lock(sd) as held:
        assert held is True
        daemon.task_session_liveness()
    assert _resume_fires(fired) == []
    assert not (sd / "daemon-wake-covered.ts").exists()


# --------------------------------------------------------------------------- #
# rotation-triggered wake (TRDD-UA4FAX67, owner failure report item 4)
# --------------------------------------------------------------------------- #
def test_a_fresh_rotation_wakes_the_pane_even_with_the_periodic_pass_OFF(
    tmp_path, monkeypatch
) -> None:
    """THE reported failure: the rotator swapped the credential successfully and the pane sat
    at the rate-limit UI anyway, so the owner pressed the key the rotation was supposed to make
    unnecessary. A rotation is positive, causal, freshly-timestamped evidence that the wall
    those panes are stuck behind was just removed — so it overrides the default-OFF knob that
    (correctly) suppresses the untriggered periodic sweep."""
    import time

    root = tmp_path / "proj"
    _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})],
                   enabled="0")
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()

    assert len(_resume_fires(fired)) == 1, "a rotation must unblock the panes it just fixed"


def test_the_control_no_rotation_and_the_knob_off_types_NOTHING(tmp_path, monkeypatch) -> None:
    """The control that gives the test above its meaning: same pane, same flag, no rotation.
    Without this, the assertion above would pass on a pass that simply always runs."""
    root = tmp_path / "proj"
    _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})],
                   enabled="0")
    daemon.task_session_liveness()

    assert _resume_fires(fired) == [], "the periodic sweep stays default-OFF"


def test_a_STALE_rotation_does_not_authorize_a_wake(tmp_path, monkeypatch) -> None:
    """The evidence expires. A rotation hours ago says nothing about a pane blocked now, and a
    stamp that never goes stale would silently convert the default-OFF pass into always-on for
    the rest of the daemon's life."""
    import time

    root = tmp_path / "proj"
    _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})],
                   enabled="0")
    gs.record_rotation_success(int(time.time()) - daemon._ROTATION_WAKE_WINDOW_S - 60)
    daemon.task_session_liveness()

    assert _resume_fires(fired) == []


def test_a_frozen_pane_is_still_NOT_command_injected_after_a_rotation(
    tmp_path, monkeypatch
) -> None:
    """MF1 / P7WU40G9 survives the new trigger: a frozen pane buffers a typed command on its
    retry-blocked input line and floods. ESC-only esc_nudge owns frozen panes, and a rotation
    must not become a back door around that."""
    import time

    root = tmp_path / "proj"
    _rl(root, since=1000)
    fired = _setup(monkeypatch, tmp_path, [_inst("frozen", root, {"tmux_pane": "%5"})],
                   enabled="0")
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()

    assert _resume_fires(fired) == [], "frozen panes are ESC-only, rotation or not"


def test_rotation_evidence_is_fail_CLOSED_on_absent_or_future_stamps(tmp_path, monkeypatch) -> None:
    """This gate types into a user's pane, so it acts only on positive evidence: no stamp, an
    unreadable one, or a future-dated one (clock skew / a bad write) all read as 'no rotation'."""
    import time

    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs2"))
    now = int(time.time())
    assert gs.rotation_succeeded_within(600, now=now) is False       # absent
    gs.record_rotation_success(now + 5_000)
    assert gs.rotation_succeeded_within(600, now=now) is False       # future-dated
    gs.record_rotation_success(now)
    assert gs.rotation_succeeded_within(600, now=now) is True        # the positive control
