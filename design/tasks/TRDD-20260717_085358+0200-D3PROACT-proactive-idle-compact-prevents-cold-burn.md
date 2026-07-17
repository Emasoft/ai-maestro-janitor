---
trdd-id: D3PROACT
title: Proactively compact an idle large context to prevent the cold-cache burn
column: dev
created: 2026-07-17T08:53:58+0200
updated: 2026-07-17T08:53:58+0200
current-owner: session
task-type: feature
release-via: publish
parent-trdd: EUWIHP0G
implementation-commits: []
---

# Proactively compact an idle large context to prevent the cold-cache burn

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-17

**NEXT ACTION:** part of the pre-publish batch — publish after the CC-compat pass.

**The ask (USER, 2026-07-17, verbatim):** *"the maintainer agent just now burned tokens because
it executed the janitor before executing the compacting … the compacting (to prevent the cache
creation burn) should run first! … you must make this fail-proof. improve the hook. improve the
cron. find a way."*

**THE PHYSICS (verified, immutable) — why "compact first" is impossible on a cron fire:** a cron
fire IS a turn. The turn re-reads the whole transcript to build the API request BEFORE the model
can emit any tool call. If the cache is cold (>1h gap), that re-read is the ~2× cache-creation
write — paid at turn start. `dispatch.py` runs as a Bash tool call AFTER it, so the burn is always
already paid by the time the janitor can queue a `/compact`. The design comment says so: *"the
inevitable cold cache-creation write."* The ONLY context that runs before a turn's re-read is a
HOOK — which is why the SessionStart path can beat the burn, but no cron fire can.

**THE INSIGHT:** the burn is only large when a LARGE context meets a COLD cache. You cannot stop
every cold event (a >1h working turn — crons can't fire mid-query, so the fire after it is always
cold; a rate limit; a restart). But you CAN ensure the context is never large when one hits — by
shrinking it PROACTIVELY during a cheap WARM idle fire, before any gap. Then every cold event
reads ~50k, not ~600k. This is the only path that PREVENTS the burn instead of mitigating it after.

**What shipped (3 parts):**
1. **NEW `dispatch._phase_proactive_idle_compact`** (Phase 1.2, before the maintenance
   early-return so a long unattended maintenance session — the prime target — is covered). Fires a
   SOFT `/compact` when ALL hold: enabled + off-cooldown, the user is ABSENT from this pane
   (`user_intent.user_is_present` False — ≥5 min no input), the session is NOT active-waiting
   (`_cadence_active_waiting` False — no resume/keep-going/directive/pending agent), and the
   context is large (≥`min_context_tokens`, 270k). Pure decision in
   `cold_cache_compact.should_compact_proactively_idle`. Self-limiting (context small after →
   size gate fails; shared cooldown blocks a re-fire) and fail-safe (NO_ITERM → no cooldown
   stamp, so the reactive paths still fire; any fault → no compact).
2. **Hardened the SessionStart hook** (`_maybe_cold_compact_on_session_start`): if the passed
   transcript path yields no size, fall back to the project's newest transcript before giving up
   — a stale/rotated path used to silently mean "no compact" → the full 2× write on turn one.
3. **Knob** `CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED` (default ON, gated by the master
   `cold_cache_compact_enabled` too), so a user can keep only the reactive backstops.

**Why prevention over mitigate-only (the rejected option):** mitigate-only still pays the first
cold write EVERY time — that IS the current behavior the user is frustrated by, so it does not meet
"fail-proof". Prevention (keep idle contexts small) is the only thing that eliminates the burn.

**The tradeoff, owned explicitly:** proactive compaction is LOSSY. The absent-user + not-waiting +
large gates confine it to a genuinely-abandoned session, where compacting is the right call (a cold
event is coming and will burn). The user had already accepted lossy auto-compaction of large
contexts on cold events (SessionStart + rate-limit paths); this extends it to idle. The user did
not answer the go/no-go (away >5 min); I chose prevention on the standing "make it fail-proof"
directive and HELD at publish for review.

## Pass criteria

- An idle (user absent) session with a large context gets a soft `/compact` on the next warm
  heartbeat; a present user or any pending work vetoes it.
- After the compact the context is small → no re-fire; cooldown holds.
- NO_ITERM/headless → no compact AND no cooldown stamp (the 3 trigger points agree on "fired").
- SessionStart hook recovers the size from the newest transcript when the passed path is unreadable.
- Reactive backstops (SessionStart, rate-limit cold path) unchanged.

## Out of scope

- The immediate cold write on a fire that IS already cold — physically unavoidable (see PHYSICS).
  Prevention makes it cheap by keeping the context small; it cannot make a cold re-read free.
- Cron survival / cadence — the dynamic cadence already caps SLOW at `*/30` ≤ the 1h TTL, so a
  FIRING cron never lets the cache go cold; the residual gaps (long turn, rate limit, restart) are
  what this TRDD's prevention covers.

## Notes and lessons learned

[^1]: [id:ATOM-D3PR-OACT, status:valid, keywords:"janitor_ran_before_compacting compact_should_run_first cache_creation_burn cold_cache token_burn", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT expect a heartbeat/cron `/compact` to prevent ITS OWN fire's cold burn, BECAUSE a cron
  fire re-reads the whole transcript (the cache-creation write) BEFORE the dispatcher runs — the
  burn is paid at turn start. DO prevent it upstream: keep an idle context SMALL (proactive warm
  compaction) so no cold event is ever expensive; only a pre-turn HOOK (SessionStart) can compact
  before a turn's re-read.
