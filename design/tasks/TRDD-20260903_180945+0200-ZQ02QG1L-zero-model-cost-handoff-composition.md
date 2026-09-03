---
trdd-id: ZQ02QG1L
title: Compose every janitor handoff out of process — no model turn spent authoring one
column: todo
created: 2026-09-03T18:09:45+0200
updated: 2026-09-03T18:09:45+0200
current-owner: main-session
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

# Compose every janitor handoff out of process — no model turn spent authoring one

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

- **Audit is done.** `reports/handoff-cost-audit/20260903_175606+0200-handoff-zero-cost-audit.md`
  holds the per-surface cost table. Read it before touching anything.
- **CORRECTED 2026-09-03, after tracing the live pipeline.** An earlier revision of this
  block named `run_llm_ext_summary` + `compose_handoff` as the engine to reuse. That was
  wrong, and the mistake came from a grep that EXCLUDED the file the caller would live in.
  Those two, plus `compose_template_handoff` and `HandoffInputs`, have **no production
  caller anywhere** — they are fully tested but unwired, a richer composer that was
  designed and never landed. Do not build on them without deciding that question first.
- **The LIVE zero-cost pipeline, end to end, is three steps.**
  1. `scripts/summarize_previous_session.py` — the ONLY writer of handoff files. It calls
     `external_clear.summarize_with_retry(transcript, deadline)` (not `run_llm_ext_summary`)
     and writes the raw llm-ext text via `handoff_files.write`.
  2. `external_handoff_clear.py` does NOT compose synchronously. It captures the transcript
     as the summary source, writes `summary-pending.json`, takes a hold, and delegates.
  3. The cleared session's SessionStart hook `_inject_post_clear_handoff` reads the whole
     group with `handoff_files.newest_group(sd)` and injects it before the first turn.
- **So the gap is smaller than the card first claimed.** A zero-cost transcript-to-handoff
  path already runs in production. It is aimed at the PREVIOUS session at SessionStart.
  What is missing is the same thing aimed at the CURRENT session, on demand.
- **NEXT ACTION** — write `scripts/compose_agent_handoff.py` modelled directly on
  `summarize_previous_session.py`, differing in one respect: resolve the CURRENT transcript
  rather than excluding it. Verified 2026-09-03 that newest-by-mtime does return the live
  session's own `.jsonl` mid-session. Reuse `summarize_with_retry` and `handoff_files.write`;
  do not reach for the unwired composers.
- Then collapse `skills/janitor-write-handoff/SKILL.md` step 2 to a call of that script.
- Then point `skills/janitor-handoff-and-clear/SKILL.md` step 2 at the existing
  external composer instead of asking the model to author the link-only index.

## Why

The owner's directive of 2026-09-03: every janitor command must cost zero model tokens.
Where intelligence is genuinely needed, it comes from the `llm-ext` CLI running against
its own free models, out of process, never from this session's window.

The audit found three surfaces that violate this. All three ask the model to author prose
that a script plus `llm-ext` can produce from material already on disk.

| surface | what the model does today |
|---|---|
| `janitor-write-handoff` | authors a rich six-section semantic handoff by hand |
| `janitor-handoff-and-clear` | authors the link-only handoff index by hand |
| `janitor-compact-context` | composes a one-line resume directive |

## The three zero-cost engines that already exist

Nothing new has to be invented. The work is routing.

- `scripts/external_handoff_clear.py` composes a handoff from on-disk facts, TRDD `## STATE`
  blocks, git log and the findings ledger, then upgrades the prose through `llm-ext`.
  Reached today by exactly one skill, `janitor-externalized-compaction`.
- `scripts/summarize_previous_session.py` summarizes a completed session transcript through
  `llm-ext` at SessionStart. Proves the transcript-to-summary path works unattended.
- `scripts/hooks/pre-compact-handoff.py` writes the mechanical handoff on every compact,
  free, from git and the filesystem.

The gap is a semantic handoff for the CURRENT session. That is the only new code.

## Scope boundaries

- The resume push is **not** overhead. A resume must eventually hand control to the model,
  so that turn is the work itself.
- Native `/compact` re-reads the whole window. That cost is inside Claude Code and cannot
  be removed from this plugin. `janitor-compact-context` already tells the model to prefer
  the cheaper siblings.
- The harvest precondition in `janitor-handoff-and-clear` step 1 stays. It captures
  knowledge that is not yet on disk, which no out-of-process composer can see. Deleting it
  would lose facts, not save tokens.

## Scope widened by owner directive, 2026-09-03

> *"all operations of compacting/handoff/etc. are executed by scripts (via llm-ext if
> necessary) and never by agents. no token should be used or consumed in the operations
> related to resume/clear/compact/rearm/etc."*

| operation | reachable at zero model cost? | why |
|---|---|---|
| compose a handoff | **yes** | script + `llm-ext`, out of process. The engine exists. |
| clear / compact trigger | **already is** | `clear_trigger.py` / `compact_trigger.py` are pure scripts. |
| verify across the clear | **already is** | `handoff_clear_verify.py` is a pure script. |
| inject the handoff on resume | **already is** | the SessionStart hook injects it before the first turn. |
| decide to shrink | **yes, not yet wired** | `external_handoff_clear.py` decides in-script, but only a model invoking the skill calls it. A hook or the daemon could. |
| **the resume turn itself** | **no — and it is not overhead** | a resume exists to hand control back to the model; that turn IS the work. |
| **re-arm** | **NO — platform limit** | `CronCreate` is a MODEL tool. No script can schedule a cron; the janitor's own bootstrap types `/janitor-arm` into the pane for exactly this reason. Make it RARE (7-day expiry + SessionStart re-plumb), not free. |
| native `/compact` | **no** | Claude Code internal; it re-reads the window. Avoid it, cannot cheapen it. |

**The honest summary: everything except the resume turn and the re-arm is reachable, and
most of it is already there but unreachable without a model deciding to call it.** The
remaining work is therefore mostly WIRING, not building — move the trigger from "a skill the
model invokes" to "a hook or daemon task that fires on its own".

## Deliberately NOT in this task

The owner also asked that skills and files stop being reloaded each session, with the agent
merely told what was read last time. That is a separate and larger change, and the saving is
unproven: a note costs a line, and if the model re-reads anyway the cost is paid twice.
Measure first, in its own TRDD.

## Acceptance

- [ ] `scripts/compose_agent_handoff.py` exists, writes a handoff with no model turn.
- [ ] `janitor-write-handoff` no longer instructs the model to author prose.
- [ ] `janitor-handoff-and-clear` step 2 delegates to the external composer.
- [ ] Each converted skill degrades to the on-disk template when `llm-ext` is absent,
      exactly as `external_handoff_clear.py` already does. A missing CLI is never a
      reason to skip the handoff.
- [ ] `uv run pytest` green; `uv run ruff check scripts tests` and
      `uv run mypy scripts/ --ignore-missing-imports` clean.

## Notes and lessons learned
