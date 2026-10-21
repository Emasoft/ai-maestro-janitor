"""Tests for `dispatch._active_waiting_signal` (TRDD-DMH25CYD, issue 340).

The boolean `_cadence_active_waiting` told an operator nothing about WHICH of four unrelated
signals was holding the external-clear watcher. `_active_waiting_signal` returns the same
decision as (kind, expiry_text) so the VERDICT line can name it. Real I/O against a tmp state
dir, no mocks except the one OSError injection, which no real file layout can produce.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import time
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
    for mod in ("dispatch", "state", "global_state", "pending_agents"):
        sys.modules.pop(mod, None)
    return project


def _import_dispatch():
    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_waiting_signal_ut", str(_PROJECT_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sd(proj: Path) -> Path:
    return proj / ".janitor" / "state"


def _add_agent(agent_id: str, now: int) -> None:
    pa = importlib.import_module("pending_agents")
    pa.add(agent_id, "a real background task", now=now)


def _stamp(sd: Path, ts: int) -> None:
    (sd / "last-resume.ts").write_text(str(ts), encoding="utf-8")


def _directive(sd: Path, age_s: int) -> None:
    path = sd / "resume-directive.txt"
    path.write_text("continue TRDD-DMH25CYD", encoding="utf-8")
    mtime = time.time() - age_s
    os.utime(path, (mtime, mtime))


def test_recovery_flag_reports_no_timer(proj: Path) -> None:
    """A pending resume flag is reported as recovery-flag with the on-consume expiry."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    (sd / "rate-limited.flag").write_text("x", encoding="utf-8")
    assert dispatch._active_waiting_signal(sd, int(time.time())) == ("recovery-flag", "on-consume")


def test_abandoned_unarmed_clear_flag_is_not_a_recovery_signal(proj: Path) -> None:
    """A 10 h old resume-after-clear.flag whose /clear never ran (no clear-observed.ts) no longer
    holds the watcher: the age floor in external_clear.recovery_pending ignores it."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    flag = sd / "resume-after-clear.flag"
    flag.write_text("x", encoding="utf-8")
    old = time.time() - 36_000
    os.utime(flag, (old, old))
    assert dispatch._active_waiting_signal(sd, int(time.time())) is None


def test_resume_stamp_reports_seconds_left(proj: Path) -> None:
    """A fresh last-resume stamp is reported with the seconds until its 30-minute window ends."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    _stamp(sd, now - 100)
    assert dispatch._active_waiting_signal(sd, now) == ("resume-stamp", "1700s")


def test_resume_directive_reports_seconds_left(proj: Path) -> None:
    """A fresh directive file is reported with the seconds until its window ends (mtime pinned)."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    _directive(sd, 600)
    got = dispatch._active_waiting_signal(sd, int(time.time()))
    assert got is not None and got[0] == "resume-directive"
    assert re.fullmatch(r"1(199|200)s", got[1]), got


def test_agents_report_a_count_and_never_an_id(proj: Path) -> None:
    """Fresh external agents are reported as a count; the agent id never appears in the text."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    _add_agent("zz-agent-id-must-not-leak", now)
    assert dispatch._active_waiting_signal(sd, now) == ("agents", "1-running")


def test_the_1800s_boundary_returns_none_for_stamp_and_directive(proj: Path) -> None:
    """A stamp exactly 1800 s old and a directive past 1800 s no longer count as waiting."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    _stamp(sd, now - 1800)
    assert dispatch._active_waiting_signal(sd, now) is None
    _directive(sd, 1805)
    assert dispatch._active_waiting_signal(sd, now) is None
    _stamp(sd, now - 1799)
    assert dispatch._active_waiting_signal(sd, now) == ("resume-stamp", "1s")


def test_daemon_coverage_suppresses_only_the_stamp(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh daemon-wake-covered stamp hides the resume stamp but not the directive or agents."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "1")
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    _stamp(sd, now - 10)
    (sd / "daemon-wake-covered.ts").write_text(str(now), encoding="utf-8")
    assert dispatch._active_waiting_signal(sd, now) is None, "covered stamp must be suppressed"

    _directive(sd, 60)
    got = dispatch._active_waiting_signal(sd, now)
    assert got is not None and got[0] == "resume-directive"

    (sd / "resume-directive.txt").unlink()
    _add_agent("covered-agent", now)
    assert dispatch._active_waiting_signal(sd, now) == ("agents", "1-running")


def test_signals_are_reported_in_priority_order(proj: Path) -> None:
    """Recovery flag beats stamp beats directive beats agents when several hold at once."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    _add_agent("order-agent", now)
    assert dispatch._active_waiting_signal(sd, now)[0] == "agents"  # type: ignore[index]
    _directive(sd, 60)
    assert dispatch._active_waiting_signal(sd, now)[0] == "resume-directive"  # type: ignore[index]
    _stamp(sd, now - 10)
    assert dispatch._active_waiting_signal(sd, now)[0] == "resume-stamp"  # type: ignore[index]
    (sd / "resume-after-clear.flag").write_text("x", encoding="utf-8")
    assert dispatch._active_waiting_signal(sd, now)[0] == "recovery-flag"  # type: ignore[index]


def _s_empty(sd: Path, now: int) -> None:
    pass


def _s_flag(sd: Path, now: int) -> None:
    (sd / "resume-after-compact.flag").write_text("x", encoding="utf-8")


def _s_stamp(sd: Path, now: int) -> None:
    _stamp(sd, now - 5)


def _s_old_stamp(sd: Path, now: int) -> None:
    _stamp(sd, now - 4000)


def _s_directive(sd: Path, now: int) -> None:
    _directive(sd, 30)


def _s_old_directive(sd: Path, now: int) -> None:
    _directive(sd, 4000)


def _s_agent(sd: Path, now: int) -> None:
    _add_agent("parity-agent", now)


@pytest.mark.parametrize(
    "setup",
    [_s_empty, _s_flag, _s_stamp, _s_old_stamp, _s_directive, _s_old_directive, _s_agent],
)
def test_wrapper_boolean_matches_the_signal(proj: Path, setup) -> None:
    """`_cadence_active_waiting` is exactly `_active_waiting_signal(...) is not None`."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    setup(sd, now)
    assert dispatch._cadence_active_waiting(sd, now) == (
        dispatch._active_waiting_signal(sd, now) is not None
    )


def _boom(*args, **kwargs):
    raise OSError("injected")


def test_an_oserror_in_the_file_checks_skips_to_the_agent_check(
    proj: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError reading the stamp skips the file signals and still reports agents, in both."""
    dispatch = _import_dispatch()
    sd = _sd(proj)
    now = int(time.time())
    _add_agent("oserror-agent", now)
    _stamp(sd, now - 10)
    assert dispatch._active_waiting_signal(sd, now)[0] == "resume-stamp"  # type: ignore[index]  # control

    monkeypatch.setattr(dispatch.state, "read_int_state", _boom)
    assert dispatch._active_waiting_signal(sd, now) == ("agents", "1-running")
    assert dispatch._cadence_active_waiting(sd, now) is True


