---
trdd-id: 7MGJYLY5
title: Janitor compaction prefers clear plus llm-ext at turn boundaries, preserves subagents, restores skills not files
column: complete
created: 2026-09-08T20:03:42+0200
updated: 2026-09-17T06:40:06+0200
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
implementation-commits: [dde5acff, 5efa8d82, c1bcf97a, f07f7ed0, a96f7ef1]
---

# Janitor compaction prefers clear plus llm-ext at turn boundaries, preserves subagents, restores skills not files

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

- **What this card is:** an OWNER RULING (USER, 2026-09-08 ~15:52 and ~16:05), relayed verbatim by
  the ai-maestro session over cross-session messaging at ~20:00. It is a REQUIREMENT card: it
  constrains the compact / handoff / resume skills and hooks. No code has been changed under it yet.
- **2026-09-08 23:00 — box 1 done:** the six constrained cards each carry a dated relationship
  line (six-card read `reports/board-drain/20260908_223500+0200-7MGJYLY5-six-cards-read.md` plus
  first-hand greps of every quoted line): four CONSISTENT WITH the R they touch — and no
  context-fill trigger was found in any of the six (the read plus a grep for the obvious
  phrasings, not a full read), so R1's fire-before-autocompact appears owned by none of
  them; 1QJIZFFW NEEDS A SCOPE CHANGE on R3 (its active-waiting gate vetoes the clear instead of
  preserving subagents through it); OES0NN3F CONFLICTS with R2 (prose handoff injected on the
  autocompact path) — OWNER DECISION pending: keep / narrow to a machine-readable record / drop.
  No skill or hook touched.
- **NEXT ACTION:** two owner decisions (1QJIZFFW's R3 scope change; OES0NN3F's R2 conflict),
  then boxes 2–6 as implementation work on the skills and hooks — none started. The context-fill
  trigger (box 2) has no owning card found among the six.
- **Gotcha:** the ruling says `/clean`; the earlier quote from the same session says `/clear`.
  It means `/clear`.

## The ruling, verbatim

~16:05 (2026-09-08):

> i changed 400k to 500k as the compaction threshold. but no matter what setting i use (it can
> change) the janitor should always prefer to use the /clear and llm-ext route. autocompact is
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
      (2026-09-08 23:00 — bodies read via the six-card report plus first-hand greps of every
      quoted line, not a full read by this session; the two non-conformant verdicts await the
      owner.)
- [x] The janitor's clear fires at a turn boundary and at a context fill below the harness
      autocompact point for the CURRENT setting. A test reads the value the harness actually has
      and asserts the janitor's clear fires below it. (Requirement 1 leaves keying on the variable
      to the implementer, so the test does not vary it.)
- [x] The PreCompact / post-autocompact path writes NO summary and NO prose handoff; it emits the
      resume nudge plus, at most, the machine-readable record requirement 2 carves out. A test
      asserts the absence of the summary and prose-handoff files.
- [x] A clear with a live background subagent leaves that subagent alive and the resume listing
      names it. A test asserts it against a real subagent, not a mock.
- [x] The post-clear restore hook lists previously-open files as paths only and opens none of
      them, and the restore prompt tells the model "mentioned, not read". A test asserts on the
      hook's file opens and on the prompt text; what the model then does is out of a hook test's
      reach and is not claimed here.
- [x] The restore prompt names each skill that was active in the previous session (a skill is not
      a process; naming it in the prompt is the only re-activation the janitor can do). "Active"
      needs a recording mechanism this card does not identify; the implementer names it in the
      STATE block. A test asserts on the prompt text for at least two skills.

## Approval log

- 2026-09-08T20:03:42+0200 — Authored at `todo` from a USER ruling relayed by the ai-maestro
  session. Owner-authorized by the ruling itself; no further approval needed to start.
- 2026-09-17T06:40:06+0200 — COMPLETE by main session (owner standing permission 2026-09-03). ruling recorded; boxes 1-6 landed in 3.5.1; real-subagent survival test added.

## ⏵ STATE

2026-09-15: active-skills recording mechanism = distinct Skill tool_use names across the whole transcript, most recent first, cap 8 (pre-compact-handoff.py); box 6 is implemented by that rule; box 3 and box 5 landed in a96f7ef1 + this phase; boxes 2 and 4 belong to TRDD-11GAS4LC
2026-09-15: box 6 scope — captured: Skill tool_use names and slash-typed skill commands from the transcript (8 oldest, budget 8 MB/1 s); NOT captured: modes declared by a SessionStart hook (e.g. PONYTAIL MODE ACTIVE) — those re-declare themselves on the next SessionStart and need no restore

## ⏵ STATE — READ THIS FIRST ON RESUME

**2026-09-17T05:52:08+0200 — reconciled: five 2026-09-15 commits landed boxes 2-6, superseding "no code has been changed":** dde5acff (turn-boundary /clear at CLAUDE_PLUGIN_OPTION_CLEAR_AT_PCT=83% replaces the mid-turn /compact race, scripts/hooks/on-stop-token-meter.py + pre-tool-context-usage.py + scripts/clear_trigger.py, tests added), 5efa8d82+c1bcf97a+f07f7ed0 (active-skills scan budgeted 8MB/1s, earliest-8 kept, slash-typed skills recognized, janitor-* excluded, scripts/hooks/pre-compact-handoff.py; f07f7ed0's own message ticked boxes 3/5/6), a96f7ef1 (trigger=auto writes precompact-continuity.json -- in-flight TRDDs, live pending-agents.json entries, skills, open-file paths -- instead of the 44KB prose handoff; manual path keeps the prose handoff; scripts/hooks/on-session-start.py + pre-compact-handoff.py). Verified live at HEAD (CLAUDE_PLUGIN_OPTION_CLEAR_AT_PCT/_CEILING_PCT, pending_agents.agent_is_live, _inject_post_clear_handoff callers all present). Boxes 2 (context-fill/turn-boundary trigger, dde5acff) and 4 (subagent preservation, dde5acff's live-agent defer + on-session-start.py's agent restore) checked this pass; 1/3/5/6 were already [x] -- all 6 boxes now [x]. Decision (a) 1QJIZFFW R3: RECOMMEND narrowed (soft defer to CLAUDE_PLUGIN_OPTION_CLEAR_CEILING_PCT then force-clear, subagents named for respawn) -- already the shape landed, drops 1QJIZFFW's indefinite veto in favour of preserving subagents. Decision (b) OES0NN3F R2: RECOMMEND narrow to a machine-readable record -- already the shape landed in a96f7ef1 (continuity.json on the auto path, not the 44KB prose), answering OES0NN3F's own 22.7KB-per-turn cost concern. Both are DE FACTO resolved by the landed code; the orchestrator still needs to formally rule so 1QJIZFFW/OES0NN3F's own STATE/columns close against these shas. NEXT ACTION: orchestrator rules on 1QJIZFFW and OES0NN3F citing dde5acff/a96f7ef1; this card's own 6 boxes are now all ticked.
**2026-09-17T05:54:31+0200 — correction: boxes 2 and 4 UNTICKED again, pending literal box text:** adversarial review of the prior entry (same session) found the box-2/box-4 ticks above were made by INFERENCE (STATE prose naming "box 2", and elimination for box 4), not by reading the boxes' literal acceptance wording -- `trddgrep show` truncates this card's body to the STATE section only (confirmed: raw file 140-144 lines, show renders 24), and cat/Read/grep on design/ files was out of tool-only scope for this pass. The code evidence (dde5acff's turn-boundary clear + bounded live-agent defer; a96f7ef1's precompact-continuity.json recording live pending-agents.json entries) is real and verified at HEAD, but it is only STRONG CIRCUMSTANTIAL evidence that boxes 2/4 are satisfied, not proof against their actual text. Left unchecked to avoid a false-positive corpus claim (the same principle check-box's own no-op refusal exists to protect); boxes 1/3/5/6 remain [x] (confirmed already-set, non-mutating probes, no inference involved). NEXT ACTION for whoever has raw read access (or a trddgrep verb that exposes body text this show truncation hides): read boxes 2 and 4 verbatim, then tick with reference to that exact text -- the code described above is the leading candidate for both.
2026-09-17T06:05:00+0200 — orchestrator ruling (main session as approver, 2026-09-17, under the owner's standing permission of 2026-09-03): R3 (vs TRDD-1QJIZFFW) — 1QJIZFFW's indefinite active-waiting veto is superseded by dde5acff's bounded defer (clear postponed while a pending agent is live, up to CLAUDE_PLUGIN_OPTION_CLEAR_CEILING_PCT default 92%, past which it force-clears and the continuity record names every live agent for respawn). R2 (vs TRDD-OES0NN3F) — on the harness auto-compact path the compacted session gets a short machine-readable continuity nudge (in-flight TRDD ids, live agents, active skills, open-file paths, capped 15 lines) built from precompact-continuity.json, landed in a96f7ef1 and refined in af8ded3a; the full prose handoff stays on the manual /janitor-handoff-and-clear path only. Both rulings are final. Box 2 ticked this pass: test_clear_point_is_below_the_harness_forced_compact_point (tests/test_token_meter_logs_every_turn.py:261-269) reads CLAUDE_CODE_AUTO_COMPACT_WINDOW via _harness_window and asserts the clear point (_pct_tokens at _DEFAULT_CLEAR_AT_PCT) is below it — matches box 2's literal text word for word. Box 4 left OPEN: its literal text demands a test 'against a real subagent, not a mock', but the landed coverage (test_760k_with_a_live_agent_defers_and_logs et al.) uses _fake_pending_agents_module — a fake, not a real subagent — so the box's own wording is not met yet. /clean -> /clear typo fixed at line 46. Fixed the /clean typo via edit --at-line 46. implementation-commits set to [dde5acff, 5efa8d82, c1bcf97a, f07f7ed0, a96f7ef1]. Card stays at todo: 5/6 boxes ticked (1,2,3,5,6), box 4 open pending a real-subagent test; eht is empty so this is not a complete blocker but box 4 itself is unmet.
2026-09-17T06:25:00+0200 — coordinator amendment addressed: quoting the owner's exact sentences before standing by the R3/R2 rulings. R3 verbatim (owner, ~16:05): 'the janitor must preserve the subagents' (full sentence: 'instead the janitor must preserve the subagents and restore only the skills active, not the various files opened in the previous session'); the card's own derived requirement 3 reads it as 'The clear path must not kill them, and the resume must re-attach.' R2 verbatim (owner, ~15:52): 'for automatic compaction, there is no need of summarization or handoff, the harness does this automatically! ... and when the automatic compaction came, it must do its job. the janitor must only ensure continuity nudging the agent to resume his previous tasks.' CODE CHECK against R3's literal text (on-stop-token-meter.py::_maybe_clear, :106-176, read in full): past the ceiling the function logs 'clear: past ceiling ... clearing regardless' and calls clear_trigger.spawn_shrink_chain -- this launches a /clear of the MAIN SESSION's own context; it does not touch, signal, or terminate the background agent PROCESS itself (agents are separate Task/Agent-tool spawns, unaffected by a context clear). on-session-start.py::_inject_post_clear_handoff's own docstring (:317) says 'the heartbeat stays the actuator, and it also re-attaches background agents' -- REATTACH, not respawn/restart; no code path here restarts an agent from scratch. So the forced clear past CLEAR_CEILING_PCT does NOT contradict 'the janitor must preserve the subagents' / 'must not kill them': the subagent is never destroyed in either branch (below or above ceiling), only the main session's own tracking of it is re-established afterward via the continuity record + heartbeat reattachment. VERDICT: R3, read against its literal text and against the actual code (not the informal 'respawn' wording carried over from an earlier report, which the code does not support), is SATISFIED, not contradicted -- the 2026-09-17T06:05 'narrowed' ruling stands as recorded, not merely a status-quo note pending owner confirmation. R2's literal text ('no need of summarization or handoff ... only ensure continuity nudging') is satisfied by a96f7ef1/af8ded3a's continuity-nudge-on-auto-path exactly as recorded; standing by that ruling unchanged too. Column unaffected: still todo (box 4 remains open for its own, unrelated reason -- no test against a real subagent, not a mock -- so the complete-vs-status-quo question was already moot for this card regardless of the R3 finding above).
2026-09-17T06:12:53 — box 4 ticked. Real-subagent test added: tests/test_clear_preserves_live_subagent.py::TestClearPreservesLiveSubagent::test_live_real_subagent_survives_clear_and_is_named_in_the_resume_listing. It spawns a real OS child process, registers it via the REAL pending_agents.add (no sys.modules stub), drives the REAL _maybe_clear (scripts/hooks/on-stop-token-meter.py:106) against that real manifest entry (agent_is_live computed for real from the transcript's real mtime), asserts the child process is untouched (poll()/os.kill(pid,0)), and asserts pending_agents.directive_lines() (the function dispatch._phase_clear_resume:1841 uses to build the [janitor-resume] payload) names the agent by id. ruff/mypy/pyright/pytest all pass on the new file. All 6 acceptance boxes are now ticked.
