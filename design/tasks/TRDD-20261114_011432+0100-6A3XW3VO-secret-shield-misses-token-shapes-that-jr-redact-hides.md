---
trdd-id: 6A3XW3VO
title: Secret shield misses token shapes that jr-redact hides
column: dev
status: tasked
created: 2026-11-14T01:14:32+0100
updated: 2026-11-14T03:03:50+0100
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
implementation-commits: [6e073334, ad553852, 4fcec14c, 86c6d118, 3dcd712b, 96c29c78]
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

CURRENT (2026-11-14) — GitHub family (gap 2) landed in 6e073334, pinned and documented in ad553852 and b29d74bc; Stripe family landed in 4fcec14c (floor 16, no trailing \b); OpenAI family landed next (plain form: sk- plus 20 or more of [A-Za-z0-9_-], no trailing \b, no digit lookahead); jwt family landed next as a separate rule jwtWide applied as the last pass of redact() (a TOKENS position leaked value tails in 10962 of 39072 contextual inputs) (8-char segments, any second segment, linear; a single replacing rule could not be a superset); implementation-commits lists rule and test commits, not docs-only commits. Earlier: evidence gathered (report path above, gitignored, worker-run). Recommended (evidence: synthetic samples, file corpora), gated on the differential test in NEXT ACTION: WIDEN 1-4; KNOWN-MISSES entry for 5 (kind c, header language kept exact on purpose, rules/key-material.ts:5-14) and for 6c (port-then-path shape, kind a, existing test patterns.test.ts:249) and 6d (backtick, double quote, [ in userinfo, kind c); single quote goes to backlog TRDD-Q6LPJTPO; 6b needs no action (jr bug, jr over-hide, placeholder exemption).
Candidate rules (from the report section 7): openai (landed, see CURRENT) rules/ai.ts:8 -> \b(sk-[A-Za-z0-9_-]{20,}) (plain form chosen; one kebab-slug match in 100 MB of third-party text, over-hide pinned); github (landed 6e073334) rules/code-hosts.ts:5-6 -> \b(gh[pousr]_[A-Za-z0-9]{30,255}) and \b(github_pat_[A-Za-z0-9_]{20,255}) without trailing \b; jwt (landed, see CURRENT); stripe (landed, see CURRENT) rules/messaging-payments.ts:7 -> \b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}) without trailing \b. Runtime on 512 KB unchanged within noise; suite 655/656, the one failure is the TOKEN_ORDER source pin. The lookahead alternative (?=[A-Za-z0-9_-]*\d) was rejected: it fails the differential, because a no-digit 48 body the old rule hid would become visible.
Bounds: samples are synthetic shapes from the catalog regexes; false hits measured on files (repo text 40 MB, third-party text 100 MB), not live tool output; function level only.
KNOWN-LIMITS (accepted 2026-11-14; behaviour from 6e073334, pinned by ad553852): a gh*_/github_pat_ body over 255 characters is hidden only up to 255 and the tail stays visible — no GitHub token format is that long (classic 36, fine-grained about 82); a classic token stops at an underscore, correct because classic tokens are letters and digits only. Both pinned by tests in patterns.test.ts. jwt family (accepted 2026-11-14): a JWT header with a space after the brace (first segment eyAi) is not hidden; the third segment takes trailing - and _ characters; with jwtWide as the last pass, a jr-shape JWT inside an Authorization header or an assignment keeps the bearer-token or assignment kind, and gets the jwt kind only where no other rule hid it.
FOLLOW-UP (2026-11-14): the stripeWebhookSecret underscore gap found in the 4fcec14c review is out of this card's scope and tracked on TRDD-RSI2OZ0B. KNOWN-MISS candidate (2026-11-14): a JWT whose header has a space after the opening brace (first segment eyAi) is hidden by neither jwt rule; widening the first segment beyond eyJ needs its own measured change.
NEXT ACTION: the KNOWN-MISSES entries in a separate commit (5, 6c, 6d), each with its matching test title for tests/test_secret_shield_known_misses.py, keeping the leading-\b count in known-misses.test.ts; then close this card. Watch the ubs pre-commit run on rules/*.ts (whole process tree); if one runs away, stop and report, do not add ignore lines.
