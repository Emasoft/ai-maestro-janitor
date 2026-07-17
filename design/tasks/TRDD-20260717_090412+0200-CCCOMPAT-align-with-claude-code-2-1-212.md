---
trdd-id: CCCOMPAT
title: Bring the janitor up to speed with Claude Code through 2.1.212
column: dev
created: 2026-07-17T09:04:12+0200
updated: 2026-07-17T09:04:12+0200
current-owner: session
task-type: infra
release-via: publish
implementation-commits: []
---

# Bring the janitor up to speed with Claude Code through 2.1.212

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-17

**NEXT ACTION:** part of the pre-publish batch — publish after this and the two sibling fixes
([[TRDD-QW6RVAKN]], [[TRDD-D3PROACT]]) are committed.

**The ask (USER, 2026-07-17):** before publishing, bring the janitor up to speed with the recent
Claude Code changes — make all changes needed and adopt new features where possible. The user
pasted the changelog for 2.1.203 → 2.1.212.

**AUDIT RESULT — the janitor is compatible; ONE feature adopted, four surfaces verified clean.**
Details captured in `CLAUDE.md` → "Claude Code compatibility (… through 2.1.212)". Summary:

**ADOPTED — integer env-var spellings (CC 2.1.208 + 2.1.211).** CC now parses `1e6` and `64_000`
for its own int env vars. The janitor's ~50 `CLAUDE_PLUGIN_OPTION_*` int knobs flowed through
`state.coerce_int`, which gated on `str.isdigit()` → **silently rejected** those spellings and
reverted the knob to its default. Fix: new PURE `state.parse_nonneg_int` accepts the SAME set CC
does — plain / underscore-separated / scientific, whole-number only, non-negative — and
`coerce_int` plus both hook-local `_coerce_int` (`pre-tool-context-usage`, `pre-tool-token-budget`)
delegate to it (one source of truth). Regression-tested (`test_state_parse_nonneg_int.py` +
extended `test_pre_tool_context_usage.py`).

**VERIFIED CLEAN — no breakage from 2.1.210–2.1.212:**
- Task tool `mode` param deprecated (2.1.212) → the janitor passes NONE (spawns via bare markers).
- `${user_config.*}` rejected in shell hooks (2.1.207) → zero usages; options via
  `$CLAUDE_PLUGIN_OPTION_<KEY>`.
- `continue:false` hook fixes (2.1.212) → the janitor's hooks use `decision:block` /
  `additionalContext`, never `continue:false`.
- `/fork` → `/subtask` rename (2.1.212) → the janitor uses the Agent tool with
  `run_in_background`, never the `/fork` command.

**NOTED, no code change:**
- Per-session subagent cap 200 (2.1.212): the janitor's spawns are already rate-limited well under
  it (memory cadence + ticket per-day budget); a compaction does NOT reset the budget, so keep
  spawn rates conservative on multi-day sessions. Future TRDD if it ever nears the cap.
- Hook-timeout-as-rejection fix (2.1.210) + infra-error-as-rejection fix (2.1.212): both strictly
  HELP the unattended mission; confirm the janitor's fail-open, bounded-timeout hook design is
  correct — keep it.

## Pass criteria

- `state.coerce_int("64_000"/"1e6"/"2.7e5")` returns the number; `"1.5"`/`"-1e6"`/`"0x10"`/junk
  → default. Both hook `_coerce_int` match.
- CLAUDE.md compat section header reads "through 2.1.212" and lists the findings.
- Full suite + ruff green.

## Out of scope

- `CLAUDE_CODE_PROCESS_WRAPPER` (2.1.208): the fleet hard-restart rungs spawn `claude` directly and
  would bypass a corporate required-wrapper. Those rungs are DEFAULT-OFF opt-in and the wrapper is a
  niche enterprise feature — a future TRDD if a user needs it, not this pass.
- Reasoning-effort-on-transcript (2.1.212): the token model is count-based, so no adoption needed.

## Notes and lessons learned
