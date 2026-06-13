---
name: project_janitor_cc_changelog_currency
description: "is the janitor up to date with the new Claude Code release / did the CC changelog break the janitor / what Claude Code changes affect the janitor plugin / bring the janitor up to date with Claude Code"
ocd: 2026-06-11
lmd: 2026-06-13
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: claude-code-coupling
---

Triaged the full Claude Code CHANGELOG (2.1.98 → **2.1.173**) against the
janitor's coupling surface on 2026-06-11. **Verdict: 0 BREAKS.** The two
load-bearing CC couplings were RE-VERIFIED still correct against the whole
range, so do NOT re-derive them:
- **Rate-limit process-survival design STILL TRUE** — CC does NOT exit on
  rate-limit/API errors; only the turn dies; `StopFailure` fires instead of
  `Stop`. The 3-component unattended architecture (token-rotator + durable
  `CronCreate` + idempotent loop) remains correct.
- **`CronCreate` v2.1.98 floor STILL CORRECT** — durable recurring crons
  unbroken through 2.1.173 (the 2.1.105/2.1.110/2.1.136 fixes touch *one-shot*
  scheduled tasks, which the janitor does not use).

**One genuinely-stale fact — FIXED (commit `86502a6`):** the blanket "native
auto-compact is unreliable on the 1M window" claim. CC 2.1.172 added an
auto-compact-back, but ONLY for the *1M-WITHOUT-usage-credits stuck* case — NOT
the credit-bearing threshold overrun the context-watchdog (TRDD-31095269)
targets. Narrowed + version-cited in `skills/janitor-compact-context/SKILL.md`
and `scripts/hooks/pre-tool-context-usage.py`. Watchdog still warranted;
re-verify empirically per CC release. (1M context is now MAINSTREAM — Opus 4.7+,
Fable 5 default it — not the exotic case the docs framed.)

**Improvement backlog (optional; all ship via the publish, none urgent, none
breaking):**
- ADAPT: `global_state.py::daemon_is_alive` uses a wall-clock 1800s window →
  spurious daemon restart after a >30min laptop SLEEP (CC's own daemon now
  detects clock jumps). LOW severity (self-healing via the flock).
- ADAPT (higher priority, risk): migrate daemon state `$HOME/.claude/janitor-global-state/`
  → `${CLAUDE_PLUGIN_DATA}` — CC 2.1.117 expanded the `cleanupPeriodDays` sweep
  to more `$HOME/.claude/` subtrees; the unofficial dir is sweep-prone. Non-trivial
  (flock path changes under a RUNNING daemon → needs dual-read migration).
- LEVERAGE (strong security fit): `post-mcp-response-sanitizer.py` could STRIP an
  injected payload via PostToolUse `hookSpecificOutput.updatedToolOutput`
  (2.1.121/2.1.139) instead of only warning via `additionalContext`. Verify the
  field is honored first.
- LEVERAGE: PreCompact hook (2.1.105) to write the resume directive
  deterministically (robust to ANY compaction, not just the skill's self-trigger).
- LEVERAGE/DOC: `--safe-mode` (2.1.169) as a janitor-doctor diagnostic; `.claude/skills`
  auto-load (2.1.157); Stop-hook `session_crons`/`additionalContext` (2.1.145/2.1.163).

The full triage report is gitignored + ephemeral under the repo's `reports/` tree.
See `[[project_rotator_let_429_happen_version_skew]]` (the rate-limit menu that
freezes the session on 429 — the rotator must rotate PROACTIVELY via the daemon).

## Notes and lessons learned

(none yet)
