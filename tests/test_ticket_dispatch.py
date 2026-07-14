"""The ticket SCHEDULER (TRDD-CGYMUKO6) — dispatch marker, the needs-human nag, and the reminder.

The reminder is the half that is easy to get wrong, and it was: a PROJECT finding produces a PROPOSAL
and **no ticket at all**, so the scheduler's "no tickets → return" fast path silently swallowed every
reminder for exactly the findings the janitor is forbidden to fix by itself. The first test here is
that bug, written down so it cannot come back.

The detector is run as a SUBPROCESS on purpose: it takes a machine-wide flock and resolves its state
through `lru_cache`d paths, both of which are process-global. Testing it in-process would test a
carefully-mocked shape, not the thing that runs on the heartbeat.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = ROOT / "scripts" / "detectors" / "ticket-dispatch.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import state  # noqa: E402
import ticket_proposal  # noqa: E402
import tickets  # noqa: E402

NOW = 1_784_000_000


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated project + HOME + global-state dir, so no test touches the real queue or the real
    machine-wide flock."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _run(project: Path) -> str:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(project / "gs"),
    }
    proc = subprocess.run(
        [sys.executable, str(DETECTOR)], capture_output=True, text=True, env=env, cwd=project
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _propose(project: Path, title: str, *, severity: str = "high", key: str = "") -> str:
    out = ticket_proposal.propose(
        kind="security-workflow",
        title=title,
        detail="…",
        severity=severity,
        dedupe_key=key or title,
        origin="test",
        project_dir=str(project),
        now=NOW,
    )
    assert out is not None
    return out[0]


def test_the_reminder_fires_even_with_an_EMPTY_ticket_queue(project: Path) -> None:
    """THE regression. A PROJECT finding makes a proposal, not a ticket — so the queue is empty, and an
    early `if not tickets: return` would make the janitor go silent about precisely the findings it may
    not fix on its own. Nothing is fixed until someone runs the command, so the command must be said."""
    uid = _propose(project, "attacker-controlled expression in a run: block")
    assert tickets.load_all() == [], "a PROJECT finding must NOT create a ticket"

    out = _run(project)

    assert f"/janitor-support-open-ticket TRDD-{uid}" in out
    assert "await YOUR approval" in out


def test_the_reminder_is_rate_limited(project: Path) -> None:
    """A standing finding is worth an hourly line, not one every 5 minutes: a nag that recurs 288 times
    a day trains its reader to ignore it, which is how findings get lost."""
    _propose(project, "a workflow is vulnerable")

    assert "await YOUR approval" in _run(project)
    assert _run(project) == "", "a second fire inside the cooldown must be silent"


def test_the_reminder_is_capped_and_counts_the_rest(project: Path) -> None:
    """Bounded output: a repo with 30 findings must not put 30 lines into every session's context."""
    for i in range(5):
        _propose(project, f"finding number {i}", key=f"k{i}")

    out = _run(project)

    assert out.count("/janitor-support-open-ticket") == 3
    assert "…and 2 more" in out


def test_an_APPROVED_finding_stops_being_reminded_and_starts_being_DISPATCHED(project: Path) -> None:
    """The handover. Approval moves a finding from the reminder channel into the queue: the nag stops
    (the queue owns it now) and the bare marker appears (the only thing that authorizes an agent)."""
    uid = _propose(project, "a workflow is vulnerable")
    ok, _ = ticket_proposal.approve(uid, project_dir=str(project), now=NOW)
    assert ok

    out = _run(project)

    assert "[janitor-ticket]" in out, "an approved ticket must be dispatched"
    assert "janitor-security-agent" in out
    assert "await YOUR approval" not in out, "an approved finding must not still be nagged about"


def test_nothing_pending_nothing_printed(project: Path) -> None:
    """The zero-output contract: a quiet fire costs the reader nothing."""
    assert _run(project) == ""
