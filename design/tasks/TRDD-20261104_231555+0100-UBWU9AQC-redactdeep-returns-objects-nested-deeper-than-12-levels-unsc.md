---
trdd-id: UBWU9AQC
title: redactDeep returns objects nested deeper than 12 levels unscanned, so a token there is not hidden
column: todo
status: tasked
created: 2026-11-04T23:15:55+0100
updated: 2026-11-04T23:15:55+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T23:15:55+0100
---

# redactDeep returns objects nested deeper than 12 levels unscanned, so a token there is not hidden

## Problem

`mapStrings` in hooks/secret-shield/patterns.ts returns a node unchanged when its depth is over 12 (patterns.ts:370; the comment at :366 says "nodes deeper than 12 levels are left as they are"). The string check at :369 runs before the depth check, so a string is redacted wherever the walk reaches it, but an object below depth 12 is returned as it is and its strings are never visited. Nothing is marked or dropped, so the miss fails open.

Measured on 2026-11-04 at b39e8a8a with local Bun 1.3.14, calling redactDeep directly (reports_dev/sonnet-worker/20261104_230058+0100-known-misses-measure.md, gitignored and local; rows prop-depth, 3 values each): a GitHub-shaped token inside a string of an object 13 or 14 levels below the root is not hidden; at 12 levels it is hidden; the same token at depth 1 is hidden. A copy of a found value at those depths behaves the same way.

Path, inferred from register.ts:68 and :98 and not measured through the hook: the tool.call hook calls redactDeep on the tool result, so once the mod is wired (TRDD-2V7OAUPE) a tool result nested that deep would reach the model with the token in it.

## Done when

1. A known-defect test pins today's miss: a test in hooks/secret-shield/tests/known-misses.test.ts whose title carries this card's id and the slug deep-nesting-over-12, listed in hooks/secret-shield/KNOWN-MISSES.md.
2. A fix either scans every string at any depth or fails closed for a subtree it will not walk (for example, replaces it with a marker). It keeps whatever the cap protects against, which is to be found first, and stays linear (64, 256 and 512 KB, below the core count; a timing taken above the core count is inconclusive, not failed). The known-defect test then becomes a positive test. register.ts has no catch around redactDeep in tool.call, so the fix must not throw on very deep or cyclic input: a stress test at thousands of levels neither throws nor leaves a token visible.

## Unverified

Why the cap is 12: no comment says why, and the cap was not checked against the vendored upstream commit 5bbf314e. Whether real tool results nest that deep.

Found during TRDD-Q6LPJTPO (the KNOWN-MISSES measurement).

## Approval log

- 2026-11-04T23:15:55+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
