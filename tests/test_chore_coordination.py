"""Daemon singleton-chore coordination with the ai-maestro server (TRDD-PZLVT2RN Phase B2).

Owner directive (2026-07-17, TRDD-LU0C5KAR — overrode the per-class design as "too
complicated"): "by design, if the ai-maestro server is running, those chores are its
responsibility. so the janitor daemon must switch off those chores. any other event is a
bug." So the switch is BINARY on server LIVENESS: a fresh probe file ⇒ ALL absorbed
chores yield; absent/stale ⇒ the janitor runs them ALL — while the population-split ops
(session-liveness, fleet-stop) keep running on both sides, each for its own population.

These tests pin the three load-bearing properties:
  1. The yield is binary and total: server alive ⇒ every absorbed chore yields
     (capability content irrelevant — `[]` included); server gone ⇒ none do.
  2. The absorbed set names REAL tasks (typo guard) and NEVER includes a population-split
     or janitor-only Family-B task.
  3. The per-session daemon-staleness watchdog goes SILENT while the server owns the
     chores — a deliberately-yielded chore's stale stamp is expected, not an alarm.
"""

from __future__ import annotations

import io
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import daemon_watchdog  # type: ignore[import-not-found]  # noqa: E402
import harness_backend as hb  # type: ignore[import-not-found]  # noqa: E402
import state as janitor_state  # type: ignore[import-not-found]  # noqa: E402

_OVERRIDE_VARS = (hb.SERVER_CHORES_ENV, hb.SERVER_STATE_ENV)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolated global state + no leftover overrides; NO test may read the REAL
    server-liveness probe file (this machine may run the ai-maestro server, so an
    un-overridden read of ~/.aimaestro/server-liveness.json would be nondeterministic)
    — point it at a guaranteed-absent path."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for var in _OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent-liveness.json"))
    # Flush state's process-lifetime path caches (project_root & friends): an
    # in-process test that ran EARLIER in the same pytest process may have pinned
    # the REAL repo root, which would send the watchdog's emit_once seen-file to
    # the repo's own .janitor/state — where a previous run's hour-key silences the
    # alarm and flips the control test (root-caused 2026-07-17).
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()
    yield
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()


# ---------- 1. the yield policy ----------


def test_yield_is_binary_on_server_liveness() -> None:
    """An absorbed chore yields IFF the server is alive — no tri-state, no per-chore
    verification (TRDD-LU0C5KAR)."""
    name = "marketplace-refresh"
    assert daemon._task_yielded_to_server(name, True) is True
    assert daemon._task_yielded_to_server(name, False) is False


def test_non_absorbed_task_never_yields() -> None:
    """A task outside the absorbed set runs even under a running server."""
    assert daemon._task_yielded_to_server("session-liveness", True) is False


def test_server_alive_silences_all_absorbed_chores() -> None:
    """THE binary-rule pin (owner directive 2026-07-17): a RUNNING server owns EVERY
    absorbed chore — OAuth pair AND the marketplace/version trio together, regardless
    of what it advertises as live. (This deliberately INVERTS the retired per-class
    regression: a server that runs without executing a chore is a server bug, not a
    janitor guard.)"""
    for name in daemon._SERVER_ABSORBED_TASK_NAMES:
        assert daemon._task_yielded_to_server(name, True) is True, name
        assert daemon._task_yielded_to_server(name, False) is False, name


def test_absorbed_set_matches_the_contract() -> None:
    """Pin the exact absorbed-chore set: the OAuth pair + the update trio — a drift
    here silently changes which chores the handoff covers."""
    assert hb.SERVER_ABSORBED_TASKS == frozenset({
        "marketplace-refresh",
        "user-plugins-update",
        "version-update",
        "oauth-rotator-supervisor",
        "oauth-rotator-tick",
    })


def test_absorbed_set_names_real_tasks() -> None:
    """Typo guard: every absorbed name must be a task `_build_tasks` actually builds —
    a misspelled entry would silently gate nothing."""
    built = {t.name for t in daemon._build_tasks()}
    missing = daemon._SERVER_ABSORBED_TASK_NAMES - built
    assert not missing, f"absorbed names not built by the daemon: {sorted(missing)}"


def test_population_split_and_family_b_tasks_stay_janitor() -> None:
    """The split the owner directed: liveness/fleet-stop run on BOTH sides (each for its
    own population), and the janitor-only Family-B chores never yield."""
    keep = {
        "session-liveness",
        "fleet-stop",
        "memory-guard",
        "cache-prune",
        "rules-cleanup",
        "github-config-audit",
    }
    overlap = keep & daemon._SERVER_ABSORBED_TASK_NAMES
    assert not overlap, f"population-split/Family-B tasks must never yield: {sorted(overlap)}"


def test_yielded_names_cover_the_whole_absorbed_set_when_alive() -> None:
    """Server alive ⇒ exactly the absorbed subset of the built tasks yields; server
    gone ⇒ nothing does. The same set drives the due-loop AND the next-due sleep
    exclusion, so getting it wrong busy-spins the daemon at 1 s ticks."""
    tasks = daemon._build_tasks()
    assert daemon._yielded_task_names(tasks, True) == daemon._SERVER_ABSORBED_TASK_NAMES
    assert daemon._yielded_task_names(tasks, False) == set()


# ---------- 2. the liveness signal ----------


def test_chores_override_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """`$JANITOR_AIMAESTRO_SERVER_CHORES` is the chores-only operator knob; an
    unrecognized value falls through to the liveness probe (absent file here ⇒ False)."""
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert hb.server_runs_chores() is True
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "down")
    assert hb.server_runs_chores() is False
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "unknown")
    assert hb.server_runs_chores() is False


def test_chores_signal_honors_state_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset chores knob ⇒ the STATE override governs — forcing the server "down" for
    adoption also resumes the chores, immediately."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "down")
    assert hb.server_runs_chores() is False
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "up")
    assert hb.server_runs_chores() is True


def test_probe_file_drives_the_binary_yield_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """END-TO-END through the REAL probe (no monkeypatched internals): a fresh liveness
    file — even one advertising NO capabilities — means the server is RUNNING, so the
    WHOLE absorbed set yields; a STALE file means it exited, so everything resumes.
    This is the owner's rule verbatim: running ⇒ its responsibility; exited ⇒ ours."""
    import json as _json
    import time as _time

    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))

    f.write_text(
        _json.dumps({"ts": _time.time(), "pid": 1, "capabilities": []}),
        encoding="utf-8",
    )
    assert hb.server_is_alive() is True
    assert hb.server_runs_chores() is True
    tasks = daemon._build_tasks()
    assert daemon._yielded_task_names(tasks, hb.server_runs_chores()) == (
        daemon._SERVER_ABSORBED_TASK_NAMES
    )

    stale = _time.time() - (hb.LIVENESS_STALE_AFTER_S + 5)
    f.write_text(
        _json.dumps({"ts": stale, "pid": 1, "capabilities": []}), encoding="utf-8"
    )
    assert hb.server_is_alive() is False
    assert hb.server_runs_chores() is False
    assert daemon._yielded_task_names(tasks, hb.server_runs_chores()) == set()


# ---------- 3. the watchdog goes silent while the server owns the chores ----------


def _seed_stale_task_and_dead_daemon(gsd: Path, task: str) -> None:
    """A completion stamp far past the threshold + a dead daemon: the exact state in
    which the watchdog WOULD alarm — unless chore ownership suppresses it."""
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / f"{task}.last-run.ts").write_text(str(int(time.time()) - 7200), encoding="utf-8")
    (gsd / "daemon.pid").write_text("999999", encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text(str(int(time.time()) - 7200), encoding="utf-8")


def _run_watchdog() -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        daemon_watchdog.emit_if_daemon_stale(
            task_name="marketplace-refresh",
            last_run_filename="marketplace-refresh.last-run.ts",
            cadence_env="CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_INTERVAL",
            default_cadence_s=60,
            subject="global marketplaces last refreshed",
        )
    return buf.getvalue()


def test_watchdog_silent_while_server_owns_chores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A yielded chore's stamp goes stale BY DESIGN — the per-session watchdog must not
    cry wolf about it while the server is running."""
    project = tmp_path / "proj"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    _seed_stale_task_and_dead_daemon(tmp_path / "gs", "marketplace-refresh")
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert _run_watchdog() == ""


def test_watchdog_still_alarms_when_server_not_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CONTROL for the suppression test: identical stale-stamp + dead-daemon state with
    the server forced down ⇒ the alarm fires. Proves the silent case above is silent
    because of the ownership gate, not because the alarm path was broken."""
    project = tmp_path / "proj"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    _seed_stale_task_and_dead_daemon(tmp_path / "gs", "marketplace-refresh")
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "down")
    out = _run_watchdog()
    assert "marketplace-refresh" in out and "not responding" in out
