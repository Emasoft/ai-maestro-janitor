---
trdd-id: 1IKF0A6D
title: cmd_auto excludes a locally-expired alternate without a refresh-retry — close the documented RENEW-before-rotate residual
column: dev
created: 2026-06-24T16:45:28+0200
updated: 2026-06-24T16:45:28+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 1
severity: HIGH
effort: S
labels: [oauth-rotator, rotate, renew, deadlock, immortality]
task-type: bugfix
parent-trdd: TRDD-32acd15f
relevant-rules: []
release-via: publish
test-requirements: [unit, lint]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-1IKF0A6D — cmd_auto: refresh-retry a locally-expired alternate before excluding it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

### The bug (the documented RENEW residual, lesson [^2] of `oauth-rotation-renew-reauth.md`)
`scripts/oauth_rotator/rotator.py::cmd_auto` builds the alternate-candidate list. At the
top of the per-slot loop (rotator.py ~line 1133) it has:

```python
if _blob_locally_expired(b):
    continue  # never rotate ONTO a dead/dying token
```

A slot whose ACCESS token is locally expired is **dropped outright — without ever
attempting a refresh**, even when it carries a valid `refreshToken` and the account is
perfectly usable. The refresh-on-err safety net just below (the 2026-06-11 / 2026-06-20
deadlock fixes) only catches slots that REACH the usage probe; a locally-expired slot
never gets there. This is the exact deadlock CLASS — a rescuable alternate excluded
because its access token lapsed between ticks (a keepalive gap: the daemon was down, a
tick was skipped, or a transient refresh failure). The memory note flags it verbatim:
"Residual: a slot excluded EARLIER by the locally-expired guard is not yet refresh-retried."

### The fix
At the locally-expired guard: when the slot has a `refreshToken` AND the network is up,
**refresh-retry-then-heal it before excluding** — mirroring the refresh-on-err net — so a
recovered slot rejoins the candidate flow. If it has no refresh grant, the API is
unreachable (status 0 — a refresh HTTP call would also fail), the refresh returns None, or
the refreshed token is STILL locally expired, it is excluded exactly as before (never
rotate onto a still-dead token).

To keep ONE source of truth, the refresh+keychain-heal+index-update kernel shared by the
locally-expired guard and the existing refresh-on-err block is extracted into
`_refresh_and_heal_slot(email, blob, state) -> (fresh|None, index_changed)`. The existing
block's surrounding degraded-fallback logic (the 2026-06-20 fix) is preserved BYTE-FOR-
BYTE at the call site; only the refresh+write+meta kernel moves into the helper. The full
existing refresh-on-err test set (6+ tests) is the regression net.

### TDD
- NEW `test_cmd_auto_refreshes_locally_expired_alternate_with_refresh_token` — expired
  alt + refresh succeeds → rotated onto the FRESH token + slot healed (FAILS pre-fix).
- NEW `test_cmd_auto_excludes_locally_expired_alternate_when_refresh_fails` — expired alt +
  refresh returns None → excluded (no switch) (safety preserved).
- UPDATED `test_cmd_auto_never_rotates_onto_expired_alternate` — sharpened to the
  no-refresh-token case (`refresh=None`): excluded AND `refresh_oauth_token` never called
  (the test previously left the real network call uncontrolled and only passed by accident).

### Scope guard / non-goals
SCHEDULER-class, additive, fail-soft. Does NOT touch `_keepalive_refresh`, `reauth.py`,
the cascade SSOT, or the switch thresholds. fmuaddib's specific deadness is NOT in scope
(its REFRESH token is dead → correct reauth-nudge; this fix is for slots whose ACCESS
token lapsed but whose refresh grant still works).

### Ship
TDD green + ruff clean → `publish.py` (the USER is present; the running daemon auto-rolls
to the published version — a fix in source is not a fix in production until published,
lesson [^2]).

## Why now
The deep-night hold over-deferred this. With a working LIVE token there was always room to
complete it; the residual is the documented unfinished hardening of the ROTATE/RENEW
robustness and directly reduces freeze exposure (LIVE observed at 7d=85% with the only
alternate in reauth-nudge — every robustness gap that drops a rescuable alternate matters).
