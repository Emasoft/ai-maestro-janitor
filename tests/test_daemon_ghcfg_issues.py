"""Tests for the daemon's Rule-4 filer: _file_github_config_issues (scripts/daemon.py).

TRDD-WP7TCRME Rule 4 — a finding about ANOTHER repo goes on THAT repo's tracker, not into an
unrelated session's context. This is that rule's first real caller: the fleet GitHub-config
audit already knows every fleet repo's gaps, and most of those repos have no live session for
weeks, so today their gaps reach nobody who can act on them.

The safety properties (owner-only, never-twice, no `@`) live in cross_project_issue and are
tested there. What is tested HERE is what this caller decides: which findings are handed over,
how they are keyed, that the burst is bounded and the truncation is reported, and that a broken
tracker cannot take the audit beat down with it. `cpi.file_finding` is monkeypatched throughout —
these tests never touch the network and never open a real issue.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _PROJECT_ROOT / "scripts" / "daemon.py"

sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import github_config_audit as gca  # noqa: E402


def _import_daemon():
    import importlib.util as _u

    spec = _u.spec_from_file_location("janitor_daemon_under_test_ghcfg_issues", str(_DAEMON))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Audit:
    """Just the one attribute the filer reads off a FleetAudit."""

    def __init__(self, findings):
        self.findings = findings


def _audit(*pairs):
    return _Audit([gca.Finding(slug=s, code=c, detail=f"detail for {c}") for s, c in pairs])


def _capture(daemon, monkeypatch, *, outcome="filed"):
    """Monkeypatch the filer's only outward call and record every kwargs set it was given."""
    calls: list[dict] = []

    def fake(**kw):
        calls.append(kw)
        return (outcome, "https://example.invalid/1")

    monkeypatch.setattr(daemon.cpi, "file_finding", fake)
    monkeypatch.setattr(daemon.state, "log_line", lambda *a, **k: None)
    return calls


def test_files_one_issue_per_repo_with_every_gap_in_the_body(monkeypatch) -> None:
    """One issue per REPO, not per finding — three gaps on one repo is one problem to fix, and
    three issues would be three notifications for it."""
    daemon = _import_daemon()
    calls = _capture(daemon, monkeypatch)
    daemon._file_github_config_issues(
        _audit(("o/a", "MISSING_RULESET"), ("o/a", "LINEAR_HISTORY"), ("o/b", "NO_CI"))
    )
    assert [c["slug"] for c in calls] == ["o/a", "o/b"]
    body = calls[0]["detail"]
    assert "MISSING_RULESET" in body and "LINEAR_HISTORY" in body
    assert "NO_CI" not in body, "a repo's issue must not carry another repo's findings"


def test_key_is_the_gap_set_so_a_new_gap_is_not_swallowed(monkeypatch) -> None:
    """The dedupe key covers the CODES, not just the slug: an unchanged set dedupes forever
    (good — a detector fires every cadence), but a repo that develops a NEW gap must not stay
    silent behind the marker of the old one."""
    daemon = _import_daemon()
    calls = _capture(daemon, monkeypatch)
    daemon._file_github_config_issues(_audit(("o/a", "MISSING_RULESET")))
    daemon._file_github_config_issues(_audit(("o/a", "MISSING_RULESET"), ("o/a", "NO_CI")))
    assert calls[0]["key"] != calls[1]["key"]
    # ...and the same set in a different ORDER is the same finding, not a new one.
    before = calls[1]["key"]
    calls.clear()
    daemon._file_github_config_issues(_audit(("o/a", "NO_CI"), ("o/a", "MISSING_RULESET")))
    assert calls[0]["key"] == before, "key must not depend on finding order"


def test_burst_is_capped_and_the_truncation_is_logged(monkeypatch) -> None:
    """A first-ever audit can find gaps on every repo at once. Filing them all in one beat is
    how an automated reporter gets rate-limited; a SILENT cap is how it looks complete anyway."""
    daemon = _import_daemon()
    calls = _capture(daemon, monkeypatch)
    logged: list[str] = []
    monkeypatch.setattr(daemon.state, "log_line", lambda _n, m: logged.append(m))

    n = daemon._GHCFG_ISSUES_PER_BEAT + 3
    daemon._file_github_config_issues(_audit(*[(f"o/r{i:02d}", "NO_CI") for i in range(n)]))

    assert len(calls) == daemon._GHCFG_ISSUES_PER_BEAT
    assert any("deferred to the next beat" in m for m in logged)
    assert any("3 repo(s) deferred" in m for m in logged), "the deferred COUNT must be right"


def test_deferred_count_excludes_the_repos_already_handled(monkeypatch) -> None:
    """The count must be "repos not reached", not "repos filed".

    With every outcome `filed` the two are numerically identical, so a mixed run is the only
    thing that can tell them apart: three already-filed repos are iterated WITHOUT consuming the
    cap, so counting filings would claim three more repos were deferred than actually were.
    """
    daemon = _import_daemon()
    logged: list[str] = []
    monkeypatch.setattr(daemon.state, "log_line", lambda _n, m: logged.append(m))
    seen: list[str] = []

    def fake(**kw):
        seen.append(kw["slug"])
        # The first three are steady-state duplicates; everything after is a fresh filing.
        return ("duplicate" if len(seen) <= 3 else "filed", "")

    monkeypatch.setattr(daemon.cpi, "file_finding", fake)

    cap = daemon._GHCFG_ISSUES_PER_BEAT
    n = 3 + cap + 4  # 3 duplicates, `cap` filings, then 4 repos never reached
    daemon._file_github_config_issues(_audit(*[(f"o/r{i:02d}", "NO_CI") for i in range(n)]))

    assert len(seen) == 3 + cap
    assert any("4 repo(s) deferred" in m for m in logged), logged


def test_duplicates_do_not_consume_the_cap(monkeypatch) -> None:
    """A steady state where every repo is already filed must keep reaching every repo — if
    duplicates burned the cap, repos past the first N would never be re-examined at all."""
    daemon = _import_daemon()
    calls = _capture(daemon, monkeypatch, outcome="duplicate")
    n = daemon._GHCFG_ISSUES_PER_BEAT + 3
    daemon._file_github_config_issues(_audit(*[(f"o/r{i:02d}", "NO_CI") for i in range(n)]))
    assert len(calls) == n


def test_opt_out_files_nothing(monkeypatch) -> None:
    daemon = _import_daemon()
    calls = _capture(daemon, monkeypatch)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_CROSS_PROJECT_ISSUES_ENABLED", "0")
    daemon._file_github_config_issues(_audit(("o/a", "NO_CI")))
    assert calls == []


def test_a_broken_tracker_cannot_break_the_audit_beat(monkeypatch) -> None:
    """The findings are already written to disk by the time this runs. Losing the audit because
    a tracker was unreachable would trade the whole beat for the optional part of it."""
    daemon = _import_daemon()
    _capture(daemon, monkeypatch)

    def boom(**_kw):
        raise RuntimeError("gh exploded")

    monkeypatch.setattr(daemon.cpi, "file_finding", boom)
    daemon._file_github_config_issues(_audit(("o/a", "NO_CI")))  # must not raise
