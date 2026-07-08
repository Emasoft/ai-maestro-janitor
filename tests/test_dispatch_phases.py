"""Tests for the new dispatch phases — `[janitor-reload]` emission and the
daemon-restart-if-stale check.

We exercise the phases in-process by importing dispatch.py as a module and
calling the underscore-private helpers directly. The full dispatch.main()
isn't appropriate here because it also walks the detector roster; we want
fast, focused tests on just the two new phases.

Per-test isolation: $JANITOR_GLOBAL_STATE_DIR + $CLAUDE_PROJECT_DIR both
point at tmp_path so the user's real state is never touched.
"""

from __future__ import annotations

import sys
import time
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def env_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Point both project and global state at tmp dirs; reload dispatch + gs."""
    project = tmp_path / "project"
    project.mkdir()
    global_dir = tmp_path / "janitor-global-state"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))

    # Force-reload so module-level path resolution picks up the env.
    for mod in ("dispatch", "global_state", "state"):
        if mod in sys.modules:
            del sys.modules[mod]

    return {"project": project, "global_dir": global_dir}


def _import_dispatch():
    """Import scripts/dispatch.py without running main()."""
    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_under_test",
        str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture_stdout(fn):
    """Run fn() while capturing print() output. Return captured string."""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


# ---------- Phase 0: machine-wide global pause (TRDD-a3fa4d5d) -------------


def test_phase_global_paused_false_when_flag_absent(env_isolation: dict) -> None:
    """No global-pause flag → the phase returns False and the heartbeat proceeds."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    assert dispatch._phase_global_paused() is False


def test_phase_global_paused_true_when_flag_set(env_isolation: dict) -> None:
    """A machine-wide global pause → the phase returns True so main() self-disarms THIS
    session's heartbeat (emits [janitor-self-disarm] → the session deletes its own cron)."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_global_pause("test")
    assert dispatch._phase_global_paused() is True


# ---------- Phase 0: machine-wide global DISARM / kill-switch (TRDD-NJ22HNC3) ----------


def test_phase_globally_disarmed_false_when_flag_absent(env_isolation: dict) -> None:
    """No kill-switch → the phase returns False and the heartbeat proceeds."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    assert dispatch._phase_globally_disarmed() is False


def test_phase_globally_disarmed_true_when_kill_switch_set(env_isolation: dict) -> None:
    """A machine-wide kill-switch (/janitor-global-disarm) → the phase returns True so
    main() self-disarms THIS session's heartbeat (emits [janitor-self-disarm]) like global-pause.

    THE FIX (RQ9FIFX6): the old silent short-circuit (NJ22HNC3) stopped the detectors but the
    cron still FIRED ~618k cached tokens every 5 min ("many janitors still running"). Now Phase 0
    emits the marker so the session DELETES its cron — a true, free stop.
    """
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_kill_switch("test")
    assert dispatch._phase_globally_disarmed() is True


def test_main_self_disarms_when_globally_disarmed(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """BEHAVIORAL PROOF: with the kill-switch set, dispatch.main() short-circuits at Phase 0,
    emits EXACTLY the bare [janitor-self-disarm] marker (so the session DELETES its own cron —
    the only way a fired turn costs zero), runs NO detector (no last-run-*.ts stamp), and never
    tries to spawn the daemon. The pre-RQ9FIFX6 behavior emitted NOTHING, but the cron still
    fired ~618k cached tokens every 5 min; self-disarm is what actually stops the bleed.
    """
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    gs.set_kill_switch("disarmed")

    ran: list[str] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: ran.append(name))
    monkeypatch.setattr(
        dispatch.gs,
        "ensure_daemon_running",
        lambda *a, **k: pytest.fail("daemon spawn attempted while globally disarmed"),
    )

    out = _capture_stdout(dispatch.main)
    assert out.strip() == "[janitor-self-disarm]", f"a disarmed heartbeat must emit the bare self-disarm marker, got {out!r}"
    assert ran == [], f"a disarmed heartbeat must run NO detector, ran {ran}"
    stamps = list(state.state_dir().glob("last-run-*.ts"))
    assert stamps == [], f"no detector should have stamped last-run, found {stamps}"


def test_main_self_disarms_when_globally_paused(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """global-pause (the "stop the project heartbeats but keep the daemon" control) ALSO
    self-disarms: main() emits the bare [janitor-self-disarm] marker and runs no detector.
    Pre-RQ9FIFX6 it only SILENCED — the cron kept firing ~618k cached tokens. Now it TRULY
    stops (deletes the cron = free), which is what the user asked for.
    """
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    gs.set_global_pause("paused")

    ran: list[str] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: ran.append(name))
    monkeypatch.setattr(
        dispatch.gs,
        "ensure_daemon_running",
        lambda *a, **k: pytest.fail("daemon spawn attempted while globally paused"),
    )

    out = _capture_stdout(dispatch.main)
    assert out.strip() == "[janitor-self-disarm]", f"a globally-paused heartbeat must emit the bare self-disarm marker, got {out!r}"
    assert ran == [], f"a globally-paused heartbeat must run NO detector, ran {ran}"
    stamps = list(state.state_dir().glob("last-run-*.ts"))
    assert stamps == [], f"no detector should have stamped last-run, found {stamps}"


def test_main_self_disarm_is_idempotent_self_limiting(env_isolation: dict) -> None:
    """A self-disarm fire emits the marker but stamps NO state and clears NO flag — it relies on
    the SESSION deleting the cron (so there are no more fires). Two consecutive disarmed fires
    therefore emit the same single marker each time (idempotent); the real stop is the cron
    deletion the marker triggers, not anything dispatch persists.
    """
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_kill_switch("disarmed")

    first = _capture_stdout(dispatch.main).strip()
    second = _capture_stdout(dispatch.main).strip()
    assert first == "[janitor-self-disarm]"
    assert second == "[janitor-self-disarm]", "marker re-emits each fire until the cron is deleted"


# ---------- Phase 1.6: plugin reload --------------------------------------


def test_phase_plugin_reload_silent_when_flag_absent(env_isolation: dict) -> None:
    """No reload-needed.flag → no marker emitted, no log lines."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    assert gs.reload_flag_present() is False

    out = _capture_stdout(dispatch._phase_plugin_reload)
    assert out == "", f"phase must be silent when no flag is set, got {out!r}"


def test_phase_plugin_reload_emits_marker_and_advances_ack(env_isolation: dict) -> None:
    """generation present + project not yet acked → bare [janitor-reload] emitted,
    per-project ack advanced, and the global generation LEFT INTACT (never cleared
    by a reader — that is what starved concurrent sessions in the old design)."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_reload_flag("ai-maestro-janitor@ai-maestro-plugins")

    out = _capture_stdout(dispatch._phase_plugin_reload)
    assert out.strip() == "[janitor-reload]", f"phase must emit exactly the bare marker, got {out!r}"
    assert gs.reload_flag_present() is True, "phase must NOT clear the global generation — other projects still need it"
    # The SAME project does not re-emit: its ack now equals the generation.
    second = _capture_stdout(dispatch._phase_plugin_reload).strip()
    assert second == "", "same project must not re-emit once it has acked the generation"


def test_phase_plugin_reload_idempotent_within_same_fire(env_isolation: dict) -> None:
    """Calling the phase twice only emits one marker — the per-project ack advances
    on the first emit, so the second consecutive call (no newer generation) is
    silent. The dispatch is generation-driven: one marker per real update per
    project.
    """
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_reload_flag("plugin@mp")

    first = _capture_stdout(dispatch._phase_plugin_reload).strip()
    second = _capture_stdout(dispatch._phase_plugin_reload).strip()
    assert first == "[janitor-reload]"
    assert second == ""


def test_phase_plugin_reload_per_project_no_starvation(env_isolation: dict) -> None:
    """THE BUG FIX: the global generation is NEVER cleared by a reader, so a
    project that has not yet acked still reloads even after another project
    already did. The old single-flag design cleared the flag on the first emit,
    so only the first session/project ever saw `[janitor-reload]` — every other
    live session (e.g. an autonomous fleet agent in a different project) stayed on
    stale plugin code until restart. We model a second, un-acked project by
    removing this project's ack stamp: the generation is untouched, so it reloads.
    """
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    gs.set_reload_flag("plugin@mp")  # one global generation, shared by all projects

    # Project A reloads, records its ack, and does NOT re-emit on a second call.
    assert _capture_stdout(dispatch._phase_plugin_reload).strip() == "[janitor-reload]"
    assert _capture_stdout(dispatch._phase_plugin_reload).strip() == "", "the same project must not re-emit once it has acked the generation"

    # The global generation is still readable — a reader never cleared it.
    assert gs.reload_flag_present() is True

    # A DIFFERENT project has no ack yet (model it by removing this one's stamp).
    # Because the generation was never cleared, the un-acked project reloads too.
    (state.state_dir() / "reload-acked.ts").unlink()
    assert _capture_stdout(dispatch._phase_plugin_reload).strip() == "[janitor-reload]", "an un-acked project still reloads — the generation was never consumed by project A"


# ---------- Phase 1.62: standalone-skills reload (TRDD-LQU7OXXV) ------------


def test_phase_skills_reload_silent_when_flag_absent(env_isolation: dict) -> None:
    """No skills-reload-needed.flag → no marker emitted."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    assert gs.skills_reload_flag_present() is False
    out = _capture_stdout(dispatch._phase_skills_reload)
    assert out == "", f"phase must be silent when no flag is set, got {out!r}"


def test_phase_skills_reload_emits_marker_and_advances_ack(env_isolation: dict) -> None:
    """generation present + project not yet acked → bare [janitor-reload-skills],
    per-project ack advanced, global generation LEFT INTACT; same project silent next."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_skills_reload_flag("via /janitor-global-reload-skills")

    out = _capture_stdout(dispatch._phase_skills_reload)
    assert out.strip() == "[janitor-reload-skills]", f"expected the bare marker, got {out!r}"
    assert gs.skills_reload_flag_present() is True, "must NOT clear the global generation"
    assert _capture_stdout(dispatch._phase_skills_reload).strip() == "", "same project must not re-emit after acking"


def test_phase_skills_reload_per_project_no_starvation(env_isolation: dict) -> None:
    """The generation is never cleared by a reader, so an un-acked project still
    reloads after another already did (modelled by removing this project's ack)."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    gs.set_skills_reload_flag("skill-x")
    assert _capture_stdout(dispatch._phase_skills_reload).strip() == "[janitor-reload-skills]"
    assert _capture_stdout(dispatch._phase_skills_reload).strip() == ""
    (state.state_dir() / "skills-reload-acked.ts").unlink()
    assert _capture_stdout(dispatch._phase_skills_reload).strip() == "[janitor-reload-skills]", "an un-acked project still reloads"


def test_phase_skills_reload_independent_of_plugin_reload(env_isolation: dict) -> None:
    """The two reload signals are INDEPENDENT: a plugin-reload generation must NOT
    make _phase_skills_reload fire, and a skills-reload generation must NOT make
    _phase_plugin_reload fire (separate flag files, separate acks)."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    # Only the PLUGIN reload flag is set → skills phase stays silent.
    gs.set_reload_flag("plugin@mp")
    assert _capture_stdout(dispatch._phase_skills_reload).strip() == "", "skills phase must ignore a plugin-only generation"
    # Now only the SKILLS reload flag advances → plugin phase (already acked) stays silent.
    _capture_stdout(dispatch._phase_plugin_reload)  # ack the plugin generation first
    gs.set_skills_reload_flag("skill-y")
    assert _capture_stdout(dispatch._phase_plugin_reload).strip() == "", "plugin phase must ignore a skills-only generation"
    assert _capture_stdout(dispatch._phase_skills_reload).strip() == "[janitor-reload-skills]"


# ---------- Phase 1.65: daemon restart if stale ---------------------------


def test_phase_daemon_restart_no_daemon_is_noop(env_isolation: dict) -> None:
    """No running daemon → phase is a silent no-op (never raises)."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    # No pid file → daemon_needs_restart returns False → no SIGTERM attempted.
    dispatch._phase_daemon_restart_if_stale()  # must not raise


def test_phase_daemon_restart_sends_sigterm_on_mismatch(env_isolation: dict) -> None:
    """When daemon_needs_restart returns True, the phase delivers SIGTERM.

    We use a spawned `sleep` subprocess as a controllable stand-in for the
    daemon: it's a real OS process we can write into daemon.pid, and we
    monkey-patch _read_process_cmdline to return a path that mismatches
    the expected one. SIGTERM brings sleep down within milliseconds.
    """
    import subprocess as _sp

    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()

    # Spawn a real, controllable child process.
    sleeper = _sp.Popen(["sleep", "30"], stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    try:
        gs.write_daemon_pid(sleeper.pid)
        # Synthesize a "stale" argv so daemon_needs_restart returns True.
        gs._read_process_cmdline = lambda _pid: (  # type: ignore[attr-defined]
            "uv run --script --quiet /old/cache/0.4.0/scripts/daemon.py"
        )
        assert gs.daemon_needs_restart() is True

        dispatch._phase_daemon_restart_if_stale()

        # SIGTERM should bring the sleep child down quickly.
        try:
            sleeper.wait(timeout=5.0)
        except _sp.TimeoutExpired:
            sleeper.kill()
            pytest.fail("phase did not SIGTERM the stale daemon")
        assert sleeper.returncode is not None
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait(timeout=2.0)


def test_phase_daemon_restart_swallows_exceptions(env_isolation: dict) -> None:
    """If daemon_needs_restart raises, the phase logs and continues (no crash).

    Monkey-patch the function on the *imported gs module inside dispatch*
    so the wrap is exercised.
    """
    dispatch = _import_dispatch()

    # Make daemon_needs_restart blow up; phase must NOT propagate.
    def _boom() -> bool:
        raise RuntimeError("simulated filesystem failure")

    dispatch.gs.daemon_needs_restart = _boom  # type: ignore[assignment]
    dispatch._phase_daemon_restart_if_stale()  # must not raise


# ---------- Phase 1.1: post-compact resume --------------------------------


def _arm_compact_flag(state, directive: str, *, age_s: int = 0) -> None:
    """Simulate what the PostCompact hook writes: directive flag + ts sidecar."""
    state.init_state()
    sd = state.state_dir()
    state.atomic_write(sd / "resume-after-compact.ts", str(int(time.time()) - age_s))
    state.atomic_write(sd / "resume-after-compact.flag", directive)


def test_phase_compact_resume_silent_when_flag_absent(env_isolation: dict) -> None:
    """No resume-after-compact.flag → no marker emitted, phase returns False."""
    dispatch = _import_dispatch()
    out = _capture_stdout(dispatch._phase_compact_resume)
    assert out == "", f"phase must be silent when no flag is set, got {out!r}"


def test_phase_compact_resume_emits_directive_and_clears(env_isolation: dict) -> None:
    """flag present → bare [janitor-resume] marker + directive on line 2 (F7); flag cleared."""
    dispatch = _import_dispatch()
    import state

    _arm_compact_flag(
        state,
        "continue TRDD-31095269 (Context-compact watchdog) — read its STATE block first.",
        age_s=42,
    )
    out = _capture_stdout(dispatch._phase_compact_resume)
    assert out.startswith("[janitor-resume]"), f"must lead with the resume marker, got {out!r}"
    assert "continue TRDD-31095269" in out
    assert "42s ago" in out, "age from the .ts sidecar must be reported"
    sd = state.state_dir()
    assert not (sd / "resume-after-compact.flag").exists(), "flag must be cleared after emission"
    assert not (sd / "resume-after-compact.ts").exists(), "ts sidecar must be cleared too"


def test_resume_marker_line_is_bare_whole_line(env_isolation: dict) -> None:
    """F7 (wikimem audit): BOTH resume phases emit the [janitor-resume] marker as a
    BARE whole line with the prose/directive on line 2 — the cron prompt honors
    whole-line markers only, so a prose-carrying marker line would legitimize
    prefix-mimicry (`[janitor-resume] …` inside any detector line being honored)."""
    dispatch = _import_dispatch()
    import state

    # Post-compact resume: marker bare, directive on line 2.
    _arm_compact_flag(state, "continue TRDD-31095269", age_s=42)
    out = _capture_stdout(dispatch._phase_compact_resume)
    lines = out.splitlines()
    assert lines[0] == "[janitor-resume]", f"marker line must be bare, got {lines[0]!r}"
    assert "continue TRDD-31095269" in lines[1]

    # Rate-limit resume: same two-line shape.
    sd = state.state_dir()
    (sd / "rate-limited.flag").write_text("", encoding="utf-8")
    state.atomic_write(sd / "rate-limited-since.ts", str(int(__import__("time").time()) - 30))
    out2 = _capture_stdout(dispatch._phase_rate_limit_recovery)
    lines2 = out2.splitlines()
    assert lines2[0] == "[janitor-resume]", f"marker line must be bare, got {lines2[0]!r}"
    assert "rate-limit cleared" in lines2[1]


def test_phase_compact_resume_returns_true_when_emitted(env_isolation: dict) -> None:
    """Returns True so main() returns early and skips the detector roster this fire."""
    dispatch = _import_dispatch()
    import state

    _arm_compact_flag(state, "continue TRDD-abcd1234")
    assert dispatch._phase_compact_resume() is True


def test_phase_compact_resume_idempotent_within_same_fire(env_isolation: dict) -> None:
    """Second consecutive call emits nothing — the flag self-clears (fires once)."""
    dispatch = _import_dispatch()
    import state

    _arm_compact_flag(state, "continue TRDD-abcd1234")
    first = _capture_stdout(dispatch._phase_compact_resume).strip()
    second = _capture_stdout(dispatch._phase_compact_resume).strip()
    assert first.startswith("[janitor-resume]")
    assert second == "", "no flag left → second call is silent"


def test_phase_compact_resume_defangs_marker_mimicry(env_isolation: dict) -> None:
    """A directive embedding fake [janitor-*] markers is defanged before emission.

    Defends against a TRDD title / directive file trying to smuggle a second
    heartbeat marker into the resume line. sanitize_for_drift_line rewrites the
    ASCII brackets to lookalikes, so only our own leading [janitor-resume]
    survives as a real marker.
    """
    dispatch = _import_dispatch()
    import state

    _arm_compact_flag(state, "continue [janitor-reload] then [janitor-renew] now")
    out = _capture_stdout(dispatch._phase_compact_resume)
    assert out.count("[janitor-resume]") == 1, "only our own marker may use ASCII brackets"
    assert "[janitor-reload]" not in out, "smuggled marker must be defanged"
    assert "[janitor-renew]" not in out, "smuggled marker must be defanged"
    assert "janitor-reload" in out, "the words still read (inside the bracket lookalikes)"


def test_phase_compact_resume_generic_cue_when_flag_empty(env_isolation: dict) -> None:
    """Flag present but empty → still cue a generic resume (don't stall idle)."""
    dispatch = _import_dispatch()
    import state

    _arm_compact_flag(state, "")
    out = _capture_stdout(dispatch._phase_compact_resume)
    assert out.startswith("[janitor-resume]")
    assert "in-flight task" in out


def test_rate_limit_recovery_also_clears_compact_flag(env_isolation: dict) -> None:
    """A rate-limit resume subsumes a pending compact-resume — clear both flags.

    Prevents a redundant second [janitor-resume] on the next fire when a
    compaction and a rate-limit happened to overlap in the same window.
    """
    dispatch = _import_dispatch()
    import state

    state.init_state()
    sd = state.state_dir()
    state.atomic_write(sd / "rate-limited.flag", "1")
    state.atomic_write(sd / "rate-limited-since.ts", str(int(time.time()) - 30))
    _arm_compact_flag(state, "continue TRDD-abcd1234")

    out = _capture_stdout(dispatch._phase_rate_limit_recovery)
    assert out.startswith("[janitor-resume]")
    assert not (sd / "rate-limited.flag").exists()
    assert not (sd / "resume-after-compact.flag").exists(), "compact flag must be cleared too"
    assert not (sd / "resume-after-compact.ts").exists()


# ---------- _run_detector wall-clock timeout (audit finding 1) -------------
#
# A hung detector must NOT wedge the whole heartbeat turn. These tests spawn a
# REAL detector subprocess that really sleeps; the real subprocess.run(timeout=)
# kills it. No mocks — only dispatch._HERE is repointed so _run_detector resolves
# our controllable script from a tmp `detectors/` dir instead of the shipped ones.


def _install_fake_detector(detectors_dir: Path, name: str, body: str) -> None:
    """Write an executable Python detector at detectors_dir/<name>.py."""
    detectors_dir.mkdir(parents=True, exist_ok=True)
    script = detectors_dir / f"{name}.py"
    script.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    script.chmod(0o755)


def test_run_detector_kills_hung_detector_within_timeout(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A detector that sleeps far past the timeout is killed; the call returns fast.

    Proves the heartbeat can't be wedged: a real subprocess sleeps 30 s, the
    timeout is 1 s, and _run_detector must return in well under the sleep
    duration (the real subprocess.run timeout kill is what bounds it).
    """
    dispatch = _import_dispatch()
    import state

    fake_root = env_isolation["project"] / "fake_plugin_root"
    _install_fake_detector(
        fake_root / "detectors",
        "hang",
        "import time\ntime.sleep(30)\n",
    )
    monkeypatch.setattr(dispatch, "_HERE", fake_root)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT", "1")

    state.init_state()
    start = time.monotonic()
    dispatch._run_detector("hang", interval=0)  # interval 0 → always due
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, f"hung detector wedged the call for {elapsed:.1f}s — timeout did not fire"


def test_run_detector_stamps_last_run_after_timeout(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """On timeout, last-run is stamped so the detector backs off to its cadence.

    Without the stamp, a chronically-slow detector would re-fire (and re-hang)
    every single heartbeat. The fix stamps last-run on the timeout path too.
    """
    dispatch = _import_dispatch()
    import state

    fake_root = env_isolation["project"] / "fake_plugin_root"
    _install_fake_detector(
        fake_root / "detectors",
        "hang2",
        "import time\ntime.sleep(30)\n",
    )
    monkeypatch.setattr(dispatch, "_HERE", fake_root)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT", "1")

    state.init_state()
    dispatch._run_detector("hang2", interval=3600)

    last_run = state.state_dir() / "last-run-hang2.ts"
    assert last_run.is_file(), "last-run.ts must be stamped even on timeout"
    ts = int(last_run.read_text(encoding="utf-8").strip())
    assert abs(int(time.time()) - ts) < 60, "stamp must be a fresh epoch second"
    # And now the detector is NOT due again (cadence not elapsed) — it backs off.
    assert dispatch._detector_is_due("hang2", 3600) is False


def test_run_detector_fast_detector_runs_normally(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-behaved detector under the timeout runs to completion and stamps last-run."""
    dispatch = _import_dispatch()
    import state

    fake_root = env_isolation["project"] / "fake_plugin_root"
    _install_fake_detector(
        fake_root / "detectors",
        "fast",
        "print('all-clear')\n",
    )
    monkeypatch.setattr(dispatch, "_HERE", fake_root)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT", "30")

    state.init_state()
    dispatch._run_detector("fast", interval=0)

    last_run = state.state_dir() / "last-run-fast.ts"
    assert last_run.is_file(), "a fast detector must still stamp last-run on success"


# ---------- Phase 0: maintenance-mode (TRDD-FPL60EKV) ----------


def test_maintenance_mode_active_false_when_no_flags(env_isolation: dict) -> None:
    """No local or global maintenance flag → maintenance-mode is not active."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    assert dispatch._maintenance_mode_active() is False


def test_maintenance_mode_active_true_from_local_flag(env_isolation: dict) -> None:
    """The per-session .janitor/state/maintenance-mode flag activates maintenance-mode."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    (state.state_dir() / "maintenance-mode").write_text("", encoding="utf-8")
    assert dispatch._maintenance_mode_active() is True


def test_maintenance_mode_active_true_from_global_flag(env_isolation: dict) -> None:
    """The machine-wide /janitor-global-maintenance flag activates maintenance-mode."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_maintenance_mode("test")
    assert dispatch._maintenance_mode_active() is True


def test_resolve_heartbeat_mode_full_when_no_flags(env_isolation: dict) -> None:
    """No stop and no maintenance → the heartbeat runs in FULL mode."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    assert dispatch._resolve_heartbeat_mode() == "full"


def test_resolve_heartbeat_mode_stop_on_kill_switch(env_isolation: dict) -> None:
    """A kill-switch with no maintenance opt-in resolves to STOP (self-disarm)."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_kill_switch("test")
    assert dispatch._resolve_heartbeat_mode() == "stop"


def test_resolve_heartbeat_mode_stop_on_global_pause(env_isolation: dict) -> None:
    """A global-pause with no maintenance opt-in resolves to STOP (self-disarm)."""
    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_global_pause("test")
    assert dispatch._resolve_heartbeat_mode() == "stop"


def test_resolve_heartbeat_mode_maintenance_wins_over_kill_switch(env_isolation: dict) -> None:
    """Maintenance is the highest-priority intent: even with the kill-switch set, a session
    that opted into maintenance resolves to MAINTENANCE (keep the cache warm), NOT stop. This
    is the "keep one session warm while the fleet stays down" property (TRDD-FPL60EKV)."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    gs.set_kill_switch("fleet-down")
    (state.state_dir() / "maintenance-mode").write_text("", encoding="utf-8")
    assert dispatch._resolve_heartbeat_mode() == "maintenance"


def test_main_maintenance_fires_cheap_no_chores_but_ensures_daemon(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """BEHAVIORAL PROOF: in maintenance-mode main() does close to the MINIMUM — it emits ONLY
    the never-stop keep-going nudge and runs NO detector — but it DOES call
    ensure_daemon_running (TRDD-8PH8YOIJ): the daemon's existence is SURVIVAL (it beats the
    60s oauth-rotator-tick that rotates accounts), not a chore. Before this, a daemon that
    died during maintenance stayed dead — nobody rotated, the 5h window exhausted, and the
    user had to /login by hand (incident 2026-07-02)."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    (state.state_dir() / "maintenance-mode").write_text("", encoding="utf-8")

    ran: list[str] = []
    ensured: list[bool] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: ran.append(name))
    monkeypatch.setattr(
        dispatch.gs,
        "ensure_daemon_running",
        lambda *a, **k: ensured.append(True),
    )

    out = _capture_stdout(dispatch.main)
    assert "[janitor-self-disarm]" not in out, "maintenance must NOT self-disarm (that kills the warm cache)"
    expected = "[janitor-resume]\ncontinue your pending task (keep-going mode) — if nothing remains, say so briefly and run /janitor-keep-going off"
    assert out.strip() == expected, f"a maintenance fire must emit ONLY the keep-going nudge, got {out!r}"
    assert ran == [], f"a maintenance fire must run NO detector, ran {ran}"
    stamps = list(state.state_dir().glob("last-run-*.ts"))
    assert stamps == [], f"no detector should have stamped last-run, found {stamps}"
    assert ensured == [True], "maintenance MUST attempt ensure_daemon_running (TRDD-8PH8YOIJ survival)"


def test_main_maintenance_under_kill_switch_keeps_beating(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """The keep-warm-while-fleet-down property end-to-end: with the kill-switch set AND the
    maintenance flag set, main() does NOT self-disarm and the daemon is NOT actually spawned —
    the session keeps a cheap cache-refresh beat while the fleet/daemon stay down
    (TRDD-FPL60EKV). Since TRDD-8PH8YOIJ, maintenance DOES call ensure_daemon_running (the
    survival respawn), so this test lets the REAL gate run and asserts the deeper
    spawn_daemon_detached is never reached — a deliberate global STOP still wins."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    gs.set_kill_switch("fleet-down")
    (state.state_dir() / "maintenance-mode").write_text("", encoding="utf-8")

    ran: list[str] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: ran.append(name))
    monkeypatch.setattr(
        dispatch.gs,
        "spawn_daemon_detached",
        lambda *a, **k: pytest.fail("daemon spawned while the fleet is kill-switched"),
    )

    out = _capture_stdout(dispatch.main)
    assert "[janitor-self-disarm]" not in out, "maintenance must override the kill-switch self-disarm"
    assert ran == [], "maintenance runs no detectors"


# ---------- Phase 1.5a: keep-going never-stop nudge (TRDD-TKNSTP82 Part B) --

_KEEP_GOING_LINE = "continue your pending task (keep-going mode) — if nothing remains, say so briefly and run /janitor-keep-going off"


def test_phase_keep_going_nudge_silent_full_mode_no_flag(env_isolation: dict) -> None:
    """RUNAWAY GUARD: full mode with no keep-going flag and not maintenance → silent. This is
    what keeps a plain interactive/default session from ever seeing the nudge."""
    dispatch = _import_dispatch()
    import state

    state.init_state()
    out = _capture_stdout(lambda: dispatch._phase_keep_going_nudge("full"))
    assert out == "", f"full mode with no opt-in must stay silent, got {out!r}"


def test_phase_keep_going_nudge_emits_in_full_mode_with_flag(env_isolation: dict) -> None:
    """The standalone /janitor-keep-going opt-in: full mode + flag present → nudge emitted."""
    dispatch = _import_dispatch()
    import state

    state.init_state()
    (state.state_dir() / "keep-going").write_text("", encoding="utf-8")

    out = _capture_stdout(lambda: dispatch._phase_keep_going_nudge("full"))
    assert out.splitlines() == ["[janitor-resume]", _KEEP_GOING_LINE], f"unexpected nudge output: {out!r}"


def test_phase_keep_going_nudge_emits_in_maintenance_mode_no_flag(env_isolation: dict) -> None:
    """Maintenance ALWAYS gets the nudge, even with no standalone flag set — mode alone opts in."""
    dispatch = _import_dispatch()
    import state

    state.init_state()
    out = _capture_stdout(lambda: dispatch._phase_keep_going_nudge("maintenance"))
    assert out.splitlines() == ["[janitor-resume]", _KEEP_GOING_LINE], f"unexpected nudge output: {out!r}"


def test_phase_keep_going_nudge_no_dedupe_refires_every_call(env_isolation: dict) -> None:
    """Unlike the day-bucketed renew nudge, this MUST re-fire on every due heartbeat while the
    opt-in holds — a one-time nudge would miss a session idle across several heartbeats."""
    dispatch = _import_dispatch()
    import state

    state.init_state()
    (state.state_dir() / "keep-going").write_text("", encoding="utf-8")

    first = _capture_stdout(lambda: dispatch._phase_keep_going_nudge("full"))
    second = _capture_stdout(lambda: dispatch._phase_keep_going_nudge("full"))
    assert first == second, "the nudge must re-fire identically on every call, no dedupe"
    assert first.splitlines() == ["[janitor-resume]", _KEEP_GOING_LINE]


def test_main_full_mode_no_keep_going_flag_no_nudge(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """BEHAVIORAL PROOF: plain full mode, no flag, not maintenance → no nudge text at all."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()

    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: None)
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_phase_guard_branch_protection", lambda: None)

    out = _capture_stdout(dispatch.main)
    assert "[janitor-resume]" not in out, f"a plain full-mode fire with no opt-in must not nudge, got {out!r}"
    assert "keep-going mode" not in out


def test_main_full_mode_with_keep_going_flag_emits_nudge_and_still_runs_detectors(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """BEHAVIORAL PROOF: the standalone opt-in nudges AND keeps full-mode chores running —
    unlike maintenance, keep-going in FULL mode does NOT skip detectors/daemon."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    (state.state_dir() / "keep-going").write_text("", encoding="utf-8")

    ran: list[str] = []
    daemon_calls: list[str] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: ran.append(name))
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: daemon_calls.append("called"))
    monkeypatch.setattr(dispatch, "_phase_guard_branch_protection", lambda: None)

    out = _capture_stdout(dispatch.main)
    assert out.splitlines()[:2] == ["[janitor-resume]", _KEEP_GOING_LINE], f"nudge must lead the output, got {out!r}"
    assert len(ran) > 0, "keep-going in FULL mode must still run the due detector roster"
    assert daemon_calls == ["called"], "keep-going in FULL mode must still lazy-spawn the daemon"


def test_main_rate_limit_resume_short_circuits_before_keep_going_nudge(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A prior rate-limit resume returns early — the keep-going nudge (even with the flag set)
    must NOT also appear; only the rate-limit resume cue does."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    sd = state.state_dir()
    state.atomic_write(sd / "rate-limited.flag", "1")
    state.atomic_write(sd / "rate-limited-since.ts", str(int(time.time()) - 10))
    (sd / "keep-going").write_text("", encoding="utf-8")

    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: pytest.fail("detectors must not run"))
    monkeypatch.setattr(
        dispatch.gs,
        "ensure_daemon_running",
        lambda *a, **k: pytest.fail("daemon spawn attempted during rate-limit resume"),
    )

    out = _capture_stdout(dispatch.main)
    # F7: bare marker line, prose on line 2 (whole-line-only marker contract).
    assert out.startswith("[janitor-resume]\nrate-limit cleared"), f"rate-limit resume must lead, got {out!r}"
    assert "keep-going mode" not in out, "the keep-going nudge must not also fire this turn"


def test_main_compact_resume_short_circuits_before_keep_going_nudge(env_isolation: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same short-circuit guarantee for a prior post-compact resume."""
    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    _arm_compact_flag(state, "continue TRDD-abcd1234")
    (state.state_dir() / "keep-going").write_text("", encoding="utf-8")

    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: pytest.fail("detectors must not run"))
    monkeypatch.setattr(
        dispatch.gs,
        "ensure_daemon_running",
        lambda *a, **k: pytest.fail("daemon spawn attempted during compact resume"),
    )

    out = _capture_stdout(dispatch.main)
    # F7: bare marker line, directive on line 2 (whole-line-only marker contract).
    assert out.startswith("[janitor-resume]\nContext was compacted"), f"compact resume must lead, got {out!r}"
    assert "keep-going mode" not in out, "the keep-going nudge must not also fire this turn"


class TestStateRetentionSweep:
    """F21 (wikimem audit): the daily retention phase also sweeps dead state files."""

    def test_stale_txt_and_ts_files_are_swept_fresh_survive(self, env_isolation: dict) -> None:
        """*.txt / *.ts older than the window are removed; recently-touched ones survive."""
        dispatch = _import_dispatch()
        import os as _os

        import state

        state.init_state()
        sd = state.state_dir()
        old = time.time() - 60 * 86400  # well past the 45-day default
        stale_txt = sd / "memorize-nudge-session-deadbeef.txt"
        stale_ts = sd / "last-run-some-retired-detector.ts"
        fresh_txt = sd / "heartbeat-renew-seen.txt"
        for f in (stale_txt, stale_ts, fresh_txt):
            f.write_text("x", encoding="utf-8")
        _os.utime(stale_txt, (old, old))
        _os.utime(stale_ts, (old, old))

        dispatch._phase_log_retention()

        assert not stale_txt.exists(), "a 60-day-old per-session seen file must be swept"
        assert not stale_ts.exists(), "a 60-day-old orphan cadence stamp must be swept"
        assert fresh_txt.exists(), "a freshly-touched file must survive the sweep"

    def test_control_flags_are_never_swept(self, env_isolation: dict) -> None:
        """Flags change behavior — even ancient ones are NEVER deleted by the sweep."""
        dispatch = _import_dispatch()
        import os as _os

        import state

        state.init_state()
        sd = state.state_dir()
        old = time.time() - 365 * 86400
        flag = sd / "rate-limited.flag"
        paused = sd / "paused"
        for f in (flag, paused):
            f.write_text("", encoding="utf-8")
            _os.utime(f, (old, old))

        dispatch._phase_log_retention()

        assert flag.exists(), "*.flag files must never be swept"
        assert paused.exists(), "extensionless control files must never be swept"

    def test_dead_global_rr_cursor_is_removed(self, env_isolation: dict) -> None:
        """The pre-F2 machine-wide round-robin cursor orphan is GC'd from the global dir."""
        dispatch = _import_dispatch()
        import global_state as gs

        gs.init_global_state()
        orphan = gs.global_state_dir() / "memory-maint-rr-cursor.ts"
        orphan.write_text("3", encoding="utf-8")

        dispatch._phase_log_retention()

        assert not orphan.exists(), "the dead machine-wide cursor must be GC'd"
