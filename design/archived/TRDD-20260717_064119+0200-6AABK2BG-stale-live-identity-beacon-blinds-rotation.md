---
trdd-id: 6AABK2BG
title: A stale live-identity beacon blinds proactive rotation after a manual login
column: published
created: 2026-07-17T06:41:19+0200
updated: 2026-07-17T07:02:00+0200
current-owner: session
task-type: bugfix
release-via: publish
parent-trdd: 7PYTX4E9
implementation-commits: [8eed48e, b597355]
released-in: v0.48.0
---

# A stale live-identity beacon blinds proactive rotation after a manual login

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-17

**SHIPPED + DEPLOYED in v0.48.0** — the full chain done in the order TRDD-EQJPPZ2L's permanent
lesson mandates (a repo-only fix is INERT): published v0.48.0 (14 gates green, NIT=0) → updated
the CACHE 0.47.0 → 0.48.0 → re-staged the L0 daemon closure (`verify_or_restage` found
`rotator.py` stale and refreshed it) → ran the **cache-deployed** detector: exit 0, silent, and
`keychain-latch-status` still `clear` (no prompt storm).

**NEXT ACTION:** none — only an observation remains: the next real `/login` should produce a
`beacon: live account changed A -> B` line in rotator.log within one heartbeat, after which
`cmd_auto` must name the REAL live account. Rotation at 97% then follows on the existing,
already-working F2 path. If that line never appears after a manual rotation, re-open here.

**Verified end-to-end against the LIVE system (not inferred):**
`_primary_last_modified()` → `1784261209.0` = 06:06:49 — byte-exact with the `mdat` read by hand
from the keychain, proving the parser matches the true wire format. The current beacon (06:39:08)
is newer → the gate reports "current" → **zero `-w` reads**. During the incident at 06:10 the
beacon predated that same `mdat`, so this gate would have fired.

**Do NOT "simplify" the gate away.** The non-prompting `mdat` check is not an optimization — it
is what makes an every-fire cadence prompt-SAFE. Replacing it with a plain per-fire
`write_live_identity_beacon()` re-creates the ACL prompt flood of [[TRDD-EQJPPZ2L]] /
[[TRDD-K3WQ7XM9]].

**The symptom (USER, 2026-07-17):** *"i had to rotate the oauth manually again"* — proactive
rotation never fires, repeatedly, so the user rotates by hand. The USER's standing directive is
rotate-near-the-cap; the live thresholds are `SWITCH_AT_5H = SWITCH_AT_7D = 97`. **The threshold
was never the cause** — 97 is already more aggressive than the 98 the user remembered, and the
rotator never got as far as comparing it.

**ROOT CAUSE (verified first-hand against the live log + source + a live keychain probe — NOT
inferred):** the daemon evaluates rotation against the **wrong account**, because the
live-identity beacon is only ever stamped **once per session, at SessionStart**.

**SUPERSEDED — do NOT carry forward** (a compaction summary asserted these; both are FALSE):
- ✗ *"Nothing stamps the beacon during a normal heartbeat / only 3 call sites."* There is a 4th:
  `hooks/on-session-start.py:343` spawns `rotator.py beacon`. The beacon **is** stamped — once
  per session start. That is the whole bug: once per session is not often enough.
- ✗ *"Fold the stamp into the `keychain-health` detector."* That detector's contract is
  explicitly **"Checks FINDABILITY only — never `-w`"** (`dispatch.py` roster) because the `-w`
  secret read is what causes the ACL prompt FLOOD. A stamp needs `-w`, so it must NOT live there.

## The chain (each link verified)

1. `daemon.py:582` sets `JANITOR_ROTATOR_HEADLESS=1` for its rotator-tick subprocess.
2. `rotator._primary_secret_read_permitted()` (rotator.py:442) therefore returns False in the
   daemon, and `_read_primary_macos_keychain` returns None **without attempting the read** — a
   DELIBERATE design (FIX B2, [[TRDD-K3WQ7XM9]]): headless, a `-w` read of Claude's
   Claude-only-ACL item can only raise a GUI prompt nobody can answer (it hung ~30 min once).
3. So the daemon's `cmd_tick` → `write_live_identity_beacon()` is a **guaranteed no-op by
   design** — `_read_live_primary()` returns None → the function returns False. The comment at
   that call site says so outright ("the daemon's own ticks can't — which is the point").
4. Net: the ONLY automatic beacon stamp is SessionStart. Between session starts — hours or days
   on an unattended session — a manual `/login` silently changes the live credential and
   **nothing re-stamps the beacon**.
5. `BEACON_MAX_AGE_S` is 24h, so the stale beacon is not rejected as stale — it is
   **fresh-but-WRONG**, naming the previous account.
6. The `-livebak` mirror only updates via `cmd_capture`, which is also skipped when the primary
   is unreadable — so mirror and beacon go stale **together**, stale-CONSISTENTLY.
7. `_resolve_untrusted_live` (rotator.py:1481) hits `b_fp == mirror_fp` → concludes *"the mirror
   IS live"* with **false confidence** → probes the OLD account's usage → under 97 → *"within
   limits"* → **never rotates**, while the real live account burns to its cap.
8. The user rotates by hand → still no stamp → the daemon keeps watching the phantom. It is
   **self-perpetuating**, which is exactly why it recurred.

### Evidence (live, this incident)

```
06:10  auto: live <account-A> 5h=34% 7d=44% — within limits      ← phantom (stale beacon)
06:34  auto: live identity from session beacon: <account-B> — the mirror holds a DIFFERENT
       credential; probing the live account via its slot token (TRDD-7PYTX4E9 F2)
06:34  auto: live <account-B> 5h=51% 7d=70% — within limits       ← real account
```

The 06:34 lines land only because a `/compact` fired a fresh **SessionStart**, which re-stamped
the beacon. That is the proof of both the cause and the fix: **the F2 resolution logic is
correct and already works — it is starved of a fresh beacon.**

Live keychain probe (non-prompting, no `-w`) taken during the incident:

```
"mdat"<timedate>= "20260717040649Z"   → the manual /login, 06:06:49 local
beacon ts        = 1784263025.6       → 06:37:05 local (post-SessionStart)
```

At 06:10 the beacon's `ts` **predated** `mdat` — so an `mdat > beacon.ts` test would have caught
this exact incident, using a read that does not prompt.

## The fix — an mdat-gated, session-context beacon refresh

**Design principle:** re-stamp the beacon when the credential **actually changes**, detected by
a read that cannot prompt. Do NOT poll `-w` on a cadence (that is the prompt-flood the codebase
is architected around — [[TRDD-EQJPPZ2L]], [[TRDD-K3WQ7XM9]] FIX B2, `keychain-health`'s "never
`-w`"). In steady state the cost is one cheap metadata call per fire and **zero** `-w` reads.

1. `rotator._parse_keychain_timedate(raw)` — pure: `"20260717040649Z"` → epoch (UTC).
2. `rotator._primary_last_modified()` — cross-platform, non-prompting:
   - macOS: `security find-generic-password -s <svc> -a <acct>` **without `-w`** → parse `mdat`
     (routed through `safe_storage.run_security` for the latch + hard timeout, the same shape
     `_keychain_item_exists` already uses);
   - else: `~/.claude/.credentials.json` mtime (on Linux/Windows the primary is a plain file —
     no keychain, no prompt, so the gate is free there too);
   - unknown → None.
3. `rotator.beacon_needs_restamp(*, now)` — pure decision: True iff the beacon is
   absent/garbage/stale, OR the primary's last-modified is unknown, OR `mdat > beacon.ts`.
   **Fail-OPEN on unknown** is safe: the restamp then attempts a `-w` that the denied-latch
   short-circuits without spawning, so an unknown never becomes a prompt loop.
4. `rotator.refresh_beacon_if_stale()` — gate + `write_live_identity_beacon()`; logs via
   `_decide` **only when the identity actually changes** (a real identity event belongs in the
   durable rotator.log; an unchanged no-op does not).
5. CLI: `beacon [--if-stale]` — `--if-stale` applies the gate. The bare form stays
   unconditional (SessionStart wants an unconditional stamp).
6. New detector `detectors/oauth-beacon-refresh.py` — session context (never headless: only
   `daemon.py` sets `JANITOR_ROTATOR_HEADLESS`), opt-in by rotator-home presence (same gate the
   SessionStart hook uses, so machines without a rotator pay nothing), silent, cadence 300s.

**Why a detector and not the daemon:** the daemon is the one context that structurally CANNOT do
this (steps 1–3). This is not a scope-invariant violation — the beacon is a lock-free atomic
write of a single file the daemon only ever reads, never a global-scope mutation (PRRD S2.1 /
issue #7 single-writer is about the expensive `claude plugin` commands and state.json).

## Pass criteria

- A credential change (mdat bump) with no SessionStart → the next heartbeat re-stamps the beacon
  → `cmd_auto` resolves the true live account and rotates at 97%.
- Steady state (no /login) → zero `-w` reads, zero prompts, no log noise.
- `keychain-health`'s never-`-w` contract untouched.
- Real tests (no mocked keychain semantics for the pure parser/gate); `uv run pytest -q` +
  `ruff check` green.

## Out of scope

- The 97/90 switch policy ([[TRDD-EQJPPZ2L]] §policy) — the thresholds are correct and were
  never reached. Do NOT touch them (USER 2026-07-17: *"good, 97% is even better"*).
- Any credential mutation. This TRDD adds no rotation, no write to the live item, no capture.

## Notes and lessons learned

[^1]: [id:ATOM-6AAB-K2BG, status:valid, keywords:"rotation_never_fired manual_rotation_again wrong_account within_limits stale_beacon", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT conclude a guard is missing because a grep shows few call sites, BECAUSE
  `write_live_identity_beacon` had a 4th caller the grep missed (a CLI spawn from
  `on-session-start.py`) and a 5th that is a deliberate no-op (`cmd_tick`, headless) — the real
  defect was CADENCE (once per session), not absence. DO trace the runtime context each call
  site executes in before calling a mechanism absent.
