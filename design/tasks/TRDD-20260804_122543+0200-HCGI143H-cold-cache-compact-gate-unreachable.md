---
trdd-id: HCGI143H
title: The cold-cache compact gate is unreachable so a resumed 600k session is never compacted
column: testing
created: 2026-08-04T12:25:43+0200
updated: 2026-08-04T13:05:00+0200
current-owner: janitor-session
task-type: bugfix
severity: high
scope: project
release-via: publish
npt: []
eht: []
implementation-commits: []
---

# Cold-cache compact never fires — the threshold sits above where the harness already compacts

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-04

**Reported by the USER 2026-08-04:** they restarted several Claude Code instances that had
been idle since the previous day, each carrying 500–600k of context. The janitor should have
compacted at SessionStart *before* any turn ran; instead the first turn re-read the whole
context as a prompt-cache WRITE (~1.25×), burning the subscription window. Their ask: detect
the expired cache (last turn ≥1h ago, or better ≥55 min) and compact first.

**ROOT CAUSE — measured on the live machine, not inferred:**

| fact | value | meaning |
|---|---|---|
| `cold_cache_compact.min_context_tokens()` | **716,000** | the gate |
| derivation | `AUTO_COMPACT_WINDOW 700000` → effective 666,000 + `BACKSTOP_MARGIN` 50,000 | |
| harness's own auto-compact point | 666,000 | the gate sits **above** it ⇒ **unreachable** |
| `should_compact_on_resume(ctx)` at 300k / 500k / 600k / 700k | **False** for all four | ran it directly |
| this session's `session-start.log` at `source=resume` | no fire line at all | branch returned False |
| `context_tokens_for(newest_transcript)` | 301,980 | the reader WORKS — not a `None` bug |
| learned post-compaction floor (`read_floor`) | **242,921** | measured on this install |
| `DEFAULT_MIN_GAIN_TOKENS` | 150,000 | |

The cold-cache feature is therefore **dead code on any machine where the harness's own
auto-compaction works**: the context can essentially never climb to 716k because the harness
compacts it at 666k first.

**WHY it is set that way (in-code, owner directive 2026-07-18):** *"the janitor's compact
threshold is HARNESS-RELATIVE: it must NEVER compete with Claude Code's own auto-compaction —
it only backstops a harness compaction that FAILED."* A previous FIXED 350k default was judged
too eager (fired at 35% of a 1M window).

**The analysis (why that directive does not fit this path):** one shared
`min_context_tokens()` serves **two different economic events**.
- *Overflow backstop* — the harness auto-compacts to prevent context OVERFLOW, near the window
  limit. Not competing with it is correct.
- *Cold-cache compaction* — prevents a CACHE-WRITE BURN. The harness has **no feature for
  this**; it will never compact a 600k context because 600k is nowhere near overflow. So there
  is nothing to compete with, and deferring to the harness defers to a mechanism that does not
  exist for this problem.

**PRECEDENT that the split is right:** the `/clear` path already carries its own
`clear_min_context_tokens()` defaulting to 350,000, independent of the harness-relative number.
`should_compact_proactively_idle` already carries the `floor_tokens` + `min_gain` termination
guard this fix needs to reuse.

## Design AS RATIFIED BY THE USER (2026-08-04) — simpler than the threshold split I proposed

I proposed splitting the threshold (a separate absolute `cold_min_context_tokens()`); the USER
**overruled the entire size dimension**, twice and unambiguously:

> *"the auto compact window is a parameter that i change often according to the project. the hook
> that inject the /compact command is independent than that. it must simply inject the command
> every time the cache is expired."*
> *"you must simply check the last turn datetime. if it is older than 55 minutes, it should inject
> the compact command. no matter the value of the context."*

That is strictly better than my proposal and I dropped mine: it removes the coupling to a
per-project knob AND removes a second tunable that would have needed to agree with `min_gain`.

1. **ONE condition for both cache-expired gates: last-turn age ≥ TTL.** `should_compact_on_resume`
   and `should_compact_after_idle` take `(age, *, min_idle_s)` and nothing else — no context
   argument exists any more, so re-adding a size dependency requires a signature change (which the
   tripwire tests then fail on).
2. **`last_turn_age_for(transcript, *, now)`** — the transcript is append-only and written as each
   turn completes, so its **mtime IS the last turn's wall-clock time**: no parsing, and correct
   across a process restart, which is exactly when the resume path needs it. `None` on
   absent/unreadable, and on a FUTURE mtime (clock skew) — we fire on a POSITIVE observation of
   expiry, never on absence of evidence.
3. **TTL margin.** `DEFAULT_MIN_IDLE_SECONDS` 3600 → **3300** (55 min): the age is measured at
   CHECK time but the compact turn runs later, so waiting the full hour lets the near-boundary
   case go cold first. Firing 5 min early costs nothing on an idle session.
4. **The REPEAT guard** (USER, same session): *"ensure that a compact did not happen already in
   the latest 1h (or better in the last 65 minutes, to be safe)"* — and, on what counts: *"the user
   may have run the compact itself, or a janitor cron may have executed a planned compact… and it
   must include auto-compact of course."* So `recently_compacted()` checks **two** stamps:
   `last-compact.ts` (written by the PostCompact hook — VERIFIED unconditional, so it covers a
   manual `/compact`, a janitor-fired one, AND the harness's native auto-compact) and our own
   `cold-compact-fired.ts` (a fire that may not have landed yet). Window 3900s (65 min).
5. **`min_context_tokens()` is UNCHANGED** and stays harness-relative — it still gates the
   PROACTIVE warm-idle path, whose question really is "did the harness's own compaction fail?".
   Only the two cache-expired paths were decoupled. No dead code: the function keeps a consumer.

**THE ANTI-LOOP INVARIANT — guard (65 min) > trigger (55 min).** If the guard were ever shorter
than the trigger, a permanently idle session would clear the guard while still satisfying the
trigger and compact on a cycle forever. Asserted as an inequality in
`test_the_guard_window_exceeds_the_trigger_window`, not left to a reader to notice.

## Verification — DONE unless marked otherwise

- [x] Both gates fire at exactly 3300s and not at 3299s (boundary inclusive, both paths).
- [x] Both gates return the SAME verdict for every age — the unification is pinned, so a future
      edit that re-adds a condition to one path breaks the test.
- [x] A SMALL cold context FIRES (the retired tripwire, inverted) and the verdict is unchanged
      across `CLAUDE_CODE_AUTO_COMPACT_WINDOW` ∈ {100000, 700000, 2000000} — the decoupling proven
      by variation, not by reading the code.
- [x] Both wiring paths prove they read no size at all: `context_tokens_for` is stubbed to RAISE,
      so any surviving read explodes instead of passing quietly.
- [x] `None` age (unreadable transcript) and a FUTURE mtime both refuse to fire.
- [x] The repeat guard blocks a compaction stamped by someone else 10 min ago, still blocks at
      64 min, releases at 66; a not-yet-landed fire also blocks.
- [x] Guard > trigger asserted as an inequality (the anti-loop invariant).
- [x] `min_context_tokens()` unchanged; the proactive path's suites untouched and green.
- [x] FULL suite **14,273 passed, 1 skipped**; `ruff check scripts tests` clean.
- [ ] Real-fire observation on a resumed cold session (publish-gated on TRDD-AWXK0RFT).

## Known limit — stated, not engineered around

A `/compact` **is itself a turn**, and any first turn on a resumed session must read the context
once. The initial cold write therefore cannot be avoided by this fix; what it buys is paying that
once instead of carrying the context through every subsequent turn of the window. Avoiding the
first read outright needs `/clear`-with-handoff, not `/compact` — `clear_enabled()` already exists
as its own lever and was deliberately NOT folded in here.

## Collateral defects found and fixed while verifying (separate commits)

1. `test_keepalive_stage.py` — the daemon-closure cap was 40 and the closure is 41 since
   `oauth_rotator/burn_gate.py` legitimately joined it on 2026-08-02 (TRDD-FQXBURNR). The suite
   had been red on `main`. Raised to 45 (headroom, so the next legitimate module does not re-break
   the build) rather than nudged to 41.
2. `design/specs/wikimem-memgrep-spec.md` — MY OWN regression from TRDD-7YHT3FNK earlier this
   session: the `edit` verb and `--base-sha256` never reached the spec, so the conformance test
   `test_wikimem_spec_drift` was red. Added WM-CLI-11 (the write-concurrency gate: the lock
   formula, the flock-as-queue, the CAS refusal string) and WM-CLI-12 (`edit`), plus WM-CLI-02a
   for the pre-existing undocumented `--include-superseded`. The P4 docs pass covered the rules
   and skills but missed the conformance spec — that gap is the lesson.

## Notes and lessons learned
