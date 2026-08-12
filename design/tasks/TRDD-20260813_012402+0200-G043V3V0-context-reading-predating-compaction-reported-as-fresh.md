---
trdd-id: G043V3V0
title: A context reading that predates the compaction is reported as fresh
column: complete
created: 2026-08-13T01:24:02+0200
updated: 2026-08-13T01:47:10+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-TKNSTP82, TRDD-SMZFJVZ3]
---

# The transcript fallback cannot report staleness, so the first turn after a compaction reads the OLD context

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Observed live 2026-08-13, on this very session, immediately after a compaction.** The
`pre-tool-context-usage` PreToolUse hook injected:

> `Context window: ~65% used. ⚠ PREPARE for auto-compact: ~0k until the auto-compact point (~660k).`

**Every number in that line was wrong.** Measured seconds later from the same transcript:

| | hook said | truth |
|---|---|---|
| context tokens | ~660,000 | **273,670** |
| headroom to the auto-compact point | ~0 | **386,330** |

The advice it produced — compact NOW — would have thrown away a freshly-compacted context and
paid a full re-cache, for nothing.

## Cause, read from the source (verified, not inferred)

`token_meter.resolve_context` has two branches:

  - **snapshot branch** (`scripts/lib/token_meter.py:299-307`) — computes
    `stale = (now - ts) > _CONTEXT_SNAPSHOT_STALE_AGE_S`. Correct.
  - **transcript fallback** (`:308-312`) — `return pct, tokens, window_default, **False**`.
    **`stale` is hardcoded False; the branch cannot report staleness at all.**

The fallback is the branch that runs whenever no statusline snapshot exists — verified for this
session: `.claude/janitor/context-usage.35e1e917-….json` is **ABSENT** (seven other sessions'
snapshots are present, so the dir is real and this session simply has none).

`latest_context_size` returns the newest usage-bearing assistant entry. On the FIRST turn after a
compaction, that entry is the **pre-compaction** turn — this turn has not written one yet. So the
fallback returns a number describing a context **that no longer exists**, and labels it fresh.

Window of exposure: from the compaction until this turn's first assistant usage line lands —
exactly the window in which the agent decides what to do next.

## Why it is medium, not high — the dangerous half is already guarded

The ENFORCEMENT tier (`_maybe_enforce` → `permissionDecision: deny` + auto-compact) is protected by
the once-per-compaction-episode dedupe (`_recently_compacted`/`_mark_compacted`, its own
`_dedupe_path` stamp, `_AUTOCOMPACT_DEDUPE_S`), so a stale reading **cannot** produce a
compact-deny loop. `stale` is not even passed to `_maybe_enforce`. What is unguarded is the
ADVISORY/PREPARE text the agent reads and acts on. Cost is wasted tokens + a lossy compaction, not
a wedged session.

## The fix

`stale` is the wrong lever anyway: `_format_line` only appends `" (snapshot may lag)"`, which
*softens* a number that is not soft — it is **known wrong**. The file's own stated principle
(`latest_context_size` docstring) is the right one:

> *"correct-by-omission: the watchdog then stays silent rather than guess"*

So: when the newest reading predates the last compaction, return `(None, None, None, False)` —
`main()` already does `if pct is None: return 0`, i.e. total silence for the one turn until a real
reading exists. **Not an annotation — an omission.**

Predicate must be **compaction-aware, not age-based**. An age threshold is wrong twice: it marks a
legitimately-quiet session's valid reading stale (false positive), and it misses a compaction that
lands inside the threshold (false negative). The correct question is only
*"did a compaction land after this entry was written?"*

Signal already exists and is reachable: `last-compact.ts`, a high-water stamp written by
`post-compact-resume.py:450` → `cold_cache_compact.mark_compacted`. Verified present on disk,
written 01:15 by this very compaction.

**Injection, not import** — `cold_cache_compact` imports `token_meter`, so `token_meter` must not
import it back. `resolve_context` takes the epoch as a keyword (default `0` = unknown ⇒ gate
disabled ⇒ current behavior), and the two callers pass it. The stamp FILENAME moves to `state.py`
(imported by both the hook and `cold_cache_compact`, so no new import lands on the per-tool-call
hot path, and the constant keeps one home).

Fail-open direction: unknown entry ts, or no stamp ⇒ **not stale**. Never invent staleness.

## Fix in both callers, not just the hook

`resolve_context` exists precisely so the hook and `/janitor-token-report --live` "can never
silently drift apart" (its own docstring). `--live` would print the pre-compaction number as the
live one. Fixing only the hook would recreate the drift the shared function was created to
prevent.

## Acceptance

- [x] `resolve_context`'s transcript fallback returns a no-reading when the newest usage entry
      predates the last compaction, proven by a test that FAILS against today's code
- [x] A quiet-but-valid session (old entry, no newer compaction) is still reported — pinned by its
      own test, because an age-based predicate would break it
- [x] Unknown/absent stamp ⇒ unchanged behavior (fail-open), pinned
- [x] Both callers pass the epoch; `--live` and the hook agree
- [x] `ruff` + `mypy` + `pytest` green

## Falsification (both probes reverted; `grep FALSIFICATION` is clean)

A test that cannot fail is not evidence, so each guard was attacked:

  - **F1 — neuter the predicate** (`reading_predates_compaction` → `return False`):
    `test_resolve_context_omits_a_reading_written_before_the_last_compaction` failed with
    `(66, 660000, 1000000, False)` — the live bug's exact signature, a pre-compaction reading
    reported as fresh. The predicate unit test failed too.
  - **F2 — break the WIRING** (hook stops passing `last_compact_ts`): the same test failed. So the
    guard catches a correct predicate that nobody calls — the "exists but is not reachable from
    every caller" defect class that produced seven bugs in the preceding session.

Also caught in passing: the first `-k` filter (`predates`) silently **missed** the integration
test, whose name contains no such word — a falsification run that selects the wrong tests proves
nothing. Confirm the selected count, not just the failure.

## End-to-end proof on the real artifacts

```
newest entry: 327,209 tokens, written at 1786577315
last compaction stamp: 1786576545   entry_after_compaction=True
verdict now                              -> (47, 327209)   # reported, no false silence
verdict if a compaction landed 1s later  -> (None, None)   # omitted, the bug case
```

Full suite after the change: **14,947 passed, 1 skipped**; ruff + mypy clean over 472 files.

## Approval log

- 2026-08-13T01:24:02+0200 — Tier 0, authored directly at `column: dev`. Own-project bugfix inside
  the janitor's own machinery; no baseline deviation, no cross-project reach, reversible.
- 2026-08-13T01:47:10+0200 — dev → complete. All five acceptance boxes met, both falsification
  probes reverted, full suite green. Ships with the next publish (a USER decision, tracked
  separately) — the card claims no publish state of its own.
