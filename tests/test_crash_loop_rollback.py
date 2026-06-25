"""Tests for C4 (TRDD-T198DT1W) — bad-self-update auto-rollback.

C4 is the PRODUCER half of the dispatcher-stub's C3 quarantine-skip: when a
janitor self-update lands a newest cache version whose daemon/heartbeat
crash-loops (won't STAY alive), the dispatch heartbeat QUARANTINES that newest
version so the stub falls back to a known-good older version on the next fire —
auto-rollback, no new stub change.

Two layers are covered, both with real on-disk round-trips (no mocks):

  * the PURE decision in ``version_update_lib`` (``older_runnable_version`` +
    ``plan_crash_loop_rollback``) — the fallback-exists / already-quarantined /
    crash-loop gates;
  * the ``dispatch._phase_crash_loop_rollback`` phase — it writes the quarantine
    + emits ``[janitor-rollback]`` + dedupes + swallows faults;
  * the public read-only crash-loop signal in ``global_state``
    (``crash_loop_active`` / ``recent_spawn_count``).

CARDINAL RULE under test = FAIL-OPEN / ZERO-FALSE-ROLLBACK: a HEALTHY update is
NEVER rolled back (the spawn breaker never trips), a crash-loop with NO older
fallback rolls back nothing (the stub's own backstop runs the newest — a bad
heartbeat beats a dead one), and an already-quarantined version is never
re-alerted. The headline test is ``test_healthy_update_is_never_rolled_back``
(zero false-rollback) — run against a real multi-version cache layout.
"""

from __future__ import annotations

import importlib.util as _u
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def vu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """version_update_lib with the DATA dir redirected to a tmp tree (the
    quarantine/pin trust-anchor files), so no test touches the real ~/.claude."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    for mod in ("version_update_lib", "janitor_self_integrity", "janitor_integrity"):
        sys.modules.pop(mod, None)
    import version_update_lib as mod  # noqa: PLC0415

    return mod


def _make_cache(parent: Path, versions: dict[str, bool]) -> None:
    """Build a cache-parent tree: ``{version: has_dispatch_py}``. A version with
    has_dispatch_py=True gets a runnable ``<v>/scripts/dispatch.py``; False makes
    the version dir exist but with no dispatch.py (unrunnable)."""
    for v, runnable in versions.items():
        vdir = parent / v
        vdir.mkdir(parents=True, exist_ok=True)
        if runnable:
            scripts = vdir / "scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            (scripts / "dispatch.py").write_text("#!/usr/bin/env python3\n")


# ── older_runnable_version (pure) ───────────────────────────────────────────


def test_older_runnable_version_picks_highest_older(vu, tmp_path):
    """The highest STRICTLY-older version with a dispatch.py is the fallback."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.19.1": True, "0.20.1": True, "0.21.0": True})
    assert vu.older_runnable_version(cache, "0.21.0") == "0.20.1"


def test_older_runnable_version_none_when_no_older(vu, tmp_path):
    """No version older than the newest → None (nothing to fall back to)."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.21.0": True})
    assert vu.older_runnable_version(cache, "0.21.0") is None


def test_older_runnable_version_skips_unrunnable_older(vu, tmp_path):
    """An older version WITHOUT a dispatch.py is not a valid fallback — the next
    runnable-older one is chosen instead (here: none → None)."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.20.1": False, "0.21.0": True})  # 0.20.1 has no dispatch.py
    assert vu.older_runnable_version(cache, "0.21.0") is None


def test_older_runnable_version_skips_unrunnable_picks_next(vu, tmp_path):
    """When the closest-older version is unrunnable, the next runnable-older one
    is the fallback."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.19.1": True, "0.20.1": False, "0.21.0": True})
    assert vu.older_runnable_version(cache, "0.21.0") == "0.19.1"


# ── plan_crash_loop_rollback (pure) ─────────────────────────────────────────


def test_plan_none_when_not_crash_looping(vu, tmp_path):
    """ZERO-FALSE-ROLLBACK: crash_loop=False → None, no matter the cache. This is
    the gate that makes a healthy update un-rollbackable."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.20.1": True, "0.21.0": True})
    assert vu.plan_crash_loop_rollback(cache, crash_loop=False) is None


def test_plan_rolls_back_newest_with_fallback(vu, tmp_path):
    """Crash-looping + a runnable older version → (newest, fallback)."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.20.1": True, "0.21.0": True})
    assert vu.plan_crash_loop_rollback(cache, crash_loop=True) == ("0.21.0", "0.20.1")


def test_plan_none_with_no_fallback(vu, tmp_path):
    """Crash-looping but the newest is the ONLY runnable version → None (fail-open:
    the stub's own backstop still runs the newest — a bad heartbeat beats a dead
    one; there is nothing better to roll back to)."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.21.0": True})
    assert vu.plan_crash_loop_rollback(cache, crash_loop=True) is None


def test_plan_none_when_newest_already_quarantined(vu, tmp_path):
    """Idempotent: once the newest is quarantined, the plan returns None so the
    phase never re-alerts every fire."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.20.1": True, "0.21.0": True})
    assert vu.add_quarantine("0.21.0", "crash-loop")
    assert vu.plan_crash_loop_rollback(cache, crash_loop=True) is None


def test_plan_none_when_newest_unrunnable(vu, tmp_path):
    """A newest dir with no dispatch.py is already unrunnable — the stub skips it
    on its own, so the plan does not quarantine it (None)."""
    cache = tmp_path / "cache"
    _make_cache(cache, {"0.20.1": True, "0.21.0": False})  # 0.21.0 = newest, no dispatch
    assert vu.plan_crash_loop_rollback(cache, crash_loop=True) is None


def test_plan_none_on_empty_cache(vu, tmp_path):
    """No installed versions at all → None (nothing to reason about)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    assert vu.plan_crash_loop_rollback(cache, crash_loop=True) is None


# ── public crash-loop signal (global_state) ─────────────────────────────────


@pytest.fixture
def gs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """global_state with an isolated global-state dir (the spawn-history lives
    there)."""
    d = tmp_path / "janitor-global-state"
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(d))
    sys.modules.pop("global_state", None)
    import global_state as mod  # noqa: PLC0415

    mod.init_global_state()
    return mod


def test_public_crash_loop_active_mirrors_breaker(gs):
    """crash_loop_active() is True iff the breaker is tripped (LIMIT recent
    spawns), matching _crash_loop_active — but exposed for dispatch to read."""
    now = int(time.time())
    hist = gs._spawn_history_path()
    assert gs.crash_loop_active(now=now) is False  # no history
    recent = [str(now - 10 * i) for i in range(gs._CRASH_LOOP_SPAWN_LIMIT)]
    gs.state.atomic_write(hist, "\n".join(recent))
    assert gs.crash_loop_active(now=now) is True


def test_public_recent_spawn_count(gs):
    """recent_spawn_count() counts attempts inside the window; old ones excluded;
    missing history → 0 (fail-open)."""
    now = int(time.time())
    assert gs.recent_spawn_count(now=now) == 0  # no history → 0
    lines = [str(now - 5), str(now - 10), str(now - gs._CRASH_LOOP_WINDOW_S - 100)]
    gs.state.atomic_write(gs._spawn_history_path(), "\n".join(lines))
    assert gs.recent_spawn_count(now=now) == 2  # the two recent ones, not the aged-out one


def test_public_record_spawn_attempt_appends_one(gs):
    """KEEPQRTN HIGH-2: record_spawn_attempt() (the OS-keepalive path's recorder)
    appends EXACTLY ONE entry — the same ring _record_spawn_attempt writes — so the
    OS-respawn loop becomes visible to the breaker without double-counting."""
    now = int(time.time())
    assert gs.recent_spawn_count(now=now) == 0
    gs.record_spawn_attempt(now=now)
    assert gs.recent_spawn_count(now=now) == 1
    gs.record_spawn_attempt(now=now)
    assert gs.recent_spawn_count(now=now) == 2  # one entry per call, never more


def test_public_record_spawn_attempt_trips_breaker(gs):
    """Enough OS-keepalive records inside the window trip crash_loop_active() — the
    signal C4 reads to quarantine a die-on-start OS-respawned daemon."""
    now = int(time.time())
    assert gs.crash_loop_active(now=now) is False
    for i in range(gs._CRASH_LOOP_SPAWN_LIMIT):
        gs.record_spawn_attempt(now=now - i)  # all inside the window
    assert gs.crash_loop_active(now=now) is True


# ── dispatch._phase_crash_loop_rollback (the producer) ──────────────────────


def _import_dispatch():
    """Import scripts/dispatch.py as a module without running main()."""
    spec = _u.spec_from_file_location(
        "janitor_dispatch_c4_under_test",
        str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn) -> str:
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


@pytest.fixture
def phase_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Full isolation for the dispatch phase: a project dir, an isolated global
    state dir (spawn-history), a DATA dir (quarantine), and a cache parent that
    JANITOR_CACHE_PARENT points at. Reloads dispatch + its deps so module-level
    path resolution picks up the env."""
    project = tmp_path / "project"
    project.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    global_dir = tmp_path / "janitor-global-state"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("JANITOR_CACHE_PARENT", str(cache))
    for mod in (
        "dispatch", "global_state", "state",
        "version_update_lib", "janitor_self_integrity", "janitor_integrity",
    ):
        sys.modules.pop(mod, None)
    return {"project": project, "data": data, "cache": cache, "global_dir": global_dir}


def _trip_breaker(dispatch, now: int | None = None) -> None:
    """Write a spawn-history that trips the crash-loop breaker."""
    now = int(now if now is not None else time.time())
    hist = dispatch.gs._spawn_history_path()
    hist.parent.mkdir(parents=True, exist_ok=True)
    dispatch.gs.state.atomic_write(
        hist, "\n".join(str(now - 10 * i) for i in range(dispatch.gs._CRASH_LOOP_SPAWN_LIMIT))
    )


def test_healthy_update_is_never_rolled_back(phase_env):
    """THE zero-false-rollback proof: a multi-version cache + NO crash-loop (the
    breaker untripped, exactly like a healthy update) → the phase is a silent
    no-op and writes NO quarantine. The newest stays runnable."""
    dispatch = _import_dispatch()
    _make_cache(phase_env["cache"], {"0.20.1": True, "0.21.0": True})
    # No spawn-history at all → breaker untripped → healthy.
    out = _capture(dispatch._phase_crash_loop_rollback)
    assert out.strip() == "", "a healthy update must emit nothing"
    assert dispatch.vu.read_quarantine() == set(), "a healthy update must quarantine NOTHING"


def test_crash_loop_quarantines_newest_and_alerts(phase_env):
    """Crash-looping + an older runnable fallback → the newest is quarantined and
    a single [janitor-rollback] alert is emitted naming the fallback."""
    dispatch = _import_dispatch()
    _make_cache(phase_env["cache"], {"0.20.1": True, "0.21.0": True})
    _trip_breaker(dispatch)
    out = _capture(dispatch._phase_crash_loop_rollback)
    assert "[janitor-rollback]" in out
    assert "0.21.0" in out and "0.20.1" in out
    assert dispatch.vu.read_quarantine() == {"0.21.0"}, "the bad newest must be quarantined"


def test_crash_loop_rollback_alert_dedupes(phase_env):
    """The alert fires once per distinct bad version — a second fire while still
    crash-looping is silent (the quarantine is already in place + dedupe stamp)."""
    dispatch = _import_dispatch()
    _make_cache(phase_env["cache"], {"0.20.1": True, "0.21.0": True})
    _trip_breaker(dispatch)
    first = _capture(dispatch._phase_crash_loop_rollback)
    assert "[janitor-rollback]" in first
    second = _capture(dispatch._phase_crash_loop_rollback)
    assert second.strip() == "", "second fire must not re-alert (idempotent)"


def test_crash_loop_no_fallback_is_failopen_noop(phase_env):
    """Crash-looping but the newest is the only runnable version → NO quarantine,
    nothing emitted: fail-open, the stub's own backstop still runs the newest."""
    dispatch = _import_dispatch()
    _make_cache(phase_env["cache"], {"0.21.0": True})  # only one runnable version
    _trip_breaker(dispatch)
    out = _capture(dispatch._phase_crash_loop_rollback)
    assert out.strip() == ""
    assert dispatch.vu.read_quarantine() == set(), \
        "with no fallback, nothing may be quarantined (fail-open)"


def test_phase_swallows_exceptions(phase_env):
    """A fault inside the phase (here: crash_loop_active raising) is logged and
    swallowed — the heartbeat is never crashed by a rollback fault."""
    dispatch = _import_dispatch()

    def _boom(*_a, **_k):
        raise RuntimeError("simulated global-state failure")

    dispatch.gs.crash_loop_active = _boom  # type: ignore[assignment]
    dispatch._phase_crash_loop_rollback()  # must not raise


def test_phase_noop_when_not_crash_looping_even_with_cache(phase_env):
    """Belt-and-suspenders: with a full multi-version cache but the breaker
    untripped, the phase exits at the crash_loop_active gate — no cache probe, no
    quarantine."""
    dispatch = _import_dispatch()
    _make_cache(phase_env["cache"], {"0.19.1": True, "0.20.1": True, "0.21.0": True})
    out = _capture(dispatch._phase_crash_loop_rollback)
    assert out.strip() == ""
    assert dispatch.vu.read_quarantine() == set()
