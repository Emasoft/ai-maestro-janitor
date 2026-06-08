---
trdd-id: dfc0959a-9e74-40ae-8de9-bf7fd5b378f3
title: OAuth rotator — 3-layer cascade paradigm + keychain-encrypted cross-platform cookies + consistency fixes
column: dispatch
created: 2026-06-08T16:53:09+0200
updated: 2026-06-08T16:53:09+0200
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 1
severity: HIGH
effort: XL
labels: [oauth-rotator, security, keychain, cross-platform, cascade, redesign]
task-type: refactor
parent-trdd: TRDD-32acd15f
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, integration]
runtime-targets: [macos, linux, windows]
external-refs: []
---

# TRDD-dfc0959a — Rotator 3-layer cascade + keychain-encrypted cookies + consistency fixes

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-08

**USER design directives (2026-06-08), the authoritative spec:**
1. **Every rotator script must follow ONE paradigm in 3 parts, each FALLING BACK to the
   next when it fails:** **(1) ROTATE → (2) RENEW → (3) REAUTHENTICATE.**
   - ROTATE: swap the live keychain credential to the next stored OAuth token. Real-time,
     silent, agents never notice. Already works.
   - RENEW (fallback when no healthy alternate to rotate to / a token expired): refresh via
     the refresh-token (silent HTTP) OR, if dead, re-mint via the stored COOKIE +
     `claude auth login`/CDP-attach capture. Behind the scenes; needs a valid cookie.
   - REAUTHENTICATE (fallback when RENEW can't — cookie dead): the ONLY human step — the
     janitor NUDGES the user to run the reauth skill (`/refresh-claude-logins`); ~monthly.
   The cascade is the governing control-flow for the daemon tick AND every helper.
2. **Cookies + OAuth tokens BOTH stored ENCRYPTED in the OS keychain / safe-storage**
   (macOS Keychain, Linux Secret Service / libsecret, Windows Credential Manager / DPAPI),
   NOT as plaintext-on-disk Chrome profile sqlite. **The keychain-stored cookies are used
   to SWITCH PROFILES** (inject into the Chrome profile before a capture, scrub after).
   Security: nothing sensitive (token OR cookie) sits unencrypted on disk.

**NEXT ACTION (phased — see plan):** Phase 0 = land the bounded consistency fixes from the
audit (so the CURRENT system is correct) BEFORE the bigger redesign. Then Phase 1 = the
cascade paradigm, Phase 2 = keychain-encrypted cookies + cross-platform safe-storage
abstraction. DO NOT publish/push until at least Phase 0 + the cascade land and the chain is
validated end-to-end (which needs a non-429 session + a real reauth with "stay signed in").

**Load-bearing facts:**
- Today's transport fix (commit d05b94c) already moved the renew capture to CDP-attach to
  REAL Chrome (real keychain decrypts cookies) — see [[reference_oauth_renew_browser_transport_solution]].
- `_profiles_root()` now has a legacy fallback (macOS) — but several consumers bypass it
  (the two detectors) — see audit findings below.
- The current cookie storage = Chrome profile `Default/Cookies` sqlite (Chrome-OSCrypt
  encrypted on disk). The redesign moves cookies INTO the keychain. This changes
  profiles-root/cookie-detection fundamentally — Phase-0 path fixes may be partly superseded
  by Phase 2; do Phase 0 anyway so the system is correct in the interim.
- Session at 98% weekly (429) when this was written; end-to-end validation is blocked until
  a fresh window + a successful reauth (tick "stay signed in").

**Durable artifacts to read before acting:**
- `reports/oauth-rotator-consistency-audit/{A-core-py,B-detectors-daemon,C-shell-skills}.md`
  — the full 17-finding audit (line-level fixes).
- `reports/browser-projects-audit/20260529_171202+0200-CONSOLIDATED.md` — the transport stack.
- Memory: [[reference_oauth_rotator_three_layer_architecture]],
  [[reference_oauth_renew_browser_transport_solution]], [[reference_oauth_rotator_keychain_architecture]].

## Consolidated audit findings (2026-06-08) — fix in Phase 0

CRITICAL:
- **C1** `~/.claude/account-rotator/reauth.sh` still uses the OLD AppleScript/JXA transport;
  the refactor shipped `reauth.py` (CDP-attach) as the live-cred sibling. Two divergent
  reauth impls coexist → retire/shim `reauth.sh` to `reauth.py`.
- **C2** `lifetime-status.sh` reads OAuth health from plaintext `slots/<email>.json` files
  the keychain migration DELETES → prints a false "⚠ no healthy OAuth" banner on every
  migrated machine. Read health from the keychain slots (rotator), not the dead files.

HIGH:
- **B-F1** `scripts/detectors/oauth-login-needed.py:162-164` builds its own profiles-root
  (no legacy fallback) → silent / mis-nudge on migrated installs (today's silent failure).
  Fix: `import rotator; profiles_root = rotator._profiles_root()`.
- **B-F2** `scripts/detectors/oauth-cookie-reminder.py:110-112` — same bypass → false
  "(login needed)" alarms. Same fix.
- **C-H1** profiles-root parity currently holds only via a runtime symlink that masks the
  durable `_profiles_root` fallback; a symlink-less/fresh install diverges. Remove reliance
  on the symlink once every consumer uses `_profiles_root`.
- **C-H2** `refresh-claude-logins.md` reads the roster from legacy `state.json` but mints
  into the DATA-dir state → drift. Use `rotator.py known-emails`/`list`.
- **A-H** `reauth.py` hardcodes a legacy `reauth-chrome` dir + fixed CDP port bypassing
  `_profiles_root()` → forces a migrated user to log in twice.

MEDIUM/LOW (also Phase 0/1): both detectors' `_cookie_days` has a ">=5 cookies = session"
heuristic diverging from `rotator._profile_has_session_key` (drive eligibility off the engine
fn); stale docstrings (slot_capture_token.py:30, reauth.py:45); supervisor.py slots-dir local
resolver; diagnostic PNGs written into the credential state root; pre-existing uncalled
`_slot_keychain_delete` (also misses the `-backup` mirror); brittle version glob in a skill;
stale memory-note wording (reauth.sh≈reauth.py, "puppeteer").

CONSISTENT ✓ (audit-verified, no change): the live transport (CDP-attach in
slot_capture_browser.py + reauth.py); the sessionKey `expires_utc > now` probe everywhere
(a non-persisted session-cookie cannot pass); keychain service `Claude Code-rotator-slot`
reads; the daemon `oauth-rotator-tick` Task runs the new transport-capable tick.

## Plan (phased — do NOT push until Phase 0 + Phase 1 land + validate)

**Phase 0 — consistency fixes (bounded; from the audit):** detectors→`_profiles_root`;
retire `reauth.sh`→`reauth.py`; `lifetime-status.sh`→keychain health; roster→`rotator` API;
reauth.py profiles-root; `_cookie_days`→engine fn; doc/memory de-stale; drop symlink reliance.
Tests + re-validate the detectors fire on a logged-out+expired account.

**Phase 1 — the 3-layer cascade paradigm:** make the daemon tick (and helpers) an explicit
ROTATE → (fallback) RENEW → (fallback) REAUTHENTICATE-nudge cascade; one shared decision
module both the daemon and the detectors import; the nudge is the documented terminal
fallback. Unit-test each fallback edge.

**Phase 2 — keychain-encrypted cross-platform cookies:** a `safe_storage` abstraction
(macOS `security`/Keychain, Linux Secret Service via `secret-tool`/libsecret, Windows
Credential Manager/DPAPI). Store the per-account claude.ai cookie jar ENCRYPTED in
safe-storage; on capture, INJECT it into the Chrome profile (or drive cookies via CDP
`Network.setCookie`), scrub the on-disk copy after. Both tokens AND cookies encrypted at
rest; the keychain entry is the source used to switch profiles. Cross-platform tests/guards.

**Phase 3 — validate end-to-end + ship:** on a non-429 session, run a real reauth (tick
"stay signed in") → confirm RENEW mints a refresh-bearing slot via CDP-attach → confirm
ROTATE swaps live → confirm the nudge fires only when a cookie is genuinely dead. Then bump
the janitor version, publish, restart (USER-gated push).

## Why this TRDD exists
The USER expanded the pre-push consistency check into a rotator redesign (cascade paradigm +
keychain-encrypted cross-platform cookies). This is multi-session XL work that must survive
compaction + the 429. This TRDD is the authoritative spec + the consolidated audit so the
work is not lost and is not crammed into one maxed session.
