---
trdd-id: 6A3XW3VO
title: Secret shield misses token shapes that jr-redact hides
column: todo
status: tasked
created: 2026-11-14T01:14:32+0100
updated: 2026-11-14T01:44:24+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T01:14:32+0100
implementation-commits: [6e073334]
---

# Secret shield misses token shapes that jr-redact hides

## Approval log

- 2026-11-14T01:14:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Why

TRDD-J0TBHZ15 measured jr-redact 0.1.0 (SECRET_RULES, 10 rules) against the shield's redact() at function level, on 931 shield-test strings and 4,932 synthesized catalog samples (2026-11-14, worker run, raw data in reports_dev, not tracked). jr-redact hides 5 test strings and 75 catalog samples that the shield leaves visible. Gaps, causes inferred from rule shapes, not run per case: (1) openai-key: jr hides any sk- plus 20+ of [A-Za-z0-9_-]; the shield only known prefixes and sk- plus exactly 48 alnum (31 samples). (2) github-token: jr needs 30+ body (github_pat_ 20+), the shield 36+ (22+) (15). (3) jwt: jr eyJ.<8+>.<8+>, the shield eyJ.eyJ. with 10+ per segment (15). (4) stripe-key: jr 16+, the shield 20+ (7). (5) private-key: 3 catalog samples fully visible, 1 test string partly; reason not investigated. (6) URL password: 5 short or odd shapes; jr also hides a ${VAR} placeholder the shield exempts on purpose. (7) If both mods stay enabled, jr rewrites [JANITOR-REDACTED:url-password] into [REDACTED:password] (3 of 35 marked inputs).
Bound of this evidence: catalog samples were synthesized from the catalog regexes (the worker's reading of 'catalog oracle samples'); 171 catalog keys were not sampled and 52 regexes did not compile, so jr-only gaps among those keys are unknown. Function level only: live hook order and jr's skip of error results were not measured.

## Done when

Each gap (1) to (6) is either closed by a shield rule change with a test that hides the sample shape, or recorded as a deliberate KNOWN-MISSES entry with its reason (for example the placeholder exemption, or a length floor kept to avoid false hits). This card is terminal on gaps (1) to (6) alone. Gap (7), jr rewriting shield markers while both run, belongs to TRDD-2V7OAUPE, which disables jr-redact; tying it here would make the two cards block each other.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

CURRENT (2026-11-14) — evidence gathered (report path above, gitignored, worker-run). Recommended (evidence: synthetic samples, file corpora), gated on the differential test in NEXT ACTION: WIDEN 1-4; KNOWN-MISSES entry for 5 (kind c, header language kept exact on purpose, rules/key-material.ts:5-14) and for 6c (port-then-path shape, kind a, existing test patterns.test.ts:249) and 6d (backtick, double quote, [ in userinfo, kind c); single quote goes to backlog TRDD-Q6LPJTPO; 6b needs no action (jr bug, jr over-hide, placeholder exemption).
Candidate rules (from the report section 7): openai rules/ai.ts:8 -> \b(sk-[A-Za-z0-9_-]{20,}) (plain form, superset of today; one kebab-slug false hit in 100 MB of third-party text, to be pinned as a documented over-hide test); github rules/code-hosts.ts:5-6 -> \b(gh[pousr]_[A-Za-z0-9]{30,255}) and \b(github_pat_[A-Za-z0-9_]{20,255}) without trailing \b; jwt rules/key-material.ts:15 -> \b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}); stripe rules/messaging-payments.ts:7 -> \b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})\b. Runtime on 512 KB unchanged within noise; suite 655/656, the one failure is the TOKEN_ORDER source pin. Alternative for openai: the same with lookahead (?=[A-Za-z0-9_-]*\d), 31/31 hidden, 5 new third-party hits instead of 6; choose by the differential and false-hit test.
Bounds: samples are synthetic shapes from the catalog regexes; false hits measured on files (repo text 40 MB, third-party text 100 MB), not live tool output; function level only.
NEXT ACTION: one rule family per commit (rule, TOKEN_ORDER pin at patterns.test.ts:1410-1439, positive tests, plus the jwt payload case with a space after the opening brace); gate each on a differential test old vs new over the suite and catalog inputs (nothing hidden today becomes visible); re-measure old and new jwt at 256 KB before the jwt change (see the jwt timing card); then the KNOWN-MISSES entries in a separate commit, each with its matching test title for tests/test_secret_shield_known_misses.py, keeping the leading-\b count in known-misses.test.ts. Watch the ubs pre-commit run on rules/*.ts (whole process tree); if one runs away, stop and report, do not add ignore lines.
