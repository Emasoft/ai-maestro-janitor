---
trdd-id: KI6OWCZT
title: pre-tool-token-budget advisory must clear the actionable-and-anomalous bar
column: todo
created: 2026-08-11T18:41:10+0200
updated: 2026-08-13T04:43:15+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#246, janitor#230, TRDD-G4BCRUP7]
---

# The token-spike advisory must clear the noise bar

## Why (janitor#246, AgentlensPro peer)

`scripts/hooks/pre-tool-token-budget.py`'s cache-miss advisory fires on ordinary turns and
**its own text explains why the event is expected** ("a cache-miss write happens once when the
prompt prefix changes — an idle gap >5 min, or a recent compaction — ... already happened and
cannot be undone"). Three failures, all conceded by the message itself:

1. **Not actionable** — the cost is already incurred at the moment of the interruption.
2. **Not anomalous** — an idle gap >5 min is routine; a long session crosses it constantly.
3. **Worst position** — PreToolUse lands it BETWEEN a tool call and its result, mid-task.

At ~20 concurrent sessions on one machine this is fleet-wide interruption for a normal cost.
Same family as #230 (hooks pushing unsolicited telemetry into agent context), which the OWNER
raised — this is that complaint, one hook over.

## What — the three-test bar (the peer's, adopted verbatim)

A model-facing hook line may fire only if ALL hold:
- **own-project** — never names another project's session, cwd, or agent kinds;
- **actionable now** — the reader can change what it is about to do (an already-incurred cost
  fails this);
- **significant** — a real anomaly vs this session's OWN recent baseline, not a fixed token
  threshold.

Concretely in `pre-tool-token-budget.py`:
1. **Delete the cache-miss/cache-creation advisory branch outright** unless a use survives the
   bar — the "already happened" wording is proof it cannot be actionable. (Check the module for
   an advisory tier that IS actionable — e.g. an OUTPUT-token spike a caller can still abort —
   and keep only that.)
2. Any surviving advisory switches from a fixed threshold to a multiple of the session's own
   recent baseline (`token_baseline.robust_baseline` / `anomaly_score` already exist — reuse,
   do not reinvent).
3. The HARD-block tier (if any) is unchanged; this card is about the ADVISORY chatter only.
4. Tests: routine idle-gap cache-miss → SILENT; a genuine multi-sigma anomaly → still fires;
   the hard tier unaffected.

## Acceptance

- [ ] A routine post-idle cache-miss turn produces NO advisory (test)
- [ ] Any surviving advisory is baseline-relative, not fixed-threshold (test)
- [ ] Hard-block behavior byte-identical (test)
- [ ] #246 answered with the commit id
