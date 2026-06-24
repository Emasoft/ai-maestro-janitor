---
trdd-id: J9TM3WQK
title: Cascade — dead-refresh + live-cookie alternate must RENEW_COOKIE before REAUTH_NUDGE
column: dev
created: 2026-06-24T22:05:42+0200
updated: 2026-06-24T22:05:42+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 1
severity: HIGH
effort: S
labels: [oauth, rotator, cascade, renew-cookie, immortality, regression]
task-type: bugfix
parent-trdd: TRDD-fe45babc
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-J9TM3WQK — dead-refresh + live-cookie ⇒ RENEW_COOKIE (not REAUTH_NUDGE)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

### Status: dev — fix specified + the leg validated live; implementing TDD-first
- **THE BUG** (regression from TRDD-HJGR4I5W / #235): `cascade.classify` escalates a
  **dead-but-present** refresh token (`has_refresh ∧ refresh_failures ≥ max`)
  **straight to `REAUTH_NUDGE`** — it never checks `has_session_cookie`. The
  `RENEW_COOKIE` leg (`if acct.has_session_cookie`) is only reachable when
  `has_refresh` is False. So an alternate whose refresh died but whose claude.ai
  cookie is ALIVE is sent to a HUMAN re-login when it could auto-recover.
- **REAL-WORLD SYMPTOM**: fmuaddib had `has_refresh=true`, `refresh_failures=428`,
  `has_session_cookie=True` → cascade nudged REAUTH every tick; the user "had to
  rotate the auth manually" repeatedly. The auto-recovery (RENEW_COOKIE) was never
  even triggered — `_bootstrap_seeded_slots` gates on `_bootstrap_eligible`, which
  delegates to classify → never returns RENEW_COOKIE for a has_refresh slot.
- **PROVEN the leg WORKS** (2026-06-24, first live validation on this machine):
  `slot_capture_browser.py fmuaddib@gmail.com` drove the seeded Chrome, the live
  cookie authenticated the consent page, clicked Authorize, minted a fresh
  refresh-bearing slot — hands-free. (Logs: reports_dev/oauth/capture-fmuaddib-*.log;
  agent-browser driver also independently validated, reports_dev/oauth/agent-browser-modelA2-*.log.)
  So routing dead-refresh+cookie to RENEW_COOKIE is sound — the leg it lands on is real.
- **THE FIX (2 code edits + 1 docstring):**
  1. `cascade.classify`: in the dead-refresh branch, if `has_session_cookie` →
     `RENEW_COOKIE`; only no-cookie → `REAUTH_NUDGE`. Surgical — one `if` before the
     existing REAUTH return. No other behavior change (the no-cookie dead-refresh case
     is unchanged).
  2. `rotator._bootstrap_eligible`: add `refresh_failures` (+ `max_refresh_failures`)
     keyword params, pass them into the AccountState it builds — so a dead-refresh
     +cookie slot becomes bootstrap-eligible (today it builds refresh_failures=0 →
     classify → HEALTHY → not eligible).
  3. `rotator._bootstrap_seeded_slots`: read `refresh_failures` from the slot's
     state-index meta and pass it to `_bootstrap_eligible`.
- **NO re-capture loop**: a successful capture REPLACES the slot meta dict (omits
  `refresh_failures`), so post-capture the slot reads refresh_failures=0 → classify →
  HEALTHY/RENEW_REFRESH, never RENEW_COOKIE again. (Verified in
  `slot_capture_browser.capture()`: `st.setdefault("slots",{})[email] = {captured_at,
  fp, expires_at, via}` — no refresh_failures key.)
- **NEXT**: failing unit tests (test_cascade.py + test_oauth_bootstrap.py) → implement
  the 3 edits → run both suites → ruff + pyright → commit → publish (own release).

### Why REAUTH-before-cookie is wrong (the cascade contract)
The point of ROTATE→RENEW→REAUTH (TRDD-dfc0959a): REAUTH (a human re-login) is the
LAST resort, reached only when BOTH the refresh AND the cookie are dead. A dead refresh
with a LIVE cookie must fall to RENEW_COOKIE (auto-mint a fresh refresh from the cookie).
HJGR4I5W correctly stopped looping RENEW_REFRESH on a dead token but routed it to the
human instead of the cookie rung — jumping a cascade layer.

### Load-bearing facts
- `cascade.DEFAULT_MAX_REFRESH_FAILURES = 3`; `rotator.MAX_REFRESH_FAILURES` (line 302)
  = env-overridable `ROTATOR_MAX_REFRESH_FAILURES`, default = the cascade default.
- `AccountState` carries `refresh_failures` (default 0) + `has_session_cookie`.
- `_bootstrap_eligible(has_refresh, has_session_key)` (rotator.py ~1381) delegates to
  `classify(...) is RENEW_COOKIE`. `_bootstrap_seeded_slots` (~1571) calls it per slot.

### Scope guards / non-goals
- Surgical: the no-cookie dead-refresh case STILL returns REAUTH_NUDGE (unchanged).
- `_bootstrap_eligible`'s existing truth-table callers keep working: the new params
  default to (0, MAX_REFRESH_FAILURES), so a no-refresh slot classifies exactly as before.
- Routing fix ONLY. The capture ACTUATOR (slot_capture_browser today; an optional
  agent-browser driver next — separate TRDD) is orthogonal and unchanged here.

## Why this exists
The recurring "I had to rotate the auth manually" pain: the rotator HAD a working
auto-recovery (RENEW_COOKIE, now proven live) but the cascade never routed a
dead-refresh + live-cookie alternate to it. This makes the proven leg actually FIRE —
turning a human-nudge into a hands-free recovery.
