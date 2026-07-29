---
trdd-id: EUWIHP0G
title: Auto-compact a large context on resume after a cold-cache gap or login to save the 5h window
column: testing
created: 2026-07-13T22:15:59+0200
updated: 2026-07-29T02:45:11+0200
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

**User decisions:** (1) threshold **270k tokens** — ⚠ **SUPERSEDED 2026-07-18**, do NOT act on this
number; see the 2026-07-29 verification note below; (2) fire on the SessionStart resume path AND the
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

### 2026-07-29 — the e2e was RUN, and the acceptance criterion was found STALE

**The criterion could not be run as written, and that is the finding.** `min_context_tokens()` is
no longer the flat 270k above — the owner directive of **2026-07-18** made it **harness-relative**,
so the janitor only ever fires ABOVE where Claude Code already auto-compacts:

| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | resolved threshold | consequence |
|---|---|---|
| `700000` (this machine, in the Claude Code process) | **716_000** (`700000 − 34000 + 50000`) | reachable — the janitor is a backstop |
| unset (e.g. a bare tmux pane) | **1_016_000** (`1000000 − 34000 + 50000`) | **exceeds the 1M window ⇒ unreachable by construction**; the harness owns compaction entirely |

`should_compact_on_resume(270_000)` is therefore **False**, correctly. Running the old criterion
produces a red whose meaning is "the spec rotted", not "the code is broken" — and the two ways a
reader talks themselves out of that red are to patch working code, or to lower the threshold until
270k passes, silently restoring the janitor/harness compaction race the directive removed.

**What was actually verified** (real tmux pane I created and owned; no iTerm; production presence
gate left INTACT — it passed on its own because the user was genuinely idle, so no bypass was used):

1. **Threshold half.** A real transcript flows through `context_tokens_for` →
   `latest_context_size` into the gate. Fires at `threshold+30k`, silent at `threshold−30k`, silent
   at the retired 270k.
2. **Injection half** (the part never exercised outside a human's terminal). Inside a real pane,
   `state.terminal_kind()` resolved to `tmux` off **genuine process ancestry** (unforced — the
   pre-existing `test_tmux_real_send_delivers_keystrokes` monkeypatches this, and is skipped unless
   `JANITOR_TEST_REAL_TMUX=1`); the detached child survived the harness exit and the keystrokes
   landed. Counted, not eyeballed: 2 fires → 2 `/compact` in the pane; the dry run sent nothing.
3. **The join.** `_maybe_cold_compact_on_session_start(..., "resume", <real transcript>)` with a
   real `compact_trigger.py` subprocess: above-threshold → fired, `resume-directive.txt` and
   `cold-compact-fired.ts` written, **exactly one** `/compact` in the pane; below-threshold and
   270k → no fire, no files, no keystroke. One landing for one fire is the assertion that a
   pass-only test would have missed.

**NOT verified, and not claimable:** that a genuine `claude --continue` hands the hook
`source=resume` with a live `transcript_path` (harness behaviour — the hook gates on exactly those
two, both supplied here), and step 3 of the original criterion, "the session auto-resumes"
end-to-end. The resume half is covered at its seams by `test_post_compact_resume_hook.py` and
`test_dispatch_cold_cache.py`; the directive-write side is confirmed above.

**Regression guard:** `tests/test_cold_compact_threshold_contract.py` (8 tests) pins the
harness-relative arithmetic, the backstop-above-harness invariant, the unreachable-when-unset
invariant, and — as a tripwire — that **270k must not fire**. Mutation-checked: forcing the
threshold to 270_000 turns 6 of the 8 red. This exists because the sibling wiring test stubs
`context_tokens_for` *and* `run_subprocess` and deletes the auto-compact window, so nothing
previously exercised the real resolution.

**NEXT ACTION:** none blocking. The card's original acceptance criterion is retired; the mechanism
is verified at the real threshold. Ready for `testing → ai_review` on the owner's call.

**Knobs:** `CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED` (on), `..._MIN_CONTEXT_TOKENS`
(270000), `..._MIN_IDLE_SECONDS` (3600), `..._COOLDOWN_SECONDS` (600).

**Load-bearing:** SOFT compact (resumed REPL is idle — never ESC); best-effort/wrapped in the hook
(a fault must never break session start); the dispatch cold branch emits a NON-marker notice (NOT
`[janitor-resume]`) so the current turn doesn't resume into a context about to be compacted.

**SUPERSEDED — do NOT carry forward:** the plan's original "SessionStart requires idle ≥ 1h" — the
user's 270k message superseded it: SessionStart is context-only (≥ 270k).
