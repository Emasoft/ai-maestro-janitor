---
trdd-id: SMZFJVZ3
title: Context-size runaway guard — force a compaction near the window cap
column: complete
created: 2026-06-30T13:07:05+0200
updated: 2026-06-30T13:50:23+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: [config-schema]
attempts: 1
implementation-commits: [3f76b65]
---

# Context-size runaway guard — force a compaction near the window cap

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-30

- **USER diagnosis (the key insight):** the token bleed is NOT from many tool calls —
  it's the **per-turn context size**. A session bloated near the 1M cap re-reads ~999k
  tokens EVERY turn (agent turns AND every 5-min heartbeat fire), so ~20 turns = ~20M
  tokens regardless of output. `cost ≈ turns × context`; context is the lever.
- **Pivot:** the guard is CONTEXT-SIZE based, NOT tool-count (an earlier tool-count
  design was discarded per the user). The only thing that shrinks per-turn cost is a
  **compaction**, so the guard FORCES one near the cap.
- **Chosen profile (user, 2026-06-30):** "Protective" — default-ON, WARN at a soft %,
  hard ENFORCE near the cap.
- **Design (enhance `pre-tool-context-usage.py`, the existing watchdog hook):**
  1. **Default-ON** (was opt-in `CONTEXT_WATCHDOG_ENABLED`).
  2. **Robust context source:** prefer the statusline snapshot (has the real window →
     accurate %); FALL BACK to `token_meter.latest_context_size(transcript)` (the latest
     assistant message's input+cache_read+cache_creation = live occupancy) so the guard
     works with NO statusline. Window default 1_000_000 (configurable) when only the
     transcript is available.
  3. **Advisory tier** (≥ SUGGEST_PCT, default 60): inject the context line + the
     /janitor-compact-context nudge (existing behavior, now default-on).
  4. **Enforcement tier** (≥ HARDSTOP_PCT, default 85, gated by AUTOCOMPACT_ENABLED
     default-ON): run `compact_trigger.py` (records a resume directive + queues
     ESC+/compact on the pane) and **DENY the tool call** so the turn ends cleanly for
     /compact → post-compact-resume continues at reduced context. SAFETY: only DENY when
     compact_trigger actually fired (COMPACT_FIRED); on NO_ITERM/error fall back to the
     advisory so the agent is NEVER stuck denied-with-no-way-to-compact. Dedupe so a
     compact isn't re-triggered within a short window.
- **✅ DONE (2026-06-30):** ALL shipped + tested. `token_meter.latest_context_size`
  (512KB tail, newest-assistant input+cache occupancy); `pre-tool-context-usage.py`
  rewritten default-ON, transcript fallback, ADVISORY (>=60) + ENFORCEMENT (>=85,
  auto-compact+deny, gated by AUTOCOMPACT, 180s dedupe, terminal-gated, fail-open),
  and now SILENT below the suggest threshold (a recheck-pass fix: an additionalContext
  line rides forward and is re-read every turn, so injecting one on every low-% call
  would itself add to the bleed this guard exists to cut). plugin.json: 5 userConfig
  keys (watchdog default false->true + hardstop 85 + autocompact true + window 1M).
  Docs: README narrative + config table + CLAUDE.md hook list (all OPT-IN->DEFAULT-ON).
  Tests: `tests/test_context_size_guard.py` 32 green; ruff + pyright clean; adjacent
  425 green.
- **NEXT ACTION:** commit (this TRDD + the 6 files), then PUBLISH is USER-GATED:
  publish.py auto-rolls the daemon back to life, which conflicts with the user's
  "keep the janitor stopped" stance, so do NOT run publish.py without the user's go.
- **Load-bearing facts:** the hook fires on EVERY tool call in EVERY session (USER
  scope) — fail-open everywhere; the enforcement's terminal-gated deny is the
  load-bearing safety (no deadlock, no stuck session). Disable: per-tier env flags.

## Why

The user lost a month of tokens to context bloat: turns executing at ~999k re-read the
whole context each time. Native auto-compact under-fires on the 1M window. The janitor
already ships the compaction machinery (`janitor-compact-context` + `compact_trigger.py` +
`post-compact-resume`) but only as an OPT-IN, ADVISORY watchdog the agent can ignore.
This makes it DEFAULT-ON and ENFORCING near the cap, where compaction is the only fix.

## Config (plugin.json userConfig)

- `CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED` — default true (advisory + enforcement).
- `CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT` — warn %, default 60 (existing).
- `CLAUDE_PLUGIN_OPTION_CONTEXT_HARDSTOP_PCT` — enforce %, default 85.
- `CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED` — default true (the enforcement tier).
- `CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS` — fallback window when only the transcript
  is available, default 1000000.

## Acceptance

- A transcript whose latest assistant input+cache ≥ 85% of the window → the hook denies
  (when a compact could fire) and triggers exactly one compaction (dedup'd).
- No statusline snapshot → the guard still reads context from the transcript.
- No terminal (compact can't fire) → advisory only, never a stuck deny.
- Watchdog disabled → total no-op. Every error path → fail-open (return 0, allow).
- All existing tests pass.

## Notes and lessons learned
