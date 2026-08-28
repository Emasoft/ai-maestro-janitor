"""Tests for the staged legacy → plugin-DATA global-state migration (TRDD-2U8AH82F).

The suite-wide conftest pins JANITOR_GLOBAL_STATE_DIR, so every test here builds its
own world: HOME at a tmp dir, the override + XDG removed — exercising the REAL
resolution ladder. flock(2) locks are per open-file-description, so single-process
lock-exclusion tests are valid (a second fd in the same process still EWOULDBLOCKs).
"""

from __future__ import annotations

import fcntl
import os
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import global_state as gs  # noqa: E402

pytestmark = pytest.mark.real_state  # opts OUT of the conftest env redirect where marked


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Fresh HOME world with the ladder's escape hatches removed. Returns
    (legacy_dir, data_dir) — neither created."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("JANITOR_GLOBAL_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    legacy = tmp_path / ".claude" / "janitor-global-state"
    data = (tmp_path / ".claude" / "plugins" / "data"
            / "ai-maestro-janitor-ai-maestro-plugins" / "global-state")
    return legacy, data


def test_env_override_wins_over_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ladder rung 1: the test-suite escape hatch has absolute priority."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (data / gs._MIGRATION_MARKER).parent.mkdir(parents=True)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "pinned"))
    assert gs.global_state_dir() == (tmp_path / "pinned").resolve()


def test_fresh_install_resolves_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No legacy dir to migrate → the DATA dir is canonical from day one."""
    _, data = _isolate(tmp_path, monkeypatch)
    assert gs.global_state_dir() == data


def test_unmigrated_host_still_resolves_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRDD-ULEGRT01 retired era-1: a legacy dir on disk no longer pulls resolution
    back to it, marker or no marker. The handover is the migration's job now, not the
    resolver's — which is why `migrate_global_state_to_data_dir()` keeps an explicit
    legacy predicate instead of comparing against this function."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    assert gs.global_state_dir() == data


def test_marker_flips_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    data.mkdir(parents=True)
    (data / gs._MIGRATION_MARKER).write_text("1\n", encoding="utf-8")
    assert gs.global_state_dir() == data


def test_migration_copies_state_stamps_marker_and_tombstones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full handover: files + subdirs copied, kernel locks + pid NOT copied,
    marker stamped, tombstone dropped, resolution flipped, NEW flock returned held."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "kill-switch.flag").write_text("stop\n", encoding="utf-8")
    (legacy / "marketplace-refresh.last-run.ts").write_text("123\n", encoding="utf-8")
    (legacy / "snapshots").mkdir()
    (legacy / "snapshots" / "ps.txt").write_text("x\n", encoding="utf-8")
    (legacy / "daemon.pid").write_text("999\n", encoding="utf-8")
    (legacy / "daemon.flock").write_text("", encoding="utf-8")
    # Every OTHER flock too: a copied lock file carries zero kernel state, so each copy
    # would be an empty decoy at a path a reader can mistake for the live inode.
    (legacy / "settings-ensurer.lock").write_text("", encoding="utf-8")
    (legacy / "ticket-dispatch.lock").write_text("", encoding="utf-8")
    fd = gs.migrate_global_state_to_data_dir()
    assert fd is not None
    try:
        assert (data / "kill-switch.flag").read_text(encoding="utf-8") == "stop\n"
        assert (data / "marketplace-refresh.last-run.ts").is_file()
        assert (data / "snapshots" / "ps.txt").is_file()
        assert not (data / "daemon.pid").exists(), "pid is re-published, never copied"
        for lock in ("daemon.flock", "settings-ensurer.lock", "ticket-dispatch.lock"):
            # NB: daemon.flock DOES exist at data — created by the migration's own
            # flock-moves-LAST acquisition, never by the copy. The other locks must be
            # absent entirely: no kernel state copies, so a copy is only a decoy.
            if lock != "daemon.flock":
                assert not (data / lock).exists(), f"{lock} must not be copied"
        assert (data / gs._MIGRATION_MARKER).is_file()
        assert (legacy / "README-MOVED.txt").is_file()
        assert gs.global_state_dir() == data
        # Flock-moves-LAST: the returned fd HOLDS the new lock — a second daemon
        # resolving the new dir must lose the singleton race. (The dual acquire probes
        # the migrated data-dir inode too, and flock conflicts across open file
        # descriptions even in-process, so the held migration fd denies it.)
        assert gs.acquire_singleton_dual() is None
    finally:
        os.close(fd)


def test_migration_noop_on_fresh_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(tmp_path, monkeypatch)
    assert gs.migrate_global_state_to_data_dir() is None


def test_migration_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call after a completed migration is a clean no-op (resolution is
    already the DATA dir)."""
    legacy, _ = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    fd = gs.migrate_global_state_to_data_dir()
    assert fd is not None
    try:
        assert gs.migrate_global_state_to_data_dir() is None
    finally:
        os.close(fd)


def test_migration_aborts_without_marker_when_new_flock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ANYTHING already holds the NEW dir's flock, the marker must NOT flip — an
    unmigrated legacy dir left in place beats a two-daemon split-brain. Since
    TRDD-ULEGRT01 resolution is the DATA dir either way, so the marker (not the
    resolver) is the thing that must still say "not handed over"."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    data.mkdir(parents=True)
    holder = os.open(data / "daemon.flock", os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert gs.migrate_global_state_to_data_dir() is None
        assert not (data / gs._MIGRATION_MARKER).exists()
        assert not (legacy / "README-MOVED.txt").exists()
    finally:
        os.close(holder)


def test_legacy_kill_switch_is_no_longer_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRDD-ULEGRT01: a flag left in the retired era-1 dir is inert. The version-skew
    window it covered closed — every live writer is at control_dir() or the DATA dir —
    and the migration copies a real un-handed-over STOP forward before it can be lost."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    data.mkdir(parents=True)
    (data / gs._MIGRATION_MARKER).write_text("1\n", encoding="utf-8")
    (legacy / "kill-switch.flag").write_text("old-code stop\n", encoding="utf-8")
    assert gs.kill_switch_present() is False


def test_migration_carries_an_unhanded_over_kill_switch_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety net that makes the test above acceptable: on a never-migrated host the
    migration still runs (its predicate is explicit, not a `global_state_dir()`
    comparison that era-1 retirement would have made permanently true) and copies the
    STOP into the dir readers now use."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "kill-switch.flag").write_text("old-code stop\n", encoding="utf-8")
    fd = gs.migrate_global_state_to_data_dir()
    assert fd is not None, "a legacy dir with no marker MUST still be handed over"
    try:
        assert (data / "kill-switch.flag").is_file()
        assert gs.kill_switch_present() is True
    finally:
        os.close(fd)


def test_clear_reaches_the_retired_dir_so_migration_cannot_resurrect_a_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cleared STOP must stay cleared even though the migration copies state forward.

    The regression this pins: retiring era-1 removed the legacy READS, and removing the
    legacy UNLINK from `_flag_clear_dual` looks like the same edit. It is not. On an
    un-migrated host the legacy copy is the ONLY copy — so a clear that skips it leaves
    it for `migrate_global_state_to_data_dir()` to copy into the dir readers DO use, and
    `/janitor-global-arm` is silently undone. Ordering is load-bearing: clear FIRST, then
    migrate, which is the real sequence (arm is a user action; the migration runs on the
    daemon's next start)."""
    legacy, data = _isolate(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "kill-switch.flag").write_text("stop\n", encoding="utf-8")
    gs.clear_kill_switch()
    fd = gs.migrate_global_state_to_data_dir()
    try:
        assert not (data / "kill-switch.flag").exists(), "migration resurrected a cleared STOP"
        assert gs.kill_switch_present() is False
    finally:
        if fd is not None:
            os.close(fd)


def test_dual_read_generation_takes_max(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A newer generation stamp from EITHER live era wins — control_dir() (canonical)
    vs the pre-control-dir global_state_dir() location an older session still writes."""
    _, data = _isolate(tmp_path, monkeypatch)
    data.mkdir(parents=True)
    control = Path(gs.control_dir())
    control.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    (control / "skills-reload-needed.flag").write_text(f"{now - 100}\tnew\n", encoding="utf-8")
    (data / "skills-reload-needed.flag").write_text(f"{now}\told-code\n", encoding="utf-8")
    assert gs.skills_reload_generation() == now
