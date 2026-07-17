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
makes it terminate. Shipped 2026-07-17 (TRDD-D3PROACT; commits `1a69ec6`, `4b2c15c`).

## Governed by

- [[debugging-methodology]] — the general discipline this incident fed back into (a claim asserted
  in three places, measured in none; a gate reused at a new trigger point without re-deriving
  termination).

^compaction-does-not-shrink-the-base [desc: a_compaction_only_removes_the_transcript_never_the_base_that_reloads_after_it, keywords: compacting barely shrank anything, context still huge right after compacting, why is my context 300k on a fresh compact, compaction only freed 10 percent, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
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

^size-only-gate-cannot-terminate [desc: a_repeating_compact_trigger_gated_on_size_alone_loops_forever_because_the_floor_exceeds_the_threshold, keywords: janitor compacted my context over and over, compacts every 10 minutes forever, infinite compact loop, auto compact fires again and again, cooldown did not stop it, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**A REPEATING auto-compact trigger gated on context size alone CANNOT terminate when the
post-compaction floor sits above the threshold.** With floor 308,644 > threshold 270,000: compact →
land at the floor → still over → cooldown expires → compact again → forever, destroying context
each cycle. No threshold value fixes this in general, because the floor is set by the install, not
chosen by us.

**A cooldown DEFERS a loop; it never ends one.** It was the only thing standing between this design
and a 10-minute context-destruction cycle, and it was mistaken for a stop.

The bug entered by REUSE: the size-only gate was safe for the two ORIGINAL triggers because they
are RARE — SessionStart fires once per session, the rate-limit path once per limit. It became a
loop the instant it was reused at Stop, which fires every turn. Nothing about the gate changed; its
trigger frequency did. See [[debugging-methodology]] `^debug-re-derive-termination-on-reuse`.

^floor-gate-is-the-stop [desc: gate_on_reclaimable_tokens_above_the_learned_floor_not_on_context_size, keywords: how do I stop the compact loop, what gate makes auto compact terminate, exclude the compaction case, min gain tokens, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**Gate on RECLAIMABLE tokens, not on size:** fire only when `ctx − floor ≥ min_gain` (default
150k, `..._PROACTIVE_IDLE_COMPACT_MIN_GAIN_TOKENS`). This asks the only question that matters —
*would compacting actually free anything?* At the floor the answer is 0, so the trigger goes silent
until real work accumulates above it. It is NOT a permanent latch: a session that grows large again
still gets its compaction.

The floor is LEARNED, never assumed: `post-compact-resume.py` stamps `last-compact.ts`, and the
next **Stop** records the context it observes as the floor (`cold_cache_compact.refresh_floor`).
**Stop is the earliest point at which the post-compaction size is observable at all** — PostCompact
itself is too early, because the compacted size does not exist until a turn has run against it.
Measuring at a turn's end can only OVER-state the floor, which under-states the gain and biases
toward NOT firing: a missed optimization, never a destroyed context.

`last-compact.ts` is a high-water TIMESTAMP, never a consume-once flag — a flag some reader clears
could let a compaction go unobserved, and an unobserved compaction is one whose floor is never
learned, which silently re-opens the loop.

^threshold-must-exceed-the-floor [desc: the_min_context_threshold_is_floor_relative_and_is_the_reactive_paths_only_protection, keywords: what should the auto compact threshold be, why 350k not 270k, cold_cache_compact_min_context_tokens, lower the threshold to save more, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
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
