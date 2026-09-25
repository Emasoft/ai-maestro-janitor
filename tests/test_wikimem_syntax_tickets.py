"""TRDD-FVYV6RSG: memgrep lint findings become bounded tickets.

The wikimem-syntax detector's ticket path must (a) file a MEMCORP-001 ticket per
new finding with page path + rule code + line only, never page text; (b) name the
chore that owns the remedy; (c) skip pages under the owner-held AgentlensPro/ghbook
corpora; (d) rely on raise_issue's own dedupe so an unchanged corpus re-files nothing.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _ROOT / "scripts" / "detectors" / "wikimem-syntax.py"

sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import wikimem_syntax_lint as lint  # noqa: E402

_spec = importlib.util.spec_from_file_location("wikimem_syntax_detector_tickets", _DETECTOR)
assert _spec is not None and _spec.loader is not None
wsyntax = importlib.util.module_from_spec(_spec)
sys.modules["wikimem_syntax_detector_tickets"] = wsyntax
_spec.loader.exec_module(wsyntax)

pytestmark = pytest.mark.skipif(shutil.which("memgrep") is None, reason="memgrep binary not on PATH")


def test_verb_for_known_codes_names_the_owning_chore():
    assert "atomize" in wsyntax._verb_for("atom-oversized")
    assert "update" in wsyntax._verb_for("link-one-sided")
    assert "no chore" in wsyntax._verb_for("link-downward-cross-scope")


def test_verb_for_unknown_code_falls_back_to_update():
    assert wsyntax._verb_for("some-future-rule") == "/janitor-memory-update"


def test_held_pages_are_skipped():
    assert wsyntax._held("/x/agentlenspro/memory/foo.md")
    assert wsyntax._held("/x/GHBook/memory/foo.md")
    assert not wsyntax._held("/Users/someone/proj/.claude/project/memory/foo.md")


def test_file_tickets_carries_path_code_line_only(monkeypatch):
    filed: list[dict] = []

    class _Raised:
        ok = True

    def fake_raise(code, **kw):
        filed.append({"code": code, **kw})
        return _Raised()

    import issue_catalog

    monkeypatch.setattr(issue_catalog, "raise_issue", fake_raise)
    findings = [
        lint.Finding("ERROR", "/mem/alpha.md", 15, "msg text with page body words", "atom-oversized"),
        lint.Finding("ERROR", "/mem/agentlenspro/beta.md", 3, "msg", "link-one-sided"),
        lint.Finding("ERROR", "/mem/gamma.md", 7, "msg", ""),
    ]
    n = wsyntax._file_tickets(findings)
    assert n == 1
    call = filed[0]
    assert call["code"] == "MEMCORP-001"
    assert call["where"] == "/mem/alpha.md:15"
    joined = str(call)
    assert "atom-oversized" in joined and "atomize" in joined
    assert "msg text with page body words" not in joined
