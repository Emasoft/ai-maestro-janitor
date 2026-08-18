---
trdd-id: YXY992BN
title: Token-waste origin attribution — classify every cache-miss write from the AgentLens raw API bodies
column: superseded
superseded-by: [agentlenspro-investigate-burn]
created: 2026-07-07T15:26:48+0200
updated: 2026-07-11T13:55:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: M
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
approval-tier: 0
labels: [token-meter, observability, telemetry]
---

# TRDD-YXY992BN — Token-waste ORIGIN attribution (USER directive 2026-07-07)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-11

**SUPERSEDED — do NOT build this.** The tool the USER told us to prefer already does it,
better, today.

This TRDD proposed a home-grown engine to parse `~/.agentlens/otel-bodies/` and classify
the CAUSE of every `cache_creation` spike. **`agentlenspro investigate_burn` already
returns exactly that** — verified live 2026-07-11: it named PREMIUM_MODEL_FANOUT (256
sonnet-5 subagent calls, 34% of the window, ~$21), a FORK_STORM (fat parent forked into a
cold cache), and FAT_SESSION_REWRITES (2%), with a per-workspace/model/kind attribution
table. Building our own would duplicate it, would have to re-derive its heuristics, and
would violate the standing steer (USER, 2026-07-11): *"examine the agentlens skill and
learn how to use the cli diagnostic tool, much better than the current janitor estimations
on token usage."*

**The surviving, non-duplicative part** — CONSUME that output from the heartbeat instead of
re-deriving it — is tracked as **TRDD-HL8H3XCV** (`token-usage-anomaly` ->
`get_burn_status` / `investigate_burn`), under the adoption umbrella **TRDD-WUUR2DFX**.

**Lesson:** before building an observability engine, check whether the observability tool
already installed on the machine answers the question. Here it did, and the home-grown
version would have been strictly worse.

## The task (original — kept for the record; NOT to be implemented)

USER: "i activated the full telemetry of claude code... we need to monitor the origin of
each token waste." The machine now captures — verified live — every raw API request body
to `~/.agentlens/otel-bodies/` (`OTEL_LOG_RAW_API_BODIES`; 6,309 bodies / ~3.0 GB in the
first 4 h) plus OTLP logs/metrics/traces to `localhost:34318`. A raw request body contains
the full prompt composition (system blocks, tool list, message head), so the CAUSE of each
`cache_creation` spike is now decidable — not just its size (which the fixed meter,
TRDD-DILR8G11, reports).

## Plan

1. `scripts/lib/token_origin.py` (pure): given two consecutive request bodies of one
   session, fingerprint the prefix segments (system blocks hash-per-block, tools-list
   hash, message-head hash) and classify the delta:
   - `tool-schema-change` — the tools list changed (e.g. a ToolSearch deferred-tool load;
     measured this session: 3 loads ≈ 2.5M rewrite tokens);
   - `system-churn` — a system block changed (hook-injected dynamic content, statusline);
   - `ttl-gap` — composition identical but >5 min elapsed (prompt-cache TTL expiry);
   - `compaction` — message head replaced/shortened;
   - `growth` — plain transcript append (the healthy case).
2. `scripts/token_origin_report.py` — walk a session's bodies chronologically, join with
   each response's `cache_creation_input_tokens`, print a per-origin waste ledger
   (`N tokens because X, top offenders listed`). Surface via `/janitor-token-report
   --origins`.
3. Retention guard for the capture itself: `~/.agentlens/otel-bodies` grows ~18 GB/day at
   today's rate — same runaway class as the fseventsd incident. Fold an age-based cap into
   the S8 retention work (TRDD-LCO8229M) or a dedicated knob; NEVER unbounded.
4. Optional later: a detector that alarms when one origin class repeats N times/hour
   (e.g. tool-schema thrash), reusing the emit_once dedupe idiom.

## Derived tasks

- Verify the otel-bodies filename ↔ session/request mapping and whether RESPONSE usage is
  co-captured (if only requests are stored, join usage from the transcript by request id).
- Tests: fixture pair of bodies per class → classification; TTL-gap needs an injectable
  clock (no Date.now in fixtures); ledger formatting.
- Keep reads STREAMING (bodies are ~0.5-1.7 MB each; never load the whole dir).

## Verification

- Running the report on this session's bodies attributes the three known ToolSearch
  prefix rewrites to `tool-schema-change` and the post-idle rewrites to `ttl-gap`.
- The ledger's per-origin totals sum to the session's total cache_creation within 5%.
