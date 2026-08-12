---
trdd-id: 1QJIZFFW
title: Zero-cost compaction whenever the prompt cache is expired — wire the llm-externalizer CLI into the existing external-clear scaffold
column: blocked
created: 2026-08-12T13:11:10+0200
updated: 2026-08-13T00:15:36+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
severity: high
review-after: 2026-09-02
relevant-rules: []
npt: []
eht: []
blocked-by: [user-decision-run-the-clear]
external-refs: [TRDD-PXP08ZQC, TRDD-31095269, TRDD-D3PROACT, TRDD-WUUR2DFX]
---

# Zero-cost compaction on an expired cache

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

**~~PARKED ON THE OWNER'S GO-AHEAD~~ — GO-AHEAD GIVEN 2026-08-12, and the core is BUILT
(`df7d4cb3`).** The owner's words were "before publishing you must implement the zero tokens
compacting via llm-externalizer", which also makes this a gate on the pending release.

**DONE:** `use_llm_ext()` has a caller at last — `external_handoff_clear._compose` runs
`llm-ext session-summary` and composes the owner's three-part payload (scriptable facts +
summary + TRUNCATED tail) under ONE budget. Verified end-to-end on a real 464 KB transcript
(~1 s warm), payload inside budget at 8192/6000/4000/2500 with all three parts present, 10
tests.

**Four defects found by measuring, each of which would have shipped silently:** `facts` had no
`transcript` key (the summary branch would have degraded to template-only forever — dark code
in the commit meant to un-dark it); the unbounded summary ate the tail's room, producing a
handoff with no recent turns; a constant +38-byte overrun from appending the truncation notice
outside the accounting; and a test of mine that could not fail (`"m0" in "m100"`).

**THE REACTIVE TRIGGER IS NOW WIRED** (`169d967d`, `295c1243`). `agentlenspro cache-expired`
is the measurement; it is OR'd in AHEAD of the prediction so a fire is attributed to the
measurement when both agree. Two things it cost, both of which the code would have hidden:

  - **The watcher had been crashing on every run since `df7d4cb3`** —`_decide` passed a
    composer-only `transcript` key into the pure gate, which raised `unexpected keyword
    argument`, and the `# type: ignore[arg-type]` on that call is what kept mypy quiet. The
    feature was dead on arrival for the whole window in which it looked shipped.
  - **The probe's first timeout made the new trigger dead too.** At the burn probes' shared
    5 s it returned `None` on 2 of 3 real calls (measured CLI latency: 0.15 s, 11.5 s, 19.7 s)
    — and `None` fails open, so a too-short bound is INDISTINGUISHABLE from "agentlensPro is
    not installed". Its own 30 s constant now, pinned by a test that carries the measurement.

**STILL OPEN — this is why the column is `dev`, not `complete`:**
  1. no cross-`/clear` run through the existing `handoff_clear_verify.py` harness. This one is
     deliberately NOT self-serve: exercising it means clearing a live session's context, so it
     is run at a chosen safe point, not folded into unrelated work;
  2. the zero-Claude-token claim is REASONED (no model turn on the clear path, $0 summary) but
     not MEASURED end-to-end. Do it in the same sitting as (1) — the same run answers both.

**NEXT ACTION:** at a deliberate stopping point, run `handoff_clear_verify.py --phase before`,
`/clear`, then `--phase after`, and record BOTH the PASS/FAIL table and the turn's token
accounting on the clear path.

**SUPERSEDED — do NOT carry forward:**
  - *"STARTS WHEN: the owner says go"* / *"NEXT ACTION when unblocked: give
    `external_clear.use_llm_ext()` an actual caller"* — both discharged. The go-ahead came
    2026-08-12 and the caller landed in `df7d4cb3`.
  - *"the only remaining question is whether the owner considers v12.0.0 settled enough"* —
    answered by building against it with a hard timeout + degrade-to-template, so a young CLI
    cannot break the clear path.
  - the table row marking `use_llm_ext` **DARK** — it has a caller now
    (`external_handoff_clear._compose`).

### 2026-08-12 13:49 — the CLI has LANDED; the block is now only the owner's go-ahead

`llm-ext session-summary` ships in **llm-externalizer v12.0.0** (janitor#251). VERIFIED by
invoking it, not by reading the issue:

- Self-describes as **"$0 by construction"** — always the biggest free, text-emitting
  OpenRouter model, falling down a ranked list if one is delisted / stops being free /
  exhausts its daily cap mid-run.
- **Streams** the JSONL via map-reduce (never loads the transcript into memory) and
  **checkpoints after every chunk**, so an interrupted run RESUMES on re-invocation rather
  than restarting — re-running the same command is safe, which is what makes it usable from
  a hook that may itself be interrupted.
- `--stdout` prints the text; otherwise stdout is the report PATH, with banner/progress/errors
  on stderr — so `SUMMARY=$(llm-ext session-summary …)` is hook-safe by design.
- Relevant knobs: `--transcript` / `--session_id` (defaults to the project's most recent
  transcript), `--output`, `--prune`, `--max_chunk_tokens`, `--checkpoint`, `--resume`.

**THE INTEGRATION TRAP, measured — `CLAUDE_PLUGIN_DATA` MUST be set explicitly.** With it
unset the binary dies before doing any work:

```
[llm-externalizer] FATAL: native module 'better-sqlite3' is missing AND CLAUDE_PLUGIN_DATA
is unset. The launcher cannot self-install without a persistent data directory.
```

A janitor hook / detached child is EXACTLY that context. Worse, the value is **another
plugin's** data dir, and there are two candidates on this host
(`llm-externalizer-emasoft-plugins` and `llm-externalizer-inline`) — so it cannot be guessed
at call time and must be resolved and passed deliberately. With it set, the launcher
self-installs its native dep and runs.

Two further cautions for the wiring:

- **Do not read the exit code through a pipe.** `llm-ext … | head` reports `head`'s status;
  the launcher's own failure is invisible. Capture to a file, then inspect.
- The v12.0.0 issue thread is a FIX to this very command (an unbounded body-read hang: the
  abort was disarmed when headers arrived, so the timeout bounded time-to-first-byte only and
  a stalled generation hung forever). Treat the version as young: wrap the call in a real
  timeout of our own and degrade to `compose_template_handoff` on any non-zero exit.

## The injected payload — USER spec, 2026-08-12

**It is a HOOK that injects the handoff, not a skill or a command** (USER correction, 2026-08-12).
The hook layer already exists and runs: `PreCompact -> pre-compact-handoff.py`,
`PostCompact -> post-compact-resume.py`, `Stop -> on-stop-proactive-compact.py`. Build on those.
PXP08ZQC's "wire a task into `daemon.py`" NEXT ACTION is therefore NOT the shape to copy.

The new handoff injects THREE parts:

1. **The `llm-ext session-summary` output** — the CLI writes it to a file; inject that file.
2. **Scriptable facts about the pending TRDD(s)** — id, title, column, and the STATE block's NEXT
   ACTION. All of it is greppable from frontmatter, so it costs ZERO model tokens to assemble and
   is exactly the part that must never be paraphrased.
3. **The latest messages — TRUNCATED.** The tail of the conversation, capped.

**THE HARD CONSTRAINT: the injection must not refill the context it was built to empty.** A
handoff that restores a large payload at session start defeats the entire feature — we would pay
the cache-write we just avoided, one turn later. So the payload carries a byte/token BUDGET, and
the message tail is the part that gets cut (parts 1 and 2 are small and load-bearing; part 3 is
the elastic one). Truncate from the OLDEST end — the most recent exchanges are what a resuming
session needs.

Design notes for when this is built:
- Budget the whole injection, not each part separately, or three "small" parts add up.
- Say WHEN truncation happened ("N earlier messages dropped") — a silently clipped tail reads as
  a complete record, which is worse than an explicitly short one.
- Parts 2 and 3 must survive an llm-ext failure: if the CLI errors, inject 2 + 3 alone rather than
  nothing (degrade, never lose the handoff).

## Why (the USER's framing)

Two costs this removes, both paid today for nothing:

1. **The restart-after-a-long-pause cache miss.** Claude Code resumes with a cold prompt cache,
   so the FIRST turn re-writes the whole conversation at the cache-WRITE rate (~1.25x) instead
   of riding the 0.1x cache-read. On a large session that single turn is the most expensive of
   the day. Compacting *before* that first turn removes the thing being re-written.
2. **Every other cache expiry** — an API error, a blocking AskUser prompt nobody answered, a
   long network malfunction. Same waste, and today nothing reacts to it.

The USER's design, in intent: use the **agentlensPro CLI** to know *for certain* whether the
cache is expired; if it is, run the **llm-externalizer CLI** to compact at zero cost; then
`/clear`; then **inject the saved summary file back via a hook**.

## The socket already exists — do NOT rebuild it (VERIFIED at HEAD 2026-08-12)

The janitor already shipped this pipeline in TEMPLATE form under TRDD-PXP08ZQC. Verified
first-hand, not assumed:

| piece | where | state |
|---|---|---|
| the decision | `external_clear.should_clear_externally` | shipped — returns a named-rule verdict |
| the cache-miss predicate | `external_clear.next_fire_misses_cache` | shipped — "will the NEXT fire land on an EXPIRED cache?" |
| the TTL input | `external_clear.read_ttl_minutes` | shipped — reads the dispatcher's probed TTL |
| the handoff text | `external_clear.compose_template_handoff` | shipped — from ON-DISK facts, zero model tokens |
| the watcher/actuator | `scripts/external_handoff_clear.py` | shipped — the ZERO-model-turn clear |
| **the llm-ext switch** | **`external_clear.use_llm_ext`** | **DARK — exported, defaults True, ZERO callers** |
| the agentlens probe | `scripts/lib/agentlens_probe.py` | shipped — config-gated, bounded, fail-open |

So the work is **not** "build zero-cost compaction". It is: replace the template composer with
the llm-externalizer CLI behind the switch already written for it, and add the agentlensPro
expiry signal as a second trigger alongside the predictive one.

A switch defaulting to **True** with no callers is the exact defect shape audited all through
the 2026-08-12 session — code that exists, is exported, reads as a shipped feature, and never
runs. Its default is a promise the code does not keep; at wire-up time, re-decide the default
deliberately, because today it means nothing either way.

## What (sketch — decisions deferred until the CLI is real)

- **Trigger.** Keep `next_fire_misses_cache` (predictive) AND add the agentlensPro CERTAIN
  expiry read (reactive — API error, blocked AskUser, network gap). Predictive alone cannot see
  an unplanned expiry; reactive alone cannot pre-empt the restart case. Both, or it is partial.
- **Compose.** Behind `use_llm_ext()`: call the CLI, which writes the summary to a file and
  returns its path. Template composition stays the FALLBACK — a subprocess can fail, and a
  failed summarize must degrade to the existing zero-token template, never to a lost context.
- **Clear + re-inject.** `/clear`, then a hook injects the saved summary file. The existing
  `handoff_clear_verify.py` harness already measures a cross-`/clear` before/after — reuse it
  as the acceptance oracle rather than writing a second one.
- **Cost floor.** The whole point is ZERO Claude tokens. Any step costing a model turn defeats
  it; measure, do not assume (`llm-ext --estimate` on a paid profile).

## Acceptance (to be firmed up when unblocked)

- [x] The llm-ext compact verb exists and is invoked ONLY through `use_llm_ext()` — `df7d4cb3`
- [x] A CLI or probe failure degrades to `compose_template_handoff`, never to a lost handoff
- [x] agentlensPro-certain expiry triggers the same path as the predictive miss — `169d967d`,
      `295c1243`. Live: `cache_certainly_expired` returns a real `False` on this project.
- [ ] Measured: the whole cycle costs zero Claude tokens (no model turn on the clear path)
- [ ] Cross-`/clear` verification via the existing `handoff_clear_verify.py` harness

## Approval log

- 2026-08-12T13:11:10+0200 — QUEUED by janitor-main-session (tier 0, own scope). Filed at
  `backburner` rather than `todo` because it is blocked on an external deliverable, not on
  capacity — a WORK column would assert activity that cannot happen. The USER said "just wait";
  this card is the wait, made visible.
- 2026-08-12T18:58:36+0200 — `backburner` → `dev` by janitor-main-session (tier 0). The USER
  gave the go-ahead ("before publishing you must implement the zero tokens compacting via
  llm-externalizer"), which both unblocks the card and makes it a gate on the pending release.
  The core landed in `df7d4cb3`; three acceptance boxes remain, so the column asserts WORK
  rather than `complete`.
