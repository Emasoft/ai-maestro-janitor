---
trdd-id: AGV84UGC
title: Secret shield URL password user part and its query and password loops are flagged as a regex denial of service shape
column: todo
status: tasked
created: 2026-11-14T22:28:32+0100
updated: 2026-11-14T22:28:32+0100
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
approval-datetime: 2026-11-14T22:28:32+0100
---

# Secret shield URL password user part and its query and password loops are flagged as a regex denial of service shape

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: read redactUrlPasswords and its guard walk (USER_RUN, MARK_AT, the colon it ends at) in hooks/secret-shield/patterns.ts, then build the rewrite below as one bounded change with differential tests against the old regex; re-run the scoped CPV skillaudit on hooks/secret-shield and confirm the findings at the URL_PASSWORD, QUERY and password-loop lines are gone. Tests only run before the push. Consult the Fable advisor first: the unrolling constraints (TRDD-HF7GNHNF, TRDD-AGOEWF2E) must not regress.
- Status: not started. Blocks the CPV publish gate (v5.16.2 skillaudit) together with the JSON_OVER_BOUND card TRDD-MC895I0A. Related: archived TRDD-HF7GNHNF (URL_PASSWORD slowed between 96 KB and 128 KB), TRDD-AGOEWF2E (dev; very long URL password), TRDD-OD5Z90YL (plan; ReDoS harness).

## Finding

The CPV gate (skillaudit, REGEX_DOS, MINOR) flags hooks/secret-shield/patterns.ts line 66, the user part of URL_PASSWORD: `((?:NOT_USER|MARK_BODY)NOT_USER*(?:MARK_BODY NOT_USER*)*)`. It is linear (MARK_BODY starts with `[`, which NOT_USER excludes, so the parse is unique) and bounded by the URL guard, but it is a quantified group with an inner quantifier, the shape the scanner's TypeScript prover refuses by design. Lines 64 (QUERY: `[^\s@#:]*(?::(?!\/\/)[^\s@#:]*)*`) and 67 (the password loop `NOT_PASSWORD*(?::(?!\/\/)NOT_PASSWORD*)*`) carry the same group-with-inner-quantifier shape and escape only the line matcher (the `(?!\/\/)` breaks it); one card covers all three. Moving the source or hiding it behind an identifier would silence the line matcher with the compiled regex unchanged: a workaround, not a fix, so NOT done. The gate still blocks on line 66.

The user part interleaves NOT_USER runs and markers; no regex without nesting exists for it except a per-character group loop, which hits the engine iteration ceilings that the unrolling in TRDD-HF7GNHNF and TRDD-AGOEWF2E avoids.

## Design

Card design from the read-only check of redactUrlPasswords: the guard already walks the user part with USER_RUN and MARK_AT (the same grammar) and ends at `colon`. The regex can therefore start sticky (flag y) at that colon, with the user part sliced from the walk, which drops the user loop from the regex entirely. Then handle the QUERY loop (line 64) and the password loop (line 67) the same way, or prove them linear by an unrolled form the prover accepts. Byte-identical behaviour is required: dump TOKEN_ORDER (kind, source, flags of all TOKENS) with bun before and after and compare with cmp where the regex source is unchanged, and write differential tests (old regex versus new walk plus sticky regex) over user parts with markers, ports followed by paths and queries, passwords containing colons, passwords over the colon bound, and placeholder and marker-only passwords.

Gates after the change: scoped skillaudit as in ced9f0db (CPV 5.16.2 run_skillaudit_scan_files over the 18 hooks/secret-shield .ts and .md files; after ced9f0db: 2 non-test findings plus 28 in tests/); scripts/run_secret_shield_tests.py (845 pass, floor 800 at that commit); the mutation-check pattern used in ced9f0db (scratch copies outside the tree, claude plugin test).

Alternatives (not applied): the CPV audit-consent sentinel comment (turns the finding into a non-blocking WARNING; misleading on the shield's own code) and an upstream CPV issue for a TypeScript discriminator for such a group. See the JSON_OVER_BOUND card for the wording.

## Approval log

- 2026-11-14T22:28:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
