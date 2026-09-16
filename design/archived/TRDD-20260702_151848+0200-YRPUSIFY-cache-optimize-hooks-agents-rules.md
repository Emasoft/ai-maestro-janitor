---
trdd-id: YRPUSIFY
title: Cache-optimize the hooks, spark agent, skills, commands, and rules — stop prefix invalidation + shrink the per-agent floor
column: published
created: 2026-07-02T15:18:48+0200
updated: 2026-08-02T06:40:00+0200
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

## ⛔ SUPERSEDED — THE BUCKETING APPROACH IS FALSIFIED (2026-07-13, TRDD-K1RJUYGK)

**Do NOT carry the `_bucket_pct` / `_bucket_tokens` rationale forward. It does not work, and
this TRDD's claim that it fixes hook-injection cache churn is WRONG.**

This TRDD diagnosed the hooks' cache churn as *"the injected TEXT is unique per call"* and
fixed it by BUCKETING the volatile numbers (`~70%`, `~40k`) so two calls in the same band
emit byte-identical text. **Measured falsification (2026-07-13):** bucketing is live in EVERY
cached version (0.31.0 … 0.41.0) and `agentlenspro get_cache_break_report` still shows
`hook: PreToolUse:Bash` / `INJECTED_BLOCK_CHANGED` as the **#1 cache-break cause on the
machine** — 893 breaks, 4.96M tokens, **$23.05** — with 712 breaks in a single session.

**Why it cannot work.** The cost is not the text. Per the janitor's own upstream issue
(yvgude/lean-ctx#778): Claude Code **STRIPS stale system-reminder blocks retroactively, in
place, mid-transcript**; the strip mutates the cached PREFIX and re-bills every token after
it. A block that gets deleted later costs the same *whatever it said*. Stable text does not
survive a strip. The only remedy is the one that issue states: **"No injection → nothing to
strip → no break."**

**The real fix (shipped, TRDD-K1RJUYGK, commit d50fe8c):** bound the injection **BUDGET**, not
its text — the advisory is LATCHED to at most once per session per 10-point band, and
token-budget's repeat-suppression now fails CLOSED with a 30-minute floor. Bucketing was left
in place (it is harmless and mildly useful for human readability) but it is **not** the fix and
must not be cited as one.

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

**2026-07-11 — P2 SHIPPED (user-authorized, backup-first). Floor -70,337 B (-26%).**

**Scope was WRONG and got corrected by measurement.** P2 was scoped as "rules + CLAUDE.md +
agents/ + skills/ + commands/" (~2.9 MB). Verified against a LIVE system prompt: agent /
command / skill **bodies are NOT in the always-loaded prefix** — only their one-line
descriptions are (`agents/spark.md` is 4,413 B; it appears as ONE line). So the real floor is
only `~/.claude/rules/*.md` (233,301 B, all 30 injected IN FULL) + `~/.claude/CLAUDE.md`
(37,295 B) = **270,596 B**. Editing agents/skills/commands would have been ~2.6 MB of wasted
work for zero floor reduction.

**Technique — a lossless SPLIT, not a trim** (the 460aad0 pattern, now with a mechanical
gate). Each oversized rule became a small loaded RULE + a `~/.claude/rules-reference/
<name>-full.md` that no session loads. A verifier
(`scratchpad/verify_rule_split.py`) asserts every substantive line of the ORIGINAL survives
VERBATIM in (rule + reference) — so content is provably MOVED, never dropped. It was
self-tested against a deliberately-lossy split first. Every split below reports LOSSLESS.

| file | prefix before | prefix after | cut |
|---|---|---|---|
| trdd-approval-tiers.md | 32,816 | 11,767 | -64% |
| corpus-to-plugin-distillation.md | 19,597 | 2,493 | -87% |
| browser-ui-test-techniques.md | 17,053 | 2,917 | -82% |
| manager-approval-defaults.md | 15,382 | 5,321 | -65% |
| agent-reports-location.md | 8,512 | 4,485 | -47% |
| CLAUDE.md | 37,295 | 33,335 | -10% |

`CLAUDE.md` yielded only 10% because it is dense NORMATIVE content (RULE 0, RULE 1, the
Production directives) plus two tool-managed fenced blocks (CodeGraph, distill) left
untouched — pushing further would mean deleting guardrails, which the approval did not cover.
Two clean wins there: the `## lean-ctx — Context Runtime` section (which line 330 of the SAME
file already declared STALE — the prefix carried both the dead section and the note saying to
ignore it), and the `### agents reports` subsection, a near-verbatim DUPLICATE of the loaded
`rules/agent-reports-location.md` (the prefix carried that rule TWICE).

**Result: floor 270,596 -> 200,259 B (-70,337, -26%).** Once the janitor's own already-slimmed
rules publish (installed 87,568 -> repo 49,894), the floor reaches **162,585 B (-40% total)**.
That is ~-18k tokens re-written by EVERY cold subagent, machine-wide. Measured corroboration
the same session: each of the 3 subagents used for this work cost ~285k tokens, most of it
loading this floor before doing any work.

**RULE 0 audit trail.** Authorizing user text (AskUserQuestion, 2026-07-11): **"Approved —
backup first"**. Backup taken FIRST at 2026-07-11 15:44:56+0200 via
`cp -a {CLAUDE.md,rules,agents,commands,skills} ~/.claude/backups-cache-opt-20260711_154456+0200/`
(119 MB), verified byte-identical for every file in the edit scope (`diff -r`). NOTHING was
deleted — every edit is an in-place rewrite whose full original text is preserved in both the
backup AND the reference files. The 5 skills entries that `diff -r` flagged are pre-existing
symlinks into `~/.agents/` (all 5 preserved as symlinks; targets outside the edit scope).

**Remaining:**
- **P3 (plugin-tree CPV cache pass)** — lower value than believed: plugin skills/commands
  load on demand, so they are not in the always-on floor. Do it, but it is not the lever.
- **P1** shipped in v0.29.0 (5687848). **P2** shipped 2026-07-11 (this entry, outside git —
  backup is the recovery).

**NEXT ACTION:** none for P2. P3 is optional/low-value. The janitor-shipped half of the floor
lands automatically on the next publish.

### 2026-08-02 — CLOSED (`dev → published`)

P1 shipped in **v0.29.0** (`5687848`), P2 shipped (`460aad0`), and the card's own NEXT ACTION
has read "none" since 2026-07-13 — it then sat in `dev` for 19 days on the strength of P3
alone, which the same paragraph calls optional and low-value.

**P3 declined, with the card's own reasoning:** it is a plugin-tree CPV cache pass, and the
note above already records why it is worth less than it looks — plugin skills and commands
load ON DEMAND, so they were never in the always-on per-agent floor this card set out to
shrink. Doing it would not move the measured lever. If it is ever wanted it is a fresh card
with a fresh measurement, not a 19-day tail on a delivered one.

`release-via: publish` and the work is in a released tag, so the terminal column is
**`published`**, not `completed` — rewriting it to `completed` would destroy the fact that it
shipped (TRDD rule 12: published/live archive AS THEMSELVES).

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
