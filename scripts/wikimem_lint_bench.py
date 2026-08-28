#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""wikimem_lint_bench — measure the linter's FALSE POSITIVES and FALSE NEGATIVES.

WHY this exists, and what its numbers can honestly claim:

`memgrep lint` is a WRITE GATE. Both of its failure directions are expensive and neither is
visible without measurement:

  * a FALSE POSITIVE blocks a legitimate write, and a gate that blocks correct work is one
    people learn to route around — which costs you every finding it would ever have made;
  * a FALSE NEGATIVE lets a corrupt page through, which is the whole thing the gate exists
    to prevent.

**0% false positives is achievable in the absolute** — and is already the design law
(WM-LINT-01): every check is derived from the PARSER's own drop / failure branches
(WM-ATOM-07), so a check fires exactly when the consumer discards or fails on the input.
That is an observation of the consumer's behaviour, not a heuristic about the author's
intent, so there is nothing for it to be wrong about.

**0% false negatives is NOT achievable in the absolute, and any tool claiming it is lying.**
A false negative is "a real defect the linter did not catch", and the set of all real defects
is not enumerable — it includes a page that parses perfectly and is simply FALSE. No
structural linter can bound that.

What IS achievable, and what this benchmark measures: **0 FN relative to a labelled corpus.**
The fixture corpus IS the definition of what the linter PROMISES to catch. FN = 0 means "every
defect we have committed to catching is caught"; FP = 0 means "no page we have committed to
accepting is flagged". That converts an unprovable claim into a regression instrument — and the
corpus GROWS every time a real defect escapes in the wild, so the promise ratchets upward and
can never silently shrink.

The corpus therefore carries two populations, and the second is the one that actually keeps the
gate honest:

  * `defects/` — one page per check, each labelled with the codes it MUST produce (FN surface);
  * `clean/`   — conformant pages AND deliberate NEAR-MISSES: prose that documents the broken
    forms in inline code and fences, a quoted comma inside `desc:`, a trailing comma, the
    grandfathered legacy-slug `desc:`, a reciprocal link pair, an atom just under the size
    budget. Every one of these is a shape a naive check would flag (FP surface).

Matching is on the (file, CODE) multiset, not on message text and not on line numbers. The code
is the check's stable identity, so improving a message cannot register as a regression — and a
line-exact label would make the corpus painful to extend, which is the fastest way to stop
people extending it. Wrong-check-fired IS caught, because the code is compared.

Exit status: 0 when the run matches the baseline, 1 on any regression (a new FP, a new FN, or a
baseline/corpus mismatch).

NOT read-only any more, and that matters for what this measures. This harness shells out to
`memgrep lint`, and since TRDD-RY0IJBJI that verb AUTOFIXES as it goes (it reconciles
publish-globally/symlink state). So a run MUTATES the corpus it is scoring, and a second run can
legitimately differ from the first because the first repaired something. Point it at a COPY of a
corpus, never at a corpus whose FP/FN numbers you intend to compare across runs. This docstring
claimed "READ-ONLY — it never edits a page" until 2026-08-27; that was written before lint gained
autofix and was silently false afterwards, which is the failure mode a benchmark can least afford.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import wikimem_syntax_lint as lint  # noqa: E402

_REPO = _SCRIPTS.parent
DEFAULT_CORPUS = _REPO / "tests" / "fixtures" / "wikimem-lint-bench"
DEFAULT_CASES = _REPO / "tests" / "wikimem_lint_bench" / "cases.json"
DEFAULT_BASELINE = _REPO / "tests" / "wikimem_lint_bench" / "baseline.json"


def observed_codes(corpus: Path) -> tuple[Counter[tuple[str, str]], list[str]]:
    """Run the linter over `corpus` → (multiset of (relative-file, code), raw finding lines).

    Paths are made corpus-relative so the labels are portable: an absolute path would bake this
    machine's home directory into a committed fixture, and the benchmark would then only ever
    reproduce here.
    """
    _rc, stdout, findings = lint.run_lint([corpus])
    seen: Counter[tuple[str, str]] = Counter()
    for f in findings:
        try:
            rel = str(Path(f.path).resolve().relative_to(corpus.resolve()))
        except ValueError:
            rel = f.path
        seen[(rel, f.code or "UNCODED")] += 1
    return seen, stdout.splitlines()


def score(corpus: Path, cases: dict) -> dict:
    """Compare observed findings against the labels. Returns the full result record.

    A file the labels do not mention at all is treated as EXPECTING NOTHING, so a newly added
    fixture page cannot quietly contribute findings that nobody declared — it shows up as a false
    positive until someone labels it. That default is deliberate: the alternative (ignore unknown
    files) makes the corpus grow silently weaker.
    """
    expected: Counter[tuple[str, str]] = Counter()
    for rel, codes in cases["expect"].items():
        for code in codes:
            expected[(rel, code)] += 1

    seen, _lines = observed_codes(corpus)

    # FALSE POSITIVE: reported more times than the labels allow. FALSE NEGATIVE: the reverse.
    false_positives = sorted((f"{f}:{c}", n) for (f, c), n in (seen - expected).items())
    false_negatives = sorted((f"{f}:{c}", n) for (f, c), n in (expected - seen).items())

    labelled_files = sorted({f for f, _ in expected})
    corpus_files = sorted(
        str(p.relative_to(corpus)) for p in corpus.rglob("*.md") if p.name != "MEMORY.md"
    )
    return {
        "summary": {
            "corpus_files": len(corpus_files),
            "labelled_defect_files": len(labelled_files),
            "expected_findings": sum(expected.values()),
            "observed_findings": sum(seen.values()),
            "false_positives": sum(n for _, n in false_positives),
            "false_negatives": sum(n for _, n in false_negatives),
            "codes_covered": len({c for _, c in expected}),
        },
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def render(res: dict) -> str:
    s = res["summary"]
    out = [
        f"corpus:    {s['corpus_files']} pages ({s['labelled_defect_files']} carry labelled defects)",
        f"coverage:  {s['codes_covered']} distinct check codes exercised",
        f"findings:  {s['observed_findings']} observed / {s['expected_findings']} expected",
        f"FALSE POSITIVES: {s['false_positives']}",
        f"FALSE NEGATIVES: {s['false_negatives']}",
    ]
    for label, key in (("FP", "false_positives"), ("FN", "false_negatives")):
        for item, n in res[key]:
            out.append(f"  [{label}] {item}" + (f" ×{n}" if n > 1 else ""))
    return "\n".join(out)


def compare(cur: dict, base: dict) -> tuple[bool, list[str]]:
    """Regression gate. FP and FN may never RISE, and coverage may never SHRINK.

    Coverage is gated too because the cheapest way to make FN look perfect is to delete the
    fixture that was failing — a green run on a corpus that stopped asking the question.
    """
    problems: list[str] = []
    c, b = cur["summary"], base["summary"]
    for k in ("false_positives", "false_negatives"):
        if c[k] > b[k]:
            problems.append(f"{k} rose {b[k]} → {c[k]}")
    if c["codes_covered"] < b["codes_covered"]:
        problems.append(f"codes_covered SHRANK {b['codes_covered']} → {c['codes_covered']}")
    if c["expected_findings"] < b["expected_findings"]:
        problems.append(
            f"expected_findings SHRANK {b['expected_findings']} → {c['expected_findings']} "
            "(a label was deleted — the corpus now promises less)"
        )
    return (not problems), problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure memgrep lint's false positives + negatives.")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--check", action="store_true", help="fail on any FP/FN regression")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        res = score(args.corpus, cases)
    except lint.MemgrepMissing as e:
        print(f"lint-bench: {e}", file=sys.stderr)
        return 2

    print(json.dumps(res, indent=2) if args.json else render(res))

    if args.write_baseline:
        args.baseline.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"\nbaseline written → {args.baseline}", file=sys.stderr)
        return 0

    if args.check:
        if not args.baseline.is_file():
            print(f"\nlint-bench: no baseline at {args.baseline}", file=sys.stderr)
            return 1
        ok, problems = compare(res, json.loads(args.baseline.read_text(encoding="utf-8")))
        print("\n  no change" if ok else "\n  REGRESSION:\n    " + "\n    ".join(problems))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
