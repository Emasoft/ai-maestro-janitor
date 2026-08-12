"""The coverage bench's own guards (janitor#226).

The point of these is narrow: COVERAGE.md publishes a per-rule verdict, and a published
verdict that drifts out of date is the exact failure the document exists to prevent — an
assertion that outlives the property it describes and then suppresses the suspicion that
anyone should look. So the doc must be provably derived from the committed baseline, and
every rule in the catalog must appear in it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import agent_config_patterns as acp  # noqa: E402
import agent_context_bench as bench  # noqa: E402

_BENCH_DIR = _REPO / "tests" / "agent_context_bench"


def _baseline() -> dict:
    return json.loads((_BENCH_DIR / "baseline.json").read_text(encoding="utf-8"))


def test_coverage_doc_matches_the_committed_baseline() -> None:
    """COVERAGE.md must be exactly what the baseline renders — no hand-edits, no drift.

    If this fails, the doc is asserting a coverage verdict the measurement no longer
    supports. Regenerate with `uv run scripts/agent_context_bench.py --write-baseline`
    rather than editing the table, or the next reader trusts a stale number.
    """
    committed = (_BENCH_DIR / "COVERAGE.md").read_text(encoding="utf-8")
    assert committed == bench.coverage_doc(_baseline()), (
        "COVERAGE.md is out of sync with baseline.json — regenerate it "
        "(scripts/agent_context_bench.py --write-baseline), do not hand-edit"
    )


def test_every_catalog_rule_appears_in_the_coverage_doc() -> None:
    """A rule added to RULES must show up in COVERAGE.md, even if only as UNMEASURED.

    This is the guard against the quiet failure mode: someone adds a pattern, it is never
    seeded, and its absence from the table reads as "nothing to report" rather than
    "nobody has ever checked whether this fires".
    """
    doc = bench.coverage_doc(_baseline())
    missing = [r.id for r in acp.RULES if f"`{r.id}`" not in doc]
    assert not missing, f"rules absent from COVERAGE.md: {missing}"


def test_unmeasured_is_never_rendered_as_a_pass() -> None:
    """An unmeasured rule must say so, not show a recall number.

    Reporting 0/0 as "0%" would let an unseeded rule masquerade as a measured failure, and
    a blank cell would let it masquerade as fine. Both are worse than the word UNMEASURED.
    """
    doc = bench.coverage_doc(_baseline())
    # TABLE ROWS only. An earlier version scanned every line containing "UNMEASURED" and so
    # tripped on the header prose that explains the word — a test that fails on its own
    # documentation, which would have been quietly deleted rather than fixed.
    rows = [ln for ln in doc.splitlines() if ln.startswith("| `")]
    assert rows, "coverage doc rendered no rule rows"
    for line in rows:
        if "UNMEASURED" in line:
            assert "| — |" in line, f"unmeasured rule rendered with a recall figure: {line}"
