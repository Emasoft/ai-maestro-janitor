---
trdd-id: LU0C5KAR
title: Binary server-liveness chore switch — server running means ALL absorbed chores are its responsibility
column: testing
created: 2026-07-17T19:31:40+0200
updated: 2026-07-17T19:48:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
scope: project
severity: high
related-trdd: [N9YAH5E7, PZLVT2RN, H7NVKSAX]
coordination-issue: janitor#100
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER DIRECTIVE (2026-07-17, verbatim — given to BOTH Claudes, overrides the ratified
rev 3 per-class design):** *"i think you are both making things too complicated. why
don't just detect if the ai-maestro server is running and switch off all the janitor
daemon chores? the ai-maestro server will execute them as soon as it starts and until it
exits. and only when it exits the janitor daemon will detect that the server if not
running anymore and automatically switch on all the chores again. why having to verify
each chores if it is actually running and effective? too complicated. by design, if the
ai-maestro server is running, those chores are its responsibility. so the janitor daemon
must switch off those chores. any other event is a bug."*

**The ruling, restated as the contract:** responsibility follows PROCESS LIVENESS, not
per-chore capability. A fresh `~/.aimaestro/server-liveness.json` (ts within the 90 s
staleness window) means the server is RUNNING ⇒ the janitor's #N daemon yields ALL
absorbed chores (oauth-rotator-tick, oauth-rotator-supervisor, marketplace-refresh,
user-plugins-update, version-update). File absent or stale ⇒ server not running ⇒ the
janitor runs them all. The `capabilities` list in the probe becomes informational — the
janitor no longer reads it. A running server that does not actually execute an absorbed
chore is, by the owner's definition, a SERVER BUG to fix there — never something the
janitor compensates for with per-class verification.

**What this replaces:** TRDD-N9YAH5E7's per-class capability gating (v0.51.0, `616ab18`)
— capability-token membership checks, the per-class memo, the CLI-presence rung. The
liveness FILE + staleness window survive unchanged (they ARE the running-detector); only
the per-class interpretation is removed. ARCHITECTURE.md §2/§6 → rev 4; posted on #100
for re-ratification (the server half must now run every absorbed chore whenever it runs
— including resolving R16 vs "OAuth runs nowhere while the server is up with R16 off",
which is theirs + the owner's to settle).

**Known transition consequence (stated, accepted by the directive):** the current
ai-maestro build writes the probe at boot with `capabilities: []` while its chores are
inert/unbuilt — under the binary rule, starting THAT server silences the janitor's
chores without the server picking them up. Per the directive this is a server bug (build
the chores / don't run the server until they exist), not a janitor guard to keep. Today
the file is absent on disk, so nothing changes until they restart a server on the probe
build.

**Janitor-side changes (this TRDD):**
- `harness_backend.py`: `server_is_alive()` = fresh, well-formed probe file (override
  rung kept for tests); `server_owns_chore_class` / `server_owns_family_a` /
  `server_owns_singleton_chores` become thin aliases of it returning True/False (the
  None tri-state collapses — binary by design); `SERVER_ABSORBED_TASK_CLASS` map →
  `SERVER_ABSORBED_TASKS` frozenset (WHICH tasks yield still matters; their class no
  longer does).
- `daemon.py`: `_owned_chore_classes()` → one `server_is_alive()` snapshot per loop;
  `_task_yielded_to_server(name, server_alive)`.
- Tests: the per-class regression suite is REPLACED (its load-bearing case — family-a
  live must not silence singleton-chores — is now inverted BY DESIGN): new pins are
  fresh-file ⇒ ALL absorbed yield (capabilities content irrelevant, `[]` included);
  absent/stale/malformed ⇒ ALL run.

**IMPLEMENTED (2026-07-17 evening, same session as the directive):**
`harness_backend.server_is_alive()` + `server_runs_chores()` (binary; env overrides
first; no memo — one small file read per 60 s tick); `SERVER_ABSORBED_TASKS` frozenset
replaced the task→class map; `server_owns_family_a` / `server_owns_chore_class` /
`server_owns_singleton_chores` / `_server_owns_capability` / the per-class memo / the
CLI-presence rung / the CAP_* tokens all REMOVED (no legacy path);
`daemon._task_yielded_to_server(name, server_alive)` + `_yielded_task_names` binary;
`daemon_watchdog` gates on `server_runs_chores()`. Tests rewritten to the binary pins
(fresh file — even `capabilities: []` — ⇒ ALL absorbed yield; absent/stale/malformed ⇒
ALL run; watchdog silent iff yielding). ARCHITECTURE.md → rev 4 PROPOSED (§2 binary
switch; §6.1 "writing the file IS the claim", capabilities informational; §6.2
conflict class redefined away; ratification-log entry). CLAUDE.md prose + repomap
regenerated. 101 tests green across the affected suites, ruff clean.

**NEXT ACTION:** ships in v0.52.0 (same train as TRDD-8DR0X08A) → post rev 4 +
janitor-side `RATIFIED rev 4` on #100 — the server half to ratify: writing a fresh
probe file now claims ALL absorbed chores (implement them as
unconditional-while-running; resolve R16-off ⇒ OAuth dark while the server runs, which
is now by definition a server bug).

## Notes and lessons learned

[^1]: [id:ATOM-LIVN-BIN1, status:valid, keywords:"per class capability gating too complicated responsibility follows liveness binary switch server running owns chores coverage gap is a server bug", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT build per-capability verification into a two-daemon handoff when the owner has
  assigned responsibility by PROCESS ("if it runs, the chores are its"), BECAUSE the
  defensive complexity guards against a state the owner has defined as a bug to fix at
  the source. DO gate on liveness alone and file the coverage gap as the other side's
  bug.
