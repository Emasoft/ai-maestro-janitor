---
trdd-id: JD2QR5SQ
title: C22 — wire fixers into lint
column: blocked
status: tasked
created: 2026-10-01T19:45:13+0200
updated: 2026-10-05T01:56:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:13+0200
blocked-by: [3HLI7DMK]
pre-block-column: todo
blocker-probe: [trddgrep, why, JD2QR5SQ]
blocker-holds-if: not-match:READY
---

# C22 — wire fixers into lint

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C22, wave W2.

Writes (exclusive): src/memory.rs, src/fixers/mod.rs, scripts/memgrep/tests/cli.rs
Task: Wire C13 plus the fixers into lint_paths_with: scope lock → fix_page → write_gated; on refusal record 'unfixed' once per (page, reason) via the ledger; then the lock-only normalization path; re-lint; flags --unsafe-fixes, --diff, --show-fixes
Verify: CLI: a SAFE page gets fixed; a floor-error page stays byte-identical with exactly one ledger entry over 2 runs; --no-fix/--diff write nothing; on a scratch copy of the PROJECT memory, diff -r shows only the expected changes and validate is clean
Depends on: C21, C13, C14, C15, C16, C17, C18, C19
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:11+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 3HLI7DMK, I23YCEW7, 4G427D8M, 9SUZ48E8, QBU0HSM9, KSCAFSLD, RLD015QB, RUJQ7WSX per DSN035UN wave order

## STATE

2026-10-05: blocked-by trimmed to the two cards still open (3HLI7DMK C21, I23YCEW7). C14 to C19 (4G427D8M, 9SUZ48E8, QBU0HSM9, KSCAFSLD, RLD015QB, RUJQ7WSX) were completed and archived on 2026-10-05 after review; the fixers are unit-tested and ready to wire. Wiring notes from that review: the unused-noqa fixer needs C21 before lint emits its code; the lint-ignore frontmatter line is still rebuilt with normalised spacing; a single-quoted description with a repeated phrase is not reported by lint.
2026-10-05 later: CORRECTION to the line above. The lint-ignore frontmatter line is no longer rebuilt with normalised spacing: e0d7dc50 reassembles it from its own bytes around the bracket span (test with an oddly spaced line). The other two wiring notes still stand; the single-quoted description gap is now card TRDD-GTP15HRC and the frontmatter terminator mismatch is TRDD-ZW0GUQCG.
