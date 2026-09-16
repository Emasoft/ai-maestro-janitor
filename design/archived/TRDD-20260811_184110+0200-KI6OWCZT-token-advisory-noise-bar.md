---
trdd-id: KI6OWCZT
title: pre-tool-token-budget advisory must clear the actionable-and-anomalous bar
column: complete
created: 2026-08-11T18:41:10+0200
updated: 2026-08-18T19:55:00+0200
implementation-commits: [3890d7b1, 03253c6e]
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

- [x] A routine post-idle cache-miss turn produces NO advisory — the advisory branch was
      deleted OUTRIGHT, not thresholded: `token_meter.evaluate_turn_budget` never appends a
      cache-miss reason to `reasons_advisory` (`:612-637`), so output is the only signal that
      can reach the advisory tier. Pinned by `test_cache_miss_advisory_is_never_emitted`
      (`tests/test_pre_tool_token_budget.py:188`).
- [x] Any surviving advisory is baseline-relative, not fixed-threshold — `robust_baseline` /
      `percentile` over the session's own recent output history, gated by
      `_MIN_OUTPUT_BASELINE_HISTORY = 8` (`token_meter.py:543,575,617`). Pinned by
      `test_warns_over_baseline` and `test_no_baseline_history_stays_silent`, the latter proving
      NO fixed-threshold fallback survives.
- [x] Hard-block behaviour unchanged — the hard tier still fires on a SUSTAINED cache-miss
      pattern and still denies a spawner under ENFORCE; covered by the `test_hard_tier_*` set.
- [x] **#246 answered with the commit id — done 2026-08-18 under the USER's delegation:**
      https://github.com/Emasoft/ai-maestro-janitor/issues/246#issuecomment-5332011821
      cites both commits and names the unreachable-tier follow-up explicitly. The
      commits to cite are `3890d7b1` (the fix) and `03253c6e` (follow-up: the advisory was
      unreachable on a heartbeat-dominated log, so the first fix had shipped a tier that could
      not fire — worth naming in the reply, since the peer's report is what would otherwise read
      as still-open).

## ⏵ COLUMN 2026-08-13: `todo` → `human_review` — nothing here is pullable by an agent

All three implementable boxes are shipped and pinned. The only remaining item is posting a
reply, which only the owner can do. `todo` asserts "ready for an agent to pull", which is false;
`human_review` is the column that means "waiting on a person", so it is the true state and it
stops this card inflating the pullable queue.

## Approval log

- 2026-08-18T19:55:00+0200 — APPROVED (`human_review → complete`) by janitor-main-session under
  the USER's explicit delegation of human_review verdicts this session. The last open box
  (outward-facing #246 reply citing `3890d7b1` + `03253c6e`) was posted under that same
  delegation — our own repo, self-identified first line, no bare mentions. All four boxes now
  ticked; commits in v3.3.16.
