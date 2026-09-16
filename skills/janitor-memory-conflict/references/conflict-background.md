# CONFLICT executor — background: overview, scope boundary, exit contract

Non-procedural context moved out of SKILL.md to keep its body under CPV's token
budget (TRDD verify pass, toc-embed-fix follow-up). The pipeline steps themselves
stay in SKILL.md; this file holds the WHY and the boundary/exit rationale.

## Table of contents

- Execution context and what this is
- Scope
- EXIT / SUCCESS / idempotency contract
- What `--op merge` enforces at commit

## Execution context and what this is

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Sonnet** agent (`janitor-memory-subconscious-agent` — Sonnet, not Opus, per
> the USER cost decision 2026-06-30) — you ARE that agent. Run the whole pass here in your own
> context and return only a one-line result + the report path. A wikimem editorial pass is
> never run inline in a main session (it must not burden CPV or any other session's context).

The third, costliest leg of the autonomous wikimem editor (siblings: SPLIT, MERGE).
It reconciles **contradictory or obsolete** memory pages against the actual source +
git history, and either:

- **DEMOTE** (the DEFAULT, ~95% of cases, non-destructive): consolidate the pair —
  the page with the current truth survives, the obsolete one is retired, and its
  still-true-of-the-past fact folds into the survivor as a compounding `[^N]` whose
  **WHY is SOURCED**, never inferred. Nothing is lost (two pages about one subject
  become one).
- **DELETE** (rare, hard-gated): only a **provably FALSE** fact WITH `commits:`/`trdd:`
  provenance AND no git trace, AND only after a **majority vote of N>=3 skeptic
  agents** (told to *disprove*) + a git-history verify — structurally the same
  pair-consolidation, so even a DELETE loses no knowledge.

The skeptic votes fan out as **parallel `Agent` calls** shaped like the ultracode
`Workflow` pool — this agent's toolset has `Agent`, not `Workflow`, so ramp parallel
Agent calls and re-enqueue on rate-limit text. ALL mutation goes through
`scripts/memory_txn_cli.py` (crash-safe, hash-guarded, flock-serialized); the agent
NEVER edits a live page, only staged COPIES committed atomically. Pool/backoff code
and the agent prompts live in the references (Resources).

## Scope

ONLY reconciles contradictory/obsolete wikimem pages in ONE memory scope per pass,
through `memory_txn_cli.py`; READ-ONLY against project repos. It does NOT create,
consolidate, or split pages — those are their own skills. Full boundary, including
the PROJECT-scope opt-in:
[conflict-protocol](conflict-protocol.md#scope).

## EXIT / SUCCESS / idempotency contract

- **SUCCESS = verify-pass + applied** (LOCAL/USER atomically via the txn; PROJECT, if
  opted-in, is staged-not-pushed — committed in the working tree, never pushed
  standalone, rides `publish.py`).
- **Retry ≤3 then abort** (staging discarded, one-line finding); other pairs are
  independent.
- **Idempotent + crash-safe:** every run starts with `resume`; the completed-txn-id is
  the idempotency key; a `rate_limited` return re-enqueues, never double-applies.
- **Bounded + disable-able:** one scope/pass, top-K pairs, pool cap 6–15;
  `conflict_per_day=0` or the kill-switch / `WIKIMEM_EDITOR_ENABLED=off` stops it.

## What `--op merge` enforces at commit

The `--op merge` gate is the right structural loss-oracle for a DELETE verdict: it
enforces ≥1 real delete, `survivor.ocd == min(retired ocds)`, every retired `[^N]`
preserved, no new duplicate line, and no page linking the retired slug.
