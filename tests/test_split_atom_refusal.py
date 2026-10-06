"""janitor#326 item 2: a verbatim-quote atom that cannot be brought under budget is judged ONCE.

Before: the over-budget-atom half of `split` had no way to record a keep verdict, so the
gate re-dispatched the chore (~300k tokens) at every recheck window forever. Now the agent
records a page-granular `split-atom` refusal that re-arms only when the PAGE changes (the
content hash already guarantees that) and never on a clock.

Real memgrep binary on a real fixture page; no mocks.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from conftest import MEMGREP_BIN_PATH

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import memory_content_precheck as mcp  # noqa: E402
import memory_refusals  # noqa: E402

pytestmark = pytest.mark.skipif(MEMGREP_BIN_PATH is None, reason="memgrep binary unavailable")

CAP = 36000


@pytest.fixture
def scope_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    root = tmp_path / "mem"
    root.mkdir()
    (root / "quote.md").write_text(
        "---\nname: quote\ndescription: \"a page with an oversized verbatim atom\"\n"
        "ocd: 2026-07-01\nlmd: 2026-07-08\nmetadata:\n  node_type: memory\n"
        "  type: project\n  tier: aspect\n---\n\n"
        '^big-quote [desc: "owner quote", keywords: symptom words, ocd: 2026-07-01, lmd: 2026-07-08]\n'
        + "word " * 400
        + "\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    return root


def test_the_oversized_atom_dispatches_until_it_is_refused(scope_root: Path) -> None:
    assert mcp.split_has_work(scope_root, max_bytes=CAP, scope="LOCAL") is True


def test_a_split_atom_refusal_suppresses_dispatch(scope_root: Path) -> None:
    assert memory_refusals.record(
        "split-atom", "LOCAL", scope_root, [scope_root / "quote.md"], reason="verbatim owner quote"
    )
    assert mcp.split_has_work(scope_root, max_bytes=CAP, scope="LOCAL") is False


def test_the_refusal_never_expires_on_a_clock(scope_root: Path) -> None:
    long_ago = int(time.time()) - 400 * 86400
    memory_refusals.record(
        "split-atom", "LOCAL", scope_root, [scope_root / "quote.md"], reason="verbatim", now=long_ago
    )
    assert mcp.split_has_work(scope_root, max_bytes=CAP, scope="LOCAL") is False


def test_editing_the_page_re_arms_the_chore(scope_root: Path) -> None:
    page = scope_root / "quote.md"
    memory_refusals.record("split-atom", "LOCAL", scope_root, [page], reason="verbatim")
    page.write_text(page.read_text(encoding="utf-8") + "\nmore text\n", encoding="utf-8")
    assert mcp.split_has_work(scope_root, max_bytes=CAP, scope="LOCAL") is True


def test_other_interventions_keep_the_seven_day_ttl(scope_root: Path) -> None:
    page = scope_root / "quote.md"
    old = int(time.time()) - 8 * 86400
    memory_refusals.record("repair", "LOCAL", scope_root, [page], reason="x", now=old)
    assert not memory_refusals.is_refused("repair", "LOCAL", scope_root, [page])
