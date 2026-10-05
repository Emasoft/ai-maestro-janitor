"""`daemon.task_integrity_repin` — when a fire counts as a DECLINE (SELFINT-004).

The chore files SELFINT-004 after three consecutive fires that could not advance the C3
anchor. Ticket T-JWYHOMMV was that ticket filed against a HEALTHY anchor: certify returns
None both when it refuses and when the pin is already current, and the chore counted both.

certify, the pin and the manifest check are the real ones, run against a sandboxed cache and
DATA dir. Only the two edges that leave the machine are replaced: the GitHub release lookup
and the ticket store.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))
daemon = importlib.import_module("daemon")


@pytest.fixture
def repin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sandbox every path the chore touches; return (vu, cache_parent, declines_path, raised)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "project"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    (tmp_path / "project").mkdir()
    (tmp_path / "control").mkdir()
    cache_parent = tmp_path / "cache"
    cache_parent.mkdir()
    # Resolved HERE, per test, never at module import: the chore imports both modules by
    # name at call time, and other test files evict them from sys.modules. A module object
    # captured at import would be a stale copy the chore never sees, and the patches below
    # would silently miss — the whole file failed that way inside the full suite.
    vu = importlib.import_module("version_update_lib")
    issue_catalog = importlib.import_module("issue_catalog")
    raised: list[tuple[str, dict]] = []
    monkeypatch.setattr(vu, "resolve_cache_parent", lambda _root: cache_parent)
    monkeypatch.setattr(vu, "resolve_latest_published", lambda _root, **_kw: "2.0.0")
    monkeypatch.setattr(
        issue_catalog, "raise_issue", lambda code, **kw: raised.append((code, kw))
    )
    return vu, cache_parent, tmp_path / "control" / "integrity-repin.declines", raised


def _make_clean_version(cache_parent: Path, version: str) -> None:
    """A cached version the stub could exec and whose (empty) manifest verifies clean."""
    vdir = cache_parent / version
    (vdir / "scripts").mkdir(parents=True)
    (vdir / "scripts" / "dispatch.py").write_text("", encoding="utf-8")
    (vdir / ".integrity").mkdir()
    (vdir / ".integrity" / "manifest-sha256.json").write_text(
        json.dumps({"version": 1, "files": {}}), encoding="utf-8"
    )


def test_an_already_current_pin_is_not_counted_as_a_decline(repin) -> None:
    """A pin that already names the running version never files SELFINT-004, however many fires pass."""
    vu, cache_parent, declines_path, raised = repin
    _make_clean_version(cache_parent, "2.0.0")

    daemon.task_integrity_repin()  # certifies 2.0.0
    pin = vu.read_last_good()
    assert pin is not None and pin["version"] == "2.0.0"

    for _ in range(daemon._REPIN_DECLINE_TICKET_AFTER + 1):
        daemon.task_integrity_repin()  # steady state: the pin is current

    assert not declines_path.exists(), declines_path.read_text(encoding="utf-8")
    assert raised == []


def test_a_current_pin_ends_a_decline_streak(repin) -> None:
    """A fire that finds the pin current clears the count left by earlier declines."""
    vu, cache_parent, declines_path, raised = repin
    _make_clean_version(cache_parent, "2.0.0")
    daemon.task_integrity_repin()
    declines_path.write_text("2", encoding="utf-8")

    daemon.task_integrity_repin()

    assert not declines_path.exists()
    assert raised == []


def test_a_real_refusal_still_files_the_ticket_exactly_once(repin) -> None:
    """A version the release channel does not name is refused each fire and ticketed on the third only."""
    vu, cache_parent, declines_path, raised = repin
    _make_clean_version(cache_parent, "2.0.1")  # newer than the published 2.0.0

    for _ in range(daemon._REPIN_DECLINE_TICKET_AFTER + 1):
        daemon.task_integrity_repin()

    assert declines_path.read_text(encoding="utf-8") == "4"
    assert [code for code, _kw in raised] == ["SELFINT-004"]
    assert raised[0][1]["declines"] == daemon._REPIN_DECLINE_TICKET_AFTER


def test_an_empty_cache_is_a_decline_not_a_current_pin(repin) -> None:
    """No cached version at all is the frozen-anchor shape, so it is counted even though certify says nothing."""
    _vu, _cache_parent, declines_path, raised = repin

    daemon.task_integrity_repin()

    assert declines_path.read_text(encoding="utf-8") == "1"
    assert raised == []
