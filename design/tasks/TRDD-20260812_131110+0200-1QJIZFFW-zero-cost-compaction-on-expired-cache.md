---
trdd-id: 1QJIZFFW
title: Zero-cost compaction whenever the prompt cache is expired — wire the llm-externalizer CLI into the existing external-clear scaffold
column: backburner
created: 2026-08-12T13:11:10+0200
updated: 2026-08-12T13:11:10+0200
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

**BLOCKED ON AN EXTERNAL DELIVERABLE. Do not start.** The USER directed (2026-08-12, verbatim)
"just wait": a new **llm-externalizer CLI command that compacts a session at ZERO token cost**
is *almost done* but has not shipped. Every step below is unimplementable until it exists.

**UNBLOCKS WHEN:** the llm-externalizer CLI exposes a compact/summarize verb that writes the
summary to a FILE and costs no Claude tokens. Verify with `llm-ext --help` (its command list is
generated from the tool catalog, so it cannot drift) before assuming it landed.

**NEXT ACTION when unblocked:** give `external_clear.use_llm_ext()` an actual caller — see
"The socket already exists" below. Do NOT design a new subsystem; the scaffold is built.

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
