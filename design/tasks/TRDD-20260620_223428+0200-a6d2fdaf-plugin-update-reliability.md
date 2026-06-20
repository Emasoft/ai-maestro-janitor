---
trdd-id: a6d2fdaf-3f86-45ac-9e05-51bd54402bb9
title: Janitor plugin-update reliability — per-session reload nudge + cache prune
column: dev
created: 2026-06-20T22:34:28+0200
updated: 2026-06-20T22:34:28+0200
current-owner: ai-maestro-janitor-session
task-type: bugfix
release-via: publish
test-requirements: [unit, lint, typecheck]
relevant-rules: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/51"]
---

# TRDD-a6d2fdaf — Janitor plugin-update reliability

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-20

**Trigger:** user reported the MANAGER fleet project "couldn't run CPV — agents
not registered despite being in the cache; the janitor failed to update the
plugin." Investigation (`reports/janitor-plugin-update-investigation/`) proved
the on-disk CPV state is CORRECT (cached 2.137.0 complete + registered + enabled;
agents resolve in a fresh session). The failure is TWO janitor gaps the user
asked to fix, plus finishing the v0.14.x publish sequence.

**Two fixes (this TRDD):**

- **FIX B — per-session reload nudge (ROOT CAUSE).** `reload-needed.flag` was a
  single machine-global boolean; `dispatch._phase_plugin_reload` read it and
  `clear_reload_flag()`-ed it, so the FIRST session to fire consumed the
  `[janitor-reload]` nudge and every OTHER concurrent/autonomous session (a
  fleet agent in a different project) stayed on stale plugin code until restart.
  → Convert the flag to a monotonic GENERATION (epoch), NEVER cleared by a
  reader; each session compares it to a per-project `reload-acked.ts` and
  reloads once when the generation advances. Seed the ack at TRUE session start
  (startup/resume only, not compact/clear) so a session reloads only for updates
  that land AFTER it loaded its plugins.
  - Files: `scripts/lib/global_state.py` (gen API), `scripts/dispatch.py`
    (`_phase_plugin_reload` ack compare-and-advance), `scripts/hooks/on-session-start.py`
    (seed ack, source-aware), tests `test_global_state.py`/`test_dispatch_phases.py`/`test_daemon.py`.

- **FIX A — cache prune (bloat).** Plugin cache is 4.5 GB; CPV alone has 49
  cached versions (it publishes ~3×/day, the janitor pulls each, CC's 7-day GC
  keeps them all). → New daemon task `task_cache_prune` (low cadence): per
  plugin keep {pinned ∪ newest-N} and prune older versions, but ONLY versions
  older than `max(MIN_AGE, oldest-live-claude-session-age + margin)` so a
  long-running session's loaded version is never pruned out from under it.
  - Files: `scripts/lib/cache_prune.py` (pure logic + ps-session-age), `scripts/daemon.py`
    (`task_cache_prune` + register in `_build_tasks`), tests `test_cache_prune.py`.

**NEXT ACTION:** implement FIX B (3 edits + tests), commit; then FIX A (lib +
daemon task + tests), commit; then `uv run scripts/publish.py --minor` (v0.15.0),
watch `gh run watch` green; then post janitor#51 (corrected cache-currency
diagnosis: per-session reload + prune shipped; ai-maestro-plugin lag is by-design
fleet exclusion) + ai-maestro#44 fleet row + handle #52.

**Load-bearing facts:**
- `set_reload_flag(reason)` is the daemon producer (daemon.py:344, 388) — keep
  the name, change it to stamp `<epoch>\t<reason>`.
- The reload flag FILE path is unchanged (`reload-needed.flag`), so a
  currently-running OLD-code session still gets surfaced once via its old
  flag-present logic during the transition update; post-reload all sessions run
  new per-session code.
- Cache prune deletes REGENERATABLE cache (re-downloadable) → plain `rm` is
  correct per use-safe-delete; the SAFETY is the oldest-live-session age gate,
  NOT a fixed floor (CPV's velocity makes any fixed floor either unsafe or
  ineffective).
- `state.read_int_state(path, default)` + `state.atomic_write` are the per-session
  state primitives; `state.state_dir()` is per-PROJECT (the fleet uses one
  project dir per agent, so per-project ≈ per-agent-session — fixes the
  cross-project starvation that was the actual bug).

**SUPERSEDED — do NOT carry forward:**
- ✗ "the janitor failed to download/register CPV" — FALSE; on-disk state is
  correct (proven). The bug is the reload-nudge starvation + cache bloat.
- ✗ "ai-maestro-plugin 6 versions behind is a janitor update bug" — FALSE; it is
  a DELIBERATE fleet-self-manages exclusion (daemon log: "5 ai-maestro-plugins
  member(s) excluded").

**Durable artifacts:**
- `reports/janitor-plugin-update-investigation/20260620_214906+0200-cpv-not-registered-diagnosis.md`
