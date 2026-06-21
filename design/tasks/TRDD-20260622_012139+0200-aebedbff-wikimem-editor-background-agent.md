---
trdd-id: aebedbff-8f3e-41f2-945b-8b181964e8af
title: Wikimem editorial work runs in the janitor-memory-subconscious-agent (opus, async) — never a main session
column: dev
created: 2026-06-22T01:21:39+0200
updated: 2026-06-22T02:05:00+0200
current-owner: claude-janitor-dev
parent-trdd: null
task-type: refactor
release-via: publish
relevant-rules: []
test-requirements: [unit]
impacts: []
---

# Wikimem editorial passes → background opus agent (not main context)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-22

### REFINED ARCHITECTURE (user iterations 2 + 3 — the FINAL shape)
Three tiers, one agent:
- **Tier 1 — main agent (any session), SIMPLE ops only:** `janitor-memory-{recall,write,update}`
  — create a page / add ONE atom / update a single fact (correction protocol). A prominent
  boundary in each delegates ALL complex re-editing to the agent below. DONE.
- **Tier 2 — ONE agent `agents/janitor-memory-subconscious-agent.md`** (opus, `effort: high`,
  separate context — NOT a fork, async/background). Its FRONTMATTER `skills:` injects the
  editorial skills (today: consolidate/split/conflict/repair/harvest + write/update/recall;
  PLANNED granular set below). Carries all the IRON RULES + the txn discipline + the
  Wikipedia-grade mission. DONE (skeleton + existing skills injected).
- **Tier 3 — the janitor LAUNCHES one or many** subconscious agents in the background when
  due, token-aware. The `[janitor-memory-*]` cron marker now spawns
  `subagent_type: janitor-memory-subconscious-agent`, `run_in_background: true`, one-line
  task = the pass name. DONE (cron prompt rewired; re-arm-gated).

### PLANNED — the granular skill decomposition (Tier-2 toolkit to AUTHOR next)
User wants "dozens" of granular `janitor-memory-*` skills injected. EXIST: split,
consolidate, conflict, repair, harvest. TO AUTHOR (confirm list + naming first): `merge`
(page-merge executor, vs consolidate the planner), `create-expander` (new aspect page),
`create-reducer` (new component page), `verifier` (run the verify_* gate as a skill),
`harmonize-conflicts` (= conflict? rename or distinct), `deduplicate`, `check-references`
(link-law / broken-link audit), `scope-validation` (LOCAL/PROJECT/USER routing). Each is a
full transaction-gated skill like the existing 5 — a LARGE effort; scope/naming to confirm
with USER before authoring (esp. merge-vs-consolidate, conflict-vs-harmonize).

### Secondary tooling bug (separate follow-up): `memgrep links` (resolves `[[target]]`→file)
misses backlinks that `no_dangling_refs` (raw `\[\[…\]\]` regex vs retired slugs) catches —
the agent's redirect pre-check is incomplete. Fix so the subconscious agent's redirects are
reliable.

### Original directive ↓

USER directive (verbatim): *"such complex task requires a specialized skill with
specialized python scripts. And an opus agent working async with the skill injected.
Something that the janitor must do in background. I told the CPV plugin of not ever
try to waste its main context doing janitor work."*

CONTEXT: a CPV-plugin Claude (a NON-janitor main session) ran `/janitor-memory-consolidate`
in its OWN context and hit the `verify_merge` gate — burning its main context on complex,
verify-gated janitor work. That must never happen: the wikimem editorial passes
(split / consolidate / conflict / repair / harvest) are complex, multi-step,
transaction-gated work, and they must run in a DEDICATED background **opus agent** that
the janitor dispatches fire-and-forget — never in whatever main session happens to fire
the heartbeat.

### The mechanism today (verified)
- `memory-maintenance.py` (the SCHEDULER) decides WHEN a pass is due, dedupes
  machine-wide (one marker per fire, stamped via `memory_settings.mark_ran`), and emits
  ONE bare marker `[janitor-memory-{split|consolidate|conflict|repair|harvest}]`.
- The marker SEMANTICS live in exactly ONE authoritative place: the **cron prompt** baked
  by `skills/janitor-arm/SKILL.md` step 4 (and injected each heartbeat). Today it says
  *"silently run the matching skill — you MAY use sub-agents, then return"* → i.e. the
  firing session runs the pass IN ITS OWN CONTEXT.
- All 5 editor skills exist; the python machinery (`memory_txn_cli.py`,
  `memory_edit_verify.py`) exists. Nothing new to BUILD there.

### The change (THIS TRDD)
Rewrite the `[janitor-memory-*]` marker clause so the firing session **spawns ONE
background opus agent** (`Agent` tool: `run_in_background: true`, `model: opus`,
`subagent_type: spark`) that reads & executes
`$CLAUDE_PLUGIN_ROOT/skills/janitor-memory-<name>/SKILL.md` on the due scope and returns
a one-line result + report path, then **RETURNS IMMEDIATELY** — the firing session never
runs the editorial pass itself.

### Sites to change
1. `skills/janitor-arm/SKILL.md` step 4 — the marker clause (THE authoritative cron prompt).
2. `scripts/detectors/memory-maintenance.py` docstring — the marker-meaning description
   (currently "silently run /janitor-memory-X").
3. The 5 editor skills (`split|consolidate|conflict|repair|harvest`) — a short
   `## Execution context` note: this pass is dispatched as a background opus agent
   (self-contained; returns one line + report path), not run in a main session.

### NOT in scope (user-invoked stays in-session)
`/janitor-memory-record-recent` is USER-invoked and session-context-dependent (it reads
the session's recent changes) — it stays in-session by design. The background-agent rule
is for the AUTONOMOUS heartbeat-dispatched passes only.

### Re-arm gate (load-bearing)
The LIVE cron has the OLD prompt baked in; the new semantics take effect ONLY after the
user runs `/janitor-arm` (the existing "Re-arm rollout lag" note documents this). So this
change is review-gated: it cannot alter live behavior until the user deliberately re-arms.

### Secondary finding (separate follow-up, NOT this TRDD)
`verify_merge` blocked the CPV agent for TWO reasons: (a) it paraphrased facts — the
`body_facts_preserved` gate CORRECTLY rejected that (a merge must union facts verbatim);
(b) a `[[wikilink]]` backlink in `version-history.md` that the agent's `memgrep links`
pre-check MISSED but `no_dangling_refs` CAUGHT. (b) is a real tooling gap: `memgrep links`
RESOLVES `[[target]]`→file (by name-slug/stem) while `no_dangling_refs` uses a raw
`\[\[…\]\]` regex vs retired slugs — so the pre-check can miss a backlink the gate flags.
Worth a separate fix so the background agent's redirect step is reliable; tracked
separately, not blocking this dispatch change.

## Why this is correct
- The editorial pass is the heaviest, most context-hungry janitor work; isolating it in a
  dedicated opus agent keeps EVERY main session (CPV's or any other) free of it.
- Fire-and-forget + the scheduler's machine-wide dedupe + the txn core's per-scope flock
  mean overlapping agents are bounded and serialized — no corruption risk.
- The cadence limit (`*_per_day`) bounds how often an opus agent is dispatched.
