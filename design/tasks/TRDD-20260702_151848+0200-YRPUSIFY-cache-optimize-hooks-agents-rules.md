---
trdd-id: YRPUSIFY
title: Cache-optimize the hooks, spark agent, skills, commands, and rules — stop prefix invalidation + shrink the per-agent floor
column: dev
created: 2026-07-02T15:18:48+0200
updated: 2026-07-11T13:55:00+0200
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
implementation-commits: [5687848, 460aad0]
approval-tier: 0
---

# Cache-optimize hooks + spark agent + skills/commands/rules (USER command, 2026-07-02: "immediately")

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-11

**2026-07-11 — P4 ANSWERED (evidence) + the biggest janitor-owned lever SHIPPED (460aad0).**

**P4 root cause, measured with `agentlenspro investigate_burn --windowHours 1` (NOT
guessed).** The dominant burn is not prefix churn inside one session — it is
**PREMIUM_MODEL_FANOUT**: 256 subagent calls on claude-sonnet-5 (peak 176 in 30 min),
34% of the window, ~9.9M equivalent tokens (~$21/h), plus a **FORK_STORM** (a fan-out
forked a fat parent into a cold cache; 211 requests sharing one inherited transcript).
`FAT_SESSION_REWRITES` — the 7.6x-rewrite hypothesis this TRDD was built on — is only
**2%** of the window. So axis A (prefix stability) is real but SMALL; **axis B (floor
size) x (number of cold agents) is the whole game.** The burn is also machine-wide and
multi-project (top workspaces that hour: AgentlensPro 213 MB, a sonnet fan-out 197 MB,
ai-maestro 133 MB; the janitor was 4th at 74 MB).

**Shipped (460aad0):** the janitor's 8 rules were 112,889 B (~28k tokens) — **48% of this
machine's entire `~/.claude/rules/` floor** — and every byte of it is re-written into cache
by every COLD SUBAGENT, machine-wide. Three of them were reference DOCUMENTS, not rules.
Moved their bulk (full schemas, transition matrices, grep cheat-sheets, migration guides)
to `rules/references/<name>-full.md`, installed by the new
`rules_installer.install_references()` into `<DATA>/rules-reference/` — a persistent dir
that is NOT a rules dir and is therefore never context-loaded. **Corpus 112,889 -> 49,894 B
(-56%); zero normative content lost** (the guard test caught two dropped Layering notes and
they were restored). Ratchet tests cap the corpus at 52,000 B and any single rule at
12,000 B — the cap may go DOWN, never up.

**Remaining:**
- **P2 (user-scope standalone assets) — NEEDS USER PERMISSION.** `~/.claude/rules/*.md`
  (the ~120 KB that is NOT janitor-shipped), `~/.claude/CLAUDE.md` (37 KB),
  `~/.claude/agents/*.md`, `~/.claude/skills/**`, `~/.claude/commands/**`. These are the
  USER's own files, outside any git repo -> RULE 0: no destructive/significant edit without
  explicit written approval, and BACKUP-first to `~/.claude/backups-cache-opt-<ts>/`.
  This is now the single largest remaining floor item.
- **P3 (plugin-tree CPV cache pass)** — lower value than believed: plugin skills/commands
  load on demand, so they are not in the always-on floor. Do it, but it is not the lever.
- **P1** shipped in v0.29.0 (5687848).

**NEXT ACTION:** ask the USER to authorize P2 (their own `~/.claude/` assets, backup-first).

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
