---
trdd-id: 6A3XW3VO
title: Secret shield misses token shapes that jr-redact hides
column: complete
status: archived
created: 2026-11-14T01:14:32+0100
updated: 2026-11-14T03:28:04+0100
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
implementation-commits: [6e073334, ad553852, 4fcec14c, 86c6d118, 3dcd712b, 96c29c78, c5d04955, 9b2dea04, 019c355a, d5019802]
---

# Secret shield misses token shapes that jr-redact hides

## Approval log

- 2026-11-14T01:14:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-14T03:28:04+0100 — COMPLETE by main-agent@ai-maestro-janitor. all gaps closed per the Done-when criterion; see STATE DONE line.

## Why

TRDD-J0TBHZ15 measured jr-redact 0.1.0 (SECRET_RULES, 10 rules) against the shield's redact() at function level, on 931 shield-test strings and 4,932 synthesized catalog samples (2026-11-14, worker run, raw data in reports_dev, not tracked). jr-redact hides 5 test strings and 75 catalog samples that the shield leaves visible. Gaps, causes inferred from rule shapes, not run per case: (1) openai-key: jr hides any sk- plus 20+ of [A-Za-z0-9_-]; the shield only known prefixes and sk- plus exactly 48 alnum (31 samples). (2) github-token: jr needs 30+ body (github_pat_ 20+), the shield 36+ (22+) (15). (3) jwt: jr eyJ.<8+>.<8+>, the shield eyJ.eyJ. with 10+ per segment (15). (4) stripe-key: jr 16+, the shield 20+ (7). (5) private-key: 3 catalog samples fully visible, 1 test string partly; reason not investigated. (6) URL password: 5 short or odd shapes; jr also hides a ${VAR} placeholder the shield exempts on purpose. (7) If both mods stay enabled, jr rewrites [JANITOR-REDACTED:url-password] into [REDACTED:password] (3 of 35 marked inputs). (8), not a jr gap: a JWT whose header has a space after the opening brace (first segment eyAi) is hidden by neither jr-redact nor the shield; found 2026-11-14 while measuring the jwt family; a documented JSON form, so by the KNOWN-MISSES admission rule it is backlog on TRDD-Q6LPJTPO.
Bound of this evidence: catalog samples were synthesized from the catalog regexes (the worker's reading of 'catalog oracle samples'); 171 catalog keys were not sampled and 52 regexes did not compile, so jr-only gaps among those keys are unknown. Function level only: live hook order and jr's skip of error results were not measured.

## Done when

Each gap (1) to (6) and (8) is either closed by a shield rule change with a test that hides the sample shape, or recorded as a deliberate KNOWN-MISSES entry with its reason (for example the placeholder exemption, or a length floor kept to avoid false hits); exactly these three dispositions recorded in STATE also count: 6b needs no action; the single quote and gap (8) went to TRDD-Q6LPJTPO. This card is terminal on gaps (1) to (6) and (8) alone. Gap (7), jr rewriting shield markers while both run, belongs to TRDD-2V7OAUPE, which disables jr-redact; tying it here would make the two cards block each other.
- [x] Gaps (1) to (4) closed by shield rule changes with differential tests that hide the sample shapes (6e073334, 4fcec14c, 3dcd712b, c5d04955; tests ad553852, 86c6d118, 96c29c78, 9b2dea04).
- [x] Gap (5), 6c and 6d recorded as KNOWN-MISSES entries with matching tests (019c355a, d5019802).
- [x] 6b needs no action; the single quote and gap (8) went to backlog on TRDD-Q6LPJTPO (d5019802).
- [x] Suite 807 pass / 0 fail and pytest 38 passed at d5019802.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

CURRENT (2026-11-14) — DONE (2026-11-14): gaps (1)-(4) closed by rule changes (6e073334, 4fcec14c, 3dcd712b, c5d04955/9b2dea04), (5), 6c and 6d by KNOWN-MISSES entries (019c355a), 6b by no action, the single quote and gap (8) by backlog on TRDD-Q6LPJTPO (d5019802); gap (7) belongs to TRDD-2V7OAUPE. GitHub family (gap 2) landed in 6e073334, pinned and documented in ad553852 and b29d74bc; Stripe family landed in 4fcec14c (floor 16, no trailing \b); OpenAI family landed next (plain form: sk- plus 20 or more of [A-Za-z0-9_-], no trailing \b, no digit lookahead); jwt family landed in c5d04955 as a separate rule jwtWide (8-character segments, any second segment, linear), applied as the last pass of redact() because a TOKENS position leaked value tails in 10962 of 39072 contextual inputs, its last-pass position pinned by 9b2dea04; a single replacing rule could not be a superset; kinds: a JWT inside a header or assignment keeps the bearer-token or assignment kind, jwt only where no other rule hid it; implementation-commits lists rule commits and the commits that add, change or remove their tests. Earlier: evidence gathered (report path above, gitignored, worker-run). Recommended (evidence: synthetic samples, file corpora), each family gated on a differential test (done): WIDEN 1-4; KNOWN-MISSES entry for 5 (kind c, header language kept exact on purpose, rules/key-material.ts:5-14) and for 6c (port-then-path shape, kind a, existing test patterns.test.ts:249) and 6d (backtick, double quote, [ in userinfo, kind c); single quote goes to backlog TRDD-Q6LPJTPO; 6b needs no action (jr bug, jr over-hide, placeholder exemption).
Candidate rules (from the report section 7): openai (landed, see CURRENT) rules/ai.ts:8 -> \b(sk-[A-Za-z0-9_-]{20,}) (plain form chosen; one kebab-slug match in 100 MB of third-party text, over-hide pinned); github (landed 6e073334) rules/code-hosts.ts:5-6 -> \b(gh[pousr]_[A-Za-z0-9]{30,255}) and \b(github_pat_[A-Za-z0-9_]{20,255}) without trailing \b; jwt (landed, see CURRENT); stripe (landed, see CURRENT) rules/messaging-payments.ts:7 -> \b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}) without trailing \b. Runtime on 512 KB unchanged within noise; suite 655/656, the one failure is the TOKEN_ORDER source pin. The lookahead alternative (?=[A-Za-z0-9_-]*\d) was rejected: it fails the differential, because a no-digit 48 body the old rule hid would become visible.
Bounds: samples are synthetic shapes from the catalog regexes; false hits measured on files (repo text 40 MB, third-party text 100 MB), not live tool output; function level only.
KNOWN-LIMITS (accepted 2026-11-14; behaviour from 6e073334, pinned by ad553852): a gh*_/github_pat_ body over 255 characters is hidden only up to 255 and the tail stays visible — no GitHub token format is that long (classic 36, fine-grained about 82); a classic token stops at an underscore, correct because classic tokens are letters and digits only. Both pinned by tests in patterns.test.ts. jwt family (accepted 2026-11-14): the third segment takes trailing - and _ characters.
FOLLOW-UP (2026-11-14): the stripeWebhookSecret underscore gap found in the 4fcec14c review is out of this card's scope and tracked on TRDD-RSI2OZ0B. Gap 8 (2026-11-14): a JWT whose header has a space after the opening brace (first segment eyAi) is hidden by neither jwt rule; widening the first segment beyond eyJ needs its own measured change; backlog on TRDD-Q6LPJTPO (documented form, admission rule).
NEXT ACTION: close this card (KNOWN-MISSES entries for 5, 6c, 6d landed in 019c355a; gap 8 moved to TRDD-Q6LPJTPO).
