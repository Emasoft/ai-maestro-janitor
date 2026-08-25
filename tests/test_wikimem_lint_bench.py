"""The lint FP/FN benchmark, wired in as a GATE (WM-BENCH-08..10).

Two numbers the retrieval benchmark cannot see: how often the write gate blocks a legitimate
page (FP) and how often it waves a corrupt one through (FN). Both are regressions that ship
silently — an FP looks like a strict linter until people route around it, and an FN looks like
a clean corpus.

The tests below assert the CURRENT state (0/0 against the labelled corpus) AND — the part that
makes the number trustworthy — that the instrument still DETECTS both directions. A benchmark
that reports zero because it stopped looking is worse than no benchmark: it is a green light
nobody re-checks.

`MEMGREP_BIN` is pinned to the tree build (WM-BENCH-07): unpinned, every assertion here would
score whatever `cargo install` last left on PATH and report the old binary's numbers as this
one's.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import MEMGREP_BIN_PATH

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_REPO = _SCRIPTS.parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bench = _load(_SCRIPTS / "wikimem_lint_bench.py", "wikimem_lint_bench")

CORPUS = _REPO / "tests" / "fixtures" / "wikimem-lint-bench"
CASES = _REPO / "tests" / "wikimem_lint_bench" / "cases.json"
BASELINE = _REPO / "tests" / "wikimem_lint_bench" / "baseline.json"

needs_memgrep = pytest.mark.skipif(MEMGREP_BIN_PATH is None, reason="memgrep binary unavailable")


@pytest.fixture(autouse=True)
def _pin_binary(monkeypatch: pytest.MonkeyPatch):
    if MEMGREP_BIN_PATH:
        monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))


def _score() -> dict:
    return bench.score(CORPUS, json.loads(CASES.read_text(encoding="utf-8")))


@needs_memgrep
def test_the_linter_has_zero_false_positives_and_zero_false_negatives():
    res = _score()["summary"]
    assert res["false_positives"] == 0, _score()["false_positives"]
    assert res["false_negatives"] == 0, _score()["false_negatives"]


@needs_memgrep
def test_the_run_matches_the_committed_baseline():
    ok, problems = bench.compare(_score(), json.loads(BASELINE.read_text(encoding="utf-8")))
    assert ok, problems


@needs_memgrep
def test_an_unlabelled_defect_page_is_caught_as_a_false_positive(tmp_path: Path):
    # The instrument's FP direction. A page nobody declared must not be silently tolerated —
    # otherwise the corpus grows weaker every time someone drops a file into it.
    work = tmp_path / "corpus"
    shutil.copytree(CORPUS, work)
    # The page `description:` is deliberately compliant (15 `/`-separated phrases) so it
    # contributes no finding of its own — the ONLY defect left is the atom's missing
    # `keywords:`, which now fires BOTH `atom-no-keywords` (the prop is absent) and
    # `atom-keywords-too-few` (an absent list is 0 < the 10 minimum) from that one root cause.
    (work / "defects" / "zz-unlabelled.md").write_text(
        '---\nname: sneaky\ndescription: "an unlabelled sneaky defect page / why is this page '
        'flagged / what makes this page sneaky / undeclared defect fixture / a page absent from '
        'cases.json / does the bench catch an undeclared defect / unlabelled corpus entry / a '
        'page nobody declared in ground truth / atom missing its keywords entirely / recall '
        "surface absent from this atom / bench false-positive detection fixture / proves an "
        'unlabelled defect is not silently tolerated / corpus growth safety net / undeclared '
        'page must still be caught / sneaky unlabelled test page"\nocd: 2026-01-01\n'
        "lmd: 2026-01-02\n---\n"
        "^ATOM-SNEK-0001 [ocd: 2026-01-01, lmd: 2026-01-01]\nb.\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    res = bench.score(work, json.loads(CASES.read_text(encoding="utf-8")))
    assert res["summary"]["false_positives"] == 2, res
    assert res["summary"]["false_negatives"] == 0, res


@needs_memgrep
def test_a_check_that_stops_firing_is_caught_as_a_false_negative(tmp_path: Path):
    # The instrument's FN direction — the one that matters most, because a linter that quietly
    # stops checking something looks exactly like a corpus that got better.
    work = tmp_path / "corpus"
    shutil.copytree(CORPUS, work)
    (work / "defects" / "atom-no-keywords.md").write_text(
        '---\nname: atom-no-keywords\ndescription: "repaired"\nocd: 2026-01-01\nlmd: 2026-01-02\n---\n'
        "^ATOM-NOKW-0001 [keywords: now_it_has_one, ocd: 2026-01-01, lmd: 2026-01-01]\nbody.\n\n"
        "## Notes and lessons learned\n",
        encoding="utf-8",
    )
    res = bench.score(work, json.loads(CASES.read_text(encoding="utf-8")))
    assert res["summary"]["false_negatives"] == 1, res
    assert ("defects/atom-no-keywords.md:atom-no-keywords", 1) in res["false_negatives"]


@needs_memgrep
def test_deleting_a_label_cannot_pass_the_gate():
    # The cheapest way to fake a perfect score is to delete the failing label. Coverage and the
    # expected-finding count are gated for exactly that reason.
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    cases["expect"].pop("defects/atom-no-keywords.md")
    weakened = bench.score(CORPUS, cases)
    ok, problems = bench.compare(weakened, json.loads(BASELINE.read_text(encoding="utf-8")))
    assert not ok, "a shrunken corpus must fail the gate"
    assert any("false_positives rose" in p or "SHRANK" in p for p in problems), problems


@needs_memgrep
def test_every_labelled_code_is_one_the_linter_can_actually_emit():
    # A typo'd code in the labels would be an eternal false negative that no one could fix —
    # it can never be observed, so it would sit in the FN column forever looking like a real gap.
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    labelled = {c for codes in cases["expect"].values() for c in codes}
    observed, _lines = bench.observed_codes(CORPUS)
    emitted = {c for _f, c in observed}
    assert labelled <= emitted, f"labelled but never emitted: {sorted(labelled - emitted)}"


def test_the_uncoverable_check_is_documented_not_forgotten():
    # `link-downward-cross-scope` cannot fire in a fixture path (scope is derived from the path).
    # It must stay WRITTEN DOWN: an uncovered check nobody recorded is indistinguishable from one
    # nobody noticed.
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert "link-downward-cross-scope" in cases["not_measurable_here"]
    assert "unit test" in cases["not_measurable_here"]["link-downward-cross-scope"].lower()
