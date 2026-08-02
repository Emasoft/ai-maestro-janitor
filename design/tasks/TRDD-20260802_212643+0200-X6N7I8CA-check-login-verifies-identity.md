---
trdd-id: X6N7I8CA
title: check-login verifies WHOSE session the profile holds, not just that one exists
column: todo
created: 2026-08-02T21:26:43+0200
updated: 2026-08-02T21:26:43+0200
current-owner: janitor-session
task-type: bugfix
severity: high
scope: project
release-via: publish
external-refs: [179]
implementation-commits: []
---

# `check-login.sh` ✓s a profile signed into a DIFFERENT account (janitor#179)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Filed from the peer report janitor#179 (the ai-maestro Claude), claim
VERIFIED first-hand 2026-08-02 before filing: in `scripts/oauth_rotator/check-login.sh`
the `email` argument is a DISPLAY LABEL only — the check is "a persistent claude.ai
`sessionKey` cookie exists and is unexpired" (or ≥5 persistent cookies), never WHOSE
session it is. A profile signed into the wrong account passes with a ✓ and an expiry
date; `lifetime-status.sh:90` inherits the same blindness (same `sessionKey` existence
shape) and then reports "nothing to do" over a dead slot — advice INVERTED exactly when
action is needed.

## The fix direction (peer's evidence shows the right oracle already exists)

`slot_capture_browser.py` already resolves the profile's ACTUAL account and files under
it ("profile is logged in as X, not Y — filing under the ACTUAL account"). The identity
oracle exists; the shell checks just don't consult it. Options, cheapest first:
1. Cross-check the profile's identity WITHOUT a browser: the rotator records per-account
   state (`state.json` slots, bootstrap logs, cookie-jar snapshots keyed by email) — if a
   cheap on-disk identity artifact exists for the profile, compare it.
2. Otherwise surface honesty: when identity CANNOT be verified offline, the ✓ line must
   say "a session is saved (account unverified — capture will resolve the true owner)"
   instead of asserting `email:` logged in. Never a confident ✓ for an unverified claim.
3. `lifetime-status.sh` must treat an identity-unverified profile as UNKNOWN, not
   healthy — "nothing to do" may only follow a verified-identity ✓.

## Verification

- A profile logged into account B while checked as account A: check-login must NOT print
  the plain ✓-as-A line; lifetime-status must not report "nothing to do" over it.
- The true-positive path (profile really is A) keeps its ✓.

## Notes and lessons learned
