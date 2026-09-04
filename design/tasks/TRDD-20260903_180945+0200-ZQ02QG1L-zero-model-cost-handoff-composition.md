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

## MEASURED 2026-09-03 — the raw summary is 31,897 bytes, and that decides the design

A real `compose_agent_handoff.py --dry-run` on this session produced **31,897 bytes**
against `HANDOFF_MAX_BYTES = 4096`. Nearly 8× over, and 4× worse than the "7 KB in
practice" figure in `compose_handoff`'s own comment — which is why this was measured
instead of assumed.

**Consequence 1 — the clear path must NOT reuse `compose_agent_handoff.py`.**
`clear_trigger.check_handoff_concise` would return `too-large` on every run, immediately
before an UNRECOVERABLE `/clear`. `janitor-handoff-and-clear` therefore needs
`external_clear.compose_handoff`, which allocates the scriptable facts first, then a
guaranteed tail slice, then hands the summary whatever budget remains, and emits an
unconditional `memgrep recall` line so the result always carries a reference. That is
precisely this problem, already solved and already tested.

**So the four "unwired" functions are not dead weight — three of them are the answer.**
`compose_handoff` + `compose_template_handoff` + `HandoffInputs` should be LANDED for the
clear path, not deleted. Only `run_llm_ext_summary` remains a genuine duplicate of the
live `summarize_with_retry`.

**Consequence 2 — a size gate is owed on the path already shipped.**
`janitor-write-handoff` now writes the raw summary with no bound, and
`on-session-start.py::_inject_post_clear_handoff` injects the whole handoff group into the
fresh context. A 32 KB handoff therefore rides forward on every later turn — trading the
authoring cost for a per-turn read cost, which is the trade `token-economy-agents-and-scenarios.md`
warns against. Not wrong for `/compact` (the window survives either way), but it should be
bounded. Simplest fix: give `compose_agent_handoff.py` a `--max-bytes` defaulting to
`HANDOFF_MAX_BYTES` and route it through `compose_handoff` too.

## Deliberately NOT in this task

The owner also asked that skills and files stop being reloaded each session, with the agent
merely told what was read last time. That is a separate and larger change, and the saving is
unproven: a note costs a line, and if the model re-reads anyway the cost is paid twice.
Measure first, in its own TRDD.

## Acceptance

Box status re-verified against code on disk 2026-09-04 (delegated read-only
audit, then the load-bearing negative re-checked by hand — report:
`reports/board-drain/20260904_031250+0200-zq02qg1l-box-verification.md`).

- [x] `scripts/compose_agent_handoff.py` exists, writes a handoff with no model turn.
      — landed in `f9bf82ed`.
- [x] `janitor-write-handoff` no longer instructs the model to author prose.
      — `skills/janitor-write-handoff/SKILL.md:17` describes the composer and
      `:45` invokes it (`uv run --script --quiet
      "${CLAUDE_PLUGIN_ROOT}/scripts/compose_agent_handoff.py"`).
- [x] `janitor-handoff-and-clear` step 2 delegates to the external composer.
      — DONE 2026-09-04. Was verified NOT done by hand first (a grep for
      `compose_agent_handoff|llm-ext|llm_ext` over the skill returned nothing,
      and step 2 read `### 2. Write the CONCISE, LINK-ONLY handoff` — only ONE
      of the two skills was converted in `f9bf82ed`). Step 2 is now the same
      one-command `compose_agent_handoff.py --project-root` invocation
      `/janitor-write-handoff` uses.
      **It fixed a SECOND defect in the same edit**: the step wrote to the FIXED
      `agent-handoff.md`, the path retired by TRDD-5RXBI65T for having several
      independent writers and no coordination — one silently destroying another,
      measured twice in two days. The sibling skill already carried an explicit
      "never Write to `agent-handoff.md`" warning while THIS skill still
      instructed exactly that. The composer writes the per-session/ts/pid name
      through `handoff_files.write`, the only writer.
      Swept the repo for the retired path per the breaking-change rule: fixed a
      further 3 references in this skill (the `clear_trigger.py --directive`,
      the resume-flow description, the Resources entry) and 1 in `README.md`.
      The remaining hits are all in TRDD cards that DOCUMENT the retirement and
      are correctly historical.
- [x] Each converted skill degrades to the on-disk template when `llm-ext` is absent,
      exactly as `external_handoff_clear.py` already does. A missing CLI is never a
      reason to skip the handoff.
      — DONE 2026-09-04, unblocked by the box above. Both skills now carry the
      same stdout table: a path → proceed; `SUMMARY_FAILED <reason>` → NOT an
      error, the free mechanical `precompact-handoff.md` still covers the
      resume, say so and proceed; `NO_TRANSCRIPT` → report, nothing written.
      Both also carry the explicit prohibition that matters more than the table:
      **do not fall back to authoring the handoff yourself** — that is the cost
      the card exists to remove, and on the clear path it would be spent at the
      worst possible moment. The degradation is to the mechanical handoff, never
      to the model.
      The table was VERIFIED against the script, not transcribed from the
      sibling on faith (a review correctly flagged that I had copied it):
      `compose_agent_handoff.py:69` prints `NO_TRANSCRIPT` and `:77` prints
      `SUMMARY_FAILED {reason}`. What is NOT verified is the box's comparative
      clause — "exactly as `external_handoff_clear.py` already does" — since I
      did not read that script's absent-CLI path. The tick rests on the two
      skills sharing one composer whose literals are now confirmed, not on a
      comparison to `external_handoff_clear.py`.
- [ ] `uv run pytest` green; `uv run ruff check scripts tests` and
      `uv run mypy scripts/ --ignore-missing-imports` clean.
      — deliberately NOT ticked. The audit was told not to run these (the tree
      was in use by another suite run), so this box has no independent
      verification, and this session has already been caught twice citing a
      suite run that predated what it claimed to cover. Tick it only against a
      NAMED sha from a run that postdates the remaining work.

## What the conversion TRADED AWAY, recorded because it is a real consequence

The old step 2 imposed a shape by construction: link-never-inline, exhaustive by
reference, no duplicated TRDD `## STATE` blocks, "a few hundred bytes to low KB".
`compose_agent_handoff.py` imposes none of that — it is an `llm-ext` PROSE
SUMMARY of the transcript. So the link-only contract is gone from this path, and
that was not a stated goal of the card.

**This skill is the first to put composer output in front of the concision
check**, which makes it a NEW interaction rather than an inherited one: the
already-converted `/janitor-write-handoff` feeds `/compact`, which checks
nothing, whereas this skill's step 3 feeds `clear_trigger.py`, which does:

- `_HANDOFF_MAX_BYTES = 4096` (`clear_trigger.py:124`)
- `_REFERENCE_RE = re.compile(r"\[\[|ATOM-[A-Z0-9]|TRDD-[A-Za-z0-9]|memgrep|#\d+")`
  (`:130`)

Nothing in the composer emits those tokens BY CONSTRUCTION, and a prose summary
can exceed 4 KB. So `no-references` and/or a bloat warning may now fire on every
clear.

**Not a blocker, and the reason is verified rather than assumed:**
`clear_trigger.py:791` states the contract as *"ABSENCE IS FATAL; shape is
WARN-only"* — an absent handoff REFUSES the clear (owner invariant 2026-08-28,
after a session woke blank mid-migration), while a bloated or reference-free one
still clears, because losing the session to enforce concision is the worse
trade. So the failure mode is stderr noise, not a lost context.

**It is still worth fixing, for a reason this repo already learned once:** a
warning that fires on every run carries no information and trains its reader to
ignore it (the same argument `stage_install_smoke` makes about its async-lag
note). Either the composer should emit reference tokens, or the check should
recognise composer-authored handoffs, or the constants should move. UNCERTAIN
and not measured: an `llm-ext` summary of a session that discusses TRDD ids
would likely reproduce them, so `_REFERENCE_RE` may match incidentally — which
would make the warning INTERMITTENT, which is worse than always. Settling it
needs one real `/janitor-handoff-and-clear` run with the composer's output fed
to `check_handoff_concise`.

Deliberately NOT fixed here: the card's boxes are about removing model
authorship, this is a downstream shape contract, and guessing at a fix without
the measurement above would be the same shape as the remedies this session had
to retract.

## A SECOND cross-path interaction, found while verifying the first

`compose_agent_handoff.py:95` writes `.janitor/state/resume-directive.txt`
(`state.atomic_write`). That file is the ONE-SHOT pointer the **PostCompact**
hook (`post-compact-resume.py`) consumes.

On the `/janitor-write-handoff` path that is exactly right — a compaction
follows, and the hook consumes it. **On THIS skill's path there is no
compaction**: step 3 fires `clear_trigger.py`, which carries its own
`--directive` through the keystroke chain, a different mechanism with a
different consumer. So the composer's `resume-directive.txt` is written and
NOT consumed here, and sits on disk armed for whatever compaction happens next
— potentially an unrelated one, hours later, pointing at a session that has
already been cleared and resumed.

The two directives do NOT clobber each other (different file, different
consumer), so this is not a repeat of TRDD-5RXBI65T. It is the adjacent shape:
a one-shot pointer left armed on a path that never fires it.

NOT measured, and NOT fixed blind. What would settle it: whether
`post-compact-resume.py` validates the directive's freshness or session id
before acting, and whether `clear_trigger.py`'s own resume path clears
`resume-directive.txt`. Recorded here rather than acted on, because the
plausible fixes (have the composer skip the directive when invoked from the
clear path; have `clear_trigger.py` consume or clear it) each change a file
with multiple readers, which is how this family of bug was created in the
first place.

## Notes and lessons learned
