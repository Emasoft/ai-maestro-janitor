---
trdd-id: ZKXQXHBI
title: The janitor daemon reads the live credential's primary item behind its own latch
column: todo
created: 2026-09-24T11:21:18+0200
updated: 2026-09-29T08:02:06+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:18+0200
---

# The janitor daemon reads the live credential's primary item behind its own latch

Release 1 of TRDD-RAEGS1D5; design on TRDD-4XND73XD (decision 2 of TRDD-WZKFSQ2N, term M9). Today the daemon skips the primary read by policy (JANITOR_ROTATOR_HEADLESS) and works from the -livebak mirror; the leading, unverified hypothesis (H1 on TRDD-K0PMVRN6) is that this is why the live account's slot twin goes stale. Change: one bounded read per tick; a separate primary-read latch (a denial trips it at once, timeouts need 3 in a row, cooldown 600 s); a refusal falls back to the mirror WITHOUT tripping the shared keychain latch (errSecInteractionNotAllowed -25308), logs once per state change, and never retries within the tick. Prerequisite: test the read from the daemon's LaunchAgent context first (the 2026-09-24 test ran from an interactive session). Acceptance: a test per latch rule that fails without the change; one real daemon tick logs a primary read.

## Approval log

- 2026-09-24T11:21:18+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

The prerequisite read test must itself be safe: one bounded read with a timeout and no prompt allowed (may_prompt=False), outside the shared keychain-latch path, from the daemon's own context. A careless test can raise a dialog or trip the machine-wide denied latch, which stops rotation.
Logging that becomes live once the daemon reads the primary: (1) the F1 "primary live credential UNREADABLE" line must say whether the read was skipped by policy or refused; (2) since 88b10297, cmd_capture's unresolved-account branch and the F5 UNRESOLVABLE line in _reconcile_live_email can both fire every tick during a /roles outage: make both durable rotator.log lines, deduplicated per fingerprint. Two /roles calls per tick (capture plus reconcile) during such an outage are the accepted cost.

## Implementation log

2026-09-29: implemented in commit 3c48d054 — latch (denial-at-once, 3-timeout threshold, 600 s cooldown, latch FILE for cross-tick streak) in rotator._read_primary_macos_keychain + helpers; run_security latch_denial knob (safe_storage); per-tick read memo invalidated by write_live_blob; daemon no longer forces JANITOR_ROTATOR_HEADLESS (stays an operator lever); F1 capture line names skip-policy vs latch-refusal; capture+F5 UNRESOLVABLE lines durable and deduplicated per fp. Gates: pytest 194 passed (both touched files), ruff clean, mypy clean, pyright 0 errors. OPEN: the prerequisite LaunchAgent-context read probe (the 2026-09-24 test ran interactive) still to run before this ships in a publish; a test per latch rule exists (7 new tests).
2026-09-29 LANDED+MAIN-VERIFIED: 3c48d054 (latch implementation; file set: daemon.py 18, rotator.py 243, safe_storage.py 15, test_oauth_rotator.py 268, test_safe_storage.py 32) + 2fbdc17d (this card's log). Main's independent verification: 194 tests pass on the two touched suites (3.81s), ruff clean on all 5 files, mypy clean on rotator.py, pyright 0/0/0 on rotator.py. The mid-flight pyright diagnostics the session saw (ModuleType attribute assignments in tests, _slot_keychain_delete unused) all clear at HEAD — they were working-set noise, not landed-state findings. OPEN before publish: the LaunchAgent-context read probe (prerequisite on this card) — the code fail-safes correctly either way (unreadable read falls back to the mirror exactly as the old HEADLESS skip did).
2026-09-29 ADVERSARIAL REVIEW of 3c48d054 (fork): HOLDS, no REOPEN. Findings disposition: [1 MAJOR latch-file RMW atomicity] VERIFIED NON-ISSUE by main reading rotator.py:674-681 — _primary_read_latch_write already uses tmp+os.replace with pid-suffixed tmp; parse failure returns {} (streak reset = accepted race, one tick late, matching the reviewer's own worst case). [2 MAJOR verify runtime-written file content] PARTIALLY VERIFIED: rotator.log SECURITY contract pre-dates this change (rotator.py:~330 — decision strings carry emails+fps, NEVER token values; file under CLAUDE_PLUGIN_DATA, gitignored, user-only; size-bounded via rename rotation at _LOG_MAX_BYTES). The NEW content is the F1 reason line + deduped unresolved lines, same trust boundary. Item names/emails are the accepted shape; token material would be a NEW violation — nothing in the diff writes tokens. Bounded growth confirmed (dedupe per (branch,fp) per tick, rotator.py:368-377; log rotation bounds the file). [3 MAJOR verify tests touch real state] VERIFIED NON-ISSUE: autouse _isolate_rotator_root (test file :42-62) redirects ROOT+LOG_FILE+resets _PRIMARY_READ_MEMO for EVERY test; latch path resolves at call time off ROOT (:659-661); latch-file tests all run under the fixture. [4 MAJOR LaunchAgent probe] AGREED, stays the card's open publish-gate item (already recorded). [5 LOW -25308 conflation] accepted as designed. [6 LOW probe-vs-memo] sound (fresh subprocess per tick); one-line comment at memo site noted as optional. [7 LOW two unheadlined effects] daemon.py diff read in full by main: the un-forcing is confined to task_oauth_rotator_tick's env-set; HEADLESS remains an operator lever, capture/beacon suppression paths keep honoring it; durable /roles-outage file is rotator.log itself (rotation-bounded), not a new file. [8 LOW constants] accepted, tunable, fail-safe direction mirror-only. Q1 answer recorded: re-enables a read disabled by FIX B2 against an unverified H1 — justified because fail-safe direction is byte-identical to the old skip, with finding 4's probe as the hard publish gate.
2026-09-29 DISPOSITION-REVIEW (fork on 566db40c+faa01ca5): HOLDS. CURE discharged by completion of the evidence (option a): pyright run on tests/test_oauth_rotator.py = 0 errors/0 warnings — the 'mid-flight diagnostics all clear at HEAD' sentence is now true as written, evidence set complete (rotator.py AND the test file both 0/0/0). LOW-2 accepted: the /roles-outage line-shape check is DEFERRED to the latch's first real trip in the field — residual named here. LOW-3 accepted: one-line race note at rotator.py:_primary_read_latch_state (parse failure → {} — accepted: streak regrows, latch trips one tick late) folded into the next code touch of that function; recorded here so it is not lost. LaunchAgent probe remains the publish gate.
