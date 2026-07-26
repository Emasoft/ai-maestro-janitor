# wikimem retrieval benchmark — frozen fixture corpus

**Do not "fix" the keyword syntax in these pages.** They are authored in the SAME
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
