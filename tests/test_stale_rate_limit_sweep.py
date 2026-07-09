"""Daemon-side sweep of stale `rate-limited.flag`s (janitor#77 item C, TRDD-EFTQB9RR).

Only `dispatch.py` clears the flag, and dispatch runs only from a live heartbeat cron. So
the project that most needs its flag cleared — the one whose cron died — is exactly the one
that can never clear it. The circle is closed by construction, and on this machine 17 of 35
projects held a flag, the oldest 50 days old.

A stale flag is not harmless: `diagnose_instance` reads it before it reaches `cron_dead`, so
a merely-quiet session is classified `frozen`, and `frozen` walks the recovery ladder toward
rung 6 `force_restart` — a kill — instead of the gentle `rearm` that `cron_dead` earns. The
hard rungs are default-off today, so this is latent rather than live; anyone who enables them
inherits a fleet where 17 quiet projects sit one ladder-walk from being killed on the strength
of a 50-day-old file.

The daemon is alive when the cron is not. That is the whole reason the sweep lives there.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import fleet_scan as fs  # type: ignore[import-not-found]  # noqa: E402
import session_liveness as sl  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402

DAY = 86400


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with a `.janitor/state/` dir. Returns the root."""
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    return tmp_path


def _state_dir(root: Path) -> Path:
    return root / ".janitor" / "state"


def _write_flag(root: Path, name: str, age_s: int = 0) -> Path:
    p = _state_dir(root) / name
    p.write_text("", encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(p, (old, old))
    return p


# --------------------------------------------------------------------------- #
# The pure predicate
# --------------------------------------------------------------------------- #


def test_fresh_flag_is_never_stale() -> None:
    """A session rate-limited RIGHT NOW keeps its flag fresh — the StopFailure hook
    touch()es it on every turn-ending API error — so it must never be swept."""
    now = int(time.time())
    assert not sl.rate_limit_flag_is_stale(now - 60, now, DAY)


def test_old_flag_is_stale() -> None:
    """No API error in a full day means the session is not rate-limited by any definition."""
    now = int(time.time())
    assert sl.rate_limit_flag_is_stale(now - 2 * DAY, now, DAY)


def test_flag_exactly_at_the_window_is_stale() -> None:
    """The boundary is inclusive, so a flag cannot sit forever one second short of the cut."""
    now = int(time.time())
    assert sl.rate_limit_flag_is_stale(now - DAY, now, DAY)


def test_missing_mtime_is_never_stale() -> None:
    """We never delete what we cannot assess (mirrors diagnose_instance's unknown-age rule)."""
    assert not sl.rate_limit_flag_is_stale(None, int(time.time()), DAY)


@pytest.mark.parametrize("window", [0, -1, -DAY])
def test_nonpositive_window_disables_the_sweep(window: int) -> None:
    """`max_age_s <= 0` is the documented off switch — an ancient flag stays put."""
    now = int(time.time())
    assert not sl.rate_limit_flag_is_stale(now - 999 * DAY, now, window)


# --------------------------------------------------------------------------- #
# The I/O half
# --------------------------------------------------------------------------- #


def test_sweep_removes_a_stale_flag(project: Path) -> None:
    flag = _write_flag(project, state.RATE_LIMITED_FLAG, age_s=50 * DAY)
    assert fs.sweep_stale_rate_limit(str(project), now=int(time.time()), max_age_s=DAY)
    assert not flag.exists()


def test_sweep_keeps_a_fresh_flag(project: Path) -> None:
    """A live rate limit must survive the sweep, or the daemon would erase the very signal
    that tells it a session is frozen."""
    flag = _write_flag(project, state.RATE_LIMITED_FLAG)
    assert not fs.sweep_stale_rate_limit(str(project), now=int(time.time()), max_age_s=DAY)
    assert flag.exists()


def test_sweep_skips_a_disarmed_project(project: Path) -> None:
    """A `disarmed.flag` project is sacrosanct — the user opted out, so we touch nothing.

    Its diagnosis is `unarmed` regardless of the rate-limit flag, so there is no reason to
    write into a tree the user asked the janitor to leave alone.
    """
    _write_flag(project, state.DISARMED_FLAG)
    flag = _write_flag(project, state.RATE_LIMITED_FLAG, age_s=50 * DAY)
    assert not fs.sweep_stale_rate_limit(str(project), now=int(time.time()), max_age_s=DAY)
    assert flag.exists()


def test_sweep_on_absent_flag_is_a_noop(project: Path) -> None:
    assert not fs.sweep_stale_rate_limit(str(project), now=int(time.time()), max_age_s=DAY)


def test_sweep_on_missing_project_never_raises(tmp_path: Path) -> None:
    """No `.janitor/` at all — the sweep must be silent, not explode inside the beat."""
    assert not fs.sweep_stale_rate_limit(str(tmp_path / "nope"), now=0, max_age_s=DAY)


def test_sweep_is_idempotent(project: Path) -> None:
    """Bounded per the S3/S4 invariant: a self-heal that can run every tick must converge."""
    _write_flag(project, state.RATE_LIMITED_FLAG, age_s=50 * DAY)
    now = int(time.time())
    assert fs.sweep_stale_rate_limit(str(project), now=now, max_age_s=DAY)
    assert not fs.sweep_stale_rate_limit(str(project), now=now, max_age_s=DAY)


# --------------------------------------------------------------------------- #
# The diagnosis it exists to correct
# --------------------------------------------------------------------------- #


def test_stale_flag_makes_a_quiet_session_look_frozen() -> None:
    """The bug, stated as a test: identical inputs, and the flag alone decides between the
    gentle `rearm` rung and the ladder that ends in a kill."""
    common = dict(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=True, version_stale=False
    )
    assert sl.diagnose_instance(rate_limited=True, **common) == "frozen"
    assert sl.diagnose_instance(rate_limited=False, **common) == "cron_dead"
    assert sl.recovery_for_diagnosis("cron_dead") == "rearm"


def test_diagnose_root_sees_the_sweep_within_the_same_beat(project: Path) -> None:
    """The sweep runs BEFORE diagnose_root, so one beat both clears the litter and acts on
    the corrected diagnosis — rather than sweeping now and helping five minutes later."""
    _write_flag(project, state.RATE_LIMITED_FLAG, age_s=50 * DAY)
    now = int(time.time())
    root = str(project)

    before, _, _ = fs.diagnose_root(root, now=now, transcript_age=fs.STALE_S + 1)
    assert before == "frozen"

    assert fs.sweep_stale_rate_limit(root, now=now, max_age_s=DAY)

    after, recovery, _ = fs.diagnose_root(root, now=now, transcript_age=fs.STALE_S + 1)
    assert after == "cron_dead"
    assert recovery == "rearm"


# --------------------------------------------------------------------------- #
# gather_fleet stays read-only unless asked
# --------------------------------------------------------------------------- #


def test_gather_fleet_sweep_defaults_to_off() -> None:
    """`fleet_status` calls gather_fleet to RENDER a table. A status view that mutates the
    thing it reports on is a status view nobody can trust, so the sweep must be opt-in.
    """
    import inspect

    sig = inspect.signature(fs.gather_fleet)
    assert sig.parameters["sweep_stale_rate_limit_s"].default is None


def test_fleet_status_does_not_request_the_sweep() -> None:
    """Guard the caller, not just the default: fleet_status must never pass the kwarg."""
    src = (REPO / "scripts" / "fleet_status.py").read_text(encoding="utf-8")
    assert "sweep_stale_rate_limit" not in src


def test_daemon_requests_the_sweep() -> None:
    """...and the daemon must, or item C ships as dead code."""
    src = (REPO / "scripts" / "daemon.py").read_text(encoding="utf-8")
    assert "sweep_stale_rate_limit_s=" in src
    assert "CLAUDE_PLUGIN_OPTION_RATE_LIMIT_FLAG_MAX_AGE_HOURS" in src
