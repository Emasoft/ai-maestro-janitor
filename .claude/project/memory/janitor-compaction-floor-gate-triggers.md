---
name: janitor-compaction-floor-gate-triggers
description: "the janitor compacted my context over and over / it keeps compacting every 10 minutes forever / compacting barely shrank anything / why is the context still huge right after a compaction / what should the auto-compact threshold be / who compacts my context now that auto-compact is off / how do I turn auto-compact back on / claude stopped responding near the context limit / why did the janitor clear my session / what survives a clear now / the clear cooldown is too long / cache expired but nothing happened / why did the janitor not clear after the cache died / a busy session never gets cleared / prompt is too long / context window full and nothing happened / what is the compaction threshold now / infinite compact loop / auto compact fires again and again / does a cooldown end a loop or just defer it / what is the floor vs the threshold / skills missing after compaction"
ocd: 2026-07-17
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: proactive-compaction
  globs: ["scripts/lib/cold_cache_compact.py"]
publish-globally: false
split-lineage: 279f387b68144a63a5744f521e53338f
---

The harness's own auto-compact being disabled and the janitor's replacement triggers (the clear
cooldown, the post-clear payload order), plus the original v0.49.0 floor-gate loop-termination
bug and its fix. Split out of [[janitor-compaction-floor-gate]] (the hub overview) 2026-09-02 —
every fact below is unchanged from that page.

^ATOM-Q656-7J9E [desc: "2026-08-23: the HARNESS no longer compacts — autoCompactEnabled false, so a full window is a HARD ERROR and only the janitor's triggers prevent it", keywords: auto_compaction_disabled autoCompactEnabled_false who_compacts_my_context_now janitor_compacts_instead_of_claude_code context_limit_error_instead_of_compacting session_stops_at_the_context_boundary llm-externalizer_compaction_only context_pressure_trigger busy_session_never_gets_cleared how_do_I_turn_auto_compact_back_on prompt_is_too_long context_window_full_and_nothing_happened claude_stopped_responding_near_the_limit my_long_session_died_suddenly TRIGGER_CONTEXT_PRESSURE CLAUDE_CODE_AUTO_COMPACT_WINDOW CLAUDE_PLUGIN_OPTION_CLEAR_CONTEXT_HIGH_WATER high_water_mark_vs_floor min_context_is_not_protection why_did_my_active_session_never_compact idle_only_triggers_miss_busy_sessions who_owns_compaction_now harness_vs_janitor_compaction disable_auto_compact_settings_json, type: project, ocd: 2026-08-23, lmd: 2026-08-23]

**The harness does not compact any more.** `"autoCompactEnabled": false` is set in
`~/.claude/settings.json` (owner, 2026-08-23, TRDD-79LXF6PJ). Every compaction is the janitor's
external clear, its payload produced by `llm-ext session-summary` — free models, out of process,
zero tokens from the session being compacted.

**The consequence that bites: a full window is now a HARD ERROR, not a compaction.** The docs are
explicit — the session stops at the boundary, no automatic recovery (`/compact` still works by
hand). So the janitor's triggers are the ONLY thing between a session and a hard stop, and until
2026-08-23 all four (`next-fire-misses`, `long-idle`, `cache-certain-expired`, `resumed-cold`)
were IDLE or CACHE conditions. **A busy session — working, cache warm, never idle — was
structurally unreachable by every one of them.** `min_context_tokens()` is a FLOOR ("nothing worth
reclaiming"), never a high-water mark; reading it as protection is the trap.

`TRIGGER_CONTEXT_PRESSURE` closes that and is checked FIRST — the other four are economies (avoid
a cold-cache write), this one is survival. It does NOT outrank the safety vetoes: `awaiting_user`
still wins, because a context-limit error is recoverable by the user and a discarded question is
not. High-water resolves `CLAUDE_PLUGIN_OPTION_CLEAR_CONTEXT_HIGH_WATER` →
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` → **0 = DISABLED**; no hardcoded default, because windows differ
~5x between models. **0 means a busy session has no backstop** — check before assuming coverage. [^8]


^ATOM-LMYC-WI62 [desc: "the clear cooldown is 300s not 2h — min_context was always the real repeat-guard, and 2h suppressed the very cache-expired fires it was meant to allow", keywords: clear_cooldown_too_long cache_expired_but_nothing_happened why_did_the_janitor_not_clear_after_the_cache_died cooldown_suppressed_the_clear compacting_it_twice DEFAULT_CLEAR_COOLDOWN_SECONDS 2h_cooldown_too_long five_minute_cooldown janitor_waited_two_hours_to_clear clear_fired_once_then_never_again cache_expired_but_cooldown_blocked_it repeat_clear_guard why_is_there_a_cooldown_at_all min_context_is_the_real_repeat_guard idle_clear_fired_ts CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_COOLDOWN_SECONDS, type: project, ocd: 2026-08-23, lmd: 2026-08-23]

**The clear cooldown is 300s, not the 7200s it was** (owner, 2026-08-23: *"a cache can expire at
any time.. 5 minutes is enough.. the 300k boundary already protects against useless
compactions"*).

The 2h encoded a MISCONCEPTION: that the cooldown was what stopped a cleared session clearing
again, so it had to outlast any re-fattening. It never did that job — `min_context` (300k) does,
vetoing ahead of every trigger, and a just-cleared session sits an order of magnitude below it, so
a second clear is impossible on size alone. The cooldown only has to cover the gap between the
chain firing and the context measurement catching up: seconds.

**And 2h was ACTIVELY HARMFUL once the cache-expired trigger existed.** A prompt cache dies on its
own schedule, so a session whose cache expired 20 minutes after a clear burned a full
cache-creation write on its whole context and then waited out 100 more minutes before the janitor
was permitted to act — the cooldown suppressing precisely the fires that trigger was added to
catch. A guard aimed at a problem another guard already solved, blocking the one case it was never
meant to touch.

Pinned as a VALUE. The pre-existing `test_clear_cooldown_suppresses_a_repeat` computes its
boundary FROM the constant, so it passes at any value and would stay green if 7200 returned — it
pins the mechanism, never the decision.


^ATOM-AUCL-C04J [desc: "the post-clear payload is ACTIVE SKILLS in full then the llm-ext summary; no summary means NO CLEAR, reversing the earlier always-clear ruling", keywords: what_survives_a_clear_now no_handoff_after_the_clear skills_missing_after_compaction summary_references_a_skill_I_no_longer_have why_did_the_janitor_decline_to_clear no_summary_no_clear empty_payload_declined skills_not_reinjected_after_clear active_skills_in_full order_of_injection_after_clear skills_before_summary dangling_skill_reference command_name_vs_Skill_tool_call active_skills_extractor slash_invoked_skills_are_invisible resolution_is_the_filter llm_ext_returned_nothing_so_no_clear declined_to_clear_blind post_clear_payload_shape, type: project, ocd: 2026-08-23, lmd: 2026-08-23]

**The post-`/clear` payload is: ACTIVE SKILLS in full, THEN the `llm-ext session-summary`.** The
order is a requirement, not a preference (owner, 2026-08-23) — the summary describes a session
that had those skills loaded, so it REFERS to them; placed after it, they arrive too late to
resolve references the reader has already hit.

"Active" means INVOKED IN THAT SESSION, not every installed skill — the broad reading injects tens
of thousands of tokens the session never touched, defeating the clear. `lib/active_skills.py`
extracts them from the transcript, and matches TWO shapes: a `Skill` tool call AND
`<command-name>/plugin:skill</command-name>`. **A first draft looked only for the tool call and
found ZERO in a session that had visibly run two skills** — slash-invoked skills never produce
one. Resolution IS the filter: `/clear` and `/reload-plugins` share that exact shape, and a name
survives only if it resolves to a `SKILL.md`, so built-ins drop out with no denylist to maintain.

**NO SUMMARY MEANS NO CLEAR.** This REVERSES the 2026-08-13 ruling that the clear must succeed
unconditionally. That ruling was written when a network-free composed template always existed, so
"degrade" meant a smaller handoff. The template is retired, so an empty summary means NOTHING
survives: clearing blind costs the work, declining costs one full-price turn.

^compaction-does-not-shrink-the-base [desc: a_compaction_only_removes_the_transcript_never_the_base_that_reloads_after_it, keywords: compacting_barely_shrank_anything context_still_huge_right_after_compacting why_is_my_context_300k_on_a_fresh_compact compaction_only_freed_10_percent what_reloads_after_every_compaction is_the_floor_per-session_or_per-install does_the_floor_grow_as_plugins_are_added how_do_I_read_the_floor_live_after_a_compaction is_600k_to_50k_a_true_number what_is_the_TRDD-EUWIHP0G_savings_estimate, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
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

^size-only-gate-cannot-terminate [desc: a_repeating_compact_trigger_gated_on_size_alone_loops_forever_because_the_floor_exceeds_the_threshold, keywords: janitor_compacted_my_context_over_and_over compacts_every_10_minutes_forever infinite_compact_loop auto_compact_fires_again_and_again cooldown_did_not_stop_it why_cant_a_size-only_gate_terminate does_a_cooldown_end_a_loop_or_just_defer_it why_did_reusing_a_gate_at_Stop_create_a_loop is_the_bug_in_the_gate_or_in_the_trigger_frequency what_is_the_floor_vs_the_threshold, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
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

^floor-gate-is-the-stop [desc: gate_on_reclaimable_tokens_above_the_learned_floor_not_on_context_size, keywords: how_do_I_stop_the_compact_loop what_gate_makes_auto_compact_terminate exclude_the_compaction_case min_gain_tokens what_is_reclaimable_tokens_vs_context_size does_the_gate_go_permanently_silent_or_only_temporarily what_is_the_default_MIN_GAIN_TOKENS_value would_compacting_actually_free_anything is_the_gate_a_permanent_latch_or_a_temporary_silence does_a_grown_session_still_get_compacted, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**Gate on RECLAIMABLE tokens, not on size:** fire only when `ctx − floor ≥ min_gain` (default
150k, `..._PROACTIVE_IDLE_COMPACT_MIN_GAIN_TOKENS`). This asks the only question that matters —
*would compacting actually free anything?* At the floor the answer is 0, so the trigger goes silent
until real work accumulates above it. It is NOT a permanent latch: a session that grows large again
still gets its compaction.

^ATOM-CMPF-LEAR [desc: the_floor_is_learned_not_assumed_stop_hook_stamps_it, keywords: when_is_the_floor_measured how_is_the_learned_floor_recorded stop_hook_earliest_observable_point post_compact_resume_stamps_last_compact_ts why_not_measure_the_floor_at_PostCompact_instead_of_Stop does_over-stating_the_floor_destroy_context_or_just_miss_savings what_is_cold_cache_compact_refresh_floor is_the_floor_learned_or_assumed why_is_PostCompact_too_early_to_measure_the_floor can_over-measuring_the_floor_destroy_context, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
The floor is LEARNED, never assumed: `post-compact-resume.py` stamps `last-compact.ts`, and the
next **Stop** records the context it observes as the floor (`cold_cache_compact.refresh_floor`).
**Stop is the earliest point at which the post-compaction size is observable at all** — PostCompact
itself is too early, because the compacted size does not exist until a turn has run against it. [^2]
Measuring at a turn's end can only OVER-state the floor, which under-states the gain and biases
toward NOT firing: a missed optimization, never a destroyed context.

^ATOM-CMPF-PRIO [desc: measurement_must_run_before_the_action_gates_that_veto_it, keywords: TRDD-28XF77X6 measurement_behind_cooldown_gate_never_ran floor_needs_learning_check_first record_floor_before_cooldown_check why_did_the_v0.49.0_floor_gate_ship_inert what_is_floor_needs_learning does_the_compaction_itself_hold_the_gates_that_veto_its_own_measurement should_measurement_run_before_or_after_the_action_gates what_is_the_600s_cooldown_that_compaction_stamps why_did_v0.49.0_ship_with_the_floor_gate_inert, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**The measurement runs BEFORE the action gates** (TRDD-28XF77X6, fixed same day v0.49.0 shipped):
both call sites check `cold_cache_compact.floor_needs_learning` (cheap: `last_compact > floor_ts`)
and record the floor FIRST, then apply cooldown / user-present / active-waiting to the compact
decision only. The compaction stamps all three gates itself (`mark_fired` → 600s cooldown; its
auto-resume → `last-resume.ts`, 30-min recency; keep-going → active forever), so a measurement
placed behind them never ran in exactly the unattended sessions the trigger targets — v0.49.0
shipped with the floor gate inert, saved only by the 350k threshold sitting above the ~308k floor. [^3]

^ATOM-CMPF-HWTS [desc: last_compact_ts_is_a_high_water_timestamp_never_consume_once, keywords: is_last_compact_ts_a_flag_or_a_timestamp why_not_clear_last_compact_ts_after_reading high_water_mark_vs_consume_once_flag why_would_clearing_the_stamp_re-open_the_loop what_happens_if_a_compaction_goes_unobserved is_last-compact.ts_ever_consumed_by_a_reader what_makes_a_timestamp_safer_than_a_flag_here does_a_consume-once_flag_risk_losing_the_learning_signal does_a_high-water_mark_ever_move_backward what_reads_last-compact.ts, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
`last-compact.ts` is a high-water TIMESTAMP, never a consume-once flag — a flag some reader clears
could let a compaction go unobserved, and an unobserved compaction is one whose floor is never
learned, which silently re-opens the loop.

^threshold-must-exceed-the-floor [desc: the_min_context_threshold_is_floor_relative_and_is_the_reactive_paths_only_protection, keywords: what_should_the_auto_compact_threshold_be why_350k_not_270k cold_cache_compact_min_context_tokens lower_the_threshold_to_save_more why_do_reactive_compact_paths_have_no_floor_gate does_SessionStart_or_rate-limit_resume_ever_loop what_test_pins_the_threshold_above_the_floor what_happens_if_the_floor_grows_past_350k why_is_the_threshold_floor-relative_not_a_round_fraction why_do_reactive_paths_have_only_one_protection, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**`cold_cache_compact_min_context_tokens` (350k since 2026-07-17, was 270k) MUST sit ABOVE this
install's post-compaction floor.** It is not a round fraction of the window — it is floor-relative.

This matters most for the paths that have NO floor gate: the REACTIVE ones (SessionStart,
rate-limit resume). They fire once per rare event so they cannot loop, but at 270k each would burn
a lossy compaction on a context already sitting at its floor — reclaiming nothing. The threshold is
their only protection.

Pinned by `test_default_threshold_sits_above_the_measured_post_compaction_floor`, so a future
"lower it to 200k for more savings" fails loudly instead of quietly restoring the loop. If the
floor grows past 350k (more plugins/MCP), that test is the alarm — re-measure, don't just bump it.

## Superseded


^ATOM-6CVT-218G [desc: "2026-08-23: the HARNESS no longer compacts at all — autoCompactEnabled false, the janitor clears via llm-ext, and a busy session needs the new context-pressure trigger or it dies at the boundary", keywords: auto_compaction_disabled autoCompactEnabled_false who_compacts_my_context_now janitor_compacts_instead_of_claude_code context_limit_error_instead_of_compacting session_stops_at_the_context_boundary llm-externalizer_compaction_only context_pressure_trigger busy_session_never_gets_cleared clear_cooldown_too_long cache_expired_but_nothing_happened, type: project, ocd: 2026-08-23, lmd: 2026-08-23, status: superseded, superseded-by: ATOM-Q656-7J9E]

**The harness does not compact any more. On this machine, `"autoCompactEnabled": false` is set in
`~/.claude/settings.json`** (owner directive 2026-08-23, TRDD-79LXF6PJ). Every compaction is now
the janitor's external clear, and its payload is produced by `llm-ext session-summary` — free
models, out of process, zero tokens from the session being compacted.

**The consequence that bites: with auto-compact off, a full window is a HARD ERROR, not a
compaction.** The docs are explicit — the session stops at the boundary and there is no automatic
recovery (`/compact` still works by hand). So the janitor's triggers are now the ONLY thing
standing between a session and a hard stop, and until 2026-08-23 all four of them
(`next-fire-misses`, `long-idle`, `cache-certain-expired`, `resumed-cold`) were IDLE or CACHE
conditions. **A busy session — working, cache warm, never idle — was structurally unreachable by
every one of them.** `min_context_tokens()` is a FLOOR ("nothing worth reclaiming"), never a
high-water mark; reading it as protection is the trap.

`TRIGGER_CONTEXT_PRESSURE` closes that, and is checked FIRST: the other four are economies (avoid
paying for a cold cache), this one is survival. It does NOT outrank the safety vetoes —
`awaiting_user` still wins, because a context-limit error is recoverable by the user and a
discarded question is not. Its high-water resolves
`CLAUDE_PLUGIN_OPTION_CLEAR_CONTEXT_HIGH_WATER` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW` → **0 =
DISABLED**. There is deliberately no hardcoded default: windows differ ~5x between models, so a
constant would clear a 1M session five times too early or fire far too late on a 200K one. **0
means a busy session has no backstop at all** — check it before assuming coverage.

The policy, all three pinned by tests:

    context >= high-water                                  -> clear via llm-ext
    cache expired AND context > 300k AND >=5min since last -> clear via llm-ext
    awaiting a human decision                              -> never

The cooldown moved 2h -> **300s** the same day. The 2h assumed the cooldown was what stopped a
cleared session re-clearing; it never was — `min_context` (300k) is, and a just-cleared session
sits an order of magnitude below it. Worse, 2h SUPPRESSED THE VERY FIRES the cache-expired trigger
exists to catch: a cache dies on its own schedule, so a session expiring 20 minutes after a clear
paid a full cache-creation write and then waited out 100 more minutes.

## Governed by

- [[janitor-compaction-floor-gate]] — the hub overview this page is a detail sub-page of.

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

[^8]: [id: ATOM-1J30-7VOB, status: valid, keywords: "16_agents_hung_on_externalized_compaction sessions_frozen_at_startup_for_40_minutes resume_storm_serialized_behind_the_fleet_lane blocking_sessionstart_hook_never_returns external_compaction_hung_without_succeeding llm-ext_summary_timed_out_after_600s_retrying every_session_queued_on_the_llm-ext_lane fleet_resume_freeze no_one_getting_anywhere_after_restart compaction_triggered_below_the_300k_floor installed_plugin_still_has_the_150k_floor stale_rollout_fired_resumed-cold_at_178k", ocd: 2026-08-25, lmd: 2026-08-25] DO NOT run the abandoned-session summarize budget (2600s, unbounded lane wait) inside the BLOCKING on-resume SessionStart hook, BECAUSE a fleet-wide simultaneous resume then serializes EVERY session startup behind the fleet_max_concurrent llm-ext lane at 600s per attempt — measured 2026-08-25: 16 sessions frozen 40+ minutes, zero summaries landed. DO budget resume by the HUMAN clock instead: one attempt (resume_summary_deadline_s, 660s) and a 45s lease-wait cap (RESUME_LEASE_WAIT_S) — a lane still full then IS the storm, decline fast and let the session pay its cold turn.
