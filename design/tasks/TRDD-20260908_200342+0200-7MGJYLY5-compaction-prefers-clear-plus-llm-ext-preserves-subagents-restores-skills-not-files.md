---
trdd-id: 7MGJYLY5
title: Janitor compaction prefers clear plus llm-ext at turn boundaries, preserves subagents, restores skills not files
column: todo
created: 2026-09-08T20:03:42+0200
updated: 2026-09-08T20:03:42+0200
current-owner: janitor-session
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
labels: [compaction, handoff, resume, continuity, owner-ruling]
priority: high
npt: []
eht: []
relevant-rules: []
---

# Janitor compaction prefers clear plus llm-ext at turn boundaries, preserves subagents, restores skills not files

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

- **What this card is:** an OWNER RULING (USER, 2026-09-08 ~15:52 and ~16:05), relayed verbatim by
  the ai-maestro session over cross-session messaging at ~20:00. It is a REQUIREMENT card: it
  constrains the compact / handoff / resume skills and hooks. No code has been changed under it yet.
- **NEXT ACTION:** an implementer reads the STATE blocks of the open cards listed under
  "Cards this ruling constrains", decides per card whether it is CONFORMANT, needs a scope
  change, or is SUPERSEDED by this ruling, and records that decision in each card's STATE block
  before touching any skill or hook.
- **Gotcha:** the ruling says `/clean`; the earlier quote from the same session says `/clear`.
  It means `/clear`.

## The ruling, verbatim

~16:05 (2026-09-08):

> i changed 400k to 500k as the compaction threshold. but no matter what setting i use (it can
> change) the janitor should always prefer to use the /clean and llm-ext route. autocompact is
> consuming too many tokens and it happens too late, and without respecting turns boundaries,
> breaking agents running in background. instead the janitor must preserve the subagents and
> restore only the skills active, not the various files opened in the previous session. those
> files must only be mentioned, not read.

~15:52, same session:

> for automatic compaction, there is no need of summarization or handoff, the harness does this
> automatically! only when you do the compacting using /clear and the llm-ext cli tool ... i
> would prefer you to always compacting using /clear and llm-ext, but it is not always possible.
> and when the automatic compaction came, it must do its job. the janitor must only ensure
> continuity nudging the agent to resume his previous tasks.

## What the ruling requires (derived; the verbatim text above wins on any disagreement)

1. **Preferred path is `/clear` + llm-ext, driven by the janitor at a TURN BOUNDARY**, before the
   harness autocompact would fire. The janitor's own trigger MUST NOT depend on the value of
   `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (it changes; today 500k, was 400k). Reading it as a ceiling
   is allowed; keying behaviour on it is not.
2. **When autocompact happens anyway, the janitor does NOT summarize and does NOT write a
   handoff for it** — the harness already produces the summary. The janitor's only job on that
   path is a continuity nudge: resume the previous tasks.
3. **Background subagents survive the clear.** The clear path must not kill them, and the resume
   must re-attach (the resume listing already names them: "resume background agent via
   SendMessage: <id> — <type>").
4. **The post-clear restore re-activates only the ACTIVE SKILLS of the previous session** (for
   example `/ponytail`, `/colony`). It MUST NOT re-read the files that were open before. Those
   paths are listed as "mentioned, not read".

## Evidence the relaying session supplied (its measurement, not the owner's words)

On the relaying session, before the ruling, the pre-fill that reached the 400k threshold was NOT
the summary or the handoff (last five summaries 22–35 KB, precompact-handoff.md 6 KB). It was
the always-injected rules prefix (~583 KB deduped) against a ~500k autocompact window. So the
janitor's own re-read of previously-opened files on resume is the lever the owner is pointing at
in requirement 4.

## Cards this ruling constrains (? INFERRED from titles and columns — implementer verifies each)

All at `column: testing` on 2026-09-08 unless noted:

- `TRDD-PXP08ZQC` — external zero-turn handoff-and-clear with llm-ext. Likely CONFORMANT; check
  requirements 3 and 4 (subagent survival, skills-not-files restore).
- `TRDD-1QJIZFFW` — zero-cost compaction on EXPIRED cache. Requirement 1 widens the trigger from
  "cache expired" to "always prefer, at a turn boundary" — a scope change to record.
- `TRDD-2F3I2P18` — clear-first-then-summarize on any cache-invalidating event. Check the
  "summarize" half against requirement 2.
- `TRDD-OES0NN3F` — inject the handoff into context after a compaction. Requirement 2 says the
  autocompact path gets a NUDGE, not a handoff. Possibly SUPERSEDED in part.
- `TRDD-74AA4PAL` — compacted sessions are neither woken nor told a handoff exists. Same check as
  above: what gets injected after an autocompact is a nudge.
- `TRDD-GK35MOXU` — model-switch hooks as first-party clear triggers. Check requirement 1
  (turn-boundary discipline).

## Acceptance

- [ ] Each card above carries a dated STATE-block line naming its relationship to this ruling
      (conformant / scope changed / superseded in part), written after reading its body.
- [ ] The janitor's clear trigger has no code path that keys on `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
      (grep proves it; a read-as-ceiling is allowed and commented as such).
- [ ] A PreCompact / post-autocompact path writes NO handoff and NO summary; it emits only the
      resume nudge. A test asserts the absence.
- [ ] A clear with a live background subagent leaves that subagent alive and the resume listing
      names it. A test asserts it against a real subagent, not a mock.
- [ ] The post-clear restore lists previously-open files as paths only and re-reads none of them.
      A test asserts no Read of a listed path happens during restore.
- [ ] Active skills of the previous session are re-activated on restore. A test asserts it for at
      least two skills.

## Approval log

- 2026-09-08T20:03:42+0200 — Authored at `todo` from a USER ruling relayed by the ai-maestro
  session. Owner-authorized by the ruling itself; no further approval needed to start.
