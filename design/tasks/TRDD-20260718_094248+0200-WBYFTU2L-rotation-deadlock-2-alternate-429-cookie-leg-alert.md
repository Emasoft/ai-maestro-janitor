---
trdd-id: WBYFTU2L
title: Rotation deadlock 2 — undebounced alternate-probe 429 + silent per-alternate exclusion + cookie-leg limbo with no human alert
column: published
created: 2026-07-18T09:42:48+0200
updated: 2026-07-18T10:05:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
related-trdd: [P7WU40G9, 32acd15f, 7PYTX4E9, 1IKF0A6D]
implementation-commits: [dcd9d4d, 546db1e]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-18

**INCIDENT (owner, 2026-07-18 ~09:39, verbatim: "once again i had to rotate manually! why?"):**
NOT a recurrence of P7WU40G9 §BUG 1 — the v0.53.0 asymmetric thresholds WORKED (08:26:53 the
rotator auto-switched fmuaddib→emanuele.sabetta accepting a 7d=94% target). The new failure:
emanuele hit its REAL 7d wall (probe 97%→100%, real 429s leading the gauge) at ~09:11; from
09:18 the rotator logged `no alternate is healthy + below safe threshold and none is
structurally renewable — all paid accounts maxed` for ~21 min until the owner manually logged
into ipazia — which WORKED, proving a usable account existed that the rotator could not reach.

### The three defects (all in `scripts/oauth_rotator/`)

**D1 — alternate-probe 429 is hard-dropped, undebounced (rotator.py `cmd_auto` candidate
loop).** The LIVE account's 429 gets `LIVE_429_DEBOUNCE` (x2) because "a single 429 can be a
transient usage-endpoint throttle"; an ALTERNATE's probe 429 is treated as "genuinely MAXED"
and dropped the SAME tick. Both readings cannot be true. One endpoint-throttle tick against
the only fresh alternate produces the all-maxed deadlock.
**Fix:** per-alternate 429 streak in the slot's state meta (`alt_429_streak`), mirroring the
live debounce: streak < 2 ⇒ UNKNOWN — keep the alternate as a DEGRADED fallback when its
token is locally valid (same path as the 401/403-after-refresh case); streak ≥ 2 ⇒ maxed,
drop. Reset on any 200.

**D2 — the all-maxed line hides per-alternate WHY.** `no alternate is healthy…` is a
composite; diagnosing THIS incident required forensic log archaeology. **Fix:** when the
all-maxed branch is reached, append one compact clause per examined alternate:
`alt=<email>:<verdict>` where verdict ∈ `util(5h=..,7d=..)` | `probe-429(xN)` |
`probe-<status>` | `locally-expired-no-refresh` | `refresh-failed` | `no-slot`. One line,
greppable, sanitized.

**D3 — RENEW_COOKIE limbo has no actor and no alert.** ipazia sat in the cascade's
`renew-cookie` leg 232 ticks today (every tick since morning): the leg is NAMED in the plan
summary but nothing executes it (cookie reauth needs a browser; by design it is human/skill
driven) and nothing told the human. The one alert channel that fires unattended —
`lib/notify.py` (daemon Tier-1 desktop push, default-on) — never learns about it; the
`oauth-cookie-reminder`/`oauth-login-needed` detectors are OPT-IN. So the fleet ran one
account deep all day with a repairable third account and an unaware owner.
**Fix:** supervisor finding + notify wiring: in `oauth_rotator/supervisor.py::diagnose`, a new
alert `OAUTH-COOKIE-LEG-STUCK` when an account has been classified RENEW_COOKIE continuously
beyond `CLAUDE_PLUGIN_OPTION_OAUTH_COOKIE_LEG_ALERT_HOURS` (default 2); first-seen timestamps
persisted in the supervisor's own state (`cookie_leg_since` map). The daemon's existing
supervisor→notify path pushes it (sev HIGH, content-hash deduped, 24h capped): "account X has
needed a one-time login for Nh — run /janitor-refresh-claude-logins". Message names the
account label only (privacy: local-part prefix, existing `account_prefix`).

### Non-goals
- No change to the SWITCH/SAFE thresholds (P7WU40G9 values stand; fmuaddib at 7d=99 was
  CORRECTLY rejected — it was at the wall).
- No automation of the cookie reauth itself (browser-driven, human-gated by design).
- No change to the live-account debounce.

### Verification
- Unit: alternate 429 first-tick → kept as degraded (locally-valid token); second consecutive
  → dropped; 200 resets streak. All-maxed line carries per-alternate verdicts. Supervisor
  emits OAUTH-COOKIE-LEG-STUCK only past the threshold, deduped, cleared when the account
  leaves the leg.
- Regression: existing rotator + supervisor suites stay green.

**SHIPPED v0.55.0** (dcd9d4d + release 546db1e, 2026-07-18): D1+D2 in `rotator.py::cmd_auto`,
D3 in `supervisor.py` (`cookie-leg-stuck` — notify-pushed by the daemon's existing
every-supervisor-finding wiring). 121 rotator/supervisor tests green; full 14-gate publish passed.

## Notes and lessons learned

[^1]: [id:ATOM-ALT-429, status:valid, keywords:"all paid accounts maxed but manual login works alternate probe 429 hard drop undebounced endpoint throttle", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT interpret a single usage-probe 429 on an ALTERNATE as "account maxed" while the SAME
  code debounces the live account's 429 as "likely endpoint throttle", BECAUSE one throttled
  tick against the only fresh alternate deadlocks rotation on a usable fleet. DO apply the
  same debounce semantics to every account's probe.

[^2]: [id:ATOM-COMPOSITE-LOG, status:valid, keywords:"composite failure log line hides per account reason forensic archaeology all maxed why rejected", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT emit a composite failure verdict ("no alternate is healthy") without the per-item
  reasons, BECAUSE the next incident costs a forensic dig to answer "which account, why". DO
  append one compact per-item verdict clause to every all-candidates-rejected log line.

[^3]: [id:ATOM-COOKIE-LIMBO, status:valid, keywords:"renew-cookie leg looping no actor no alert account needs one time login fleet one account deep", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT let a cascade leg that only a HUMAN can complete (cookie/browser reauth) spin as a
  silent plan line, BECAUSE the fleet then runs thin for hours while a repairable account
  idles and the owner learns of it only at the next deadlock. DO alert the human (Tier-1
  notify) once the account has sat in that leg beyond a dwell threshold.
