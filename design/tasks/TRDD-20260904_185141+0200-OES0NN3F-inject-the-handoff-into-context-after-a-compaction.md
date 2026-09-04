---
trdd-id: OES0NN3F
title: inject the handoff into context after a compaction the way /clear already does
column: testing
created: 2026-09-04T18:51:41+0200
updated: 2026-09-04T20:28:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [continuity, hooks, compaction, handoff]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: [42a24e6f, 0b4f72c3, 2c852b51, b7fa08bf, 34b0d74d]
external-refs: [TRDD-74AA4PAL, TRDD-PXP08ZQC]
---

# Inject the handoff after a compaction, the way `/clear` already does

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-09-04

**Split out of `TRDD-74AA4PAL`** (rule 13, one atomic task per TRDD). That card diagnosed TWO
gaps and bundled two fixes; the other one changes when the janitor types keystrokes. Read
74AA4PAL for the evidence; it is not repeated here.

**⚠ THE TIER WENT `none` → `user` → `none`, AND BOTH MOVES WERE ERRORS OF THE SAME KIND.**
First filed `none` while I simultaneously asked the owner "say the word and I implement it now"
— frontmatter and prose disagreeing, with the frontmatter favouring the half I wanted to ship.
Then raised to `user`, which was the equal-and-opposite error: **the owner had already demanded
this behaviour twice** (*"they were unaware of any handoff"*, plus the recollection of asking
for scripted zero-token handoffs), so requiring their approval to deliver what they ordered was
using tier classification to avoid shipping — and its concrete cost was that the fix they were
frustrated about would not land tonight. Settled at `none` **with the cost disclosed below**:
a cost is a thing to TELL the owner, not a gate to stop on. What follows is disclosure, not
justification for a block. The change is:
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

- [x] A session that auto-compacts has the handoff text in its context at the next turn, with
      **no** heartbeat fire and **no** keystroke injection involved. — **COVERED BY
      `tests/test_session_start_compact_handoff_injection.py`, 8 tests, all passing.** The
      throwaway shell arms of earlier rounds are superseded: they were hand-run, uncounted, and
      twice produced a silence that was a FIXTURE bug rather than a working guard (a handoff
      filename outside `handoff_files`' pattern; a shell indirection that dropped an env var).
      Every test in the module now leads with a positive control for exactly that reason.
      It runs the hook as a SUBPROCESS with a real payload — still not the live
      PostCompact→SessionStart sequence, which remains the open box below.
- [x] The flag is **not** consumed by the injection (it must stay for the heartbeat, which is
      the actuator and also re-attaches background agents). — **MEASURED**: flag still on disk
      after injection.
- [x] A compaction with no handoff on disk injects nothing and logs nothing alarming. —
      `_handoff_body` returns `None`, caller returns silently (arm C).
- [x] `uv run ruff check`, `mypy --ignore-missing-imports` and `uvx --with pyright pyright` all
      clean on the changed file; `pytest -k "session_start or hooks_execute"` → **73 passed**.
- [ ] **Verified from a REAL compaction's logs, not only the simulated payload.** This is the
      one criterion still open — it needs an actual compaction to occur in a live session.

## Implementation

`scripts/hooks/on-session-start.py`:
- `_handoff_body(state, sd)` — extracted from `_inject_post_clear_handoff` so both paths build
  the payload through ONE code path. Two paths assembling the same payload separately is how
  one of them silently loses the `sanitize_for_drift_line` defang.
- `_inject_post_compact_handoff(state)` — gated on `resume-after-compact.flag`, **no
  manual/auto distinction** (compaction has no discard case, unlike `/clear`), flag deliberately
  not consumed.
- **Age bound: 24 h, shared with the CLEAR injection (`CLAUDE_PLUGIN_OPTION_COMPACT_RESUME_MAX_AGE_S`, default 86400, `0` disables the bound).**
  This took two wrong turns. 42a24e6f invented a private `..._COMPACT_RESUME_MAX_AGE_S` (24 h,
  right number, undiscoverable knob). 0b4f72c3 then adopted dispatch's 3 h directive bound to
  'fix a disagreement' — **but there was no disagreement to fix.** Dispatch's 3 h gates an
  ACTION (how long a resume directive keeps being re-cited to a live session); this gates
  CONTEXT (how old a handoff may be before injecting it is worse than silence). A 6 h-old
  compaction should restore context and NOT auto-resume the task, so the two differing is
  correct. The 3 h bound broke the case the feature exists for — **measured: compact at 02:00,
  open at 08:00 → nothing injected.** Now 1/6/12/23 h inject, 25 h does not.
- **`compact-handoff-injected.ts` guard** — compaction PRESERVES what follows it (a `/clear`
  does not), so not-consuming the flag, safe on the clear path, compounds here: 22 KB then
  44 KB then 66 KB across repeat compactions, and auto-compaction fires *because* the window
  filled. Session `71542cad` compacted 5× on 2026-09-04. Stamp compares against `written_at`,
  so a NEW compaction still injects.
- Called from the `source == "compact"` branch in `main()`, wrapped so a fault can never break
  session start.

## Notes

- **`implementation-commits:` never contains the newest CODE-CARRYING commit, by construction, and that is accepted rather
  than re-noticed each round.** The card is edited in the same change as the code, so the hash
  of the commit carrying both cannot be in it. Each entry is added by the NEXT commit; the
  newest code-carrying commit for this card is therefore never in this list. (A card-only
  edit — a STATE update, a correction — adds no hash at all, so the lag is measured against
  code commits, not against `updated:`.)

- Zero model tokens: the handoff is already composed with no model turn (`TRDD-PXP08ZQC`,
  `agent-handoff-compose.log`). This card only changes whether the existing file reaches the
  context.
