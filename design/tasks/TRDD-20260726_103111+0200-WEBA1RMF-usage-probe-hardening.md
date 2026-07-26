# Harden the 5h/7d usage probe — one throttled writer, correct UA, honest staleness

---
trdd-id: WEBA1RMF
title: Harden the 5h 7d usage probe — one throttled writer, correct UA, honest staleness
column: dev
created: 2026-07-26T10:31:11+0200
updated: 2026-07-26T10:31:11+0200
current-owner: 2f5bc976
task-type: bugfix
approval-tier: 0
scope: project
release-via: publish
impacts: [oauth-rotator, window-burn-rate, token-report]
relevant-rules: []
external-refs: [https://github.com/pizzimenti/ccgauge]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-26

- **Component state:** `scripts/lib/usage_probe.py` NOT yet written. Nothing wired.
  `rotator.usage_request` still sends the wrong UA and still has no throttle.
- **NEXT ACTION:** write `scripts/lib/usage_probe.py` (contract in §4), then
  `tests/test_usage_probe.py`, then route `rotator.usage_request` through it.
- **Load-bearing facts:** the probe endpoint is rate-limited HARD and 429s *worsen*
  under retry; `/api/oauth/usage` is the ONLY source of utilization% + resets_at;
  agentlensPro cannot supply either (§2).
- **SUPERSEDED — do NOT carry forward:** the premise that the agentlensPro CLI is the
  primary source for 5h/7d readings. Measured false on 2026-07-26 (§2). agentlensPro
  is authoritative for cache-TTL regime and burn *cause*, never for window %.

## 1. Why

The owner asked for an agentlensPro-primary 5h/7d reader with a fallback modelled on
`pizzimenti/ccgauge` (MIT). Auditing both ends turned the design around and exposed a
live defect in the path the rotator already depends on.

## 2. Measured — agentlensPro has no denominator

`agentlenspro get_account_status` (2.14.0, this machine, 2026-07-26):

```
"summary": "… 5h n/a / 7d n/a (none) · cache TTL 60min (doc-matrix)"
"usageWindows": { "windowSource": "none" }
"window": { "consumedTokens5h": 263094599, "consumedCostUsd5h": 337.4445,
            "capacityConfigured": false, "capacitySource": "none" }
```

It measures from OTEL telemetry, so it has a numerator and no denominator — no `%`,
no `resets_at`. `scripts/lib/agentlens_probe.py:18` already documented this. Roles:

| need | source |
|---|---|
| 5h/7d utilization % + `resets_at` | `/api/oauth/usage` — the ONLY source |
| cache-TTL regime | agentlensPro `get_account_status` (already wired) |
| consumed tokens/cost, burn cause, attribution | agentlensPro (already wired) |

agentlensPro becomes %-capable only if fed a capacity (`AGENTLENS_WINDOW_5H_TOKENS`
or `~/.agentlens/burn-config.json`). The janitor can compute one
(`token_baseline.estimate_window_cap`), but that writes OUTSIDE this project, so it
stays an opt-out-by-default, owner-run integration — tracked as an EHT, not done here.

## 3. The defect

ccgauge's README states the `User-Agent` is load-bearing: without a `claude-code/*`
UA the caller lands in an aggressive rate-limit bucket that 429s persistently.

The janitor sends `User-Agent: claude-account-rotator` on every `api.anthropic.com`
OAuth call — `rotator.py:1214` (roles), **`rotator.py:1251` (`usage_request`)**,
`slot_capture_token.py:121`. (`platform.claude.com` callers are a different host and
purpose; they are NOT in scope.)

Measured probe rate: `oauth-rotator-tick` every **60 s** (`cmd_auto` probes the live
account plus each alternate) and `window-burn-rate` every **900 s** across every known
account. ccgauge's floor is 600 s with backoff to 2 h. The janitor has **no TTL cache,
no cooldown, and no `Retry-After` honoring** — it re-knocks on a fixed 60 s clock,
which is precisely what keeps re-arming a server-side lockout instead of letting the
bucket drain.

Corroboration this is already biting: `rotator.py:324-335` carries TWO debounce knobs
(`LIVE_429_DEBOUNCE`, `ALT_429_DEBOUNCE`) added because a probe 429 is ambiguous
between "genuinely maxed" and "transient endpoint throttle", and TRDD-WBYFTU2L records
a 2026-07-18 deadlock where an alternate's probe-429 was misread as MAXED. Failure
shape: probe 429 → utilization unreadable for live AND alternates → `is_safe_alternate`
confirms no target → no rotation → the owner hits the real session limit. That matches
the owner's repeated "you failed to rotate again!" reports.

**Confidence.** The UA string, the cadences, and the absent throttle are VERIFIED
in-tree. That a non-`claude-code/*` UA *specifically* selects the aggressive bucket is
ccgauge's community finding — INFERRED here, and cheaply falsifiable by comparing
`cooldown_429` frequency before and after this change.

## 4. Contract — `scripts/lib/usage_probe.py`

One writer, N readers. Every technique below is adopted from ccgauge (MIT, credited in
the module header); the ones marked ✚ are janitor-specific.

1. **UA** `claude-code/<version>` derived at runtime from `claude --version`, cached
   per process, pinned fallback. Tracks CLI updates automatically.
2. **TTL cache** — cache-file `mtime` IS the clock (no extra state file, survives
   restarts). Default 600 s, env-tunable.
3. **429 cooldown** — honor `Retry-After` (delta-seconds or HTTP-date), then
   `anthropic-ratelimit-{unified,unified-5h,requests,tokens}-reset` (epoch or ISO);
   else exponential `600 × 2^(n-1)` capped at 7200 s on a persisted consecutive count.
   Floor a server-stated wait at 60 s.
4. **Cross-process non-blocking `flock`** so overlapping callers never double-hit;
   the loser serves cache. Re-check cooldown AND TTL *after* acquiring (the winner may
   have just refreshed or armed the cooldown) — this closes a real TOCTOU.
   `_NO_LOCK` sentinel when `fcntl` is missing or the FS refuses advisory locks
   (NFS/FUSE homes), so we proceed unlocked rather than serve cache forever.
5. **`outcome["reason"]` plumbing** — `fresh | ok | cooldown | no_token |
   expiring_token | 429 | lock_contended | http_error`. A stale readout must name its
   real cause; re-deriving it afterwards both mislabels lock contention and races.
6. **Token hygiene** — read `.credentials.json` honoring `CLAUDE_CONFIG_DIR`, tolerate
   either `claudeAiOauth` nesting or flat, treat `expiresAt` as **milliseconds**, and
   refuse a token within 30 s of expiry (let Claude Code rotate it).
7. **Honest staleness** — past `STALE_SECONDS` never render a cached countdown as
   live (the window may already have reset); show the last-good wall clock and say the
   values are NOT current.
8. **Never raises.** Any failure degrades to silence.
9. ✚ **State lives in `<DATA>/usage-probe/`**, not `~/.claude/` — the janitor's own
   persistence contract.
10. ✚ **Injectable HTTP getter** so every rule above is tested for real against a
    seam, with zero network and zero mocking of the code under test.

## 5. Acceptance criteria

- `rotator.usage_request` keeps its exact `(status, data)` contract, including the
  load-bearing 429/401/0 distinctions, but routes through the throttled probe.
- Live-account probe rate drops from ~1/60 s to at most 1/600 s; a 429 stops all
  probing until the cooldown expires.
- `tests/test_usage_probe.py` covers: UA derivation + fallback, ms-expiry refusal,
  TTL hit/miss, Retry-After (both forms) and each ratelimit-reset header, exponential
  escalation + cap, cooldown clear on 200, real two-process flock contention, the
  post-acquire re-check, and every `outcome` reason.
- `ruff` + `mypy` clean; full suite green.

## 6. Derived tasks (depth-1)

- **EHT-1** — feed a computed capacity into agentlensPro so it can report real
  window %; writes outside the project ⇒ owner-run, opt-in.
- **EHT-2** — verify R2: `slot_capture_token.py` captures `claude setup-token`
  tokens, which per ccgauge carry only `user:inference` and are REJECTED by
  `/api/oauth/usage` (it needs the browser login's `user:profile`). If true, those
  slots' utilization is unreadable by construction and they can never qualify as safe
  rotation targets — a second, independent cause of the rotation failures. Requires
  keychain reads; sequence it so it cannot trigger the `macos-keychain` dialog flood.

## Approval log

- 2026-07-26T10:31:11+0200 — Tier 0, authored directly in `design/tasks/`: bugfix
  wholly inside the janitor's own source, requested directly by the owner, no baseline
  deviation, no cross-project reach.
