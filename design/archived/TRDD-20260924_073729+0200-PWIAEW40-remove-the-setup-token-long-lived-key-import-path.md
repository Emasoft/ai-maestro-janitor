---
trdd-id: PWIAEW40
title: Remove the setup-token long-lived key import path
column: complete
created: 2026-09-24T07:37:29+0200
updated: 2026-10-05T11:04:14+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T07:37:29+0200
status: archived
implementation-commits: [20216dd7]
---

# Remove the setup-token long-lived key import path

The owner said "the long lived tokens are not working, so you can remove that code" (2026-09-24). This supersedes TRDD-BMITQ2MN (the setup-token CSV importer), whose ai-maestro half is now moot; the incident that prompted the decision is TRDD-K0PMVRN6. Scope: to be inventoried (files, symbols, skills, tests, docs) before any deletion; RULE 0 applies — commit before delete.

## Approval log

- 2026-09-24T07:37:29+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24 — identity correction: issuer fields changed from the host username (a trddgrep default) to the session id; original in git history.
- 2026-10-05T11:04:14+0200 — COMPLETE by main-agent@ai-maestro-janitor. landed in 20216dd7, published in v3.7.0, full suite green in the 2026-10-05 dry-run.

## Derived tasks

- Rewrite skills/janitor-refresh-cc-logins/SKILL.md (and any sibling skill or command that sends the owner to the setup-token mint) to the owner-ratified browser procedure recorded in PROJECT memory oauth-rotation-renew-reauth-operations (atom ATOM-VH28-30GK); keep the no-refresh-slot 403 tolerance (is_setup_token_slot) until no importer exists on either the janitor or the ai-maestro side.

## Implementation

2026-09-29 LANDED (commit 20216dd7, lean-worker ac682bb5, main-verified): importer + capture-token script + import skill + tests removed (RULE 0 verified — all committed history first; safe-delete to .trashcan, recoverable); refresh-cc-logins rewritten to ATOM-VH28-30GK browser procedure (2950/5000 cap, redaction rules kept); is_setup_token_slot 403 tolerance KEPT in rotator.py (2 refs — slots without refresh still exist); auto-manage-oauth-on stale sentence reworded; sweep clean (one rotator.py docstring mention left for the ZKXQXHBI worker's file ownership). Verification: rotator imports, no dangling refs in plugin.json/commands/scripts, 332+309 green, ruff clean. Known residue for a later batch: on-session-start.py:1334 comment still says 'expiring setup-token' (stale comment only, no behavior).
2026-10-05 — CLOSE CHECK STOPPED at 3d. 3a ok (min-approval none, eht absent, mandated-by none); 3b ok (20216dd7 is in v3.7.0); 3c ok (import_oauth_tokens 0 hits, slot_capture_token 1 hit in a rotator docstring only); 3d FAILED: the card names no test files behind '332+309 green' (the commit removed tests/test_slot_capture_token.py), so no re-run was possible. Card stays in testing.
2026-10-05 — CLOSING. Verified on 2026-10-05: 20216dd7 is in v3.7.0; the removed import function has 0 hits under scripts and the other removed name survives only in one rotator docstring (residue, no behaviour); the card names no test files, so the evidence is the full test suite, which contains every test and passed (17951 passed, 2 skipped) in the publish dry-run on commit c576a7ad. Approver: this session's own agent; this is self-approval, recorded as such, on the rule that outside the multi-agent harness the session's agent approves a card whose required approval is none.

## Acceptance

- [x] The setup-token import function is absent from scripts (grep count 0 on 2026-10-05).
- [x] The removal commit 20216dd7 is contained in the release tag v3.7.0.
- [x] The full test suite passed with the removal in place (17951 passed, 2 skipped, publish dry-run on c576a7ad, 2026-10-05).
