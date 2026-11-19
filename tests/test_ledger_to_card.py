"""ledger-to-card (TRDD-IP23RNLY R2, PRRD G34.1): a finding that recurs in the findings ledger becomes ONE card.

Real ledger, ticket and proposal files in a tmp project; the detector runs as a SUBPROCESS (it resolves
state through `lru_cache`d paths, same reason as test_ticket_dispatch). The one in-process test patches
only the code-owned group->code table to force a genuine `raise_issue` failure (an unknown code).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = ROOT / "scripts" / "detectors" / "ledger-to-card.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import findings_ledger  # noqa: E402
import issue_catalog  # noqa: E402
import issue_codes_gen  # noqa: E402
import state  # noqa: E402
import ticket_proposal  # noqa: E402
import tickets  # noqa: E402

_spec = importlib.util.spec_from_file_location("ledger_to_card_under_test", DETECTOR)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
# dataclass resolves its own module through sys.modules, so register before executing.
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated project + HOME + global-state dir: no test touches the real ledger, queue or flock."""
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
    proc = subprocess.run([sys.executable, str(DETECTOR), "--one-shot"], capture_output=True, text=True, env=env, cwd=project)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _seed(code: str, src: str, n: int = 3, *, sev: str = "LOW", end: int | None = None, span: int = 7200, ref: str = "-") -> None:
    """`n` ledger rows for (code, src) spread over `span` seconds ending at `end` (default: just before now)."""
    end = int(time.time()) - 10 if end is None else end
    for i in range(n):
        findings_ledger.record(sev=sev, code=code, src=src, msg=f"{code} occurrence {i}", ref=ref, now=end - span + i * (span // max(1, n - 1)))


def _proposals(project: Path) -> list[Path]:
    return sorted((project / "design" / "proposals").glob("TRDD-*.md"))


# --- the three groups ---------------------------------------------------------------------------------


def test_a_repeating_project_finding_opens_exactly_one_proposal(project: Path) -> None:
    """3 entries of one (code, src) -> ONE proposal TRDD with the approve command; a second fire adds none."""
    _seed("ADVISORY-STALE-STASH", "stale-stash")
    out = _run(project)
    assert "/janitor-support-open-ticket TRDD-" in out
    assert len(_proposals(project)) == 1
    assert tickets.load_all() == [], "a PROJECT finding must not open a ticket"
    assert _run(project) == "", "an open proposal is left to the hourly ticket-dispatch reminder"
    assert len(_proposals(project)) == 1


def test_a_repeating_janitor_finding_opens_one_ticket_and_the_next_fire_bumps_seen(project: Path) -> None:
    """HARNESS group: one dispatchable ticket; a second fire dedupes into it (seen_count 2), no duplicate."""
    _seed("HOOK-TIMEOUT-SCAN", "hook-timeout-scan", sev="MEDIUM")
    out = _run(project)
    live = tickets.load_all()
    assert len(live) == 1 and live[0].kind == "ledger-finding-harness" and live[0].status == tickets.OPEN
    assert live[0].dedupe_key == "LEDGER:HOOK-TIMEOUT-SCAN:hook-timeout-scan"
    assert live[0].evidence == ["HOOK-TIMEOUT-SCAN", "hook-timeout-scan"]
    assert "[ticket] LEDGER-001" in out
    _run(project)
    live = tickets.load_all()
    assert len(live) == 1 and live[0].seen_count == 2


def test_the_human_group_lands_in_needs_human_and_is_never_dispatched(project: Path) -> None:
    """LEDGER-003: the ticket is moved to needs_human, so the scheduler can never select it."""
    _seed("ITERM-AUTOMATION-TCC", "iterm-automation-alarm", sev="HIGH")
    out = _run(project)
    (t,) = tickets.load_all()
    assert t.kind == "ledger-finding-human" and t.status == tickets.NEEDS_HUMAN
    assert "only the owner can fix it" in out and "will repair this itself" not in out
    assert tickets.select_due([t], now=int(time.time()), per_fire=5, budget_left=5, inflight=0) == []


def test_an_unknown_src_is_a_project_finding(project: Path) -> None:
    """An unmapped detector name needs approval, the restrictive side."""
    _seed("SOMETHING-NEW", "brand-new-detector")
    _run(project)
    assert len(_proposals(project)) == 1 and tickets.load_all() == []


# --- what counts as repeating -------------------------------------------------------------------------


def test_two_close_entries_do_not_repeat_but_two_an_hour_apart_do(project: Path) -> None:
    _seed("ADVISORY-DIRTY-TREE", "dirty-tree", n=2, span=60)
    assert _run(project) == "" and _proposals(project) == []
    _seed("ADVISORY-REPO-STATE", "repo-state", n=2, span=3600)
    assert "TRDD-" in _run(project) and len(_proposals(project)) == 1


def test_info_ticketed_never_surface_and_own_codes_are_skipped(project: Path) -> None:
    _seed("SOME-INFO", "stale-stash", sev="INFO")
    _seed("TICKETED-STALE-STASH", "stale-stash")
    _seed("WINDOW-BURN", "window-burn-rate")
    for code in ("LEDGER-001", "LEDGER-002", "LEDGER-003", "LEDGER-004"):
        _seed(code, "reports-purge")
    assert _run(project) == ""
    assert _proposals(project) == [] and tickets.load_all() == []


def test_entries_written_by_raise_issue_are_skipped(project: Path) -> None:
    """A catalogued code whose ref names an existing ticket is already carded: its rows are not a recurrence."""
    r = issue_catalog.raise_issue("MEMCORP-001", scope="local", detail="x", evidence=["m.md"])
    assert r.ticket_id
    _seed("MEMCORP-001", "memory-librarian", n=4, ref=r.ticket_id)
    before = {t.id: t.seen_count for t in tickets.load_all()}
    assert _run(project) == ""
    assert {t.id: t.seen_count for t in tickets.load_all()} == before


# --- refusal and closing --------------------------------------------------------------------------------


def test_a_refused_proposal_stays_refused_across_runs_with_new_messages(project: Path) -> None:
    """A human refusal is a settled verdict: new ledger messages must not re-file the card."""
    _seed("ADVISORY-STALE-STASH", "stale-stash")
    _run(project)
    (card,) = _proposals(project)
    card.write_text(card.read_text(encoding="utf-8").replace("column: proposal", "column: refused", 1), encoding="utf-8")
    _seed("ADVISORY-STALE-STASH", "stale-stash", n=5, end=int(time.time()) + 100)
    assert _run(project) == ""
    assert len(_proposals(project)) == 1


def test_a_closed_ticket_does_not_reopen_from_old_entries_but_reopens_from_newer_ones(project: Path) -> None:
    _seed("HOOK-TIMEOUT-SCAN", "hook-timeout-scan", sev="MEDIUM")
    _run(project)
    (t,) = tickets.load_all()
    t.status = tickets.RESOLVED
    t.updated_at = int(time.time())
    tickets.save(t)
    assert tickets.load_all() == [] and len(tickets.load_archived()) == 1
    assert _run(project) == "", "the old entries pre-date the closing time"
    assert tickets.load_all() == []
    _seed("HOOK-TIMEOUT-SCAN", "hook-timeout-scan", sev="MEDIUM", end=int(time.time()) + 7300)
    _run(project)
    (fresh,) = tickets.load_all()
    assert fresh.id != t.id and fresh.status == tickets.OPEN


def test_a_janitor_withdrawn_proposal_has_a_nonzero_floor_that_blocks_old_entries(project: Path) -> None:
    """The closing floor of a withdrawn card is its frontmatter `updated:`; an unparseable one becomes 0 and would
    silently remove the floor, so assert the format `propose()` writes parses to a real time."""
    _seed("ADVISORY-STALE-STASH", "stale-stash")
    _run(project)
    key = "LEDGER:ADVISORY-STALE-STASH:stale-stash"
    assert ticket_proposal.retract(key) is not None
    (card,) = ticket_proposal.cards_for_key(key)
    assert card.column == "refused" and card.withdrawn and card.updated > 0
    assert _run(project) == "", "the old entries pre-date the withdrawal"
    _seed("ADVISORY-STALE-STASH", "stale-stash", end=int(time.time()) + 7300)
    assert "TRDD-" in _run(project)
    assert len(_proposals(project)) == 2


# --- caps -------------------------------------------------------------------------------------------------


def test_the_per_fire_cap_holds_and_the_drop_is_reported(project: Path) -> None:
    srcs = ["memory-librarian", "reports-purge", "subagent-report", "wikimem-syntax", "daemon", "hook-timeout-scan", "jev-compaction"]
    for s in srcs:
        _seed("CODE-" + s.upper(), s)
    out = _run(project)
    assert len(tickets.load_all()) == issue_catalog.MAX_RAISES_PER_FIRE == 5
    assert "2 recurring finding(s) not carded" in out


def test_the_per_day_proposal_cap_holds_across_fires_and_the_drop_is_reported(project: Path) -> None:
    for s in ("dirty-tree", "repo-state", "stale-stash", "trdd-drift", "trdd-reminder"):
        _seed("CODE-" + s.upper(), s)
    assert "2 recurring finding(s) not carded" in _run(project)
    assert len(_proposals(project)) == mod.MAX_PROPOSALS_PER_DAY == 3
    out = _run(project)
    assert len(_proposals(project)) == 3 and "2 recurring finding(s) not carded" in out


# --- read-only on the ledger ---------------------------------------------------------------------------


def test_the_owner_cursor_is_untouched(project: Path) -> None:
    _seed("ADVISORY-STALE-STASH", "stale-stash")
    findings_ledger.advance_cursor()
    cursor = findings_ledger._cursor_path()
    before = cursor.read_bytes()
    _run(project)
    assert cursor.read_bytes() == before


# --- the catalog the detector depends on ---------------------------------------------------------------


def test_every_group_code_is_in_the_catalog_with_the_right_domain() -> None:
    """Fails if a group maps to a code missing from ISSUE_CATALOG (raise_issue would reject it at run time)."""
    expected = {mod.JANITOR: (tickets.HARNESS, True), mod.PROJECT: (tickets.PROJECT, True), mod.HUMAN: (tickets.HARNESS, False)}
    for group, code in mod._CODE_BY_GROUP.items():
        assert code in issue_catalog.ISSUE_CATALOG, f"{group} -> {code} is not in ISSUE_CATALOG"
        domain, dispatches = expected[group]
        spec = tickets.KIND_REGISTRY[issue_catalog.ISSUE_CATALOG[code].kind]
        assert (spec.domain, spec.dispatch) == (domain, dispatches)
    assert set(mod._GROUP_BY_SRC.values()) == set(mod._CODE_BY_GROUP)
    assert mod.ERROR_CODE in {c.code for c in issue_codes_gen.ISSUE_CODES}


def test_a_raise_issue_failure_is_printed_and_recorded_at_high(project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """ok=False is never one swallowed line: it is also a HIGH LEDGER-004 ledger row."""
    _seed("HOOK-TIMEOUT-SCAN", "hook-timeout-scan", sev="MEDIUM")
    monkeypatch.setitem(mod._CODE_BY_GROUP, mod.JANITOR, "NOPE-999")
    assert mod.main() == 0
    assert "could not be filed" in capsys.readouterr().out
    errs = [e for e in findings_ledger.entries() if e["code"] == "LEDGER-004"]
    assert len(errs) == 1 and errs[0]["sev"] == "HIGH" and errs[0]["src"] == "ledger-to-card"
    assert tickets.load_all() == []
