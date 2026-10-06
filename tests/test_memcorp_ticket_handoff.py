"""janitor#324: MEMCORP (memory-corpus) tickets must not be dispatched to an agent that refuses them,
and an open one whose finding no longer reproduces must be closed instead of sent out.

Real code, real files: the scheduler runs as a subprocess (flock + lru_cache'd state paths are
process-global), the detector helper is exercised on real ticket files in a temp project.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import issue_catalog  # noqa: E402
import state  # noqa: E402
import tickets  # noqa: E402
import wikimem_syntax_lint as lint  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "wikimem_syntax_detector_handoff", ROOT / "scripts" / "detectors" / "wikimem-syntax.py"
)
assert _spec is not None and _spec.loader is not None
wsyntax = importlib.util.module_from_spec(_spec)
sys.modules["wikimem_syntax_detector_handoff"] = wsyntax
_spec.loader.exec_module(wsyntax)

NOW = 1_784_000_000


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
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


def _open_memcorp(page: Path, root: Path) -> tickets.Ticket:
    r = issue_catalog.raise_issue(
        "MEMCORP-001",
        where=f"LOCAL:{page.name}:3",
        dedupe_key=f"MEMCORP-001:LOCAL:{page.name}:page-no-lmd:field:lmd",
        scope="LOCAL",
        origin="wikimem-syntax",
        found=f"rule page-no-lmd at {page}:3",
        detail="page-no-lmd",
        now=NOW,
    )
    assert r.ticket_id
    t = tickets.load(r.ticket_id)
    assert t is not None
    return t


def test_a_memory_corpus_ticket_is_never_handed_to_the_ticket_marker(project: Path) -> None:
    """The ticket marker names an agent; no agent may be named for a kind none can work."""
    _open_memcorp(project / "a.md", project)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(project / "gs"),
    }
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "detectors" / "ticket-dispatch.py")],
        capture_output=True, text=True, env=env, cwd=project,
    )
    assert proc.returncode == 0, proc.stderr
    assert "[janitor-ticket]" not in proc.stdout
    assert "janitor-memory-subconscious-agent" not in proc.stdout


def test_select_due_skips_kinds_flagged_not_dispatchable(project: Path) -> None:
    t = _open_memcorp(project / "a.md", project)
    assert tickets.select_due([t], now=NOW + 10, per_fire=5, budget_left=5, inflight=0) == []


def test_an_open_ticket_whose_finding_is_gone_is_closed_invalid(project: Path) -> None:
    t = _open_memcorp(project / "a.md", project)
    closed = wsyntax._close_stale_tickets(live_keys=set(), now=NOW + 10)
    assert closed == 1
    reloaded = tickets.load(t.id)
    assert reloaded is not None and reloaded.status == tickets.INVALID
    assert "no longer" in reloaded.resolution


def test_an_open_ticket_whose_finding_still_reproduces_stays_open(project: Path) -> None:
    t = _open_memcorp(project / "a.md", project)
    closed = wsyntax._close_stale_tickets(live_keys={t.dedupe_key}, now=NOW + 10)
    assert closed == 0
    reloaded = tickets.load(t.id)
    assert reloaded is not None and reloaded.status == tickets.OPEN


def test_live_keys_cover_every_ticketable_finding_even_without_the_user_claim(tmp_path: Path) -> None:
    roots = [("LOCAL", tmp_path)]
    page = tmp_path / "p.md"
    findings = [
        lint.Finding("ERROR", str(page), 3, "m", "page-no-lmd", "field:lmd"),
        lint.Finding("WARN", str(page), 4, "m", "atom-oversized-critical", "atom:x"),
        lint.Finding("INFO", str(page), 5, "m", "whatever", "a"),
    ]
    keys = wsyntax._live_keys(findings, roots)
    assert keys == {
        "MEMCORP-001:LOCAL:p.md:page-no-lmd:field:lmd",
        "MEMCORP-002:LOCAL:p.md:atom-oversized-critical:atom:x",
    }
