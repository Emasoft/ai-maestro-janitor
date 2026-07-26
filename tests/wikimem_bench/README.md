# wikimem retrieval benchmark

Harness `scripts/wikimem_bench.py` · ground truth `queries.json` · committed `baseline.json` ·
frozen corpus `tests/fixtures/wikimem-bench/`.

The corpus dir holds **memory pages and nothing else** — this README lives here rather than beside
them because any `.md` inside that directory is parsed as a memory page: it would be linted as one
and could be returned as a retrieval candidate, quietly skewing the very numbers being measured.
It did, until it was moved (mean cost fell 443.5 → 441.4 tokens/query on the move alone).

**Do not "fix" the keyword syntax in the corpus pages.** They are authored in the SAME
comma-separated multi-word form the live corpus uses, which the parser truncates at the first
comma (TRDD-DO6X4ZF8, plan Phase 1.3). That truncation is the thing under measurement: the
committed baseline records how badly retrieval performs today, and the Phase 1.3 migration is
scored against it. Normalising these files to `underscore_joined` form by hand would erase the
very signal the benchmark exists to detect, and would silently turn the baseline into a lie.

Frozen on purpose: the live corpus changes weekly, so benchmarking against it would make every
run incomparable to the last — the opposite of a regression instrument. `wikimem_bench.py --live`
exists for spot checks and never gates.

Content is generic software-engineering material (connection pools, TLS chains, cron drift). It
deliberately shares no subject matter with the real project corpus, so a page here can never be
mistaken for, or drift against, a real memory.
