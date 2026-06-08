---
trdd-id: dfc0959a-9e74-40ae-8de9-bf7fd5b378f3
title: OAuth rotator — 3-layer cascade paradigm + keychain-encrypted cross-platform cookies + consistency fixes
column: dev
created: 2026-06-08T16:53:09+0200
updated: 2026-06-08T17:31:48+0200
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

**PHASE 0 — DONE (2026-06-08), verified.** The bounded consistency fixes from the audit
landed:
- IN-REPO (commit 3316e44; 120 oauth tests green, ruff clean): rotator.py + read-only
  `print-profiles-root` (H1) + `oauth-health [--json]` (C2) subcommands +
  cmd_live_email/cmd_known_emails doc-comments reauth.sh→reauth.py (C1);
  oauth-login-needed.py B-F1/B-F4 (`_has_live_session`→`rotator._profile_has_session_key`;
  removed the divergent ≥5-cookie heuristic, the own-root resolver, and the now-dead
  `_cookie_days`/sqlite); oauth-cookie-reminder.py B-F2 (root via `_profiles_root`);
  reauth.py A-F1 (debug-Chrome dir anchored on `rot.ROOT/reauth-chrome`, printed at
  startup + --dry-run, legacy literal de-hardcoded); slot_capture_token.py A-F2 docstring.
- IN-REPO (commit for THIS update): skills/janitor-auto-manage-oauth-on/SKILL.md M1
  (point capture at open-login.sh + auto-bootstrap, drop slot_capture_token.py steer) +
  the account-count now via `known-emails` (was falsely 0 reading the deleted plaintext
  slots/*.json — C2 class).
- USER-SCOPE (edited in place; originals backed up to gitignored
  `scripts_dev/oauth-rotator-userscope-backup-20260608_171840+0200/`): lifetime-status.sh
  C2 (OAuth health from the keychain via `oauth-health`; the false "⚠ no healthy OAuth"
  banner is gone) + H1 (`print-profiles-root`); open-login.sh + check-login.sh H1;
  reauth.sh C1 (retired → thin shim forwarding to the cached reauth.py);
  ~/.claude/commands/refresh-claude-logins.md H2 (roster via `known-emails`) + M2
  (version-glob note). Every shell fix uses a GRACEFUL FALLBACK: an older cached rotator
  that lacks the new subcommands prints "unknown command: …" to STDOUT, so the output is
  guarded by an absolute-path (`/*`) / JSON-object (`{*`) check before use — caught a real
  self-introduced bug where the garbage poisoned PROFILE_ROOT. Verified by dual-test
  (cached-fallback path + repo-subcommand path) on lifetime-status.sh and check-login.sh.
- MEMORY de-stale: [[reference_oauth_rotator_three_layer_architecture]] ("puppeteer"→
  CDP-attach) + [[feedback_oauth_rotator_resume_protocol]] (reauth.sh→retired shim;
  replaced the now-inverted per-account snapshot with a pointer to `oauth-health`).

DEFERRED (LOW; non-blocking follow-ups): A-F6 (capture PNGs → diagnostics subdir);
A-F3/B-F3 (supervisor inline root/slots-dir dup, correct today); A-F4
(`_slot_keychain_delete` dead half-primitive); A-F5 (clipboard opt-in). ALSO: bring the
user-scope shell scripts INTO the repo + an installer so these fixes ship to every install
(today they are local-machine + backed-up only).

**NEXT ACTION:** Phase 1 = the 3-layer cascade paradigm (daemon tick + helpers as an
explicit ROTATE → RENEW → REAUTHENTICATE-nudge cascade; one shared decision module both
daemon and detectors import). Then Phase 2 = keychain-encrypted cross-platform cookies.
Phase 1+ is XL and AWAITS USER GO; end-to-end validation needs a non-429 session + a real
reauth with "stay signed in". DO NOT push the unpushed commits without explicit USER go.

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
