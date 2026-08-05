"""An empty fleet scan is ambiguous — never render it as "0 running instances".

The dashboard used to print `0 instances, 0 broken janitors.` whenever the scan came back
empty, with no error and no distinction between the two very different causes:

  * genuinely no janitor-managed sessions on this host, and
  * the measurement failed — `ps` unusable, or the per-pid cwd probe (`lsof`) missing,
    denied, or sandboxed.

The second reads as an all-clear for a question that was never asked. This is not
hypothetical: an earlier "0 instances" from this dashboard was quoted (by me, to the owner)
as evidence the fleet was idle at a moment when twelve sessions were running — the same
"silence read as a verdict" family as janitor#191/#193.

THE SELF-CHECK these tests pin: this scan runs INSIDE a claude session, so a correct scan
must find at least the session that ran it. Zero claude processes is therefore proof the
probe is broken, not proof the fleet is empty.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import fleet_scan  # type: ignore[import-not-found]  # noqa: E402
import fleet_status as fstat  # type: ignore[import-not-found]  # noqa: E402

_PROCS = [(101, "ttys001", "claude"), (102, "ttys002", "claude")]


def test_no_claude_processes_at_all_is_reported_as_a_broken_probe(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """We are running inside claude, so finding none can only mean `ps` failed."""
    monkeypatch.setattr(fleet_scan, "_run", lambda *a, **k: "")
    monkeypatch.setattr(fleet_scan, "parse_ps_claude", lambda _t: [])

    reason = fstat._empty_fleet_reason()
    assert "SCAN FAILED" in reason
    assert "no claude processes" in reason
    assert "0" not in reason.split("—")[0], "must not lead with a count"


def test_unresolvable_cwd_for_every_process_is_reported_as_unknown_not_empty(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact shape of the real incident: processes found, `lsof` blocked, fleet unknown."""
    monkeypatch.setattr(fleet_scan, "_run", lambda *a, **k: "irrelevant")
    monkeypatch.setattr(fleet_scan, "parse_ps_claude", lambda _t: _PROCS)
    monkeypatch.setattr(fleet_scan, "_cwd_of", lambda _pid: "")

    reason = fstat._empty_fleet_reason()
    assert "SCAN FAILED" in reason
    assert "unknown, not empty" in reason
    assert "2 claude process(es)" in reason


def test_resolvable_processes_with_no_janitor_project_is_a_genuine_empty_fleet(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one case where an empty fleet is a real answer — and it must NOT say SCAN FAILED."""
    monkeypatch.setattr(fleet_scan, "_run", lambda *a, **k: "irrelevant")
    monkeypatch.setattr(fleet_scan, "parse_ps_claude", lambda _t: _PROCS)
    monkeypatch.setattr(fleet_scan, "_cwd_of", lambda _pid: "/somewhere/without/janitor")

    reason = fstat._empty_fleet_reason()
    assert "SCAN FAILED" not in reason
    assert "no janitor-managed sessions" in reason


def test_a_partially_resolvable_scan_is_not_called_a_failure(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a TOTAL cwd-resolution failure indicts the probe. One resolvable pid means the
    probe works and the empty result is about the fleet, not the measurement."""
    monkeypatch.setattr(fleet_scan, "_run", lambda *a, **k: "irrelevant")
    monkeypatch.setattr(fleet_scan, "parse_ps_claude", lambda _t: _PROCS)
    monkeypatch.setattr(fleet_scan, "_cwd_of", lambda pid: "" if pid == 101 else "/tmp/proj")

    assert "SCAN FAILED" not in fstat._empty_fleet_reason()
