# C30 reverted implementation — KNOWN-REJECTED evidence

The implementation of TRDD-I4MOD020 (C30) was REVERTED on 2026-10-09 after its adversarial review confirmed finding F1: the two precheck repair branches the patch drops ARE the standing discovery trigger feeding the C22-style fixers. Dropping them strands fixer-owned defects with no trigger — the fixers become dead code in the standing pipeline.

The 320-line patch is kept in git history, not in the working tree: as a file it made the release validator report 9 MAJOR findings (the diff quotes test code the scanner reads as live), which blocks every publish. Read it with:

```bash
git show 583e2e60:design/specs/c30-reverted-implementation/20261009_c30-reverted-implementation-patch.diff
```

DO NOT apply it. It is evidence for a future design decision (lint-driven discovery surface, or extending repair_has_work to consult memgrep lint for fixer-backed codes). Re-apply only after that decision, per the NEXT ACTION in the STATE block of the TRDD-I4MOD020 card.

The renamed copy under reports_dev/ is stale; use only the git command above.
