---
trdd-id: N9YAH5E7
title: Per-class capability chore gating — wire the server-liveness probe, stop sharing one ownership bit
column: testing
created: 2026-07-17T17:36:45+0200
updated: 2026-07-17T17:52:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
related-trdd: [PZLVT2RN, H7NVKSAX, FENWWB4E]
coordination-issue: janitor#100
implementation-commits: [616ab18]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**Origin:** ai-maestro's ratification round-1 reply on janitor#100 (2026-07-17 15:29 UTC,
§6.2 conflict review of `design/ARCHITECTURE.md` rev 1). Their capability probe is
**DELIVERED**: `~/.aimaestro/server-liveness.json`, shape
`{"ts": <epoch-s>, "pid": <pid>, "capabilities": ["family-a", ...]}`, rewritten every
30 s, consumers apply a 90 s staleness window; tokens are PER-CLASS and each is present
ONLY while its class is live and running (`family-a` = OAuth tick enabled;
`singleton-chores` and `fleet-recovery` RESERVED, never emitted today).

**The conflict (required janitor-side change #1 of their ratification posture):**
`server_owns_singleton_chores()` delegated to `server_owns_family_a()` — ONE ownership
bit gated ALL FIVE absorbed chores. With the per-class probe wired into that shared bit,
the instant the USER flips the OAuth flag ON (`family-a` appears), the janitor would
stop marketplace-refresh / user-plugins-update / version-update — chores NOTHING runs
(the server does not perform them). "A token without its live chore silences the
janitor" — the exact failure the #100 load-bearing rule forbids.

**The fix (this TRDD):** gate each absorbed task on its OWN capability token.

- `harness_backend.py`:
  - `server_capabilities()` — read + validate the probe file (path override
    `JANITOR_AIMAESTRO_LIVENESS_FILE` for tests; HOME at call time), 90 s staleness;
    returns the token frozenset, or None when absent/stale/malformed.
  - `_server_owns_capability(cap)` — the ONE ladder: `$JANITOR_AIMAESTRO_SERVER_STATE`
    override → fresh probe file (CONFIDENT membership both ways) → CLI presence
    (absent ⇒ False, present ⇒ None). **The legacy `list --json` subprocess rung is
    REMOVED**: a successful agent-list proves LIVENESS, not capability — keeping it as
    a True source recreates the same conflict one rung lower (a live pre-probe server
    would silence the OAuth chores it does not run). Liveness ≠ capability.
  - `server_owns_family_a()` = capability `family-a` (rung-2 slot now wired, zero
    call-site changes — as designed).
  - `server_owns_chore_class(cap)` — chores gate: `$JANITOR_AIMAESTRO_SERVER_CHORES`
    override (all classes) → memoized `_server_owns_capability(cap)` (per-class memo,
    300 s TTL).
  - `SERVER_ABSORBED_TASK_CLASS` — the SSOT map: oauth-rotator-tick/-supervisor →
    `family-a`; marketplace-refresh / user-plugins-update / version-update →
    `singleton-chores`.
- `daemon.py`: `_task_yielded_to_server(name, owned_by_class)` takes the per-class map;
  `_owned_chore_classes()` resolves it once per loop; maintenance keepalive same.
- `daemon_watchdog.py`: unchanged gate (`server_owns_singleton_chores()` — its only
  callers are the two singleton-chores shims), comment updated to name the class.

**None-policy unchanged:** a chore yields IFF its OWN class token is CONFIDENTLY fresh
and present; False/None ⇒ run (locks remain the collision backstop). Today the server
emits `capabilities: []` (family-a absent until the USER flips R16; singleton-chores
never) ⇒ the janitor keeps ALL chores — the safe default holds by construction.

**Verification:** `tests/test_harness_backend.py` (probe-file ladder: fresh+token ⇒
True, fresh−token ⇒ False, stale/malformed ⇒ None-with-CLI / False-without),
`tests/test_chore_coordination.py` (THE regression: family-a owned + singleton-chores
unknown ⇒ oauth tasks yield, marketplace/version do NOT; per-class map plumbing; memo).

**NEXT ACTION:** shipped code lands on main; `design/ARCHITECTURE.md` → rev 2 (per-class
§2 matrix + §6 filled with their delivered contracts) → post rev 2 + `RATIFIED rev 2`
on #100. Ships in v0.51.0 (Phase 5 release train).

## Notes and lessons learned

[^1]: [id:ATOM-CAPC-BIT1, status:valid, keywords:"one ownership bit gates many chores capability token liveness is not capability yield chores nothing runs shared flag conflates classes", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT gate multiple chore classes on one shared server-ownership bit, BECAUSE the
  first class that goes live flips the bit and silences every other class — chores
  nothing runs. DO gate each class on its OWN capability token, present only while that
  class is live (liveness ≠ capability).
