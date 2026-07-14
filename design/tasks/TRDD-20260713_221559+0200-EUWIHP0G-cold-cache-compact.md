---
trdd-id: EUWIHP0G
title: Auto-compact a large context on resume after a cold-cache gap or login to save the 5h window
column: testing
created: 2026-07-13T22:15:59+0200
updated: 2026-07-13T22:43:58+0200
current-owner: janitor-session
task-type: feature
severity: high
relevant-rules: [3]
parent-trdd: HI0BGQGJ
implementation-commits: [dc059f3]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-13

**Problem (user):** after a >1h stop (rate limit; or the user exits and relaunches later; or a
logout/login), the 1h prompt-cache TTL has expired. The first resumed turn re-writes the WHOLE
context as a cache-creation (~600k avg, ~1.25×), burning the 5h window. Auto-inject `/compact` at
resume so the large context is shrunk.

**Honest correction (recorded):** `/compact` is itself a turn that READS the full context, so it
CANNOT avoid the immediate cold write. It DOES make the rest of the window cheap (context → ~50k)
and every FUTURE cold resume ~50k not ~600k. Worth it for a long, repeatedly-interrupted session.

**User decisions:** (1) threshold **270k tokens**; (2) fire on the SessionStart resume path AND the
heartbeat rate-limit path AND after a login/logout.

**Design (refined after checking signals):**
- Threshold 270k everywhere (`latest_context_size` = input+cache_read+cache_creation of the last
  assistant msg = live occupancy — reuse token_meter).
- **SessionStart (startup/resume): compact if context ≥ 270k** — no idle gate. A resumed session
  with 270k+ IS the cold/large case (fresh process; relaunch-after-logout/login/exit all land
  here); a fresh empty session never trips it.
- **Heartbeat rate-limit-clear: compact if age ≥ min_idle (3600s) AND context ≥ 270k** — the
  in-session rate-limit case (`_phase_rate_limit_recovery` already computes `age`).
- Mid-session `/login` with NO gap on macOS is NOT cheaply detectable — the OAuth cred is in the
  keychain (no stattable mtime; reading it risks the ACL-prompt flood, macos-keychain lesson), and
  SessionStart has no `login` source. Covered at the next SessionStart/idle 270k check. Documented,
  not worked around.
- Mechanism: reuse `scripts/compact_trigger.py` (SOFT `/compact` + resume-directive). The existing
  post-compact-resume + HI0BGQGJ push then auto-resume + re-arm. Cooldown stamp
  (`cold-compact-fired.ts`) prevents a double-fire before the compact lands.

**STATUS: IMPLEMENTED + tests green (commit dc059f3).** `column: testing`. Shipped:
`scripts/lib/cold_cache_compact.py` (pure `should_compact_on_resume` / `should_compact_after_idle`,
plus readers, cooldown and 4 knobs); SessionStart wiring via the testable helper
`_maybe_cold_compact_on_session_start` in `scripts/hooks/on-session-start.py`; the dispatch
rate-limit branch `_maybe_cold_compact_on_rate_limit` wired into `_phase_rate_limit_recovery` in
`scripts/dispatch.py`; the 4 `.claude-plugin/plugin.json` userConfig knobs. 47 new tests
(`test_cold_cache_compact.py` 27, `test_on_session_start_cold_cache.py` 11,
`test_dispatch_cold_cache.py` 9). Full suite **12881 passed, 1 skipped**; ruff clean. All three
gates falsification-verified (lib both-conditions `and`→`or`; dispatch NO_ITERM stall-guard;
SessionStart source gate) — each neuter failed its test, then reverted.

**NEXT ACTION:** ships on the next `publish.py` release (rides with the other unpushed commits —
do NOT push standalone). Then ONE manual end-to-end confirmation in an iTerm/tmux session: relaunch
`--continue` on a >270k session and confirm `/compact` fires as the first action and the session
auto-resumes afterward (via the HI0BGQGJ push). Then move to `complete`. Nothing forceable now.

**Knobs:** `CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED` (on), `..._MIN_CONTEXT_TOKENS`
(270000), `..._MIN_IDLE_SECONDS` (3600), `..._COOLDOWN_SECONDS` (600).

**Load-bearing:** SOFT compact (resumed REPL is idle — never ESC); best-effort/wrapped in the hook
(a fault must never break session start); the dispatch cold branch emits a NON-marker notice (NOT
`[janitor-resume]`) so the current turn doesn't resume into a context about to be compacted.

**SUPERSEDED — do NOT carry forward:** the plan's original "SessionStart requires idle ≥ 1h" — the
user's 270k message superseded it: SessionStart is context-only (≥ 270k).
