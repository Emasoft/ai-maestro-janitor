---
trdd-id: 5EUYV08H
title: oauth detectors resolve a DIFFERENT rotator home than the daemon — legacy-first vs canonical-first — so the REAUTH login-nudge never reaches the user
column: complete
created: 2026-06-24T17:35:02+0200
updated: 2026-06-24T17:39:12+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 0
severity: HIGH
effort: S
labels: [oauth-rotator, reauth, detector, state-source-divergence, ssot, immortality]
task-type: bugfix
parent-trdd: TRDD-32acd15f
relevant-rules: []
release-via: publish
test-requirements: [unit, lint]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-5EUYV08H — the REAUTH login-nudge never reaches the user (detector reads stale legacy state)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

### ✅ IMPLEMENTED + PROVEN ON REAL STATE (2026-06-24 17:39) — ships next publish.py
Added `rotator.configured_rotator_home()` (SSOT); both `oauth-login-needed._rotator_home` and
`oauth-cookie-reminder._rotator_home` now delegate to it (one-liners). **PROOF on the live
machine**: the fixed detector now resolves the CANONICAL home and emits
`[oauth-login-needed] 1 account(s) need a one-time login: <account-fmuaddib> — run
~/.claude/account-rotator/open-login.sh <email> …` — where it was SILENT before (read stale legacy,
fmuaddib looked healthy). **89 affected tests pass** (4 new resolver unit tests + the full
oauth-login-needed/oauth-cookie-reminder/rotator suites), **ruff clean**. The 4 new tests cover:
both-present→canonical (the regression), only-legacy→legacy, env-override-wins, none→None. NEXT:
publish; the running daemon auto-rolls to it (lesson: source≠production until published).

### The bug (root-caused live 2026-06-24 while verifying the triad)
The daemon logs `cascade: reauth-nudge=<account-fmuaddib>` every 60s, yet the USER-FACING
`oauth-login-needed` detector emits NOTHING and never creates its seen-file — so the user is
never told to re-login. Root cause: the detector and the daemon resolve DIFFERENT rotator homes.

- Daemon `rotator._rotator_root()` order: **canonical (`$CLAUDE_PLUGIN_DATA/.../oauth-rotator`)
  first**, legacy (`~/.claude/account-rotator`) fallback.
- Detector `_rotator_home()` order (shared by `oauth-login-needed` + `oauth-cookie-reminder`):
  **legacy FIRST**, then canonical.

On a MIGRATED install BOTH `state.json` exist (`migrate_root_to_canonical` keeps the legacy copy
non-destructively). Verified on this machine:
- canonical state.json (mtime 17:28, daemon-updated): fmuaddib `refresh_failures: 374` → cascade
  REAUTH_NUDGE → daemon correctly nudges.
- legacy state.json (mtime May 30, 25 days STALE): fmuaddib has NO refresh_failures field (→ 0) →
  cascade RENEW_REFRESH ("keepalive will fix it") → detector stays SILENT.

`supervisor._slot_facts` reads `refresh_failures` from the resolved home's state.json (line ~223);
the detector reads the stale legacy file, so it sees a 25-day-old healthy snapshot while the
daemon sees the live dead-refresh truth. This is THE reason the REAUTH leg "doesn't work" from the
user's POV — the system knows the account is dead but the human is never told. It affects EVERY
migrated install. SECOND latent bug fixed for free: the detectors trusted a FOREIGN plugin's
`CLAUDE_PLUGIN_DATA` directly (the codex-env-leak class TRDD-7100178d fixed for the daemon via
`_canonical_rotator_root`'s `_JANITOR_DATA_DIRNAME` guard); delegating inherits that guard.

### The fix (single source of truth)
Add `rotator.configured_rotator_home() -> Path | None` — the ONE resolver both detectors use:
honor `CLAUDE_ROTATOR_HOME` (tests/standalone) when it has a state.json, else delegate to
`_rotator_root()` (canonical-first + foreign-CLAUDE_PLUGIN_DATA guard + legacy fallback), returning
None when no state.json exists anywhere (opt-in-by-presence preserved). Both
`oauth-login-needed._rotator_home` and `oauth-cookie-reminder._rotator_home` become one-liners that
delegate to it, so the detector and daemon can NEVER again read divergent state.

### TDD
- NEW unit tests on `configured_rotator_home`: both-present → CANONICAL (the regression: pre-fix the
  legacy-first order returned legacy); only-legacy → legacy (not-yet-migrated still works); env
  override wins; none-present → None.
- Existing `test_oauth_login_needed` / `test_oauth_cookie_reminder` integration tests still green
  (they set `CLAUDE_ROTATOR_HOME`, honored first; the opt-in-noop test sandboxes HOME).

### Scope guard / non-goals
Resolution-only fix. Does NOT change the cascade SSOT, the nudge wording, the keepalive, or
fmuaddib's actual state. fmuaddib STILL needs a one-time human OAuth login — this fix makes the
janitor TELL the user to do it (currently silent). The stale legacy state.json is left in place
(removing it is a separate migration-cleanup concern; the daemon already ignores it).

### Ship
TDD green + ruff clean → `publish.py` (USER present). Highest-priority on-mandate fix —
it's the reason the REAUTH leg never surfaced to the user.
