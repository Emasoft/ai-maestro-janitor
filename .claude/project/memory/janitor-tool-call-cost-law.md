---
name: janitor-tool-call-cost-law
description: "why did the re-arm/arm cost so many tokens / is the dynamic cadence actually saving anything or is it wasting more than it saves / how much does one tool call cost / the heartbeat keeps re-arming itself / why did one ordinary turn cost 500k cache_creation tokens / a cache break I cannot explain / an msg[N] block-changed fingerprint blames the wrong message / should I disarm the janitor to save tokens / does disarming save money or does it backfire / is a config change to the cron actually free / why does a cadence tier flap between fast and slow / what does turn_cost equal in terms of tool calls / how many tool calls does janitor-arm actually cost / a cache_creation spike appeared out of nowhere / distrust an absolute-index cache-break diff / why did one turn cost 500k cache_creation tokens / is there a re-arm cooldown"
ocd: 2026-07-14
lmd: 2026-08-16
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

^tool-call-cost-law [desc: every_tool_round_trip_rereads_the_whole_context_and_is_billed_for_it, keywords: how_much_does_one_tool_call_cost_in_a_claude_code_turn cost_equals_tool_calls_times_context_times_0.1 why_is_a_six_step_skill_expensive every_tool_round-trip_re-reads_the_whole_context dead_linear_at_52k_per_call_on_a_520k_context a_skills_step_count_is_its_price_tag fold_shell_steps_into_one_script_to_cut_re-reads cache_read-driven_so_only_the_0.1x_price_enters_it a_quiet_heartbeat_fire_is_one_tool_call turn_cost_formula_tool_calls_times_context_times_0.1 how_much_does_one_tool_call_cost cost_is_driven_by_tool-call_count_not_work_per_call, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**Every tool round-trip re-reads the ENTIRE conversation at the 0.1× cache-read rate.** So the
cost of a turn is driven by its TOOL-CALL COUNT, not by how much work each call does:

```
turn_cost ≈ tool_calls × context_tokens × 0.1
```

Measured on this repo's own `.janitor/state/token-meter.jsonl` (2026-07-14, ~520k context;
weighted = `output + input + cache_creation + 0.1×cache_read`[^3]): **1 call ≈ 52k · 3 ≈ 157k ·
6 ≈ 311k** — dead linear at ~52k/call, which is exactly `520k × 0.1`. A quiet heartbeat fire is
ONE tool call. [^2]

The law is **`cache_read`-driven, so the 0.1× is the only price that enters it** — it is unaffected
by how the janitor weights a cache WRITE, and the numbers above stand regardless.

The practical consequence: **a skill's step count is its price tag.** Folding four shell steps into
one script is not cosmetic — it removes three full context re-reads. This is why `/janitor-arm` runs
`arm_prepare.py` + `arm_record.py` instead of six inline bash blocks (TRDD-DLI76AUC).

^cadence-actuation-is-billed [desc: the_dynamic_cadence_control_loop_runs_through_the_model_so_its_actuation_is_billed, keywords: dynamic_cadence_re-arms_and_that_costs_a_full_model_turn dispatch_cannot_call_CronCreate_only_the_model_can optimizer_whose_adjustments_cost_more_than_they_save is_the_dynamic_cadence_actually_saving_anything payback_time_equals_arm_tool_calls_over_fires_saved_per_hour demoting_the_cadence_needs_30_to_45_minutes_to_break_even the_context_size_cancels_out_of_the_payback_threshold no_re-arm_cooldown_causes_flapping_between_tiers observed_a_tier_flap_in_25_minutes_saving_nothing heartbeat_cadence_demote_fires_defaults_to_two why_did_the_re-arm_cost_so_many_tokens a_tier_change_is_a_full_claude_turn_not_a_config_write, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**The dynamic cadence's control loop runs through the MODEL, so its actuation is billed at model
rates.** `dispatch.py` CANNOT call `CronCreate` — only the model can — so a tier change is not a
config write, it is a **full Claude turn**: the dispatcher emits `[janitor-renew]`, the session runs
`/janitor-arm`, and that arm costs (post-TRDD-DLI76AUC) 4 tool calls ≈ 4 quiet fires. It was 6. [^1]

TRDD-0QQX9H0G priced the FIRES it saves but never the TRANSITIONS it costs. So:

```
payback_time = arm_tool_calls / fires_saved_per_hour
```

Demoting `*/5 → */15` saves 8 fires/hour ⇒ at 6 calls the demotion needs **45 min** to break even;
at 4 calls, **30 min**. **The context size CANCELS OUT** — the arm cost and the fire saving are both
0.1× reads scaling linearly with session size — so this threshold is a **CONSTANT**, not something
to tune per session. That is the load-bearing fact.

`heartbeat_cadence_demote_fires` defaults to **2**, which at `*/5` is **10 minutes** — so the
janitor commits a demotion ~4.5× sooner than it can pay for it, and any activity inside the next
35 min re-promotes it. Observed live 2026-07-14: `*/15 → */5 → */15` in **25 minutes** — two renews,
~620k weighted, saving nothing. There is **no re-arm cooldown** anywhere. Raising the hysteresis to
match the payback is the open fix (deferred, not yet approved — see TRDD-DLI76AUC §Deferred).

^arming-is-not-the-cost [desc: killing_the_churn_never_means_disarming_the_cron_always_exists, keywords: do_not_disarm_to_save_tokens_the_heartbeat_is_a_cache_keepalive a_renew_is_delete_plus_create_the_janitor_stays_armed_throughout always_on_always_armed should_I_disarm_the_janitor_to_save_tokens disarming_backfires_and_forces_full-price_rebuilds the_cron_never_ceases_to_exist_only_its_period_changes killing_the_churn_never_means_disarming what_churns_is_how_often_the_period_is_rewritten a_renew_is_delete_then_create_never_a_gap_in_arming disarming_kills_the_cache_keep-alive_and_forces_full-price_rebuilds a_local-scope_note_records_a_session_that_made_this_mistake disarming_is_the_recurring_misdiagnosis, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**Killing the churn NEVER means disarming.** A renew is a `CronDelete` immediately followed by a
`CronCreate` — the cron never ceases to exist and the janitor is armed throughout. What churns is
how often the cron's PERIOD is rewritten, not whether it exists. Disarming to save tokens is the
recurring misdiagnosis and it BACKFIRES (it kills the cache keep-alive and forces full-price
rebuilds) — a LOCAL-scope note records a session that made exactly that mistake. It is deliberately
NOT linked: this page is PROJECT scope and therefore pushed, so naming a machine-private page would
publish that name to every cloner. Downward references exist for precisely this reason.



^ATOM-E98O-SQZG [desc: "A large cache_creation on an ordinary turn is usually client-side: one measured break came from cache_control moving off the previous last message, not from any edited text", keywords: cache_break_rebuilt_the_whole_prefix huge_cache_creation_on_an_ordinary_turn cache_control_moved why_did_one_turn_cost_500k_tokens prompt_cache_orphaned two_calls_51_seconds_apart_diverged_by_535k_tokens cache_control_ephemeral_ttl_annotation_disappeared the_marker_rides_the_currently-last_message client-side_claude_code_behaviour_not_a_plugin_or_hook rule_out_cold_start_compaction_growth_before_blaming_edits editing_an_injected_instruction_file_mid-session_costs_150k the_causal_step_is_supported_not_proven, type: reference, ocd: 2026-08-16, lmd: 2026-08-16]

**A large `cache_creation` on an ordinary turn is usually NOT something you did.** Measured on this
repo's own traces 2026-08-13 (report under `reports/ij94o8yd/`): two consecutive calls 51 s apart
went 553,919 cache_read → **535,371 cache_creation**, with 816 of 925 body parts BYTE-IDENTICAL.
The first divergence was a message whose visible text was identical in both — the only delta was
that `"cache_control":{"type":"ephemeral","ttl":"1h"}`, present on it in the earlier request, was
gone in the later one (762 → 714 bytes, exactly the annotation's length). The marker rides the
currently-LAST message and moves as the conversation grows: client-side Claude Code behaviour, not
a plugin, rule file, or hook, and not preventable from one. The causal step is SUPPORTED, not
proven — the diff shows the annotation removed; where it went was never confirmed.

Practical order when a spike appears: rule out the expected causes first (cold start, compaction,
append-only growth), then look for an avoidable one. Editing an injected instruction file
mid-session IS avoidable and costs ~150k, but it is EPISODIC — it shows up in a measurement window
only when rules were actually edited — and it is not the dominant term.


^ATOM-UND7-X0OB [desc: "Distrust an msg[N] cache-break fingerprint: absolute-index diffing reports a change on ordinary conversation growth — corroborate by sha before acting", keywords: msg_index_N_block_changed unclassified_cache_break cache_break_fingerprint_is_wrong usertext_block_changed_at_pos classifier_blames_the_wrong_message distrust_an_msgN_block-changed_fingerprint_before_acting messages363_reappears_unchanged_at_messages364 the_array_simply_grew_not_a_real_cache_break diffing_the_same_absolute_index_on_a_growing_array corroborate_by_sha_at_shifted_indices_before_believing_it 786_changes_found_across_59_sessions same_sha_after_the_array_grew_by_one, type: reference, ocd: 2026-08-16, lmd: 2026-08-16]

**Distrust an `msg[N] <block> changed` cache-break fingerprint before acting on it.** Scanning this
machine's retained traces for `messages[363]` found 786 "changes" across 59 sessions. Checking one
directly: the earlier body's `messages[363]` reappears UNCHANGED at `messages[364]` in the later
body — same sha. The array simply grew, so a classifier that diffs the SAME absolute index reports
a change on essentially every turn of every long session, whether or not a cache break occurred.
Corroborate by sha at shifted indices before believing the actor string names the culprit.

## See also

- [[janitor-beat-tasks-and-limitations]] — the measured per-fire cost that this law predicts.


- [[janitor-compaction-floor-gate]] — this law is WHY the janitor compacts an idle context at
  all (context size is the cost multiplier); that page owns when compacting is worth it, and
  the post-compaction FLOOR that caps how much it can ever buy back.


## Superseded


^ATOM-Q6AN-1PDO [desc: "Diagnosing a big cache_creation spike: an msg[N] fingerprint is often an index-shift artifact, and one real break came from cache_control moving, not from edited text", keywords: cache_break_rebuilt_the_whole_prefix huge_cache_creation_on_an_ordinary_turn cache_control_moved msg_index_N_block_changed unclassified_cache_break why_did_one_turn_cost_500k_tokens prompt_cache_orphaned archived_superseded_snapshot_of_the_cache_break_diagnosis old_combined_atom_before_the_split_into_two see_the_non-superseded_atoms_for_the_live_facts reconstructed_from_agentlensPros_cas_store historical_record_of_the_original_combined_diagnosis, type: reference, ocd: 2026-08-16, lmd: 2026-08-16, status: superseded, superseded-by: ATOM-E98O-SQZG]

**A large `cache_creation` on an ordinary turn is usually NOT something you did.** Measured on
this repo's own traces 2026-08-13 (report under `reports/ij94o8yd/`), reconstructing real request
bodies from agentlensPro's CAS store after the raw bodies had rotated away:

Two consecutive calls 51 s apart went 553,919 cache_read → **535,371 cache_creation**, with 816 of
925 body parts BYTE-IDENTICAL. The first divergence was a message whose visible text was identical
in both requests — the only delta was that `"cache_control":{"type":"ephemeral","ttl":"1h"}`,
present on it in the earlier request, was gone in the later one (762 → 714 bytes, exactly the
annotation's length). The marker rides the currently-LAST message and moves as the conversation
grows. That is client-side Claude Code behaviour: nothing in a plugin, a rule file, or a hook
caused it, and nothing in one can prevent it. (The causal step is supported, not proven — the diff
shows the annotation removed; where it went was never confirmed.)

**And distrust an `msg[N] <block> changed` fingerprint before acting on it.** Scanning for
`messages[363]` found 786 "changes" across 59 sessions. Checking one directly: the earlier body's
`messages[363]` reappears UNCHANGED at `messages[364]` in the later body — same sha. The array
grew, so a classifier diffing the SAME absolute index reports a change on essentially every turn
of every long session, whether or not a cache break occurred. Corroborate by sha before believing
the actor string.

**Practical order when a spike appears:** classify the expected causes first (cold start,
compaction, append-only growth), and only then look for an avoidable one. Editing an injected
instruction file mid-session IS avoidable and costs ~150k — but it is EPISODIC (it appears in a
measurement window only when rules were actually edited) and it is not the dominant term.
## Notes and lessons learned

[^1]: [id:ATOM-MG05-0013, status:valid, keywords:"optimizer_actuation_billed_at_model_rate price_the_actuation_not_steady_state hysteresis_or_negative_value", ocd:2026-07-14, lmd:2026-07-14] An optimizer whose control loop runs through the MODEL is
  itself billed at model rates. TRDD-0QQX9H0G's dynamic cadence modelled the steady state (fewer
  fires = less cost) and never modelled its own actuation — because in most systems changing a cron
  is a free config write. Here it is a Claude turn. An optimizer whose adjustments cost more than
  they save is a pessimizer, and this one demonstrably was whenever the tier flapped. Lesson: when
  the feedback loop passes through a billed agent, **price the actuation, not just the steady
  state** — and if you cannot make the adjustment cheap, make it RARE (hysteresis) or the feature
  is negative-value in exactly the volatile conditions it was built for.

[^3]: [id:ATOM-MG05-0014, status:valid, keywords:"grep_prose_not_what_code_does cache_creation_weight_1x_not_docstring read_the_expression_that_computes_it", ocd:2026-07-14, lmd:2026-07-14] This page first wrote the formula as
  `output + 1.25×cache_creation + 0.1×cache_read`. The code weights `cache_creation` at **1.0×**
  (`token_baseline.weighted_tokens`, `token_history.weighted`) — the `1.25` lives only in the
  surrounding DOCSTRINGS, and I asserted the arithmetic from a grep of the prose instead of reading
  the expression. That is the SECOND time in one session I claimed code behavior from a string match
  (see `[^7]` on the TRDD-CGYMUKO6 page: a grep for `add_parser(` "proved" two subcommands did not
  exist; they were registered in a loop). Compounding it, `1.25×` is the **5-minute-TTL** write
  price; the main agent runs a **1-hour** TTL where a write costs **2×**. So the metric is a
  RELATIVE load index that under-counts a cache-miss turn ~2× — deliberately, since every learned
  baseline is calibrated against it. Lesson: **a grep of prose tells you what the author BELIEVED,
  never what the code DOES.** To state what code does, read the expression that computes it.

[^2]: [id:ATOM-MG05-0015, status:valid, keywords:"fuzzy_join_invented_relationship approximate_key_join_false_number law_in_raw_rows_not_summary_stat", ocd:2026-07-14, lmd:2026-07-14] I first "measured" the arm's cost by joining the token meter's
  records to arm timestamps with a ±4-minute window, and reported an arm costs 25× a quiet fire. It
  does not — the matched record had 39 tool calls and was an unrelated WORK turn. The number came
  from my own fuzzy join, not from the data. Lesson: a join on an approximate key INVENTS a
  relationship the data never asserted. Prefer a law visible in the RAW ROWS (here: cost scales with
  the `tool_calls` column, plain to see) over a summary statistic computed from a guessed mapping.
