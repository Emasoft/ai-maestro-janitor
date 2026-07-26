"""Regression gate for the wikimem retrieval benchmark (TRDD-DO6X4ZF8).

Retrieval quality is the memory system's whole value, and it is the kind of property that decays
silently: a ranking tweak or an output change can cost accuracy with nothing failing. This test is
what makes that impossible to ship unnoticed — it re-runs the frozen benchmark and fails if
accuracy drops at all, or if the end-to-end token cost rises beyond tolerance.

Real end-to-end: it invokes the actual `memgrep` binary against the committed fixture corpus. No
mocks — a mocked retrieval benchmark would measure the mock.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_BENCH = _REPO / "scripts" / "wikimem_bench.py"
_BASELINE = _REPO / "tests" / "wikimem_bench" / "baseline.json"

# The benchmark drives the real Rust binary. When it is not installed the honest outcome is SKIP
# with a reason a human can act on — not a pass (which would hide a real regression behind a
# missing tool) and not a failure (the code under test is fine; the environment lacks a binary).
_memgrep = shutil.which("memgrep")
requires_memgrep = pytest.mark.skipif(
    _memgrep is None,
    reason="memgrep not on PATH — install it: cargo install --path scripts/memgrep",
)


@requires_memgrep
def test_retrieval_has_not_regressed():
    """🐌 The frozen benchmark still meets the committed baseline for accuracy and token cost."""
    proc = subprocess.run(
        [sys.executable, str(_BENCH), "--check"],
        capture_output=True, text=True, timeout=600, cwd=str(_REPO),
    )
    assert proc.returncode == 0, (
        "wikimem retrieval regressed against tests/wikimem_bench/baseline.json:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


@requires_memgrep
def test_baseline_is_committed_and_well_formed():
    """The baseline exists and carries the metrics the gate compares on.

    Without this, a deleted or truncated baseline would make the gate above silently vacuous —
    the failure mode where a regression test passes because it is no longer testing anything.
    """
    assert _BASELINE.is_file(), f"missing baseline: {_BASELINE}"
    data = json.loads(_BASELINE.read_text(encoding="utf-8"))
    summary = data["summary"]
    for key in ("hit_at_1", "hit_at_3", "hit_at_10", "mrr", "mean_total_tokens", "queries"):
        assert key in summary, f"baseline summary missing {key!r}"
    assert summary["queries"] > 0


def test_queries_ground_truth_targets_exist():
    """Every query's expected atom actually exists in the fixture corpus.

    Guards the ground truth itself: a typo'd atom id would make its query permanently unhittable,
    quietly depressing the baseline and making a later real improvement look like a regression.
    Pure filesystem check, so it runs even without the binary.
    """
    spec = json.loads((_REPO / "tests" / "wikimem_bench" / "queries.json").read_text(encoding="utf-8"))
    corpus = _REPO / spec["corpus"]
    missing = []
    for q in spec["queries"]:
        page, _, atom = q["expect"].partition("#")
        src = corpus / f"{page}.md"
        if not src.is_file() or f"^{atom} [" not in src.read_text(encoding="utf-8"):
            missing.append(q["expect"])
    assert not missing, f"ground-truth atoms not found in the corpus: {missing}"
