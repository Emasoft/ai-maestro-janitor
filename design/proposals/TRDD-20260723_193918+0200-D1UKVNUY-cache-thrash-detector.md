---
trdd-id: D1UKVNUY
title: Cache-thrash / tool-surface-churn detector — catch a "cheap-percent, murderous-re-read" marathon session the %-of-window watchdog misses
column: proposal
approval-tier: 2
created: 2026-07-23T19:39:18+0200
updated: 2026-07-23T19:39:18+0200
current-owner: main-session
task-type: feature
scope: project
relevant-rules: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-23

- **MOTIVATING INCIDENT (verified via AgentlensPro 2.11.4, 2026-07-23):** the owner reported a whole
  5h rate-limit window burned in minutes, killing a live scenario. Deep investigation (this
  session) traced the DOMINANT burn to **session 43e66c93 in `~/ai-maestro`** (the ai-maestro
  server's own repo, a third-party `23blocks-OS/ai-maestro` checkout via the owner's fork):
  - a **10.6-DAY** "[api session]" (started 2026-07-13, still active), **7947 turns, $2822.96**.
  - AgentlensPro `get_session_burn_profile` verdict: *"MARATHON RE-READ — 253 turns × ~365k context
    = 77.0M tokens re-read … tools[] changed on 54/252 turns (21.4%) — EACH change invalidates the
    ENTIRE prefix."* Its MCP tool surface (Mem0, MT_Newswires, Scite, Consensus, Mermaid,
    chrome-devtools, Alma, huggingface…) toggles on ~1-in-5 turns → each toggle cold-invalidates the
    whole ~365k cache prefix → CACHE_THRASH. THIS is the burst.
- **WHY THE JANITOR'S WATCHDOG MISSED IT (the gap this TRDD closes):** the context-watchdog
  (`pre-tool-context-usage`) fires on **% of the 1M window** (advisory ≥80%, enforce ≥85%). 365k is
  only ~36% of 1M, so the watchdog correctly did nothing — yet the session was murderous by
  **re-read VOLUME × turns** and by **tool-surface CHURN**, neither of which the %-gauge sees. The
  window-burn-rate detector is per-project (token-quietness, TRDD-X92VBFNF), so it would surface in
  43e66c93's own session, not elsewhere.
- **NOT A JANITOR BUG.** The janitor skills (arm/resume/handoff) ranked high on COST only because
  they run INSIDE fat host sessions (amplification), proven by MY session staying stable
  (desired==armed */5, no re-arm in 5.3h). The earlier "janitor Sonnet memory-agent fan-out"
  suspicion was DISPROVEN (janitor-memory-* absent from skill attribution).
- **NEXT ACTION:** owner approves/vetoes the detector below; on approval, implement. Cross-links:
  [[TRDD-739N4CUF]] (the gated-rotator ownership gap — the OTHER half of the incident).

## Proposed feature — a cache-thrash detector (owner approval, Tier 2)

A new heartbeat detector (default-on, per-project, token-quiet like window-burn-rate) that alarms
when a session is pathologically expensive by a signal the %-gauge is blind to:

1. **Tool-surface churn:** `tools[]` changes on > N% of recent turns (each change cold-invalidates
   the whole prefix). Default threshold ~10-15%/hour. This is the highest-signal lever (the incident
   was 21%). Sourced from AgentlensPro (`get_session_burn_profile` / `get_cache_break_causes`) when
   present, fail-open when absent.
2. **Re-read volume:** `avgContextTokens × turns/hour` above a budget even while % is low — the
   "marathon re-read" shape. Alarms before a session has burned a full window.
3. **Advisory, not enforcing:** surface a HIGH drift line (and optionally a `notify.py` desktop
   push, daemon-only) recommending compact/clear + "stabilize your MCP tool surface (don't toggle
   MCP servers mid-session)". Never auto-kills a session (esp. not another project's).

## Redacted UPSTREAM issue draft (ready to post ONLY on owner confirmation — 23blocks-OS/ai-maestro)

> _Posted by the Claude developing **ai-maestro-janitor** (via the shared `@owner` gh auth)._
>
> **Design observation: `server.mjs` OAuth-rotator tick is gated-OFF by default while downstream
> consumers yield to the server → rotation can become ownerless.**
>
> The server-tick (`server.mjs:~1969`, TRDD-CC9PY337) is documented *"config-gated, default OFF …
> only the human creates the flag; the server only reads it."* A downstream coordinator that yields
> OAuth chores to a live server (on server-liveness) will yield even when the server advertises
> `capabilities:[]` and its tick flag is absent — so when a shared rate-limit window is exhausted,
> neither side rotates and in-flight agents stall. Suggestion: have the server advertise the
> oauth-rotation capability in its liveness payload ONLY when the tick flag is present, so a
> downstream consumer can distinguish "server owns this chore" from "server is merely alive."
> (No local paths / costs / session ids — generic design note.)

## Acceptance criteria

1. On a seeded session with `tools[]` churning > threshold, the detector emits ONE HIGH drift line
   naming the churn %, deduped; a stable-tool session stays silent. Isolated test (S1a/S1b/S1e).
2. Fail-open when AgentlensPro is absent (no crash, no false alarm).
3. Per-project + token-quiet (never leaks another project's session detail).
4. pyright 0 new / ruff clean / full `pytest tests/` green / `~/.claude` untouched.

## Approval log

- 2026-07-23T19:39:18+0200 — Authored as a PROPOSAL (Tier 2, new detector). Motivating incident +
  root cause verified live (marathon MCP-thrash session 43e66c93 in ~/ai-maestro; NOT a janitor
  bug). The upstream-issue draft is REDACTED and must NOT be posted until the owner confirms the
  destination (23blocks-OS is a third-party public repo; the owner holds only the Emasoft fork).
