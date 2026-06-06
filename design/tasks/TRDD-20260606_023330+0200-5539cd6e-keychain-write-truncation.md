---
trdd-id: 5539cd6e-f0d3-49ff-9615-7ca9fc4871db
title: CRITICAL — keychain slot write silently truncates every OAuth blob to 128 bytes
column: testing
created: 2026-06-06T02:33:30+0200
updated: 2026-06-06T02:45:00+0200
implementation-commits: [655a870]
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 0
severity: CRITICAL
effort: M
labels: [oauth-rotator, keychain, security, bug]
task-type: bugfix
parent-trdd: TRDD-32acd15f-a856-4770-ba99-24a27058d725
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
runtime-targets: [macos]
last-test-result: not-run
external-refs: []
---

# TRDD-5539cd6e — Keychain slot write truncates every OAuth blob to 128 bytes

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-06

### ✅ FIXED + PROVEN (commit 655a870) — all 5 fix items landed
1. argv write (no 128 truncation) ✓  2. write_slot strips to claudeAiOauth ✓
3. _switch_blob merges (preserves live mcpOAuth) ✓  4. cmd_capture read-back-verify fails loud ✓
5. tests: real-keychain regression round-trips 130B/600B/9000B byte-for-byte; +strip/merge/verify
unit tests; 47 rotator tests pass; ruff clean. PROVEN LIVE: re-captured the live account →
read_slot round-trips (471B claudeAiOauth-only, real 7.6h expiry, fp matches). **fmuaddib is now a
healthy refreshable slot.** REMAINING: user must `/login` to the 2nd account (emanuele) → capture
it (now round-trips) → 2 healthy slots → rotation can fire. THEN watch a real switch (#142).

---
**THIS is why "the oauth rotator didn't work at all."** Found 2026-06-06 ~02:30 while
diagnosing an overnight failure (live account hit the 5h session cap; nothing rotated).

### The bug (VERIFIED, decisive)
`scripts/oauth_rotator/rotator.py::_security_add_password_via_stdin` writes the slot via
`security add-generic-password -s <svc> -a <acct> -w` in **stdin-PROMPT mode** (no value on
argv — to keep the token out of `ps`, the "M1/M2 leak" hardening). But that mode reads the
secret via macOS **`getpass()`, which has a hard 128-byte buffer**. So ANY value > 128 bytes
is **silently truncated to exactly 128 bytes**. VERIFIED with a throwaway service:
```
in=100 -> stored=100 OK ;  in=200 -> 128 ;  in=480 -> 128 ;  in=8884 -> 128  (all TRUNCATED)
```
OAuth blobs are 400–8900 bytes, so **every capture stored a 128-byte corrupt fragment**
(invalid JSON — "Unterminated string"), which `read_slot` then can't parse → returns `None`
→ rotation has no usable alternate. `capture` **never reads the slot back**, so it always
reported "captured: … (expires ~Xh)" (computed from the in-hand LIVE blob) while persisting
garbage. The bug has silently broken ALL slot storage since the stdin-prompt change.

Why emanuele's old slot (471B) still reads: it was written by the OLDER `-w DATA` (argv)
path, before the stdin-prompt "hardening". Its access token is now expired anyway.

### Second issue (bloat): live blob is 8884 bytes
The live `Claude Code-credentials` blob is `{"mcpOAuth": {...huge...}, "claudeAiOauth": {...}}`.
The rotator only needs `claudeAiOauth` (the Claude account credential: accessToken /
refreshToken / expiresAt). Storing the whole thing (incl. all MCP server OAuth tokens) is
unnecessary secret-bloat AND interacts with the truncation.

### Threat-model note that unblocks the fix
The stdin-prompt mode existed to avoid the token appearing in `ps`/argv during write. BUT the
slot keychain items are created WITHOUT `-A`/`-T` and are nonetheless **readable via
`security find-generic-password -w` by any user process with NO prompt** (verified: a fresh
foreign process read both slots fine). So the read side is already fully open — the
argv-during-write exposure adds essentially nothing a local attacker couldn't get by just
running `security find …`. The "hardening" was security-theater that broke the feature.

### THE FIX (chosen, in progress)
1. **Store ONLY `claudeAiOauth`** in slots (strip `mcpOAuth` + other top-level keys) → ~480 B,
   smaller exposure, all rotator helpers already go through `_oauth(blob)` so a
   `{"claudeAiOauth": {...}}` slot works for fingerprint/expiry/usage/refresh.
2. **Merge-on-switch**: because slots are now claudeAiOauth-only, `_switch_blob` must read the
   CURRENT live blob and replace only its `claudeAiOauth` (preserving the user's live
   `mcpOAuth`), NOT overwrite the whole live blob with the slot. Else a rotation would wipe the
   user's MCP OAuth tokens.
3. **Replace the 128-truncating write**: use `security add-generic-password -U -s -a -w <DATA>`
   (argv) — handles any size; the redundant-exposure analysis above makes this acceptable.
   (Future hardening option, NOT now: ctypes SecKeychainAddGenericPassword for zero argv
   exposure — deferred; risk of getting ctypes argtypes wrong at 2am > the redundant exposure.)
4. **Read-back verification in `cmd_capture`** (the guardrail that would have caught tonight):
   after write_slot, read_slot it back and assert it parses + has a non-empty accessToken;
   if not, FAIL LOUD (non-zero / logged error), never report success. fail-fast.
5. Tests: write round-trips at 100/500/2000/9000 bytes; capture fails loud on a corrupt
   store; switch preserves mcpOAuth. Full rotator suite + ruff.

### NEXT ACTION
Apply 1–5, run tests, then **capture fmuaddib (live now) and VERIFY round-trip** (proves the
fix). Then user logs into emanuele → capture + verify → two healthy slots. THIS finally
exercises #142 (loop end-to-end) for real. The two backup tokens cannot be "captured" until
this lands — a capture today still truncates.

### Load-bearing facts
- 128 = macOS `getpass()` buffer in `security -w` prompt mode. Not configurable.
- Slot keychain service = `Claude Code-rotator-slot`; backup mirror = `…-slot-backup`;
  live = `Claude Code-credentials`; live backup = `…-livebak`. The shared write helper feeds
  all of them — fixing it fixes all.
- All rotator blob helpers use `_oauth(blob)` to reach `claudeAiOauth`, so claudeAiOauth-only
  slots are compatible. The ONLY place that needs the full blob is restoring the live
  credential on switch → hence merge-on-switch (#2).

## Why this TRDD exists
The user (rightly) demanded this be recorded so a future compacted/rate-limited session does
not re-lose the diagnosis. Cross-referenced from TRDD-32acd15f (the rotator master TRDD).
