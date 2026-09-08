---
trdd-id: 7MGJYLY5
title: Janitor compaction prefers clear plus llm-ext at turn boundaries, preserves subagents, restores skills not files
column: todo
created: 2026-09-08T20:03:42+0200
updated: 2026-09-08T23:00:40+0200
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
- **2026-09-08 23:00 — box 1 done:** the six constrained cards each carry a dated relationship
  line (six-card read `reports/board-drain/20260908_223500+0200-7MGJYLY5-six-cards-read.md` plus
  first-hand greps of every quoted line): four CONSISTENT WITH the R they touch — and none of the
  six delivers R1's fire-before-autocompact on context fill, that trigger is owned by none of
  them; 1QJIZFFW NEEDS A SCOPE CHANGE on R3 (its active-waiting gate vetoes the clear instead of
  preserving subagents through it); OES0NN3F CONFLICTS with R2 (prose handoff injected on the
  autocompact path) — OWNER DECISION pending: keep / narrow to a machine-readable record / drop.
  No skill or hook touched.
- **NEXT ACTION:** two owner decisions (1QJIZFFW's R3 scope change; OES0NN3F's R2 conflict),
  then boxes 2–6 as implementation work on the skills and hooks — none started. The context-fill
  trigger (box 2) has no owning card yet.
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

1. **Preferred path is `/clear` + llm-ext, driven by the janitor at a TURN BOUNDARY and earlier in
   the context fill than the harness autocompact** (owner: autocompact "happens too late, and
   without respecting turns boundaries" — one clause per timing), and preferred regardless of the configured threshold (owner: "no matter what
   setting i use (it can change)"; today 500k, was 400k). The relaying session's derivation, NOT
   the owner's words: that the trigger must not key on `CLAUDE_CODE_AUTO_COMPACT_WINDOW`. A
   trigger that reads the window and fires below it also satisfies the owner's sentence; the
   implementer decides that, the card does not.
2. **When autocompact happens anyway, the janitor writes NO summary and NO prose handoff for
   it** — the harness already produces the summary. The janitor's only job on that path is a
   continuity nudge: resume the previous tasks. A machine-readable record of what the nudge must
   name (live background subagents, active skills, opened-file paths) is read here as NOT a
   handoff, a boundary the owner did not draw, and stays allowed; requirement 3 depends on it.
3. **Background subagents survive the clear** (owner: "the janitor must preserve the subagents").
   The clear path must not kill them, and the resume must re-attach. The relaying session reports its resume listing already names them ("resume
   background agent via SendMessage: <id> — <type>"); unverified in this repo.
4. **The post-clear restore re-activates only the ACTIVE SKILLS of the previous session** (for
   example `/ponytail`, `/colony`). It MUST NOT re-read the files that were open before. Those
   paths are listed as "mentioned, not read".

## Evidence the relaying session supplied (its measurement, not the owner's words)

On the relaying session, before the ruling, the pre-fill that reached the 400k threshold was NOT
the summary or the handoff (last five summaries 22–35 KB, precompact-handoff.md 6 KB). It was
the always-injected rules prefix (~583 KB deduped) against a ~500k autocompact window. The
relaying session concluded from this that the re-read of previously-opened files on resume is the
lever behind requirement 4. The owner's sentence says what to stop doing, not why; this card does
not adopt the peer's "why".

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

- [x] Each card above carries a dated STATE-block line naming its relationship to this ruling
      (conformant / scope changed / superseded in part), written after reading its body.
      (2026-09-08 23:00 — see STATE; the two non-conformant verdicts await the owner.)
- [ ] The janitor's clear fires at a turn boundary and at a context fill below the harness
      autocompact point for the CURRENT setting. A test reads the value the harness actually has
      and asserts the janitor's clear fires below it. (Requirement 1 leaves keying on the variable
      to the implementer, so the test does not vary it.)
- [ ] The PreCompact / post-autocompact path writes NO summary and NO prose handoff; it emits the
      resume nudge plus, at most, the machine-readable record requirement 2 carves out. A test
      asserts the absence of the summary and prose-handoff files.
- [ ] A clear with a live background subagent leaves that subagent alive and the resume listing
      names it. A test asserts it against a real subagent, not a mock.
- [ ] The post-clear restore hook lists previously-open files as paths only and opens none of
      them, and the restore prompt tells the model "mentioned, not read". A test asserts on the
      hook's file opens and on the prompt text; what the model then does is out of a hook test's
      reach and is not claimed here.
- [ ] The restore prompt names each skill that was active in the previous session (a skill is not
      a process; naming it in the prompt is the only re-activation the janitor can do). "Active"
      needs a recording mechanism this card does not identify; the implementer names it in the
      STATE block. A test asserts on the prompt text for at least two skills.

## Approval log

- 2026-09-08T20:03:42+0200 — Authored at `todo` from a USER ruling relayed by the ai-maestro
  session. Owner-authorized by the ruling itself; no further approval needed to start.
