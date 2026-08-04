---
name: janitor-compaction-floor-gate
description: "the janitor compacted my context over and over / it keeps compacting every 10 minutes forever / why is the context still huge right after a compaction / what should the auto-compact threshold be / compacting barely shrank anything"
ocd: 2026-07-17
lmd: 2026-07-17
metadata:
  node_type: memory
  type: project
  tier: component
---

The janitor's PROACTIVE-idle auto-compact trigger (`cold_cache_compact` +
`on-stop-proactive-compact.py` + `dispatch._phase_proactive_idle_compact`) and the one gate that
makes it terminate. Shipped in **v0.49.0** (2026-07-17; TRDD-D3PROACT; the loop fix is `1a69ec6`,
release-bump `b5c298a`). The buggy loop-prone form was NEVER published — it was caught in the
pre-publish batch, so no release ever shipped the size-only gate.

## Governed by

- [[debugging-methodology]] — the general discipline this incident fed back into (a claim asserted
  in three places, measured in none; a gate reused at a new trigger point without re-deriving
  termination).

^compaction-does-not-shrink-the-base [desc: a_compaction_only_removes_the_transcript_never_the_base_that_reloads_after_it, keywords: compacting_barely_shrank_anything context_still_huge_right_after_compacting why_is_my_context_300k_on_a_fresh_compact compaction_only_freed_10_percent, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**A compaction cannot shrink the BASE — only the transcript above it.** After every compaction the
harness reloads CLAUDE.md, every enabled plugin's skills/agents/hooks, `~/.claude/rules/*`, the MCP
tool schemas, and the freshly-written summary. That floor is a property of the INSTALL, not of the
conversation, so it is identical after every compaction.

Measured on this repo 2026-07-17 (~10 plugins + several MCP servers): a real compaction went
**343,007 → 308,644** — a 10% shrink. The often-quoted "compaction takes ~600k → ~50k" is FALSE on
a heavy install; TRDD-EUWIHP0G's cold-burn savings estimate was written against that wrong premise.

The floor is per-machine and GROWS as plugins/MCP servers are added — so any threshold expressed
relative to it must be re-measured, never assumed. Read it live with
`token_meter.latest_context_size` on the first turn after a compaction.

^size-only-gate-cannot-terminate [desc: a_repeating_compact_trigger_gated_on_size_alone_loops_forever_because_the_floor_exceeds_the_threshold, keywords: janitor_compacted_my_context_over_and_over compacts_every_10_minutes_forever infinite_compact_loop auto_compact_fires_again_and_again cooldown_did_not_stop_it, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**A REPEATING auto-compact trigger gated on context size alone CANNOT terminate when the
post-compaction floor sits above the threshold.** With floor 308,644 > threshold 270,000: compact →
land at the floor → still over → cooldown expires → compact again → forever, destroying context
each cycle. No threshold value fixes this in general, because the floor is set by the install, not
chosen by us.

**A cooldown DEFERS a loop; it never ends one.** It was the only thing standing between this design
and a 10-minute context-destruction cycle, and it was mistaken for a stop. [^1]

The bug entered by REUSE: the size-only gate was safe for the two ORIGINAL triggers because they
are RARE — SessionStart fires once per session, the rate-limit path once per limit. It became a
loop the instant it was reused at Stop, which fires every turn. Nothing about the gate changed; its
trigger frequency did. See [[debugging-methodology]] `^debug-re-derive-termination-on-reuse`.

^floor-gate-is-the-stop [desc: gate_on_reclaimable_tokens_above_the_learned_floor_not_on_context_size, keywords: how_do_I_stop_the_compact_loop what_gate_makes_auto_compact_terminate exclude_the_compaction_case min_gain_tokens, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**Gate on RECLAIMABLE tokens, not on size:** fire only when `ctx − floor ≥ min_gain` (default
150k, `..._PROACTIVE_IDLE_COMPACT_MIN_GAIN_TOKENS`). This asks the only question that matters —
*would compacting actually free anything?* At the floor the answer is 0, so the trigger goes silent
until real work accumulates above it. It is NOT a permanent latch: a session that grows large again
still gets its compaction.

^ATOM-CMPF-LEAR [desc: the_floor_is_learned_not_assumed_stop_hook_stamps_it, keywords: when_is_the_floor_measured how_is_the_learned_floor_recorded stop_hook_earliest_observable_point post_compact_resume_stamps_last_compact_ts, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
The floor is LEARNED, never assumed: `post-compact-resume.py` stamps `last-compact.ts`, and the
next **Stop** records the context it observes as the floor (`cold_cache_compact.refresh_floor`).
**Stop is the earliest point at which the post-compaction size is observable at all** — PostCompact
itself is too early, because the compacted size does not exist until a turn has run against it. [^2]
Measuring at a turn's end can only OVER-state the floor, which under-states the gain and biases
toward NOT firing: a missed optimization, never a destroyed context.

^ATOM-CMPF-PRIO [desc: measurement_must_run_before_the_action_gates_that_veto_it, keywords: TRDD-28XF77X6 measurement_behind_cooldown_gate_never_ran floor_needs_learning_check_first record_floor_before_cooldown_check, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**The measurement runs BEFORE the action gates** (TRDD-28XF77X6, fixed same day v0.49.0 shipped):
both call sites check `cold_cache_compact.floor_needs_learning` (cheap: `last_compact > floor_ts`)
and record the floor FIRST, then apply cooldown / user-present / active-waiting to the compact
decision only. The compaction stamps all three gates itself (`mark_fired` → 600s cooldown; its
auto-resume → `last-resume.ts`, 30-min recency; keep-going → active forever), so a measurement
placed behind them never ran in exactly the unattended sessions the trigger targets — v0.49.0
shipped with the floor gate inert, saved only by the 350k threshold sitting above the ~308k floor. [^3]

^ATOM-CMPF-HWTS [desc: last_compact_ts_is_a_high_water_timestamp_never_consume_once, keywords: is_last_compact_ts_a_flag_or_a_timestamp why_not_clear_last_compact_ts_after_reading high_water_mark_vs_consume_once_flag, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
`last-compact.ts` is a high-water TIMESTAMP, never a consume-once flag — a flag some reader clears
could let a compaction go unobserved, and an unobserved compaction is one whose floor is never
learned, which silently re-opens the loop.

^threshold-must-exceed-the-floor [desc: the_min_context_threshold_is_floor_relative_and_is_the_reactive_paths_only_protection, keywords: what_should_the_auto_compact_threshold_be why_350k_not_270k cold_cache_compact_min_context_tokens lower_the_threshold_to_save_more, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**`cold_cache_compact_min_context_tokens` (350k since 2026-07-17, was 270k) MUST sit ABOVE this
install's post-compaction floor.** It is not a round fraction of the window — it is floor-relative.

This matters most for the paths that have NO floor gate: the REACTIVE ones (SessionStart,
rate-limit resume). They fire once per rare event so they cannot loop, but at 270k each would burn
a lossy compaction on a context already sitting at its floor — reclaiming nothing. The threshold is
their only protection.

Pinned by `test_default_threshold_sits_above_the_measured_post_compaction_floor`, so a future
"lower it to 200k for more savings" fails loudly instead of quietly restoring the loop. If the
floor grows past 350k (more plugins/MCP), that test is the alarm — re-measure, don't just bump it.

## See also

- [[janitor-tool-call-cost-law]] — why context size is the cost driver at all, and why shrinking an
  idle context is worth a lossy operation.
- [[janitor-hooks-two-import-conventions]] — the `from lib import state` vs bare `import state`
  trap; both the Stop hook and its tests live on that fault line.


^ATOM-34JJ-8P4R [desc:"the cold-cache compact trigger is last-turn AGE only, never context size, and its repeat guard must stay longer than its trigger", keywords: the_janitor_did_not_compact_my_big_context_on_restart resumed_session_paid_a_full_cache_write_on_the_first_turn compact_threshold_never_fires cold_cache_compact_dead_code why_is_my_600k_session_not_compacted changing_the_auto_compact_window_changed_janitor_behaviour compact_fired_over_and_over_on_an_idle_session, ocd: 2026-08-04, lmd: 2026-08-04]

The CACHE-EXPIRED compact trigger (`should_compact_on_resume` + `should_compact_after_idle`) fires on ONE thing: the last turn is older than the prompt-cache TTL — 55 min, `DEFAULT_MIN_IDLE_SECONDS=3300`. It consults NO context size (USER directive 2026-08-04). It used to also require `context_tokens >= min_context_tokens()`, and that clause made the whole feature DEAD CODE: `min_context_tokens()` is harness-relative (`CLAUDE_CODE_AUTO_COMPACT_WINDOW - summary_overhead + backstop_margin`), so with the window at 700000 it resolved to 716,000 while Claude Code's own auto-compaction fires at 666,000 — a bar no context can reach, because the harness compacts first. Measured live: the gate returned False at 300k/500k/600k/700k, and resumed 500-600k sessions each paid a full cache WRITE on their first turn. The deeper error was one function serving two different economic events: OVERFLOW compaction (prevent running out of window — correctly defers to the harness) and CACHE-WRITE compaction (the harness has no such feature at all, so there is nothing to defer to). `min_context_tokens()` still exists and still gates the PROACTIVE warm-idle path, which really is asking "did the harness's compaction fail?". [^5]


^ATOM-MQ3R-WT50 [desc:"the compact repeat-guard window must stay LONGER than the expiry trigger, or an idle session compacts on a loop forever", keywords: compact_fired_over_and_over_on_an_idle_session repeat_guard_window did_a_compact_already_happen_recently last-compact.ts_stamp does_the_guard_cover_a_manual_compact_or_auto-compact compact_loop_on_an_abandoned_session, ocd: 2026-08-04, lmd: 2026-08-04]

Two invariants hold the cache-expired compact path together. (1) The TRIGGER (55 min) is deliberately UNDER the 1h prompt-cache TTL, because the last-turn age is measured at CHECK time while the compact turn runs later. (2) The REPEAT guard (`recently_compacted`, 65 min) reads TWO stamps: `last-compact.ts`, which the PostCompact hook writes unconditionally — so it covers a `/compact` the user ran by hand, one a janitor cron fired, AND Claude Code's native auto-compact, none of which the janitor would otherwise know happened — plus our own `cold-compact-fired.ts` for a fire that may not have landed yet. **GUARD (65) > TRIGGER (55) is load-bearing**: reverse them and a permanently idle session clears the guard while still satisfying the trigger, and compacts on a cycle forever. What none of this fixes: a `/compact` is ITSELF a turn, so the FIRST cold read of a resumed context is unavoidable — the win is paying it once instead of carrying the context through every later turn of the window. Getting under that first read needs `/clear`-with-handoff, which is a separate lever (`clear_enabled()`).

## Notes and lessons learned

[^1]: [id:ATOM-CMPF-LOOP, status:valid, keywords:"self_limiting_claim_was_false claimed_it_stops_without_measuring termination_claim_in_docstring", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT write "self-limiting" or any termination claim into a docstring, config description, or
  TRDD without a measurement or test behind it, BECAUSE the claim then propagates as established
  fact — here "after the compact the context is small, so the size gate fails next fire" was
  asserted in all three places, was false in all three, and only the USER's question ("*are you
  sure it actually stops after the compaction ended?*") caught it before it shipped. DO pin every
  termination claim with a regression test carrying the REAL measured numbers.

[^2]: [id:ATOM-CMPF-CRON, status:valid, keywords:"compact_should_run_first cron_fire_burned_tokens_before_compacting cache_creation_burn_at_turn_start", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT expect a heartbeat/cron `/compact` to prevent ITS OWN fire's cold burn, BECAUSE a cron
  fire IS a turn: it re-reads the whole transcript (the cache-creation write) BEFORE `dispatch.py`
  runs as a tool call, so the burn is already paid. DO prevent it upstream — keep an idle context
  small while the cache is WARM (Stop, which fires at the end of every turn, is the event that can;
  crons cannot fire mid-query, so a >1h working turn has no heartbeat inside it).

[^3]: [id:ATOM-OBSV-GATE, status:valid, keywords:"floor_never_learned observation_behind_action_gates compact_floor_json_absent measurement_blocked_by_cooldown gate_inert_in_production", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT place a passive MEASUREMENT behind the gates that veto the ACTION it informs, BECAUSE
  the action's own side effects can hold every gate closed in exactly the target population —
  the compaction stamped the cooldown AND the resume recency, keep-going holds active-waiting
  forever, so `refresh_floor` never ran and v0.49.0's floor gate was inert (verified live: three
  fires after a real compaction, `compact-floor.json` never written). DO gate observations only
  on "is there something unobserved?" (`floor_needs_learning`) and record before any early-return.

[^4]: [id:ATOM-TEST-IMPS, status:valid, keywords:"test_passed_on_impossible_state fixture_missing_side_effects mark_compacted_without_mark_fired regression_test_wrong_state", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT hand-build a test fixture from the ONE stamp the assertion needs, BECAUSE the production
  event writes SEVERAL stamps and the omitted ones may be exactly what blocks the code under test
  — the loop test stamped `mark_compacted` alone (no `mark_fired`, no `last-resume.ts`), a state
  production can never reach, so it proved the floor gate worked in a configuration that does not
  exist. DO reproduce the event's FULL side-effect set, and prove the test FAILS on the pre-fix
  code (stash the fix, run, restore).
[^5]: [id:ATOM-SLM9-5K1D, status:valid, keywords:"a_feature_never_fires_but_its_tests_are_green threshold_derived_from_an_unrelated_setting gate_sits_above_the_point_another_system_already_acts dead_code_that_looks_configured", ocd:2026-08-04, lmd:2026-08-04] DO NOT derive a feature's threshold from a setting that belongs to a DIFFERENT mechanism, BECAUSE the two move independently and the gate can silently drift past the point where that other mechanism already acts — here the cold-compact bar (716,000) sat above Claude Code's own auto-compact point (666,000), so the feature could never fire, every unit test stayed green, and the burn it existed to prevent ran for weeks unnoticed. DO gate on the quantity the feature is actually about (cache expiry is a TIME fact, so trigger on last-turn AGE), and when a threshold must exist, prove it is REACHABLE by evaluating it against the live environment rather than reading the formula.
