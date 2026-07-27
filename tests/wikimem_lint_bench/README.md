# The lint FP/FN benchmark

Two of the four numbers that steer the wikimem tools (WM-BENCH-00). The other two —
retrieval accuracy and end-to-end token cost — live in `tests/wikimem_bench/`.

```
export MEMGREP_BIN="$PWD/scripts/memgrep/target/release/memgrep"   # WM-BENCH-07
uv run scripts/wikimem_lint_bench.py            # score
uv run scripts/wikimem_lint_bench.py --check    # the gate (non-zero on regression)
```

## What the numbers mean

* **FP = 0 is an absolute claim** and it holds by construction: every check mirrors the
  parser's own drop/failure branch (WM-ATOM-07), so it fires exactly when the consumer
  discards the input.
* **FN = 0 is RELATIVE to this corpus**, and cannot be anything else — "all real defects"
  is not an enumerable set. The corpus IS the promise. It **grows every time a real defect
  escapes in the wild**; that is the only way the promise gets stronger.

## The two populations

* `defects/` — one page per check, each labelled in `cases.json` with the codes it MUST
  produce. This is the **false-negative** surface.
* `clean/` — conformant pages **and deliberate near-misses**. This is the **false-positive**
  surface, and it is the half that keeps the gate honest: documentation showing the broken
  forms in inline code and fences, a quoted comma in `desc:`, a trailing comma, the
  grandfathered legacy-slug `desc:`, a reciprocal link pair, an atom just under budget.

An **unlabelled** page expects nothing, so dropping a file in without declaring it shows up
as an FP rather than quietly weakening the corpus.

## Extending it

When a real defect escapes into the live corpus: add the smallest page that reproduces it to
`defects/`, label it, and re-baseline. When a false positive is reported: add the shape that
was wrongly flagged to `clean/` — unlabelled — so the fix is pinned against recurrence.

Matching is on `(file, code)` — never message text (so improving wording is not a regression)
and never line numbers (so extending a page is not one either). Coverage is gated too
(WM-BENCH-11): deleting the label that was failing is the cheapest way to fake a green run.
