---
trdd-id: OES0NN3F
title: inject the handoff into context after a compaction the way /clear already does
column: complete
created: 2026-09-04T18:51:41+0200
updated: 2026-09-17T07:24:53+0200
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
implementation-commits: [42a24e6f, 0b4f72c3, 2c852b51, b7fa08bf, 34b0d74d, 57f015ba, e6cc2036, 9f601253, a96f7ef1, af8ded3a]
external-refs: [TRDD-74AA4PAL, TRDD-PXP08ZQC]
review-after: 2026-09-24
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

**2026-09-08 — vs owner ruling TRDD-7MGJYLY5:** CONFLICTS with R2. The ruling forbids any summary
or prose handoff on the harness's own AUTOcompact path (continuity nudge only); this card's
compact-path injection (`_inject_post_compact_handoff`, gated on `resume-after-compact.flag`)
delivers exactly such a handoff (22,702 bytes per the card). OWNER DECISION pending: keep as is
(overriding R2), narrow to a machine-readable record only, or drop in favour of the nudge. No
code change until decided; if the injection stays, the real-compaction check remains blocked on
a release as the card says. R3: subagents are mentioned, not their preservation through a clear
(per the six-card read); R4: outside this card's scope.
2026-09-17T06:10:00+0200 — orchestrator ruling R2 (main session as approver, 2026-09-17, under the owner's standing permission of 2026-09-03), resolving the 2026-09-08 CONFLICTS-with-R2 note above: on the harness auto-compact path the compacted session receives a short machine-readable continuity nudge (in-flight TRDD ids, live agents, active skills, open-file paths, capped 15 lines), not the full prose handoff -- landed in a96f7ef1 and refined in af8ded3a. scripts/hooks/on-session-start.py::_inject_post_compact_handoff (:291, confirmed present via tldr structure) now branches: trigger==auto calls _continuity_nudge (:270); the manual /clear path keeps _handoff_body (:221) unchanged, per R2's own carve-out ('the manual path is unchanged'). This is the 'narrow to a machine-readable record' option the 2026-09-08 STATE listed, chosen over 'keep as is' or 'drop'. Box re-read: none of the acceptance boxes literally demand the FULL PROSE handoff by name -- box 1 ('the handoff text in its context ... no heartbeat fire ... no keystroke injection') reads generically and is honestly met by the narrowed nudge text, which is still handoff text injected the same way; the card's own Implementation section (describing an unconditional _handoff_body call) is now STALE against the branched code and should be read superseded by this note, not by the acceptance boxes themselves. The one open box (verified from a REAL compaction's logs) is UNCHANGED by R2 -- it is a live-observation requirement orthogonal to prose-vs-nudge, and per TRDD-74AA4PAL's 2026-09-17 GAP2 finding the current branching code is verified live at HEAD but no session has yet confirmed the NUDGE (not the old prose) firing from an actual auto-compaction's logs. DECISION: neither complete nor superseded -- the card's purpose is intact and satisfied in the narrowed form for every already-ticked box, and the sole open box is not a prose-vs-nudge conflict, so the binary complete/superseded choice in the assignment does not apply; left at todo pending that one live observation. implementation-commits appended (not overwritten, per TRDD rule 8's 'accumulates the SHAs' -- overwriting would erase the 8 SHAs already on record): a96f7ef1, af8ded3a.
2026-09-17T06:30:00+0200 — review follow-up: softening and naming an owner for the open box. The prior entry's 'is honestly satisfied by the narrowed nudge' is a JUDGMENT, not a measurement -- re-flagged here as ? INFERRED, not settled fact: nobody has re-run this card's own test module against the branched _inject_post_compact_handoff to confirm box 1's positive controls still hold for the trigger==auto path (only TRDD-74AA4PAL's unrelated post-compact-resume.py tests were re-run this session). NAMED NEXT ACTION for the one open box (verified from a REAL compaction's logs): the next session with heartbeat access should (1) grep .janitor/logs/session-start.log for a source=compact entry logged by a plugin_root build that contains _continuity_nudge (grep -c _continuity_nudge against that build, mirroring the box's own 2026-09-05 corrected recipe), (2) confirm the nudge text (not the old prose) actually reached context, then tick this box citing that log line. Until that happens this card is an unowned live-observation gate, same failure class TRDD-74AA4PAL flagged for its own box 3 -- recording it explicitly here so it is not silently parked again.
2026-09-17T06:43:20+0200 — Box 8 TICKED with real evidence (evidence sweep, board-drain). ANIME2SVG project (~/Code/ANIME2SVG/.janitor/logs/session-start.log:1620-1629): session s:61f17503 entered plugin_root=…/ai-maestro-janitor/3.5.0 at 2026-09-15T16:59:08+0200, logged source=compact at 16:59:08, and ~/Code/ANIME2SVG/.janitor/state/compact-handoff-injected.ts was written at epoch 1789484354 = 2026-09-15T16:59:14+0200 (6s later, same session id) — the stamp _inject_post_compact_handoff writes AFTER a successful print. 3.5.0 contains the fix (grep -c _inject_post_compact_handoff on-session-start.py = 2, confirmed on every installed build 3.4.15-3.5.5). This satisfies both halves the box demands: a real source=compact entry AND a fix-carrying build, with the stamp as positive proof of injection (not just absence of a crash log). Same pattern also found in tldr-code, agents-discipline, fastedit, AgentlensPro, this repo itself, and ai-maestro (6 more stamps, all on builds >=3.5.0). Moved to testing — remaining work is none; all other boxes already ticked in the body.

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
      `tests/test_session_start_compact_handoff_injection.py`, the module's tests, all passing,
      and MUTATION-TESTED.** The
      throwaway shell arms of earlier rounds are superseded: they were hand-run, uncounted, and
      twice produced a silence that was a FIXTURE bug rather than a working guard (a handoff
      filename outside `handoff_files`' pattern; a shell indirection that dropped an env var).
      Every test in the module now leads with a positive control for exactly that reason.
      It runs the hook as a SUBPROCESS with a real payload — still not the live
      PostCompact→SessionStart sequence, which remains the open box below.
- [x] **Each test catches the defect it is named for, proven by mutation** (2026-09-04): the
      stamp guard removed → the two once-only tests fail; the bound set to dispatch's 3 h → the
      overnight test fails; `source == "compact"` replaced by `if True` → the source test
      fails; **`sanitize_for_drift_line` dropped → only the defang test fails, and all eight
      others pass** — which is why that ninth test exists: a security control could have been
      deleted without reddening the suite.
- [x] **The flag SURVIVES injection** — asserted in the once-only test. `flag.unlink()` after
      the print passed every other test; the heartbeat is the actuator and also re-attaches
      background agents, which this hook cannot do.
- [x] **The source gate is PRECISE, not merely present.** Widening it to
      `("compact", "clear")` first SURVIVED all nine tests: the control run had written the
      stamp, so the `clear` arm returned early on the guard instead of exercising the gate. The
      stamp reset that catches it had been removed as "dead ceremony" — dead only while the
      gate is correct, which is precisely what the test is for. Restored, and the mutation now
      fails the test named for it.
- [x] The flag is **not** consumed by the injection (it must stay for the heartbeat, which is
      the actuator and also re-attaches background agents). — **MEASURED**: flag still on disk
      after injection.
- [x] A compaction with no handoff on disk injects nothing and logs nothing alarming. —
      `_handoff_body` returns `None`, caller returns silently (arm C).
- [x] `uv run ruff check`, `mypy --ignore-missing-imports` and `uvx --with pyright pyright` all
      clean on the changed file; `pytest -k "session_start or hooks_execute"` → **73 passed**.
- [ ] **Verified from a REAL compaction's logs, not only the simulated payload.** This is the
      one criterion still open — it needs an actual compaction to occur in a live session.
      **CHECKED 2026-09-05 AND STILL OPEN — with the exact recipe, so the next session spends
      one command instead of re-deriving it.** `.janitor/logs/session-start.log` records the
      trigger as `source=compact`. Every such line predates this fix: the last two are
      `2026-09-04T06:37:02` and `2026-09-04T13:22:32`, while the implementation landed that
      evening (`0f00fd60`, 19:57:37). So **no compaction has occurred since the code shipped**,
      and `.janitor/state/resume-after-compact.flag` is absent right now.
      **⚠ THAT RECIPE WAS INCOMPLETE AND WOULD HAVE MIS-TICKED THIS BOX — corrected
      2026-09-05 by running it.** It said: *"any entry after 2026-09-04T19:57 is the evidence
      this box wants"*. A real compaction then happened
      (`[2026-09-05T04:44:39+0200] [s:58951a2c] source=compact`), which satisfies that
      condition **and proves nothing**, because the SESSION WAS RUNNING A BUILD WITHOUT THE
      FIX:
      - installed `…/ai-maestro-janitor/3.4.14/scripts/hooks/on-session-start.py` →
        `grep -c _inject_post_compact_handoff` = **0**; repo HEAD = **2**.
        **That 3.4.14 tree IS what the session loaded** — its own `entered` line says so:
        `[2026-09-05T04:44:39+0200] [s:58951a2c] entered
        (plugin_root=/Users/…/ai-maestro-janitor/3.4.14)`. Cited because the corrected recipe
        below tells the next reader to run exactly this check, and a card that teaches a check
        without showing its result makes them redo the work to trust the conclusion.
        *(“Could it live in 3.4.14 under another name?” — ruled out independently of naming:
        no `compact-handoff-injected.ts` stamp and no injection log line, so the BEHAVIOUR is
        absent however it might have been spelled.)*
      - `v3.4.14` was tagged **2026-09-04 00:38:38**; the fix landed **2026-09-04 19:57:37**
        (`0f00fd60`) — about 19 h AFTER the release. So no session on 3.4.14 can exercise it.
      - Consistent with that: no `.janitor/state/compact-handoff-injected.ts` stamp exists, and
        `session-start.log` goes straight from `source=compact` to `armed` with no injection
        line. **The code did not fail — it was not there.**
      **The corrected check, both halves required:** (1) a `source=compact` entry, AND (2) the
      session that logged it was running a build that CONTAINS the fix — verify with
      `grep -c _inject_post_compact_handoff` against the plugin_root that same log line records
      (`session-start.log` prints it on the `entered` line). Then confirm the handoff text
      reached that session's context: the `compact-handoff-injected.ts` stamp is the cheap
      witness.
      **So this box is now blocked on a RELEASE, not on a compaction.** Compactions are
      plentiful here; builds carrying the fix are not. Do not re-run the old recipe and tick
      this box — it is satisfiable only after a publish lands and this machine installs it.
      **⚠ A `/clear` DOES NOT COUNT and must not be mistaken for one.** This very session
      resumed from a post-CLEAR injection (`post-clear resume cue emitted (age 877s)`), which
      exercises `_inject_post_clear_handoff` — a DIFFERENT path from the
      `resume-after-compact.flag`-gated `_inject_post_compact_handoff` this box is about.
      Reading the clear as satisfying this box is the easy mistake here, and it would tick the
      one criterion that exists precisely because the simulated payload already passes.

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

- **The empty-body path's silence is now DISTINGUISHED from a crash's silence** (was recorded as
  "known, not covered, low value" — wrong: the gap swallows the whole feature for every
  compacted session, and the test that needed it already existed).
  `test_an_empty_handoff_injects_nothing` now also asserts `post-compact handoff injection
  failed` is absent from `.janitor/logs/session-start.log`. **Measured 2026-09-04:** with
  `if body is None: return` deleted, that assertion is the ONLY thing that fails —
  `TypeError('can only concatenate str (not "NoneType") to str')` in the log and no banner on
  stdout (the crash precedes the print — stdout is not empty, it still carries the hook's other
  output; `_injections` counts BANNER occurrences), so the `== 0` above still passes. **One mutation generalizes because the assertion is coupled to
  the SINK, not to the mutated line:** `_inject_post_compact_handoff` has exactly one call site,
  inside `main()`'s lone `try`, so an exception raised anywhere beneath it — `_handoff_body`,
  `sanitize_for_drift_line`, the `print` — unwinds to that one `except` and emits that one
  string. Boundary: a crash AFTER the banner reaches stdout fails on the `== 0` count instead,
  with a misleading message but no false pass.
  **That probe is a PROXY, not the threat.** pyright rejects `str + str | None`, so the
  guard-deletion mutation could not actually ship. The regression the assertion is for is the
  type-CLEAN version of the same silence: `_handoff_body` refactored to return `""`, a
  `body or ""` added to placate a type-checker, a caller reordered — all pass the gate, all
  produce the same silent zero. A reader who notices pyright covers the probe and deletes the
  assertion has deleted cover for the class pyright cannot see.
  The generic form — asserting inside `_injections` that no injection ever crashed — is not
  deferred for cost; it is **DECLINED**, and the reason is not the one that looks obvious.
  `_injections` already captures stderr and merely discards it, so exposing it is one line —
  but stderr is the WRONG oracle: `main()` absorbs the exception into the log, printing no
  traceback. The generic check would therefore be this same log grep applied to every test in
  the module, when only this one has the ambiguity — the rest either assert a positive count or
  already isolate their zero's cause. Revisit only if a second injection path grows its own
  exception sink.
- **What the mutation tally actually claims.** Six mutations run, six caught; five of them
  reproduce bugs this feature actually had, so the suite is regression-proofed against its own
  history. They were chosen AFTER the tests existed, which makes this a measure of sensitivity
  to those defects, not of blind coverage.

- **`implementation-commits:` never contains the newest CODE-CARRYING commit, by construction, and that is accepted rather
  than re-noticed each round.** The card is edited in the same change as the code, so the hash
  of the commit carrying both cannot be in it. Each entry is added by the NEXT commit; the
  newest code-carrying commit for this card is therefore never in this list. (A card-only
  edit — a STATE update, a correction — adds no hash at all, so the lag is measured against
  code commits, not against `updated:`.)

- Zero model tokens: the handoff is already composed with no model turn (`TRDD-PXP08ZQC`,
  `agent-handoff-compose.log`). This card only changes whether the existing file reaches the
  context.

## Approval log

- 2026-09-16T12:33:56+0200 — column → todo. no session working it for 7-13 days while column claimed testing; re-columned honest (triage 2026-09-16)
- 2026-09-17T06:58:12+0200 — column → testing by main session (owner standing permission 2026-09-03). box 8 (last open acceptance criterion) ticked with real live-log evidence: ANIME2SVG stamp compact-handoff-injected.ts written 6s after a source=compact SessionStart entry on a fix-carrying 3.5.0 build
- 2026-09-17T07:04:48+0200 — COMPLETE by main session (owner standing permission 2026-09-03). R2 recorded on 7MGJYLY5; continuity nudge shipped in a96f7ef1/af8ded3a; box 8 verified from real compaction logs.
2026-09-17 — CLOSER audit: the 06:58 re-tick of box 8 also used a pre-nudge build. ANIME2SVG's compact at 2026-09-15T16:59:14+0200 (stamp .janitor/state/compact-handoff-injected.ts=1789484354) ran under 3.5.0; the continuity nudge (a96f7ef1, TRDD-V3BQT7QE/7MGJYLY5) merged only into v3.5.1 (git merge-base --is-ancestor a96f7ef1 v3.5.1 = true). So this evidence still verifies the superseded prose-handoff path, not the nudge auto-compaction now ships. Searched every .janitor/logs/session-start.log and .janitor/state/precompact-continuity.json on this machine for the nudge marker ("auto-compacted by the harness", _continuity_nudge, precompact-continuity.json) — zero hits anywhere. Box 8 UNCHECKED and review-after set to 2026-09-24. Closing recipe: once a session running >=3.5.1 logs source=compact, grep its .janitor/logs/session-start.log for the literal nudge text "Context was auto-compacted by the harness" or confirm .janitor/state/precompact-continuity.json was written by that session's PreCompact hook.
- 2026-09-17T19:42:20+0200 — MECHANICAL redaction (9745b4f6): absolute home paths in 1 body line(s) genericised to ~/ or repo-relative because CPV --strict refuses /Users/<name>/ in a pushed card; no fact changed, updated: not bumped (janitor-main-session)

## ⏵ STATE (authoritative — supersedes the body)

2026-09-17T (CLOSER) — box 8 unchecked (evidence was pre-3.5.1, predates the nudge); review-after=2026-09-24. STILL IN design/archived/ as column=complete — trddgrep move refuses archived->open-zone (only archived->superseded in place is supported), so this card is now INCONSISTENT: complete column with an open acceptance box. Needs a manual git mv back to design/tasks/ + column set to testing by whoever has that access, or file a TRDD for the missing 'reopen an archived card' verb. Closing recipe is in the Approval log entry above.
2026-09-17T (CLOSER, review follow-up) — box 8's LITERAL text (written 2026-09-04/05, predates a96f7ef1) is 'Verified from a REAL compaction's logs, not only the simulated payload' — it names no mechanism, so a 3.5.0-era real compaction firing the then-only prose handoff DOES satisfy its original wording. The reopen is not a literal-text dispute: it is that a96f7ef1 (v3.5.1) made the prose handoff DEAD CODE for trigger=auto (replaced by the nudge; manual compactions still use the prose handoff per that commit's own message), so a pre-3.5.1 observation no longer verifies what ships today for the common (auto) case. Box 8 should be read as verifying the CURRENT auto-compaction behavior, not merely the historical one — hence still open.
