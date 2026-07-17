"""Daemon singleton-chore coordination with the ai-maestro server (TRDD-PZLVT2RN Phase B2).

Owner directive (2026-07-17): when the ai-maestro server is ACTIVE, the #N daemon must
deactivate the machine-wide ONCE-ONLY chores (oauth rotation, marketplace/plugin updates,
self-update) — "to avoid doing the same chores twice" — while the population-split ops
(session-liveness, fleet-stop) keep running on both sides, each for its own population.

These tests pin the three load-bearing properties:
  1. The yield policy fires ONLY on a CONFIDENT True — the None-policy here is the
     OPPOSITE of the fleet-actuation exclusion (chores run on unknown; nobody doing the
     chores breaks the machine, doing them twice is merely lock-backstopped waste).
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
    """Isolated global state + no leftover overrides; NO test may reach the real
    probe subprocess (this machine has the ai-maestro CLI installed, so an
    un-overridden call would spawn it — slow and nondeterministic)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for var in _OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    hb._chores_cache = None  # noqa: SLF001 -- reset the memo between tests
    # Flush state's process-lifetime path caches (project_root & friends): an
    # in-process test that ran EARLIER in the same pytest process may have pinned
    # the REAL repo root, which would send the watchdog's emit_once seen-file to
    # the repo's own .janitor/state — where a previous run's hour-key silences the
    # alarm and flips the control test (root-caused 2026-07-17).
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()
    yield
    hb._chores_cache = None  # noqa: SLF001
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()


# ---------- 1. the yield policy ----------


def test_yield_only_on_confident_true() -> None:
    """An absorbed chore yields IFF ownership is CONFIDENTLY True — None and False both
    keep the chore running (the machine must never lose its chores to a probe hiccup)."""
    name = "marketplace-refresh"
    assert daemon._task_yielded_to_server(name, True) is True
    assert daemon._task_yielded_to_server(name, None) is False
    assert daemon._task_yielded_to_server(name, False) is False


def test_non_absorbed_task_never_yields() -> None:
    """A task outside the absorbed set runs even under a confirmed-active server."""
    assert daemon._task_yielded_to_server("session-liveness", True) is False


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


def test_yielded_names_cover_the_whole_absorbed_set_when_owned() -> None:
    """With ownership True, exactly the absorbed subset of the built tasks yields —
    and with None, nothing does. The same set drives the due-loop AND the next-due
    sleep exclusion, so getting it wrong busy-spins the daemon at 1 s ticks."""
    tasks = daemon._build_tasks()
    assert daemon._yielded_task_names(tasks, True) == daemon._SERVER_ABSORBED_TASK_NAMES
    assert daemon._yielded_task_names(tasks, None) == set()
    assert daemon._yielded_task_names(tasks, False) == set()


# ---------- 2. the ownership signal ----------


def test_chores_override_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """`$JANITOR_AIMAESTRO_SERVER_CHORES` is the chores-only operator knob."""
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert hb.server_owns_singleton_chores() is True
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "down")
    assert hb.server_owns_singleton_chores() is False
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "unknown")
    assert hb.server_owns_singleton_chores() is None


def test_chores_signal_delegates_to_family_a_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset chores knob ⇒ the family-A override governs both signals — forcing the
    server "down" for adoption also resumes the chores, immediately (memo bypassed)."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "down")
    assert hb.server_owns_singleton_chores() is False
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "up")
    assert hb.server_owns_singleton_chores() is True


def test_chores_probe_result_is_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no overrides, the underlying probe runs at most once per TTL — the daemon
    calls this every 60 s tick and must not spawn a probe subprocess each time."""
    calls = {"n": 0}

    def fake_probe(*, timeout: int = 10):
        calls["n"] += 1
        return None

    monkeypatch.setattr(hb, "server_owns_family_a", fake_probe)
    assert hb.server_owns_singleton_chores() is None
    assert hb.server_owns_singleton_chores() is None
    assert calls["n"] == 1, "second call within the TTL must hit the memo"


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
    cry wolf about it while the server is confirmed active."""
    project = tmp_path / "proj"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    _seed_stale_task_and_dead_daemon(tmp_path / "gs", "marketplace-refresh")
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert _run_watchdog() == ""


def test_watchdog_still_alarms_when_server_not_confirmed(
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
