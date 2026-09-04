---
trdd-id: OES0NN3F
title: inject the handoff into context after a compaction the way /clear already does
column: todo
created: 2026-09-04T18:51:41+0200
updated: 2026-09-04T19:05:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: user
labels: [continuity, hooks, compaction, handoff]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-74AA4PAL, TRDD-PXP08ZQC]
---

# Inject the handoff after a compaction, the way `/clear` already does

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-09-04

**Split out of `TRDD-74AA4PAL`** (rule 13, one atomic task per TRDD). That card diagnosed TWO
gaps and bundled two fixes; the other one changes when the janitor types keystrokes. Read
74AA4PAL for the evidence; it is not repeated here.

**⚠ THIS CARD WAS FIRST FILED AS `min-approval-requirement: none`. THAT WAS AN
UNDER-CLASSIFICATION, and it was the half I wanted to ship** — the tell was filing it as
approval-free while simultaneously asking the owner "say the word and I implement it now". The
frontmatter is what a future agent reads, so the two must not disagree. Raised to `user`,
because the change is:
- **fleet-wide** — the janitor is USER-scope, so this fires in **every** repo on the machine,
  not just this one;
- **not free, despite "zero tokens"** — that phrase means *no model turn composes the handoff*,
  which is true and is NOT the same as costless. Today's handoff was **22,702 bytes**; injected
  into a compacted session it is billed as input on that turn and rides forward at the
  cache-read rate on every subsequent turn. On a machine where window burn is an active
  concern, that is a real cost the owner should price;
- **irreversible per occurrence** — text already in a context window cannot be recalled.
"Types nothing" is true and answers a question nobody asked; the keystroke risk belonged to the
*other* card. The risk here is context and cost.

**THE ONE FACT THIS CARD RESTS ON** (measured, 74AA4PAL GAP 2): `_inject_post_clear_handoff`
(`scripts/hooks/on-session-start.py:304`, called `:529`, gated on `resume-after-clear.flag`) is
the **only** handoff-injection function in `scripts/`. A session that COMPACTS gets no
equivalent — it is left `resume-after-compact.flag` and learns the handoff exists only if a
heartbeat cue arrives to tell it to read the file.

**WHY IT MATTERS INDEPENDENTLY OF THE WAKE FIX.** The owner's report was two sentences, and the
second one is this card: *"and even so they were unaware of any handoff."* Even a session woken
perfectly — by a cue, or by the owner typing `/janitor-resume` — still has to be TOLD. An
injection lands before the first turn and needs no nudge to have fired.

## NEXT ACTION

1. Add a compact-path sibling to `_inject_post_clear_handoff`, gated on
   `resume-after-compact.flag` (mirroring the clear path's 7-day age bound and its
   already-injected guard — `lib/handoff_files.py:108` documents the double-injection bug that
   guard exists to prevent).
2. Decide the ONE genuine design question: `/clear` distinguishes a janitor-driven clear (flag
   present ⇒ inject) from a MANUAL `/clear` (no flag ⇒ only point at the handoff, because the
   user may have meant the clear as a discard — `on-session-start.py:258-298`). **Compaction has
   no discard case** — nobody compacts to throw work away — so the compact path should inject
   unconditionally when the flag is present, with no manual/auto distinction. Confirm that
   reading against `dispatch.py::_phase_compact_resume` before writing the branch.

## Acceptance criteria

- [ ] A session that auto-compacts has the handoff text in its context at the next turn, with
      **no** heartbeat fire and **no** keystroke injection involved.
- [ ] No double-injection when a cue also fires later (the `handoff_files` group guard holds).
- [ ] A compaction with no handoff on disk injects nothing and logs nothing alarming.
- [ ] Verified from a REAL compaction's logs, not only by unit test.
- [ ] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports` and
      `uvx --with pyright pyright` all clean.

## Notes

- Zero model tokens: the handoff is already composed with no model turn (`TRDD-PXP08ZQC`,
  `agent-handoff-compose.log`). This card only changes whether the existing file reaches the
  context.
