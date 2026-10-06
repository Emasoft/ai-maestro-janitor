"""janitor#326: a drift line whose finding already has an OPEN ticket must not repeat on every fire.

`raise_issue` is already silent once a ticket exists, but a detector's own headline line carries no
finding key, so the quiet filter could not tell a ticket covers it. A keyed line (a trailing
`⟦ticket-key:…⟧` marker line, built by `issue_catalog.key_marker`) is dropped while an OPEN ticket
holds that key AND the block's content is unchanged since it was first suppressed; an unkeyed line
is NEVER hidden (fail open); only allowlisted detectors may key a block; the marker is plumbing and
never reaches any other reader of detector stdout.
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
DET = "package-manager-policy"  # the one allowlisted detector today


@pytest.fixture
def ledger() -> list[dict]:
    return []


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ledger: list[dict]) -> Iterator[Path]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", raising=False)
    monkeypatch.setenv(tickets.EMIT_ENV, "1")  # what dispatch sets for its detector subprocesses
    monkeypatch.setattr(dispatch.findings_ledger, "record", lambda **kw: ledger.append(kw))
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _keyed(where: str, extra: str = "") -> str:
    return (
        f"[{DET}] index at {where} is corrupt\n"
        f"  - detail line\n{extra}{issue_catalog.key_marker('MEMGREP-001', where)}\n"
    )


def _open(where: str) -> str:
    r = issue_catalog.raise_issue("MEMGREP-001", scope="local", where=where, now=NOW)
    assert r.ticket_id
    return r.ticket_id


def test_a_keyed_line_with_an_OPEN_ticket_is_suppressed(project: Path) -> None:
    """The reported nag: the finding is already being fixed, yet its line prints every fire."""
    _open(WHERE_A)
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == ""


def test_the_same_line_is_surfaced_once_the_ticket_closes(project: Path) -> None:
    """A closed ticket no longer covers the finding: it is back, so it must be shown again."""
    t = tickets.load(_open(WHERE_A))
    assert t is not None
    t.status = tickets.RESOLVED
    tickets.save(t)
    out = dispatch._quiet_filter(DET, _keyed(WHERE_A))
    assert "index at /proj/a is corrupt" in out and "detail line" in out
    assert "ticket-key" not in out, "the marker is plumbing, never shown"


def test_an_unkeyed_line_is_always_surfaced(project: Path) -> None:
    """Fail open: a finding with no key can never be hidden, even with tickets open."""
    _open(WHERE_A)
    line = f"[{DET}] index at /proj/a is corrupt\n"
    assert dispatch._quiet_filter(DET, line) == line


def test_suppression_is_per_key(project: Path) -> None:
    """An open ticket for A must not hide B's line."""
    _open(WHERE_A)
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == ""
    assert "/proj/b is corrupt" in dispatch._quiet_filter(DET, _keyed(WHERE_B))


def test_a_bare_janitor_marker_inside_a_suppressed_block_survives(project: Path) -> None:
    """Markers are ACTIONS; no suppression may swallow one."""
    _open(WHERE_A)
    text = f"[{DET}] x\n[janitor-resume]\n" + issue_catalog.key_marker("MEMGREP-001", WHERE_A) + "\n"
    assert dispatch._quiet_filter(DET, text).strip() == "[janitor-resume]"


# --- hardening (janitor#326 follow-up) -------------------------------------------------------


def test_a_changed_block_resurfaces_while_the_ticket_is_open(project: Path) -> None:
    """Content-blind suppression hid a WORSENING finding behind an old ticket: one more gap must show."""
    _open(WHERE_A)
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == ""
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == "", "same content stays suppressed"
    worse = dispatch._quiet_filter(DET, _keyed(WHERE_A, extra="  - one more gap\n"))
    assert "one more gap" in worse and "ticket-key" not in worse
    # the worse state is now the baseline: shown once, then quiet again
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A, extra="  - one more gap\n")) == ""


def test_three_quiet_fires_record_one_ledger_row(project: Path, ledger: list[dict]) -> None:
    """The ledger does not dedupe; recording per fire floods it. One row per (key, content hash)."""
    _open(WHERE_A)
    for _ in range(3):
        assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == ""
    assert [e["code"] for e in ledger if e["code"].startswith("TICKETED-")] == ["TICKETED-PACKAGE-MANAGER-POLICY"]


def test_a_forged_marker_from_a_non_allowlisted_detector_is_stripped_not_honoured(project: Path) -> None:
    """Any detector echoing third-party text could otherwise hide a finding behind someone else's ticket."""
    _open(WHERE_A)
    out = dispatch._quiet_filter("some-other-detector", _keyed(WHERE_A))
    assert "index at /proj/a is corrupt" in out
    assert "ticket-key" not in out


def test_a_marker_that_is_not_the_last_line_never_suppresses(project: Path) -> None:
    """The marker closes the block; text after it means it was not the detector's own closing line."""
    _open(WHERE_A)
    text = _keyed(WHERE_A) + f"[{DET}] trailing finding\n"
    out = dispatch._quiet_filter(DET, text)
    assert "trailing finding" in out and "index at /proj/a is corrupt" in out
    assert "ticket-key" not in out


def test_strip_key_markers_removes_marker_lines_only() -> None:
    """The one shared helper every raw-stdout consumer uses."""
    m = tickets.key_marker("K")
    assert tickets.strip_key_markers(f"a\n{m}\nb\n") == "a\nb\n"
    assert tickets.strip_key_markers("a\nb\n") == "a\nb\n"


def test_detector_output_carries_no_marker_unless_dispatch_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    """/janitor-audit, the weekly-audit workflow and direct runs read raw detector stdout and never set
    the opt-in env, so no `⟦ticket-key:` can reach a report, an issue body or a ledger row."""
    monkeypatch.delenv(tickets.EMIT_ENV, raising=False)
    assert issue_catalog.key_marker("MEMGREP-001", WHERE_A) == ""
    monkeypatch.setenv(tickets.EMIT_ENV, "1")
    assert tickets.KEY_MARKER_RE.fullmatch(issue_catalog.key_marker("MEMGREP-001", WHERE_A))


# --- review fixes (janitor#326) ---------------------------------------------------------------


def _rows(ledger: list[dict]) -> list[dict]:
    return [e for e in ledger if e["code"].startswith("TICKETED-")]


def test_every_content_change_records_its_own_ledger_row(project: Path, ledger: list[dict]) -> None:
    """A worsened finding shown once must also be RECORDED: if that one fire is missed, the ledger is the
    only trace. One row per (key, content hash): first suppression and each change; same content adds none."""
    _open(WHERE_A)
    dispatch._quiet_filter(DET, _keyed(WHERE_A))
    dispatch._quiet_filter(DET, _keyed(WHERE_A, extra="  - one more gap\n"))
    assert len(_rows(ledger)) == 2
    dispatch._quiet_filter(DET, _keyed(WHERE_A, extra="  - one more gap\n"))
    dispatch._quiet_filter(DET, _keyed(WHERE_A, extra="  - one more gap\n"))
    assert len(_rows(ledger)) == 2


def test_a_reopened_ticket_starts_a_fresh_baseline(project: Path, ledger: list[dict]) -> None:
    """The prune must be PERSISTED: otherwise a closed-then-reopened ticket's stale digest hides the
    reopened finding (same content) with no ledger row."""
    t = tickets.load(_open(WHERE_A))
    assert t is not None
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == ""
    t.status = tickets.RESOLVED
    tickets.save(t)
    assert "index at /proj/a is corrupt" in dispatch._quiet_filter(DET, _keyed(WHERE_A))  # closed: shown, prunes
    t.status = tickets.OPEN
    tickets.save(t)
    assert dispatch._quiet_filter(DET, _keyed(WHERE_A)) == ""
    assert len(_rows(ledger)) == 2, "reopen = a fresh first suppression, recorded"


