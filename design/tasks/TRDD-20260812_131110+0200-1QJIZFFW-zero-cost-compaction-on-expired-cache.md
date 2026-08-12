---
trdd-id: 1QJIZFFW
title: Zero-cost compaction whenever the prompt cache is expired — wire the llm-externalizer CLI into the existing external-clear scaffold
column: backburner
created: 2026-08-12T13:11:10+0200
updated: 2026-08-12T13:49:13+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
severity: high
review-after: 2026-09-02
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-PXP08ZQC, TRDD-31095269, TRDD-D3PROACT, TRDD-WUUR2DFX]
---

# Zero-cost compaction on an expired cache

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

**PARKED ON THE OWNER'S GO-AHEAD — not on any task. Do not start.** No `blocked-by:` is set
because nothing on this board blocks it: `column: backburner` is the honest resting state, and
the wait is a human decision.

The USER directed (2026-08-12, verbatim) "just wait": the llm-externalizer CLI that compacts a
session at ZERO token cost was *almost done*. **It has since SHIPPED** — see the dated section
below. So the original technical precondition is MET and the only remaining question is whether
the owner considers v12.0.0 settled enough to build against (its own issue thread is a fix to
that very command).

**STARTS WHEN:** the owner says go. Nothing else is outstanding.

**NEXT ACTION when unblocked:** give `external_clear.use_llm_ext()` an actual caller — see
"The socket already exists" below. Do NOT design a new subsystem; the scaffold is built.

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

- [ ] The llm-ext compact verb exists and is invoked ONLY through `use_llm_ext()`
- [ ] A CLI or probe failure degrades to `compose_template_handoff`, never to a lost handoff
- [ ] agentlensPro-certain expiry triggers the same path as the predictive miss
- [ ] Measured: the whole cycle costs zero Claude tokens (no model turn on the clear path)
- [ ] Cross-`/clear` verification via the existing `handoff_clear_verify.py` harness

## Approval log

- 2026-08-12T13:11:10+0200 — QUEUED by janitor-main-session (tier 0, own scope). Filed at
  `backburner` rather than `todo` because it is blocked on an external deliverable, not on
  capacity — a WORK column would assert activity that cannot happen. The USER said "just wait";
  this card is the wait, made visible.
