# C30 reverted implementation — KNOWN-REJECTED evidence

`20261009_c30-reverted-implementation-patch.diff` is the implementation of TRDD-I4MOD020 (C30) that was REVERTED on 2026-10-09 after its adversarial review confirmed finding F1: the two precheck repair branches the patch drops ARE the standing discovery trigger feeding the C22-style fixers. Dropping them strands fixer-owned defects with no trigger — the fixers become dead code in the standing pipeline.

DO NOT apply this patch. It is preserved as evidence for a future design decision (lint-driven discovery surface, or extending repair_has_work to consult memgrep lint for fixer-backed codes). Re-apply only after that decision, per the NEXT ACTION in the STATE block of design/tasks/TRDD-20261001_194517+0200-I4MOD020-c30-drop-precheck-repair-branches.md.

Source: reports_dev/20261009_c30-reverted-implementation-patch.diff (reports_dev/ is gitignored; this copy is the durable one).
The reports_dev twin is now STALE — never apply it or diff it against HEAD; use only this tracked path.