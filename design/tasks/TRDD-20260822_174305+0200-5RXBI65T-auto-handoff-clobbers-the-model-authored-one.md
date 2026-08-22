---
trdd-id: 5RXBI65T
title: The auto-composed handoff overwrites the model-authored one at the same path
column: todo
created: 2026-08-22T17:43:05+0200
updated: 2026-08-22T22:59:10+0200
current-owner: janitor-main-session
task-type: bugfix
severity: medium
scope: project
approval-tier: 0
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: []
implementation-commits: []
---

# `.janitor/state/agent-handoff.md` has TWO writers and no coordination

## ⏵ STATE — READ THIS FIRST ON RESUME

**Not started.** Diagnosed 2026-08-22 by having it happen: a rich handoff this session had just
authored was silently replaced mid-session.

### F1 — the overwrite is unconditional (certain, read in source)

`scripts/external_handoff_clear.py:428`

```python
state.atomic_write(sd / "agent-handoff.md", text)
```

No guard, no read-before-write, no merge. That path is **also** where the
`/janitor-write-handoff` skill writes the model-authored handoff — the expensive one, authored
deliberately at a delicate juncture to carry exactly the reasoning a mechanical snapshot cannot
produce. The skill's own docs describe the rich handoff and the mechanical
`precompact-handoff.md` as complementary files that "coexist"; nothing anticipated a **third**
writer aimed at the rich one's path.

So the cheap automatic artifact destroys the costly deliberate one, and the loss is silent —
there is no `.prev`, and `.janitor/state/` is gitignored, so nothing recovers it.

### F2 — and the replacement was already stale when written (certain from evidence)

| fact | value |
|---|---|
| file mtime | `2026-08-22 17:38:10 +0200` |
| header stamp inside it | `2026-08-22T16:48:21+0200` |
| what it says about TRDD-4GQ94FNJ | `` `dev` `` |
| what that card actually said, since 17:04 | `column: human_review` (`07d3bb2e`) |

Written at 17:38 carrying a card snapshot from 16:48 that had been wrong for 34 minutes. The
clobber traded current information for stale information.

**⚠ RETRACTED 2026-08-22, SAME DAY, BY THE LOG. The section below was headed "MECHANISM PINNED
DOWN — read in source, no instrumentation needed". That heading was wrong twice over: the card
had said "do NOT guess it; instrument it", and I answered it with a better-sourced guess, then
committed it as fact (`2994469a`).**

**The settling evidence: `.janitor/logs/external-clear.log` contains ZERO lines dated
2026-08-22** (file mtime 2026-08-20T08:21). `main()` logs on every path that reaches the write —
`fired:` (:430, immediately after `atomic_write` at :428), `handoff degraded to template` (:317),
`handoff violates the concision contract` (:419), `declined:` (:413). None of them fired that
day. **So `external_handoff_clear` did not write `agent-handoff.md` at 17:38 on 2026-08-22, and
F2's premise — that the clobbering write came from this script — is unsupported.** F1's
attribution of the clobber inherits that doubt: the unconditional `atomic_write` at :428 is real
and dangerous, but it is not shown to be what happened on 08-22. *(Bound on this evidence: a run
whose verdict is HOLD logs nothing, so silence does not prove the script never RAN — only that it
never reached the write.)*

**What survives, and is now EMPIRICAL rather than deduced:** the compose-blocks-for-tens-of-
minutes mechanism is real, and the log proves it on a different date —
`2026-08-20T08:05:48 summary: transient — timed out after 600s; retrying in 6s` →
`08:21:29 summary: ok on attempt 2` → `08:21:29 fired:`. `_compose` was inside the retry loop for
~26 minutes on that run, with `now_iso` and the cards already captured. So the staleness hazard
below is genuine; only its use to explain the 17:38 observation is withdrawn.

Two further proxy reads in the retracted reasoning, worth keeping as guardrails: I quoted
`DEFAULT_SUMMARY_DEADLINE_S = 2600` as the effective value when `summary_deadline_s()` prefers
`$CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_SUMMARY_DEADLINE_S`; and I never confirmed the
`if ec.use_llm_ext() and transcript:` branch was taken. The 2 989 s vs 2 600 s shortfall I booked
as "unmeasured residue" also had a better candidate sitting in the same file — the deadline is
checked BETWEEN attempts, so a final attempt starting just under it runs a further
`LLM_EXT_TIMEOUT_S = 600` and overshoots.

**The code shape below is still accurately read; treat it as the hazard's description, not as an
explanation of the 17:38 event.**
`_compose` and `atomic_write` are adjacent in `main()` (compose at :416, write at :428), so the
delay is not between them — it is INSIDE `_compose`, and it is by design:

```
external_handoff_clear._compose
  :278  _gather_cards(root)          ← the card snapshot is taken HERE
  :286  now_iso = time.strftime(…)   ← the header is stamped HERE
  :306  ec.summarize_with_retry(…, deadline = now + ec.summary_deadline_s())
                                      ← BLOCKS up to DEFAULT_SUMMARY_DEADLINE_S = 2600 s (43m20s)
  :318  ec.compose_handoff(…, now_iso=now_iso, tail=ec.recent_messages(transcript))
```

The cards and the stamp are captured BEFORE a retry loop budgeted at four 600 s llm-ext attempts
plus backoff. Observed gap 16:48:21 → 17:38:10 = **2 989 s**; the deadline alone accounts for
2 600 s of it, with the remainder plausibly `recent_messages()` + `compose_handoff()` parsing a
multi-MB transcript (that residue is NOT yet measured — do not assert it as fact).

**The fix is a move, not a redesign:** take `_gather_*` and `now_iso` AFTER the summary returns,
immediately before `compose_handoff`. `summarize_with_retry` consumes only `transcript`, so
nothing else depends on the current ordering. Keep `facts["idle_seconds"]` / `["context_tokens"]`
at DECISION time — those justified the fire and are correctly historical; only the material the
next session reads as current state must be write-time.

**This is independent of the A/B/C question below** — the stale stamp is wrong under every one of
the three options, so it can land first without pre-judging the design decision.

### Why this is the same defect class we have hit twice already

A shared resource with independent writers that cannot see each other — recorded on
TRDD-YWMKNKVT (the USER-scope MOVED notice, 247 redirect lines of churn) and TRDD-KVS6K7P9
finding 3 (the USER memory root). The twist here is that **both writers are the janitor's own**,
in one process tree, so this one is entirely ours to fix.

## The design question — do NOT pick unilaterally

Both files answer the same question ("what does the next turn read first"), so a second path is
not obviously right either.

| option | cost | objection |
|---|---|---|
| **A** — external writes `agent-handoff-auto.md`; readers read both | touches `clear_trigger.py`, `dispatch.py`, `handoff_clear_verify.py`, which all name the filename | two files to keep ordered; a reader that forgets one gets half the story |
| **B** — preserve: rename the existing file to `.prev` before writing | one file, one function | the pointer still says read `agent-handoff.md`, which no longer has the rich content — preserves the bytes, not the usefulness |
| **C** — merge: keep the auto index, append the prior model-authored handoff below it under a marked heading | one file, one function, nothing lost | collides with the concision contract (`HANDOFF_NOT_CONCISE`), which is a **ratified** constraint and must not be quietly widened |

C looks right on the merits — the contract's target is not inlining what a pointer can resolve,
and a handoff the model chose to write is not that. But the contract is ratified, so widening it
is a decision, not an implementation detail. **Consult the advisor and confirm with the USER
before building.**

## Acceptance

- [ ] a model-authored `agent-handoff.md` survives an external `external_handoff_clear` fire
      (test: write a rich handoff, fire the composer, assert the rich content is still reachable)
- [ ] the auto-composed text's card columns match the cards on disk **at write time** — the F2
      staleness is instrumented and closed, not assumed away
- [ ] whichever option lands, `/clear` recoverability is unchanged (the handoff is the only thing
      that survives a clear, so a regression here is unrecoverable by construction)

## Notes and lessons learned

The operational lesson, which applies before any code changes: **`.janitor/state/agent-handoff.md`
is not durable storage.** It is gitignored and has an automatic second writer. Anything that must
survive belongs in a TRDD or the wiki. This card exists because a flake roster and a
memorize-nudge ruling were parked there and evaporated within the hour; the gate analysis
survived only because it had also been written into TRDD-4GQ94FNJ's own `## Gate` section.
