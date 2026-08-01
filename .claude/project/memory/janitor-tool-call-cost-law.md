---
name: janitor-tool-call-cost-law
description: "why did the re-arm/arm cost so many tokens / is the dynamic cadence actually saving anything or is it wasting more than it saves / how much does one tool call cost / the heartbeat keeps re-arming itself"
ocd: 2026-07-14
lmd: 2026-07-17
metadata:
  node_type: memory
  type: project
  tier: component
---

^tool-call-cost-law [desc: every_tool_round_trip_rereads_the_whole_context_and_is_billed_for_it, keywords: how_much_does_one_tool_call_cost_in_a_claude_code_turn cost_equals_tool_calls_times_context_times_0.1 why_is_a_six_step_skill_expensive, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
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

^cadence-actuation-is-billed [desc: the_dynamic_cadence_control_loop_runs_through_the_model_so_its_actuation_is_billed, keywords: dynamic_cadence_re-arms_and_that_costs_a_full_model_turn dispatch_cannot_call_CronCreate_only_the_model_can optimizer_whose_adjustments_cost_more_than_they_save, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
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

^arming-is-not-the-cost [desc: killing_the_churn_never_means_disarming_the_cron_always_exists, keywords: do_not_disarm_to_save_tokens_the_heartbeat_is_a_cache_keepalive a_renew_is_delete_plus_create_the_janitor_stays_armed_throughout always_on_always_armed, type: project, ocd: 2026-07-14, lmd: 2026-07-14]
**Killing the churn NEVER means disarming.** A renew is a `CronDelete` immediately followed by a
`CronCreate` — the cron never ceases to exist and the janitor is armed throughout. What churns is
how often the cron's PERIOD is rewritten, not whether it exists. Disarming to save tokens is the
recurring misdiagnosis and it BACKFIRES (it kills the cache keep-alive and forces full-price
rebuilds) — a LOCAL-scope note records a session that made exactly that mistake. It is deliberately
NOT linked: this page is PROJECT scope and therefore pushed, so naming a machine-private page would
publish that name to every cloner. Downward references exist for precisely this reason.

## See also

- [[janitor-compaction-floor-gate]] — this law is WHY the janitor compacts an idle context at
  all (context size is the cost multiplier); that page owns when compacting is worth it, and
  the post-compaction FLOOR that caps how much it can ever buy back.

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
