"""Cross-project issue filing (TRDD-WP7TCRME Rule 4).

This is the janitor writing to GitHub under the OWNER's shared identity, unattended. Every
test here pins a refusal rather than a capability — the capability is one `gh` call, and the
refusals are the whole reason it is safe to leave running.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import cross_project_issue as cpi  # noqa: E402


class _P:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_never_files_on_a_repo_the_user_does_not_own():
    """The identity is shared across every agent on this machine. A janitor opening issues on
    strangers' repos is a spam bot wearing the owner's face."""
    out, _ = cpi.file_finding(slug="someone-else/repo", code="C", key="k", title="t",
                              detail="d", detector="x", observed_in="p", login="emasoft")
    assert out == "not-owned"


def test_ownership_is_exact_not_a_prefix():
    """`emasoft-labs/x` is not `emasoft/x`. A prefix test would file on the wrong account."""
    assert cpi.is_owned_by("emasoft/x", "emasoft")
    assert cpi.is_owned_by("EMASOFT/x", "emasoft"), "owner comparison is case-insensitive"
    assert not cpi.is_owned_by("emasoft-labs/x", "emasoft")
    assert not cpi.is_owned_by("notemasoft/x", "emasoft")
    assert not cpi.is_owned_by("", "emasoft") and not cpi.is_owned_by("emasoft/x", "")


def test_a_failed_search_does_NOT_file(monkeypatch):
    """The dangerous default. A transient network error must not read as 'nothing was filed' —
    that is exactly the state in which filing again is wrong, and it would reopen the issue on
    every fire until a human noticed."""
    monkeypatch.setattr(cpi, "_already_filed", lambda *a, **k: None)
    called = []
    out, _ = cpi.file_finding(slug="emasoft/x", code="C", key="k", title="t", detail="d",
                              detector="x", observed_in="p", login="emasoft",
                              runner=lambda *a, **k: called.append(1) or _P())
    assert out == "unknown"
    assert not called, "must not call gh issue create when the search was inconclusive"


def test_an_existing_issue_is_not_reopened(monkeypatch):
    """A detector fires every cadence forever; one persistent condition must be one issue."""
    monkeypatch.setattr(cpi, "_already_filed", lambda *a, **k: True)
    called = []
    out, _ = cpi.file_finding(slug="emasoft/x", code="C", key="k", title="t", detail="d",
                              detector="x", observed_in="p", login="emasoft",
                              runner=lambda *a, **k: called.append(1) or _P())
    assert out == "duplicate" and not called


def test_the_body_carries_no_at_mention():
    """A bare `@name` outside a code span PAGES a real account, and a template is copied
    verbatim into places where that is not obvious (janitor#171)."""
    body = cpi.build_body(code="C", key="k", detail="something broke", detector="d",
                          observed_in="/some/project")
    assert "@" not in body, f"template must carry no @ at all: {body!r}"


def test_the_body_self_identifies_as_an_agent():
    """PRRD G1.1: every agent writes through the same human owner's auth, so a post that does
    not say which agent wrote it is indistinguishable from the human writing it by hand."""
    body = cpi.build_body(code="C", key="k", detail="d", detector="det", observed_in="/p")
    assert "ai-maestro-janitor" in body.splitlines()[0]


def test_the_marker_is_stable_and_distinguishes_distinct_findings():
    """Same finding twice → same marker (dedupe works). Different condition → different marker
    (two real problems get two issues)."""
    assert cpi.dedupe_marker("C", "a/b.yml") == cpi.dedupe_marker("C", "a/b.yml")
    assert cpi.dedupe_marker("C", "a/b.yml") != cpi.dedupe_marker("C", "a/c.yml")
    assert cpi.dedupe_marker("C", "k") != cpi.dedupe_marker("D", "k")


def test_the_marker_survives_a_human_editing_the_title():
    """Dedupe is keyed on a hidden body marker, not the title — a human retitling the issue
    must not silently un-dedupe the finding forever."""
    m = cpi.dedupe_marker("C", "k")
    assert m.startswith("<!--") and m.endswith("-->")
    assert m in cpi.build_body(code="C", key="k", detail="d", detector="x", observed_in="p")


def test_a_filed_issue_reports_its_url(monkeypatch):
    monkeypatch.setattr(cpi, "_already_filed", lambda *a, **k: False)
    out, detail = cpi.file_finding(
        slug="emasoft/x", code="C", key="k", title="t", detail="d", detector="x",
        observed_in="p", login="emasoft",
        runner=lambda *a, **k: _P(0, "https://github.com/emasoft/x/issues/7\n"),
    )
    assert out == "filed" and detail.endswith("/issues/7")
