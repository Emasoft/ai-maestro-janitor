---
trdd-id: HJGR4I5W
title: OAuth cascade — a dead-but-present refresh token is trapped in RENEW_REFRESH, never escalated to REAUTH
column: todo
created: 2026-06-24T01:19:58+0200
updated: 2026-06-24T01:19:58+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 2
severity: HIGH
effort: M
labels: [oauth, rotator, cascade, survival, immortality]
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
attempts: 0
last-test-result: not-run
implementation-commits: []
audit-trigger: manual
audit-target: oauth-rotator cascade (scripts/oauth_rotator/cascade.py + rotator._keepalive_refresh)
audit-conclusion: issue-confirmed
external-refs: []
---

# TRDD-HJGR4I5W — OAuth cascade: a dead-but-present refresh token never escalates to REAUTH

## ⏵ STATE — READ THIS FIRST — 2026-06-24

**NEEDS USER DECISION — touches the USER's authoritative cascade design
(`cascade.py` docstring: "USER's authoritative design"). I confirmed the gap but did
NOT fix it (sensitive, high-blast-radius — a wrong change breaks the rotation/survival
mechanism itself). Surfaced for the user to decide.**

**Discovered live, 2026-06-24 ~01:1x**, during the autonomous overnight session: the
alternate account `fmuaddib@gmail.com` has been **stuck-expired** (`oauth-health
days=-0.1`) for 30+ minutes while the global daemon is **alive and ticking** (heartbeat
30s fresh; `oauth-rotator-tick.last-run.ts` at 01:17). So the alternate is a **dead
rotation target**, and nothing surfaced it.

**Survival impact:** the autonomous session currently has **NO usable rotation
alternate** (LIVE `emanuele.sabetta` is healthy — `days=0.1`, refreshes via Claude
Code's own grant — but if its 5h/7d budget is exhausted, ROTATE has nowhere to go →
the session gets stuck rate-limited, the exact failure the immortality work prevents).
**Prudent until the alternate is restored: keep token usage LOW (no heavy agent fleets
/ big builds) so LIVE's budget isn't burned with no safety net.**

## Confirmed root cause (code-traced, not assumed)

`fmuaddib` has a refresh token but its token is expired (`token_expires_h ≈ -2.4h`).

1. `cascade.classify` (cascade.py:111-115): `has_refresh=True` AND
   `token_expires_h (-2.4) <= keepalive_ahead_h` → returns **`RENEW_REFRESH`** — i.e.
   "the daemon will silently refresh it."
2. `rotator._keepalive_refresh` (rotator.py:1275-1278): refreshes any slot with
   `eh <= KEEPALIVE_AHEAD_H` (default **6h**, line 267). `-2.4 <= 6` → fmuaddib **is
   attempted every tick**.
3. `rotator.refresh_oauth_token` (rotator.py:756) is **best-effort: returns `None` on
   failure, never raises** (line 1259). fmuaddib's refresh keeps **failing silently**
   (the daemon ticked at 01:17 and the token is still expired) — most likely a
   dead/revoked refresh token (could be a transient token-endpoint flake, but 30+ min
   stuck points to dead).
4. `cascade.classify` routes to the human-nudge **`REAUTH_NUDGE` only when
   `has_refresh is False`** (cascade.py:117+). A **present-but-dead** refresh token has
   `has_refresh=True` forever → it is **never** classified `REAUTH_NUDGE` → the
   `oauth-login-needed` detector never nudges the user → the dead alternate is silent.

## The gap (precise)

The cascade's documented intent — "**REAUTH** (fallback when **RENEW can't**)"
(cascade.py:28-31) — is **not realized for `RENEW_REFRESH`**: there is no detection of
"a RENEW_REFRESH slot whose refresh keeps failing." `_keepalive_refresh` swallows the
failure (no failure count), and `classify` keys REAUTH off `has_refresh` (presence),
not refresh **viability**. So a dead-but-present refresh token is an absorbing state
with no escalation edge to the human re-login nudge.

(The `RENEW_COOKIE` → `REAUTH` edge exists, via `has_refresh=False` + no session. Only
the `RENEW_REFRESH` → `REAUTH` edge is missing.)

## Fix direction (for the USER to approve — their authoritative design)

Add **refresh-viability tracking** so a persistently-failing RENEW_REFRESH slot
escalates to REAUTH:

- Persist a per-slot **consecutive-`refresh_oauth_token`-failure counter** (reset to 0
  on any success). `_keepalive_refresh` increments it when `refresh_oauth_token`
  returns `None`.
- Thread a small fact into `AccountState` (e.g. `refresh_failures: int`) so the SSOT
  `classify` can decide: `has_refresh=True` AND `refresh_failures >= N` (e.g. N=3, a
  few ticks ⇒ minutes — long enough to clear a transient endpoint flake, short enough
  to surface a dead token within the hour) → **`REAUTH_NUDGE`** (treat the refresh
  token as dead). One new branch in `classify`, one counter in `_keepalive_refresh`,
  the detector already surfaces `REAUTH_NUDGE`.
- Keep it the SSOT: both the daemon and the detectors read the same classification, so
  they still never disagree.

## Immediate remediation (USER, independent of the code fix)

Re-login `fmuaddib@gmail.com` (its refresh token appears dead) — via
`/refresh-claude-logins` / the rotator's reauth path — to restore a working rotation
alternate. Until then there is no rotation safety net.

## Verification (when the fix is built)

- Unit: `classify` with `has_refresh=True, refresh_failures>=N` → `REAUTH_NUDGE`;
  `<N` → still `RENEW_REFRESH`; a success resets the counter (no spurious escalation).
- The counter persists across daemon restarts and resets on a real refresh success.
- The `oauth-login-needed` detector surfaces the newly-escalated slot.

## Why this matters

The whole point of the rotator is that "a healthy account always exists to rotate TO"
(cascade.py:16-17). A silent dead alternate defeats that — and during unattended
overnight autonomy (when this was found) it is precisely when no human is watching to
notice the alternate rotted.
