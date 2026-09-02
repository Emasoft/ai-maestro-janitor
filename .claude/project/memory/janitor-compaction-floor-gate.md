---
name: janitor-compaction-floor-gate
description: "the janitor compacted my context over and over / it keeps compacting every 10 minutes forever / why is the context still huge right after a compaction / what should the auto-compact threshold be / compacting barely shrank anything / who compacts my context now that auto-compact is off / prompt is too long / context window full and nothing happened / how do I turn auto-compact back on / claude stopped responding near the context limit / what is the compaction threshold now / why did the janitor clear my session / where did my context go / the summary replaced my conversation / my session stopped at the context limit instead of compacting / the janitor did not clear even though the cache expired / a busy session never gets cleared / what survives a clear now / 16 agents hung on the externalized compaction / the fleet froze for 40 minutes after a restart / a resume storm serialized every session behind the llm-ext lane / sessions stuck at startup on a blocking SessionStart hook / the compaction fired below the floor because the installed plugin was a stale rollout"
ocd: 2026-07-17
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: proactive-compaction
  globs: []
publish-globally: false
split-lineage: 279f387b68144a63a5744f521e53338f
---

The janitor's PROACTIVE-idle auto-compact trigger (`cold_cache_compact` +
`on-stop-proactive-compact.py` + `dispatch._phase_proactive_idle_compact`) and the one gate that
makes it terminate. Shipped in **v0.49.0** (2026-07-17; TRDD-D3PROACT; the loop fix is `1a69ec6`,
release-bump `b5c298a`). The buggy loop-prone form was NEVER published — it was caught in the
pre-publish batch, so no release ever shipped the size-only gate.

This page is the map — the fact detail lives in three sub-pages (split 2026-09-02 to stay under
the page-size cap; no fact moved, only relocated).

## Applies to

- [[janitor-compaction-floor-gate-hooks]] — the compaction hooks' own correctness bugs: the
  first-turn-after-compaction stale reading, the cold-resume "cache state unknown" refusal, the
  llm-ext-not-on-PATH degrade, and the 2026-08-18 refusal-classified-as-success incident.
- [[janitor-compaction-floor-gate-triggers]] — the harness's own auto-compact being disabled, the
  clear cooldown/payload rules, and the original v0.49.0 floor-gate loop-termination bug + fix.
- [[janitor-compaction-floor-gate-clear-lever]] — the cache-expired trigger, the clear+re-arm
  atomicity rule, the agent-invoked manual compaction lever, the external zero-model-turn clear,
  and the terminal-identity dict-shape trap.

## Governed by

- [[debugging-methodology]] — the general discipline this incident fed back into (a claim asserted
  in three places, measured in none; a gate reused at a new trigger point without re-deriving
  termination).

## See also

- [[janitor-tool-call-cost-law]] — why context size is the cost driver at all, and why shrinking an
  idle context is worth a lossy operation.
- [[janitor-hooks-two-import-conventions]] — the `from lib import state` vs bare `import state`
  trap; both the Stop hook and its tests live on that fault line.

## Notes and lessons learned
