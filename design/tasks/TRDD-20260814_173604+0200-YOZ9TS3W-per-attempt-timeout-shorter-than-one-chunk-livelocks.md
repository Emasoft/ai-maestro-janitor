---
trdd-id: YOZ9TS3W
title: A per-attempt llm-ext timeout shorter than one chunk can never make progress
column: complete
created: 2026-08-14T17:36:04+0200
updated: 2026-08-14T20:42:00+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: [e4ec23b0]
---

# A per-attempt llm-ext timeout shorter than one chunk can never make progress

## The defect

Three constants in `scripts/lib/external_clear.py` interact badly:

| constant | value | scope |
|---|---|---|
| `LLM_EXT_TIMEOUT_S` (:149) | 240 s | **per attempt** (`subprocess.run(timeout=…)`) |
| `DEFAULT_SUMMARY_DEADLINE_S` (:296) | 540 s | total effort |
| `DEFAULT_FLEET_LEASE_TTL_S` (:258) | 300 s | must exceed the per-attempt timeout |

`summarize_with_retry` retries until the deadline, and `classify_llm_ext_failure`
(:484) returns `OUTCOME_TRANSIENT` for **every** timeout — "a timeout always is
[worth retrying] — it is the shape a stalled generation and a dead network both
take."

That reasoning is right for a *stalled* generation. It is wrong for a chunk that
is simply **slower than the per-attempt budget**, and the two are indistinguishable
at this layer because both present as `timed_out=True`.

llm-ext checkpoints after every chunk/fold and resumes on re-invocation. So the
janitor's retry loop only makes forward progress **when an attempt completes at
least one chunk**. If a single chunk takes longer than `LLM_EXT_TIMEOUT_S`, that
chunk can never finish, nothing is ever checkpointed, and every retry restarts the
same doomed chunk until the 540 s deadline — then degrades to the template.

At 540 s total / 240 s per attempt that is at most ~2 attempts, both guaranteed to
fail, on any transcript whose next chunk exceeds 240 s.

## The measurement that makes this concrete

Supplied 2026-08-14 by the llm-externalizer maintainer session, measured at v13.5.0
(treat as reported data, not as a claim verified in this repo):

- Full session transcript, 3.49 MB → **194 s** wall-clock end to end. So the ~180 s
  mean the current 240 s was sized against is about right.
- **Per-chunk time ranged 91 s – 1478 s** on free models. The spread is queue
  contention, not chunk size: a 4× smaller chunk was no faster.
- No supported way to bound TOTAL wall-clock; `--chunk_timeout_s` is per-ATTEMPT by
  design (its own default is 600 s), and a client-side kill IS the intended
  mechanism for bounding total time.

The maintainer explicitly declined to quote a p90, having only the range and not the
distribution. Do not manufacture one — size against the observed upper end.

**The key number: the CLI's own per-attempt allowance is 600 s and ours is 240 s.**
We kill our own client less than halfway through what the server considers one
legitimate attempt.

## Why this is not "just raise the timeout"

`DEFAULT_FLEET_LEASE_TTL_S` (300 s) is **coupled** and its comment says why: it is
"comfortably over the ~180 s a run is expected to take AND over `LLM_EXT_TIMEOUT_S`
(240 s), so a lease never expires under a call that is still legitimately running —
that would admit a fourth worker while three are active, quietly defeating the cap."

Raise `LLM_EXT_TIMEOUT_S` past 300 s without raising the TTL and the fleet lane
silently over-admits: leases expire under still-running calls, and the free-tier
burst protection the owner asked for (max 3 concurrent, 2026-08-13) stops holding.
The cap would fail open with nothing reporting it.

`DEFAULT_SUMMARY_DEADLINE_S` (540 s) is also coupled: a per-attempt timeout that is
a large fraction of the total deadline means at most one or two attempts, so the
retry loop stops being a retry loop.

## Options

**A — raise all three, keeping the documented ordering invariant.**
e.g. per-attempt 600 s (matching the CLI's own `--chunk_timeout_s` default), lease
TTL comfortably above it, total deadline a small multiple of the per-attempt value.
*Pro:* an attempt is finally allowed to finish a normal slow chunk. *Con:* a
genuinely hung call now occupies a fleet lease far longer, and the external clear
takes longer to give up and degrade.

**B — classify a bare timeout as retryable only when progress was observed.**
Distinguish "stalled" from "slower than our budget" by checking whether the
checkpoint advanced between attempts; retry only when it did. *Pro:* attacks the
real defect — retrying something that provably cannot progress is exactly the case
`summarize_with_retry` documents it should stop early on. *Con:* needs the
checkpoint path, which is currently left at the CLI's deterministic default; reading
it couples us to a file the CLI owns.

**C — both.** Raise the values (A) so normal chunks fit, and add the progress check
(B) so a truly stuck run degrades promptly instead of burning the whole deadline.

**Recommendation: C**, with A first since it is a three-constant change with a
measured justification, and B behind it as the durable fix.

## Acceptance criteria

- [x] **DECISION: C (both), as recommended** — raise the constants so a normal slow
      chunk fits, AND add the progress gate so a truly stuck run degrades promptly
      instead of burning the whole deadline. A alone would have made a hung call sit
      on a fleet lease for the full 2600 s; B alone would still have killed every
      normal chunk at a budget below the measured 91–1478 s band. Shipped in
      `e4ec23b0`. **The progress gate ships OFF by default**
      (`test_the_progress_gate_is_off_by_default`): it reads a checkpoint file the
      CLI owns, so it is opt-in until that coupling is proven stable — B is present
      and tested, not yet load-bearing.
- [x] The ordering invariant `per-attempt < lease TTL` holds by construction, with a
      test that FAILS if a future edit breaks it (the coupling is currently only a
      prose comment, which is what let this drift).
      → `test_the_per_attempt_timeout_is_shorter_than_the_lease_ttl`. The TTL is
      DERIVED (`LLM_EXT_TIMEOUT_S + _FLEET_LEASE_TTL_MARGIN_S`), never a literal, so
      the invariant cannot drift by editing one number. A second test,
      `test_the_blocking_sessionstart_hook_timeout_covers_the_summary_deadline`,
      pins the other ordering pair — which is the one that was actually broken.
- [x] The per-attempt value is justified in a comment against the CLI's own 600 s
      `--chunk_timeout_s` default, not against the ~180 s mean.
      → `scripts/lib/external_clear.py:156`, citing the maintainers' measured
      91–1478 s per-chunk band alongside the 600 s default.
- [x] A test proving a chunk slower than the per-attempt budget is not retried
      forever with zero progress (whatever option lands).
      → `test_a_chunk_stuck_past_the_budget_stops_after_two_timeouts_not_the_deadline`,
      with `test_a_chunk_that_keeps_checkpointing_is_not_mistaken_for_stuck` as its
      falsification partner — a gate that fires on everything would pass the first
      test alone, so the pair is what makes it evidence.
- [x] `uv run pytest`, `uv run ruff check scripts tests`,
      `uv run mypy scripts/ --ignore-missing-imports` clean.
      → 83 passed on the targeted set; ruff clean; mypy clean over 484 files.

## Provenance

Found 2026-08-14 while auditing the janitor's llm-ext call contract for the
`/janitor-externalized-compaction` skill. The verb-spelling and checkpoint-durability
questions came back clean (the flat `session-summary` is the primitive, and the
checkpoint write is atomic tmp+rename, so our SIGKILL costs progress, not
correctness). This timeout finding is the one real defect the audit surfaced, and it
is on OUR side of the boundary, not the CLI's.
