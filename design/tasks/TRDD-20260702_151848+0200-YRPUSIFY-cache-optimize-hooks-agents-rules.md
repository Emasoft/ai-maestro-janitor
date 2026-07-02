---
trdd-id: YRPUSIFY
title: Cache-optimize the hooks, spark agent, skills, commands, and rules — stop prefix invalidation + shrink the per-agent floor
column: dev
created: 2026-07-02T15:18:48+0200
updated: 2026-07-02T15:18:48+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: L
task-type: refactor
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
approval-tier: 0
---

# Cache-optimize hooks + spark agent + skills/commands/rules (USER command, 2026-07-02: "immediately")

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **WHY (measured, reports/token-attribution + scratchpad/spark_cost_breakdown.py):** two spark
  agents: peak context ~246k/312k but cache_creation 1.86M/1.84M — a **~7.6× rewrite factor**
  (writes >> final context ⇒ repeated prefix invalidation), plus a **~155-160k first-call base
  write PER AGENT** (the harness floor: system prompt + CLAUDE.md + rules corpus) that is NOT
  shared across agents (early per-session divergence — e.g. the session-id-bearing scratchpad
  path — breaks cross-agent prefix sharing). Output (real work) was only 17-44k.
- **USER command (verbatim):** "immediately rewrite the hooks to be cache optimized, rewrite the
  spark agent to be cache optimized, and rewrite the skills and commands and rules to be cache
  friendly, no matter if standalone or inside a plugin!"
- **Two axes:** (A) PREFIX STABILITY — no per-call/per-session varying text in anything injected
  into context (timestamps, raw counters, %s, session paths, per-version ${...} that resolves
  differently); (B) FLOOR SIZE — shrink the always-loaded corpus (rules, CLAUDE.md, agent defs).
- **Doctrine:** CPV's CA-01..CA-07 prompt-cache invalidation patterns (cache-validation-skill /
  cpv-batch-caching-audit|optimize) — use them, don't re-derive.

## Phases (collision-aware — OY0W6LX5 agents own some files until landed)
1. **P1 janitor hook-text stabilization (agent, NOW):** every hook/detector-emitted string that
   reaches model context must be cache-stable: BUCKET numbers (tokens→nearest 10k, %→5 steps),
   DROP per-call counters ("(6 msg / 2 tool calls)"), fixed phrasing. Files: pre-tool-token-budget.py,
   pre-tool-context-usage.py (+ their tests). Semantics unchanged, thresholds unchanged.
2. **P2 user-scope standalone assets (agent, NOW):** ~/.claude/agents/*.md (spark first),
   ~/.claude/rules/*.md, ~/.claude/skills/**, ~/.claude/commands/** — BACKUP-first (full copy to
   ~/.claude/backups-cache-opt-<ts>/, outside git ⇒ RULE-0 recoverability), then CONSERVATIVE
   cache-friendly rewrite: remove dynamic/dated/derived content, dedupe exact repetition,
   stable ordering; NEVER drop a normative statement; report per-file what changed.
3. **P3 janitor plugin skills/commands/CLAUDE.md/README (after OY0W6LX5 lands):** CPV
   cache-optimizer pass (CA-01..CA-07 + Phase-4 broader) on the plugin tree; ride the next publish.
4. **P4 root-cause investigation (separate, evidence-first):** WHY 7.6× — instrument one spark run;
   suspects: per-session scratchpad path in the system prompt (breaks cross-agent base sharing),
   usage `iterations` double-count, hook additionalContext churn, parallel-branch cache races.

## Delivery
P1 rides the next janitor publish (v0.29.0 with OY0W6LX5 + 8PH8YOIJ + 56374Z36). P2 is
outside-git (backup = recovery). P3/P4 follow-up in the same TRDD, updated on landing.
