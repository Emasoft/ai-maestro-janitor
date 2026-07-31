"""Tests for the fixed control-plane directory (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X).

The machine-wide MODE flags (kill-switch, maintenance, the two reload generations,
version-update-request) move from `global_state_dir()`'s 4-rung resolution
ladder to ONE fixed path (`~/.claude/janitor-control/`) so an external program — the
ai-maestro server, with no fixed install location of its own — can hardcode and `stat()`
it without reproducing a ladder it cannot know about.

Isolation: every test points BOTH `JANITOR_CONTROL_DIR` and `JANITOR_GLOBAL_STATE_DIR` at
fresh tmp dirs so nothing here ever touches the real `~/.claude/janitor-control/` or the
real global-state dir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Isolated (control_dir, global_state_dir) pair, neither created — the real
    per-flag write helpers must mkdir on write, so a fresh test starts with nothing
    on disk. Also drop any cached module state from a previous test's import."""
    control = tmp_path / "control"
    gsd = tmp_path / "global-state"
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(control))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    for mod in ("global_state",):
        if mod in sys.modules:
            del sys.modules[mod]
    return control, gsd


def _gs():
    """Import global_state fresh after the env is set (mirrors test_global_state.py)."""
    import global_state  # type: ignore[import-not-found]

    return global_state


# Each live flag, paired with its present()/set()/clear() API and the on-disk filename.
# `global-pause.flag` was a seventh row until 2026-07-31: the pause switch is retired
# (owner directive), and only its CLEAR survives, as a migration sweep — so there is no
# set()/present() pair left to round-trip.
_FLAGS = [
    ("kill-switch.flag", "kill_switch_present", "set_kill_switch", "clear_kill_switch"),
    ("maintenance-mode.flag", "maintenance_mode_present", "set_maintenance_mode", "clear_maintenance_mode"),
    ("reload-needed.flag", "reload_flag_present", "set_reload_flag", "clear_reload_flag"),
    ("skills-reload-needed.flag", "skills_reload_flag_present", "set_skills_reload_flag", "clear_skills_reload_flag"),
    ("version-update-requested.flag", "version_update_requested_present", "request_version_update", "clear_version_update_request"),
]


@pytest.mark.parametrize("fname,present_fn,set_fn,clear_fn", _FLAGS)
def test_each_flag_round_trips_through_control_dir(
    dirs: tuple[Path, Path], fname: str, present_fn: str, set_fn: str, clear_fn: str
) -> None:
    """Every one of the six flags is absent → present → absent through its own API,
    and the SET write actually lands at control_dir() — not at the old
    global_state_dir() location — since that FIXED path is the whole point of the
    move (an external reader must be able to hardcode it)."""
    control, _gsd = dirs
    gs = _gs()
    present = getattr(gs, present_fn)
    set_ = getattr(gs, set_fn)
    clear = getattr(gs, clear_fn)

    assert present() is False
    set_("test-reason")
    assert present() is True
    assert (control / fname).is_file(), f"{set_fn} must write into control_dir(), got nothing at {control / fname}"
    clear()
    assert present() is False


@pytest.mark.parametrize("fname,present_fn,_set_fn,_clear_fn", _FLAGS)
def test_flag_at_old_global_state_dir_is_still_seen(
    dirs: tuple[Path, Path], fname: str, present_fn: str, _set_fn: str, _clear_fn: str
) -> None:
    """A flag written by a NOT-YET-UPDATED session — one still running the previous
    release's code, which wrote to `global_state_dir()` rather than `control_dir()` —
    must still be honored. Without this dual-read, upgrading the janitor on one host
    while an older cached session runs elsewhere would silently blind that older
    session to a fleet-wide stop it should obey."""
    _control, gsd = dirs
    gs = _gs()
    present = getattr(gs, present_fn)

    assert present() is False
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / fname).write_text("legacy body", encoding="utf-8")
    assert present() is True, f"{present_fn} must dual-read the pre-control-dir global_state_dir() location"


@pytest.mark.parametrize("fname,present_fn,set_fn,clear_fn", _FLAGS)
def test_clear_removes_from_both_new_and_old_paths(
    dirs: tuple[Path, Path], fname: str, present_fn: str, set_fn: str, clear_fn: str
) -> None:
    """clear() must sweep BOTH the new control_dir() location AND the old
    global_state_dir() location in one call. A clear that only wiped the new path
    would look like it failed — the stale old-path copy would keep reading as SET —
    which is exactly the kind of "disarm didn't work" bug this flag exists to prevent."""
    control, gsd = dirs
    gs = _gs()
    present = getattr(gs, present_fn)
    set_ = getattr(gs, set_fn)
    clear = getattr(gs, clear_fn)

    set_("reason")  # lands at control_dir()
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / fname).write_text("stale old-path copy", encoding="utf-8")  # simulate an old writer
    assert present() is True
    clear()
    assert not (control / fname).exists()
    assert not (gsd / fname).exists()
    assert present() is False


def test_control_dir_ignores_xdg_state_home_and_global_state_dir_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """control_dir() must NOT move when the OTHER ladder's escape hatches are set —
    it has no ladder of its own. If it silently inherited $XDG_STATE_HOME or
    $JANITOR_GLOBAL_STATE_DIR, a host that sets those for the global_state_dir()
    ladder would relocate the control plane too, defeating the whole point of a
    single fixed path an external reader can hardcode."""
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("JANITOR_CONTROL_DIR", raising=False)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gsd"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    if "global_state" in sys.modules:
        del sys.modules["global_state"]
    gs = _gs()
    assert gs.control_dir() == fake_home / ".claude" / "janitor-control"


@pytest.mark.parametrize("fname,present_fn,_set_fn,_clear_fn", _FLAGS)
def test_malformed_or_legacy_body_still_reads_as_set(
    dirs: tuple[Path, Path], fname: str, present_fn: str, _set_fn: str, _clear_fn: str
) -> None:
    """Readers key on PRESENCE only, never on the body parsing cleanly. A flag with a
    bare non-JSON legacy body (pre-provenance content, e.g. "stopped" or
    "maintenance") must still read as SET — the exact opposite (a parse error making
    a present flag look absent) would silently swallow a real kill-switch."""
    control, _gsd = dirs
    gs = _gs()
    present = getattr(gs, present_fn)

    control.mkdir(parents=True, exist_ok=True)
    (control / fname).write_text("not json at all", encoding="utf-8")
    assert present() is True

    prov = gs.read_flag_provenance(fname)
    assert prov["by"] == "unknown"
    assert prov["set_at"] == 0


@pytest.mark.parametrize("fname,_present_fn,set_fn,_clear_fn", _FLAGS)
def test_provenance_round_trips(
    dirs: tuple[Path, Path], fname: str, _present_fn: str, set_fn: str, _clear_fn: str
) -> None:
    """The provenance body (`by`/`set_at`/`pid`/`reason`) written by set_*() is
    recoverable via read_flag_provenance() — the diagnostic half of TRDD-QK7M2B0X's
    "provenance is MANDATORY" requirement: a flag found set on a real host must be
    traceable to who set it and when, not just that it is set."""
    control, _gsd = dirs
    gs = _gs()
    set_ = getattr(gs, set_fn)

    set_("a specific reason")
    prov = gs.read_flag_provenance(fname)
    assert prov["reason"] == "a specific reason"
    assert prov["set_at"] > 0
    assert prov["by"] != "unknown"
    assert isinstance(prov["pid"], int) and prov["pid"] > 0

    # And the on-disk body really is the JSON shape the docstring promises.
    raw = (control / fname).read_text(encoding="utf-8")
    data = json.loads(raw)
    assert set(("set_at", "by", "pid", "reason")).issubset(data.keys())


def test_the_control_dir_is_NEVER_the_real_one_during_tests() -> None:
    """The isolation guard for the whole suite, not just this file.

    `control_dir()` is a FIXED literal path by design — it does NOT move when a test sets
    `JANITOR_GLOBAL_STATE_DIR`, which is the isolation every other test reaches for. So an
    unisolated test writing a stop flag hits the REAL machine: a leaked `kill-switch.flag`
    disarms the fleet, a leaked `maintenance-mode.flag` idles every daemon chore silently.

    Three files were doing exactly that before the autouse `_isolate_control_dir` fixture
    landed, and the way it surfaced is the reason this test exists: NOT as "a leak", but as
    two ordinary-looking assertion failures in `test_daemon_fleet_stop`, because a leftover
    real kill-switch outranks a pause and changed what the next test saw. A failure mode
    that disguises itself as an unrelated test bug needs a test that names it.
    """
    import os
    from pathlib import Path

    import global_state as gs

    real_home = os.environ.get("HOME", "")
    resolved = str(gs.control_dir())
    assert resolved != str(Path(real_home) / ".claude" / "janitor-control"), (
        f"tests must never resolve the live control plane, got {resolved}"
    )
    assert os.environ.get("JANITOR_CONTROL_DIR"), "the autouse isolation fixture must always set the override"
