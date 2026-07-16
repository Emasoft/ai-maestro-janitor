---
trdd-id: V5RXQ4NB
title: Rotator keychain READ re-prompts — the app resets the credentials item partition list on every token refresh
column: backburner
created: 2026-07-16T03:16:02+0200
updated: 2026-07-16T03:16:02+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: major
labels: [oauth-rotator, keychain, macos]
relevant-rules: []
---

# Rotator keychain READ re-prompts (partition-list flap)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-16

**Origin:** GitHub issue **#82** (verified live 2026-07-11 by the AgentlensPro session). This is
the READ-side sibling of TRDD-EQJPPZ2L (which fixed the WRITE-side ACL prompt and is LIVE since
v0.44.1 — read its STATE + `macos-keychain.md` gotchas FIRST; the latch is now a self-healing
half-open breaker, so a flap darkens rotation for ≤ one 600s cooldown, not forever).

**The mechanism (from the issue — re-verify live before designing):** Claude Code (a signed app)
REWRITES the `Claude Code-credentials` item on every token refresh, which resets the item's
partition list to app-only — so the CLI `security` read prompts (no Always Allow), hangs
unattended, and trips the denied-latch. `security set-generic-password-partition-list
-S apple-tool:,apple: -s 'Claude Code-credentials'` cures it — until the next app refresh flaps
it back. Rotator-slot items (CLI-written) are stable; ONLY the app-owned live item flaps.

**Design constraints (hard — learned in EQJPPZ2L, do not re-litigate):**
- NEVER run an ACL-touching `security` op unattended against the login keychain — that class of
  op (`SecKeychainItemSetAccess`, incl. partition-list set, which may itself prompt for the
  keychain password) is exactly what flooded the user with prompts and broke `/login`.
- Any cure that prompts belongs in an INTERACTIVE, user-invoked skill (one prompt, user present),
  never in the daemon tick.
- The unattended path must instead AVOID the app-owned item read where possible: the
  `read_live_blob` ladder (primary → mirror) + the session-stamped live-identity beacon already
  exist — evaluate whether the tick can run beacon/mirror-first and touch the app item only when
  those disagree or age out.

**Candidate design (verify each leg):** (a) detect the flap cheaply (item mod-date/fingerprint
change since last tick) and mark the app item "hot — skip direct read this tick"; (b) prefer
beacon/mirror for identity; (c) surface a ONE-TIME advisory (once per flap, deduped) telling the
user the interactive cure command, via `/janitor-…` skill they can run when present; (d) measure:
with (a)-(c), does the latch ever trip in a normal day?

## NEXT ACTION
1. Re-verify the flap live (read-only observation: item moddate across an app token refresh).
2. Prototype beacon/mirror-first reads in `rotator.py` tick; count remaining direct app-item reads.
3. Interactive cure skill + once-per-flap advisory; tests (isolated keychain, real, no mocks).

## Verification
- A full day of ticks with app refreshes flapping the partition list: zero prompts, zero latch
  trips, rotation still resolves the live identity correctly (beacon/mirror path proven).

## Notes and lessons learned
