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
# The PRIMARY corpus: the same pages in the `underscore_joined` form the spec MANDATES. The legacy
# corpus above encodes a keyword form `atom-dropped-props` now rates CRITICAL, so gating only on it
# would mean tuning retrieval for input the system no longer accepts.
_CONFORMANT_CORPUS = _REPO / "tests" / "fixtures" / "wikimem-bench-conformant"
_CONFORMANT_BASELINE = _REPO / "tests" / "wikimem_bench" / "baseline-conformant.json"

# The benchmark drives the real Rust binary — and it MUST be the binary built from THIS tree.
#
# Without pinning it, the harness resolves `memgrep` from PATH, i.e. whatever is INSTALLED. That is
# not a theoretical hazard: it fired here. A change to the page-row locator landed in the tree, the
# baselines were re-captured from the tree build, and the suite then failed — because it had
# measured the stale installed binary against the new baselines. The mirror-image failure is the
# dangerous one: measure a stale binary against stale baselines and every run passes while the code
# under test is never exercised at all.
#
# `find_or_build_memgrep` prefers this tree's target/ and builds it when absent, so the pin is also
# what makes the gate meaningful on a machine with no `cargo install`ed copy.
from conftest import MEMGREP_BIN_PATH  # noqa: E402

_memgrep = MEMGREP_BIN_PATH or shutil.which("memgrep")
requires_memgrep = pytest.mark.skipif(
    _memgrep is None,
    reason="memgrep could not be found or built from this tree",
)


def _bench_env() -> dict[str, str]:
    """The environment every benchmark subprocess runs under: `MEMGREP_BIN` pinned to the binary
    under test, so the harness can never silently score a different build."""
    import os

    env = dict(os.environ)
    if _memgrep:
        env["MEMGREP_BIN"] = _memgrep
    return env


@requires_memgrep
def test_retrieval_has_not_regressed():
    """🐌 The frozen (legacy, intentionally comma-form) benchmark still meets its baseline.

    `--allow-dropped-keywords` is required here (issue #119): this corpus is deliberately kept
    in the pre-migration comma form (see tests/wikimem_bench/README.md), so it lints
    atom-dropped-props-dirty on purpose — the fixture the fail-fast gate below exists to allow.
    """
    proc = subprocess.run(
        [sys.executable, str(_BENCH), "--check", "--allow-dropped-keywords"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(_REPO),
        env=_bench_env(),
    )
    assert proc.returncode == 0, f"wikimem retrieval regressed against tests/wikimem_bench/baseline.json:\n{proc.stdout}\n{proc.stderr}"


@requires_memgrep
def test_legacy_corpus_is_refused_without_the_dropped_keywords_flag():
    """🐌 A corpus with atom-dropped-props findings is REFUSED, not silently scored (issue #119).

    Before this gate existed, `wikimem_bench.py --check` on the legacy corpus (which lints
    atom-dropped-props-dirty — see the sibling test) exited 0 and printed a confident accuracy
    number, even though several atoms' recall surface is truncated by the parser bug it is
    measuring around. hit@1/3/10 could not then tell "the ranker missed it" from "nothing could
    ever have retrieved it". This proves the omitted flag now fails fast instead.
    """
    proc = subprocess.run(
        [sys.executable, str(_BENCH), "--check"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(_REPO),
        env=_bench_env(),
    )
    assert proc.returncode == 2, (
        "a corpus with atom-dropped-props findings must be REFUSED, not scored:\n"
        + proc.stdout + proc.stderr
    )
    assert "atom-dropped-props" in proc.stderr, proc.stderr
    assert "REGRESSION" not in proc.stdout, "a refused corpus must not also report a score"


@requires_memgrep
def test_conformant_corpus_needs_no_dropped_keywords_flag():
    """🐌 The PRIMARY (spec-conformant) corpus lints clean, so the fail-fast gate never fires
    on it — the escape hatch is for the LEGACY fixture only, never for the number that matters.
    """
    proc = subprocess.run(
        [
            sys.executable, str(_BENCH), "--check",
            "--corpus", str(_CONFORMANT_CORPUS),
            "--baseline", str(_CONFORMANT_BASELINE),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(_REPO),
        env=_bench_env(),
    )
    assert "atom-dropped-props" not in proc.stderr, (
        "the conformant corpus must never need --allow-dropped-keywords:\n" + proc.stderr
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"


@requires_memgrep
def test_conformant_retrieval_has_not_regressed():
    """🐌 The PRIMARY (spec-conformant) corpus still meets its committed baseline."""
    proc = subprocess.run(
        [
            sys.executable,
            str(_BENCH),
            "--check",
            "--corpus",
            str(_CONFORMANT_CORPUS),
            "--baseline",
            str(_CONFORMANT_BASELINE),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(_REPO),
        env=_bench_env(),
    )
    assert proc.returncode == 0, f"wikimem retrieval regressed against the CONFORMANT baseline {_CONFORMANT_BASELINE.name}:\n{proc.stdout}\n{proc.stderr}"


@requires_memgrep
def test_a_corpus_baseline_mispairing_is_refused_not_reported_as_a_regression():
    """🐌 `--corpus` and `--baseline` default INDEPENDENTLY, so measuring the conformant corpus
    while forgetting to redirect the baseline compares it against the legacy numbers.

    That produced `REGRESSION mean_total_tokens: 174.3 -> 273.0 (limit 177.8)` — a precise,
    confident, entirely false report, indistinguishable from a real regression by anything except
    knowing which flags were passed. The danger is the direction it fails in: the operator's next
    move is to go hunting for a performance bug that does not exist, or to "re-baseline" and
    thereby destroy the real committed numbers.

    The guard compares the corpus each side was MEASURED on rather than inspecting the flags, so
    it equally catches a `--baseline` aimed at the wrong file. Exit 2 (a usage error), never 1 —
    a caller must be able to tell "you asked the wrong question" from "the answer got worse"."""
    proc = subprocess.run(
        [sys.executable, str(_BENCH), "--check", "--corpus", str(_CONFORMANT_CORPUS)],
        capture_output=True, text=True, timeout=600, cwd=str(_REPO), env=_bench_env(),
    )
    assert proc.returncode == 2, (
        "a corpus/baseline mispairing must be REFUSED, not scored:\n" + proc.stdout + proc.stderr
    )
    assert "mismatch" in proc.stderr, proc.stderr
    assert "REGRESSION" not in proc.stdout, "the mispairing was still reported as a regression"


@requires_memgrep
def test_conformant_corpus_retrieves_every_query_at_rank_one():
    """On a spec-conformant corpus retrieval is PERFECT — and this pins it there.

    A plain baseline comparison would happily accept 0.99 as "no regression beyond tolerance". The
    conformant corpus is the shape the spec mandates and the tiered scorer resolves every symptom
    query to rank 1 on it, so anything less is a real defect rather than a rounding difference.
    """
    baseline = json.loads(_CONFORMANT_BASELINE.read_text(encoding="utf-8"))["summary"]
    assert baseline["hit_at_1"] == 1.0, "conformant hit@1 must be perfect"
    assert baseline["mrr"] == 1.0, "conformant MRR must be perfect"


def test_the_two_corpora_differ_only_in_keyword_FORM():
    """The conformant corpus is the legacy one REPAIRED — same pages, same facts, same atom ids.

    If they drifted into two different corpora the 2×2 comparison in the README would be measuring
    two unrelated things while looking like a controlled experiment. Pure filesystem check.
    """
    legacy = sorted(p.name for p in (_REPO / "tests" / "fixtures" / "wikimem-bench").glob("*.md"))
    conformant = sorted(p.name for p in _CONFORMANT_CORPUS.glob("*.md"))
    assert legacy == conformant, "the two benchmark corpora must hold the same pages"
    for name in legacy:
        a = (_REPO / "tests" / "fixtures" / "wikimem-bench" / name).read_text(encoding="utf-8")
        b = (_CONFORMANT_CORPUS / name).read_text(encoding="utf-8")
        ids_a = [ln.split()[0] for ln in a.splitlines() if ln.startswith("^")]
        ids_b = [ln.split()[0] for ln in b.splitlines() if ln.startswith("^")]
        assert ids_a == ids_b, f"{name}: atom ids diverged between the corpora"


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
