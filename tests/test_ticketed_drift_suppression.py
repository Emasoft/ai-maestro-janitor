"""janitor#326: a drift line whose finding already has an OPEN ticket must not repeat on every fire.

`raise_issue` is already silent once a ticket exists, but a detector's own headline line carries no
finding key, so the quiet filter could not tell a ticket covers it. A keyed line (a trailing
`⟦ticket-key:…⟧` marker line, built by `issue_catalog.key_marker`) is dropped while an OPEN ticket
holds that key; an unkeyed line is NEVER hidden (fail open).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import dispatch  # noqa: E402
import issue_catalog  # noqa: E402
import state  # noqa: E402
import tickets  # noqa: E402

NOW = 1_784_000_000
WHERE_A = "/proj/a"
WHERE_B = "/proj/b"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", raising=False)
    monkeypatch.setattr(dispatch.findings_ledger, "record", lambda **kw: "x")
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _keyed(where: str) -> str:
    return (
        f"[memgrep-index-health] index at {where} is corrupt\n"
        f"  - detail line\n{issue_catalog.key_marker('MEMGREP-001', where)}\n"
    )


def _open(where: str) -> str:
    r = issue_catalog.raise_issue("MEMGREP-001", scope="local", where=where, now=NOW)
    assert r.ticket_id
    return r.ticket_id


def test_a_keyed_line_with_an_OPEN_ticket_is_suppressed(project: Path) -> None:
    """The reported nag: the finding is already being fixed, yet its line prints every fire."""
    _open(WHERE_A)
    assert dispatch._quiet_filter("memgrep-index-health", _keyed(WHERE_A)) == ""


def test_the_same_line_is_surfaced_once_the_ticket_closes(project: Path) -> None:
    """A closed ticket no longer covers the finding: it is back, so it must be shown again."""
    t = tickets.load(_open(WHERE_A))
    assert t is not None
    t.status = tickets.RESOLVED
    tickets.save(t)
    out = dispatch._quiet_filter("memgrep-index-health", _keyed(WHERE_A))
    assert "index at /proj/a is corrupt" in out and "detail line" in out
    assert "ticket-key" not in out, "the marker is plumbing, never shown"


def test_an_unkeyed_line_is_always_surfaced(project: Path) -> None:
    """Fail open: a finding with no key can never be hidden, even with tickets open."""
    _open(WHERE_A)
    line = "[memgrep-index-health] index at /proj/a is corrupt\n"
    assert dispatch._quiet_filter("memgrep-index-health", line) == line


def test_suppression_is_per_key(project: Path) -> None:
    """An open ticket for A must not hide B's line, even in the same output."""
    _open(WHERE_A)
    out = dispatch._quiet_filter("memgrep-index-health", _keyed(WHERE_A) + _keyed(WHERE_B))
    assert "/proj/b is corrupt" in out and "/proj/a is corrupt" not in out


def test_a_bare_janitor_marker_inside_a_suppressed_block_survives(project: Path) -> None:
    """Markers are ACTIONS; no suppression may swallow one."""
    _open(WHERE_A)
    text = "[memgrep-index-health] x\n[janitor-resume]\n" + issue_catalog.key_marker("MEMGREP-001", WHERE_A) + "\n"
    assert dispatch._quiet_filter("memgrep-index-health", text).strip() == "[janitor-resume]"
