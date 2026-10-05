---
trdd-id: C7M4RXQ2
title: Chain-clear birthing a startup-source process injects nothing — post-clear handoff and resume flag gated on source=clear only
column: testing
created: 2026-09-27T00:53:12+0200
updated: 2026-10-05T10:57:16+0200
current-owner: ai-maestro-plugin-orchestrator
task-type: bugfix
relevant-rules: [S2.1]
status: tasked
---

# Chain-clear births a `source=startup` process — nothing injected, resume never armed

## Symptom (owner, 2026-09-26, verbatim)

"the behaviour at restart is still bad.. clear without the jev-compacting (or maybe just a empty txt injected), and the agent idle"

Restart #1, 2026-09-25 22:48–22:58 local: the janitor's chain cleared session `e4484982` at
670k tokens; the Jev handoff WAS composed and landed on disk (`jev-compacted-b7213080.md`,
22:58:45) — but the fresh session `8b0c6023` started with `source=startup` (new process:
the chain types `/clear` into the pane and the harness re-enters SessionStart on some
platforms as a fresh startup rather than a clear), and the janitor injected NOTHING. No
pointer, no body, no `[janitor-resume]` flag (see defect 2 of this pair). The agent sat idle
until the owner typed "resume" by hand — the exact "cleared without compacting / empty txt"
experience.

## Root cause (verified in source 2026-09-27)

`scripts/hooks/on-session-start.py`:

- `main()` line ~861: `if source == "clear":` gates the ENTIRE post-clear service — the
  `clear-observed.ts` stamp, the `resume-after-clear.session-id.txt` stamp, and
  `_inject_post_clear_handoff(state)`.
- `_inject_post_clear_handoff` itself (line ~309) never re-checks source; it is simply never
  called on any other source. `_emit_manual_clear_pointer` (line ~258) is likewise only
  reachable through clear paths.
- A chain-clear (janitor's own `clear_trigger.py` firing the `/clear` keystroke) is
  indistinguishable from "the user opened a new pane" when the harness reports
  `source=startup`: same source, same blank hook input. Today the janitor treats both as
  "nothing to do".

The harness's own contract (memory `claude-code-clear-and-compact` ^bootstrap-after-clear):
SessionStart DOES fire on `source=clear` and `additionalContext` injection works there — but
the janitor cannot rely on WHICH source the chain's re-entry reports. The service must be
gated on EVIDENCE THAT A CLEAR JUST HAPPENED, not on the source string alone.

## What evidence exists on a startup-sourced chain re-entry

- `resume-after-clear.flag` (written by `clear_trigger.py::_persist_resume_state` BEFORE the
  clear fires) is present and fresh — it is exactly the "a clear is about to happen / just
  happened" signal the flag was built for (its own docstring: a PRE-marker).
- The per-pane sidecar `resume-after-clear.<pane_key>.transcript*` names THIS pane's
  transcript — the same evidence `on-session-start-post-clear-compact.py` consumes.
- `clear-observed.ts` freshness cannot be used (it is the thing this defect fails to write).

## Required behaviour

1. When `source == "startup"` AND a fresh `resume-after-clear.flag` exists (age under
   `CLAUDE_PLUGIN_OPTION_CLEAR_RESUME_MAX_AGE_S`, default 86400 s) AND a per-pane sidecar
   for this pane exists — treat it as a chain-clear: run the same service the
   `source=clear` branch runs (stamp `clear-observed.ts` + session id, inject via
   `_inject_post_clear_handoff`, which already delegates to the sidecar-consuming dedicated
   hook or degrades to the honest pointer).
2. On startup WITHOUT the flag/sidecar evidence: behave exactly as today (no service). A
   genuinely fresh pane must not inherit a stale flag — the existing age check plus the
   session-id stamp discipline covers the race where the flag outlives its clear by a pane
   generation; the sidecar freshness window (`_SIDECAR_FRESH_MAX_AGE_S` in the dedicated
   hook) bounds the rest.
3. Do NOT duplicate the sidecar-consumption logic — `_inject_post_clear_handoff` already
   handles "dedicated hook owns it" (sidecar present/consumed → return) and "cannot verify"
   (keyed handoff → pointer). Re-entering it is the whole fix.
4. Keep the flag-consumption semantics: `dispatch.py::_phase_clear_resume` owns deleting
   `resume-after-clear.flag`; this hook only OBSERVES it here — do not unlink the flag on
   the startup path (the stamp discipline relies on it surviving until the resumed turn
   consumes it).

## Gates

- A unit test reproducing the 2026-09-25 shape: flag + sidecar present, source=startup →
  `clear-observed.ts` stamped, handoff body or pointer printed.
- A negative test: source=startup, NO flag → output identical to today's.
- Full suite (`pytest`) green on the janitor repo.

## Implementation notes for the worker

- Use `tldr` (tldr-code skill) to locate symbols; `fastedit` (fastedit skill) for the edit;
  `jgrep` for any behavioural search ("where does SessionStart gate on source").
- The edit is in `scripts/hooks/on-session-start.py` `main()`, around the `source == "clear"`
  branch (line ~861). Read the whole branch plus `_inject_post_clear_handoff` and
  `_persist_resume_state`'s writer side in `clear_trigger.py` before editing.
- `design/tasks/TRDD-20260922_213255+0200-RAEGS1D5-*.md` is the parent continuity card — its
  STATE block supersedes its body; read it for vocabulary before writing prose.

## Owner context

Filed from the owner's complaint + this session's verification. Related live reproduction
(TRDD-DQXMND59's hold defect) is carded separately — that one reproduces on EVERY clear,
this one only on the startup-sourced re-entry shape.

## Adversarial review amendments (2026-09-27)

REVIEW FINDINGS 1+2 APPLIED — requirements 1-3 superseded. (1) _inject_post_clear_handoff alone does NOT inject on startup: when the per-pane sidecar exists it defers to on-session-start-post-clear-compact.py, whose _main gates source!=clear -> return 0 — so the fix ALSO relaxes that gate to accept source==startup (its existing _SIDECAR_FRESH_MAX_AGE_S minutes-scale freshness check stays). (2) The startup branch's evidence bound is the SIDECAR freshness (minutes-scale), never the 86400s flag age: a reused pane with a day-old flag must not inherit yesterday's clear's service. (3) The session-id stamp written at service time records the INHERITING session, so it cannot discriminate stale inheritance — the sidecar freshness bound is the real guard. Verified finding 1 against source before amending.

## Adversarial review round 2 (2026-09-27)

TOPOLOGY + OWNERSHIP pinned. (i) Shared-file serialization: on-session-start-post-clear-compact.py is edited by BOTH workers' cards (the gate relaxation here, the hold release in K8YF2WQ5) — the two implementers are serialized on it: W1 lands on-session-start.py first, waits, applies the gate relaxation only after W2's edits land. (ii) ONE owner per clear: when the per-pane sidecar is present OR already consumed this start, on-session-start.py's startup branch stamps clear-observed.ts + session-id and injects NOTHING (the dedicated hook owns the body); absent sidecar falls through to the keyed-pointer path. A pointer must never follow a body for the same clear. (iii) Double-stamp semantics: the startup path stamping clear-observed.ts seconds after the source=clear stamp is an overwrite with the same epoch — expected-harmless, recorded in the test comment. (iv) The session-id stamp is BOOKKEEPING, not a guard (it records the inheriting session); the sidecar-freshness bound is the only staleness guard. (v) Review round-2 note: hook execution order within one SessionStart event was never pinned as a fact — the ownership rule above is written to be order-independent, which is why it is stated in terms of sidecar presence/consumption rather than which hook runs first.

## Adversarial review round 3 (2026-09-27)

CONSUMED-ARM GLOB VERIFIED IN SOURCE. _consume_sidecar (on-session-start-post-clear-compact.py:102) renames resume-after-clear.<pane_key>.transcript -> resume-after-clear.<pane_key>.transcript.consumed-<epoch>: the pane_key prefix is RETAINED, so the existing pane-scoped glob resume-after-clear.{pane_key}.transcript* already sees the consumed form (round 3's rename-drops-prefix premise was wrong; its directory-wide-glob false-ownership scenario does not arise). The round's surviving point stands: the * epoch wildcard is UNBOUNDED — yesterday's .consumed-<epoch> for the same pane still matches, so the startup branch's consumed-arm check must apply the freshness bound to the matched file's EPOCH SUFFIX (or mtime), same minutes-scale window as _SIDECAR_FRESH_MAX_AGE_S. 'This start' = freshness-bounded match, not a process-lifetime notion. Also from round 3: worker targeted runs must be FILE-SCOPED (pytest tests/test_<hook>.py -k ...) not -k over the whole directory — collection imports sibling test modules and worker 2's half-written edit can false-red worker 1. Two-rounds-max reached on this design thread: further changes are mechanical corrections of review-found defects only, then the overall result goes to the owner.

## Adversarial review round 4 (2026-09-27)

MECHANICAL SCOPE CONFIRMED with one precision defect, now corrected. Round 4 verified the _consume_sidecar read was sound (writer-side read + docstring corroboration) and that every new instruction traces to rounds 2-3. Its surviving finding, VERIFIED against source before amending: _inject_post_clear_handoff's internal defer-glob (resume-after-clear.{pane_key}.transcript*, on-session-start.py:369) is UNBOUNDED — in the stale-consumed case the new freshness gate says 'fall through to the keyed-pointer path', but the fall-through target matches the stale .consumed-<epoch> and returns SILENTLY: stale-consumed + startup -> silence, the exact failure class this card kills. Correction for worker 1: the startup branch must NOT route the stale-consumed case through _inject_post_clear_handoff's early return. Either (a) stale-consumed matches -> call _emit_manual_clear_pointer(state, sd, reason=<freshness>) DIRECTLY, or (b) compute the startup branch's arm check as: fresh-unconsumed present -> stamp + inject nothing; freshness-bounded-consumed present -> stamp + inject nothing; nothing-fresh -> stamp + _emit_manual_clear_pointer directly (bypassing the unbounded defer-glob). Option (b) keeps one decision site — preferred. The epoch test must assert the POINTER IS EMITTED (not merely 'no stamp + no body' — that assertion passes while the silence hole ships). Two rounds' residual nits recorded here: the second-clear-same-pane case is safe by construction (fresh unconsumed sidecar dominates the glob; the dedicated hook consumes it) and hook-order is moot under order-independent arms — closed. The round-3 'no round 4' clause meant no round on the DESIGN; a mechanical-scope check is exempt (this round was one).

## Implementation record (2026-09-27)

IMPLEMENTATION LANDED 14431416 (phase 1 by worker after [W1-PHASE1-DONE], phase 2 gate relaxation [W1-PHASE2-DONE]; both diffs verified by the orchestrator against this card's amended design before commit). Full suite serial on the final tree: 17574 passed, 2 skipped, 8 subtests in 11m11s, exit 0. All review rounds' gates satisfied: epoch-freshness bound, silence-hole bypass, pointer-emitted assertion, file-scoped tests, flag-never-unlinked. Remaining for done: none in code; card moves todo -> testing per board discipline.

## Adversarial review round 6 (2026-09-27)

Round 6 (first code-level review of 14431416) ruled the implementation correct for every writer-produced state; three items to land before complete. (1) POINTER-ARM CUE CONTRACT — now stated, as intended: the pointer arm DOES stamp clear-observed.ts, arming dispatch's resume cue on top of the pointer. Intentional: on an unattended pane the cue is the only wake (a pointer alone never starts a turn), and the cue's turn re-grounds from the newest handoff on disk; on an attended pane the redundant wake is the accepted cost. (2) CONSISTENCY TEST REQUIRED before complete: the duplicated _SIDECAR_FRESH_MAX_AGE_S=300 has no cross-module guard; a mismatch fails silent-and-empty (on-session-start says fresh, hook says stale -> both defer to nothing). Ten-line regex test asserting both sources' values equal; no import of the hyphenated module. (3) KNOWN RESIDUAL — crash-after-consume: if the dedicated hook consumes the sidecar (rename done) and crashes mid-compose, its except path returns 0 with no body and no template, and the startup branch already deferred; the armed cue is the sole recovery and falls back to a newest-handoff lookup the crashed hook never wrote. Narrow (seconds) and strictly better than pre-fix silence; recorded, fix deferred to a future card. Docstring nit: _sidecar_fresh's mtime-fallback clause should note a consumed file's mtime is the WRITE time, not consume time. todo->testing supported: suite green serial, all five rounds' gates implemented; testing = the real-world chain-clear validation these hooks only reveal on live clears.

## Adversarial review round 7 (2026-09-27)

Round 7 ruled the round-6 turn in-scope EXCEPT one disposition, now corrected: 'stated as intended' for the pointer-arm cue contract was a PRODUCT RULING the orchestrator made unilaterally — round 6 explicitly left it 'either intended or a defect', and no owner statement exists. Round 7's fact-check also overturned the rationale's load-bearing premise: 'a pointer alone never starts a turn' is a recorded fact only for the POST-CLEAR shape; on the STARTUP shape the harness begins its own turn, so the cue may be redundant even unattended (turn burned to discover 'hold for instructions'). CORRECTED RECORD: the pointer-arm cue disposition is PROVISIONAL — owner confirms at the acceptance gate. Two defensible options: (a) keep cue-on-pointer as belt-and-braces for the subset of startup re-entries where no auto-turn begins (the 'on some platforms' hedge leaves this open), or (b) suppress the stamp in the pointer arm (one-line revert riding this same card if the owner rules against). OWNER QUESTION for the acceptance gate: on your machine's startup-shaped chain re-entries, do you want the [janitor-resume] cue to fire on top of the pointer, or should the pointer arm stamp nothing? Everything else in the round-6 turn was in-scope and correctly shaped (test brief matched round 6 exactly and slightly stronger on rename-loudness; docs-only commit shape correct; commit subject accurately scoped).

## Adversarial review round 9 (2026-09-27)

REVIEW LOOP CLOSED. Round 9 ruled the round-8-response turn mechanical-only and terminated the review thread: every design and code question from rounds 1-8 is implemented, recorded, or routed to the owner. No round 10 — further appends (recording the owner's answer, a one-line revert if (b), the column move) are exempt as corrections of already-reviewed material. Two MINOR presentation nits corrected here: (1) the owner question is anchored to 'before complete' (the column transition the owner's answer gates), not to a review 'acceptance gate' the owner may not treat as a review moment; (2) the owner-facing options presentation is neutrally re-presented in this card so both options carry one defensible-why clause each ('belt-and-braces' vs 'one-line revert') with no recommendation. Uncovered item round 9 named, now owned: if the owner picks (a), the 'empty-hands cue' shape (what the resumed turn does when it fires with only a pointer and no fresh handoff on disk) becomes the next card's first line — behavior, not bookkeeping. Round 8's verdict (pending at round 9's writing) arrived in the same window and ruled the test commit correct with no defects; its two directives (flag owner now; track the docstring nit) were already satisfied same-turn. The crash-after-consume residual stays a future card; this closure does not discharge it. Card rests in testing: OWNER DECISION (a)/(b) + real-world chain-clear validation are the only gates to complete; the card is NOT closable by default without them.

## STATE banner — review loop closed (2026-09-27)

BANNER FOR THE NEXT SESSION: the adversarial-review loop on this card is CLOSED (round 9 ruled closure, round 10 confirmed it sound with the full question-by-question disposition table). Do NOT reopen it; further gate-demanded review forks on this thread's already-reviewed appends are pure process cost — the sanctioned exit applies. New substantive work on this subject is NEW material with its own normal review: (i) the owner's pointer-arm (a)/(b) answer landing — if (b), the one-line revert MUST also update round 6's 'stated as intended' language so the card does not self-contradict; (ii) the empty-hands-cue card (only if (a)); (iii) the crash-after-consume card. The card rests in TESTING on exactly two gates to complete: the owner's decision and a real-world chain-clear validation. Neither can be closed by default.
2026-10-05 — DECIDED (owner delegated decisions; the owner may reverse it): the resume cue stays on the pointer arm, as shipped in v3.7.0. Reason: it prevents an idle agent after a startup-sourced re-entry, and its cost is at most one redundant turn; reverting is one line. The cross-hook freshness-constant test landed in b123a392. RESUME POINT. Column testing. NAMED LIVE EVENT: the next chain clear that logs source=startup; pass when the new session's context opens with the handoff body or the pointer and the clear-observed stamp is written.
