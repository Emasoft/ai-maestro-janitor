"""Tests for the heartbeat cadence surface after TRDD-BRHJHWW0.

TRDD-0QQX9H0G's dynamic tier controller (`_phase_cadence_tier`, `[janitor-renew]` on every
promote/demote) is GONE: measured 2026-08-08, the janitor's own memory-chore agents flipped the
tier back and forth and re-armed the cron five times in ~6.5h, each re-arm a full billed model
turn. The cadence is now a single fixed cron (`arm_prepare.DEFAULT_CRON`, still overridable by
`CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON`), and the ONLY surviving renew trigger is
`_phase_heartbeat_renew`'s 7-day cron-expiry check.

`_cadence_active_waiting` survives — it still gates the idle-compact and idle-clear phases (a
session waiting on a resume must not be shrunk/cleared out from under itself) — so its own
behavior is still exercised directly here, real I/O, no mocks.
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


# --------------------------------------------------------------------------- #
# TRDD-BRHJHWW0 acceptance: zero renews across a simulated day of tier-state
# flapping — pending background agents (the exact TRDD-CI6ZTNB9 driver) appear
# and disappear across many fires, and none of it may emit [janitor-renew].
# --------------------------------------------------------------------------- #


def test_a_day_of_tier_state_flapping_emits_no_renew(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate ~24 fires with pending agents flapping on/off (the old FAST/SLOW churn driver).
    With the tier controller gone there is nothing left to flap, and no `heartbeat-armed-at.ts`
    on disk means `_phase_heartbeat_renew` has nothing to expire either — so across the whole
    simulated day, not one fire may print `[janitor-renew]`."""
    import json

    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_run_detector", lambda *a, **k: None)
    sd = _state(proj)

    for i in range(24):
        pending = sd / "pending-agents.json"
        if i % 2 == 0:
            pending.write_text(
                json.dumps([{"agentId": "a" * 17, "description": "memory-chore", "ts": 0, "nudges": 0, "transcript": ""}]),
                encoding="utf-8",
            )
        else:
            pending.unlink(missing_ok=True)
        out = _run_main(dispatch)
        assert "[janitor-renew]" not in out, f"fire {i} emitted a renew — tier flapping must never re-arm"

    assert not (sd / "desired-cadence.cron").exists(), "nothing writes a tier-driven cron any more"
    assert not (sd / "cadence-state.json").exists()


def test_rate_limit_fire_stamps_resume_and_never_renews(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rate-limit recovery, and the fire right after it, must both stay renew-free.

    Fire 1: rate-limited.flag → main() emits [janitor-resume] and returns EARLY, having unlinked
    the flag, leaving a last-resume.ts stamp. Fire 2: the flag is gone but the stamp is still
    fresh — `_cadence_active_waiting` reads True — yet with the tier controller retired that
    boolean no longer drives any cron write or renew at all."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_run_detector", lambda *a, **k: None)
    (_state(proj) / "rate-limited.flag").write_text("")

    out1 = _run_main(dispatch)
    assert "[janitor-resume]" in out1
    assert "[janitor-renew]" not in out1
    assert not (_state(proj) / "rate-limited.flag").exists()
    assert (_state(proj) / "last-resume.ts").is_file()

    out2 = _run_main(dispatch)
    assert "[janitor-renew]" not in out2
    assert not (_state(proj) / "desired-cadence.cron").exists()


def test_a_retired_maintenance_sentinel_changes_nothing_about_the_fire(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host upgraded while in local maintenance still has `.janitor/state/maintenance-mode` on
    disk from an older janitor version; that file must be inert — the fire runs its full course
    and, absent a `heartbeat-armed-at.ts`, emits no renew at all."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    (st.state_dir() / "maintenance-mode").write_text("set by an older janitor")
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_run_detector", lambda *a, **k: None)

    out = _run_main(dispatch)
    assert "[janitor-renew]" not in out
    assert not (_state(proj) / "desired-cadence.cron").exists()
    # And the sentinel is SWEPT, so it cannot keep confusing whoever reads the state dir.
    assert not (st.state_dir() / "maintenance-mode").exists()


# --------------------------------------------------------------------------- #
# TRDD-BRHJHWW0 acceptance: the 7-day expiry renew still fires, exactly once.
# --------------------------------------------------------------------------- #


def test_armed_cron_near_7day_expiry_renews_exactly_once(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`heartbeat-armed-at.ts` older than the threshold (default 6 days) renews on the first
    fire that sees it, and the day-bucket dedupe silences every later fire on the same day."""
    import time

    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_run_detector", lambda *a, **k: None)
    armed_at = int(time.time()) - 7 * 86400
    (_state(proj) / "heartbeat-armed-at.ts").write_text(str(armed_at), encoding="utf-8")

    out1 = _run_main(dispatch)
    assert out1.count("[janitor-renew]") == 1

    out2 = _run_main(dispatch)
    assert "[janitor-renew]" not in out2, "same-day dedupe must silence the second fire"


def test_armed_cron_within_threshold_does_not_renew(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A freshly-armed cron (age well under the 6-day default threshold) never renews."""
    import time

    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_run_detector", lambda *a, **k: None)
    armed_at = int(time.time()) - 3600  # 1h old
    (_state(proj) / "heartbeat-armed-at.ts").write_text(str(armed_at), encoding="utf-8")

    out = _run_main(dispatch)
    assert "[janitor-renew]" not in out


# --------------------------------------------------------------------------- #
# TRDD-BRHJHWW0 acceptance: a compact-resume path never renews either.
# --------------------------------------------------------------------------- #


def test_post_compact_resume_fire_never_renews(proj: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A post-compact resume returns early with [janitor-resume] (never [janitor-renew]),
    and — with no tier controller left to react to the stamp it leaves behind — the very next
    fire stays renew-free too."""
    import time

    dispatch = _import_dispatch()
    import global_state as gs
    import state as st

    gs.init_global_state()
    st.init_state()
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_run_detector", lambda *a, **k: None)
    sd = _state(proj)
    sd.mkdir(parents=True, exist_ok=True)
    dispatch.state.atomic_write(sd / "resume-after-compact.ts", str(int(time.time())))
    dispatch.state.atomic_write(sd / "resume-after-compact.flag", "continue TRDD-SOMETHING")

    out1 = _run_main(dispatch)
    assert out1.startswith("[janitor-resume]")
    assert "[janitor-renew]" not in out1
    assert not (sd / "resume-after-compact.flag").exists()

    out2 = _run_main(dispatch)
    assert "[janitor-renew]" not in out2


# --------------------------------------------------------------------------- #
# MF4 — the daemon-injectability handshake (TRDD-X07E7HTN, D1 v1). A rate-limit
# resume may DEMOTE off "active waiting" ONLY when the daemon has stamped
# daemon-wake-covered.ts (it injected /janitor-resume into this pane for free).
# The coverage stamp — not active_waiting itself — is the SOLE demotion authority,
# and it demotes ONLY the rate-limit/resume reason. DEFAULT-OFF: absent the opt-in
# a stamp is ignored. `_cadence_active_waiting` itself is exercised directly since
# it still gates the idle-compact / idle-clear phases (see their own test files).
# --------------------------------------------------------------------------- #


def _fresh_cover(proj: Path) -> None:
    import time

    (_state(proj) / "daemon-wake-covered.ts").write_text(str(int(time.time())))


def test_active_waiting_non_ratelimit_reasons_stay_true_without_coverage(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE NEGATIVE TEST (MF4): active-waiting for a NON-rate-limit reason — a resume directive
    or pending background agents — stays True with NO fresh daemon-wake-covered.ts. This proves
    the coverage stamp, NOT active_waiting, authorizes demotion: the stamp demotes ONLY the
    rate-limit/resume reason, never these."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_fresh_external_agent_count", lambda now, state_dir=None: 0)

    (sd / "resume-directive.txt").write_text("continue TRDD-X07E7HTN")
    assert dispatch._cadence_active_waiting(sd, now) is True
    (sd / "resume-directive.txt").unlink()

    monkeypatch.setattr(dispatch, "_fresh_external_agent_count", lambda now, state_dir=None: 1)
    assert dispatch._cadence_active_waiting(sd, now) is True


def test_coverage_stamp_never_demotes_a_non_ratelimit_reason(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a FRESH coverage stamp must NOT demote a session waiting on a resume DIRECTIVE: the
    stamp suppresses ONLY the rate-limit/resume reason. A pending directive is an independent
    True signal, so a covered session with one is still True — this is why the demotion keys on
    the reason, not on active_waiting as a whole."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _state(proj)
    monkeypatch.setattr(dispatch, "_fresh_external_agent_count", lambda now, state_dir=None: 0)
    (sd / "resume-directive.txt").write_text("continue TRDD-X07E7HTN")
    _fresh_cover(proj)
    assert dispatch._cadence_active_waiting(sd, int(time.time())) is True


def test_ratelimit_resume_demotes_only_with_fresh_coverage(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SOLE demotion condition: a recent resume stamp forces True UNLESS a FRESH
    daemon-wake-covered.ts proves the daemon owns the wake for free. Stale/absent coverage
    keeps True (the cron stays the trigger)."""
    import time

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_fresh_external_agent_count", lambda now, state_dir=None: 0)
    (sd / "last-resume.ts").write_text(str(now))

    assert dispatch._cadence_active_waiting(sd, now) is True  # no coverage → True

    (sd / "daemon-wake-covered.ts").write_text(str(now))
    assert dispatch._cadence_active_waiting(sd, now) is False  # fresh coverage → demote

    (sd / "daemon-wake-covered.ts").write_text(str(now - 100_000))
    assert dispatch._cadence_active_waiting(sd, now) is True  # stale coverage → True again


def test_coverage_ignored_when_feature_disabled(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEFAULT-OFF preserves today's behavior: a fresh coverage stamp is IGNORED unless the
    opt-in is set, so a rate-limited session stays True exactly as before D1 — a stray stamp
    can never silently demote (and under-cover) a session while the feature is disabled."""
    import time

    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", raising=False)
    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_fresh_external_agent_count", lambda now, state_dir=None: 0)
    (sd / "last-resume.ts").write_text(str(now))
    _fresh_cover(proj)
    assert dispatch._cadence_active_waiting(sd, now) is True


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


def test_a_stale_resume_directive_no_longer_pins_active_waiting(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE measured idle-burn defect (2026-08-02), and the asymmetry that caused it.

    `resume-directive.txt` is unlinked by exactly ONE consumer — `post-compact-resume.py`,
    "one-shot per compact". The soft `/compact` is only ENQUEUED, so a session that never ends
    its turn (or is restarted first) never runs it and the pointer is never consumed. The old
    check was `is_file() and st_size > 0` with NO age bound, while its sibling signal — the
    resume STAMP one line above — has always been bounded to 30 min. Same signal class, one
    bounded, one not.

    The fix bounds the CADENCE claim only. The file is still read as CONTENT by the resume
    phases and the keep-going nudge — an old directive still says what to resume, it just stops
    asserting "actively waiting RIGHT NOW"."""
    import os
    import time

    dispatch = _import_dispatch()
    sd = _state(proj)
    now = int(time.time())
    monkeypatch.setattr(dispatch, "_fresh_external_agent_count", lambda now, state_dir=None: 0)

    d = sd / "resume-directive.txt"
    d.write_text("continue TRDD-SOMETHING")
    # PIN the mtime instead of racing the wall clock. `now` is sampled ABOVE, before the write,
    # so if the write crosses a second boundary — routine under a loaded full-suite run —
    # `st_mtime` lands one second AHEAD of `now`, `age` is -1, and the production code's
    # `0 <= age` clock-skew guard correctly rejects it. The assertion below then fails on a
    # brand-new directive and the test looks flaky while the code under test is fine. Every
    # other case here already sets its own mtime; this one just inherited the clock.
    os.utime(d, (now, now))

    # Fresh: still True — the signal must keep working for a real, current wait.
    assert dispatch._cadence_active_waiting(sd, now) is True

    # Two days old, exactly the observed case: must NOT hold True any more.
    stale = now - 2 * 24 * 3600
    os.utime(d, (stale, stale))
    assert dispatch._cadence_active_waiting(sd, now) is False, (
        "a stale directive still pins active-waiting — the idle-burn defect is back"
    )

    # ...and the file is NOT deleted: it is still the pointer to what to resume.
    assert d.is_file() and d.read_text() == "continue TRDD-SOMETHING"

    # Just inside the window is still True (boundary, so the bound cannot be silently widened).
    fresh = now - (dispatch._RESUME_RECENCY_WINDOW_S - 60)
    os.utime(d, (fresh, fresh))
    assert dispatch._cadence_active_waiting(sd, now) is True


def test_active_waiting_reads_the_manifest_of_the_sd_it_was_given(
    proj: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 2026-08-08 (blocked a release at the test gate): the resume and directive
    branches of `_cadence_active_waiting` always honoured `sd`, but the pending-agents
    count read the AMBIENT `state.state_dir()` — so a caller judging a DIFFERENT project
    (the external-clear watcher, the future daemon fleet walk) had the calling session's
    in-flight agents leak into that project's verdict. Concretely: this session's
    code-review workflow agents flipped a tmp fixture project to `active-waiting`."""
    import json as _json
    import time as _time

    dispatch = _import_dispatch()
    now = int(_time.time())

    # The AMBIENT project (CLAUDE_PROJECT_DIR) has a fresh, external, in-flight agent.
    ambient_sd = proj / ".janitor" / "state"
    (ambient_sd / "pending-agents.json").write_text(
        _json.dumps([{"agentId": "a" * 17, "description": "workflow-subagent",
                      "ts": now, "nudges": 0, "transcript": ""}]),
        encoding="utf-8",
    )

    # A DIFFERENT project's empty state dir — the one the caller is deciding about.
    other_sd = tmp_path / "other-project" / ".janitor" / "state"
    other_sd.mkdir(parents=True)

    assert dispatch._cadence_active_waiting(ambient_sd, now) is True, (
        "sanity: the ambient project itself IS actively waiting"
    )
    assert dispatch._cadence_active_waiting(other_sd, now) is False, (
        "the ambient session's agents leaked into another project's verdict"
    )
