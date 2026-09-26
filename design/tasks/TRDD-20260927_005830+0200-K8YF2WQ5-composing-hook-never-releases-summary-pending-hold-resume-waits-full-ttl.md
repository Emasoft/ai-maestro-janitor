---
trdd-id: K8YF2WQ5
title: Composing hook never releases the summary-pending hold it finds — resume waits the full 15-minute TTL after the handoff is already in context
column: testing
created: 2026-09-27T00:58:30+0200
updated: 2026-09-27T01:43:13+0200
current-owner: ai-maestro-plugin-orchestrator
task-type: bugfix
relevant-rules: [S2.1]
status: tasked
---

# Summary hold outlives the handoff that satisfied it — 15-minute dead air after a successful compose

## Symptom (live reproduction, 2026-09-27 00:27–00:43 local, this orchestrator's own session)

A `/clear` at 00:27:53 captured `summary-pending.json` (hold taken by the chain's clear lane
or the detached summarizer). The synchronous hook
`scripts/hooks/on-session-start-post-clear-compact.py` composed and INJECTED the Jev
handoff successfully seconds later. But the hold file was never removed: the heartbeat
logged "resume deferred — summary hold active" until the record's TTL expired
(`expires: 1790462573` = 00:42:53) and `[janitor-resume]` finally fired at 00:43:33 —
**15 minutes of idle session** for a summary that had been sitting in context since 00:28.
Identical shape to Restart #2 on 2026-09-26 08:30 (hold taken 08:30:00, hold released by TTL
08:45, cue fired 08:48:28 — 18 minutes idle; see handoff
`.janitor/state/agent-handoff-95ea2f51-20260927_002816+0200-5844.md`).

## Root cause (verified in source 2026-09-27)

- `scripts/external_handoff_clear.py` defines the hold lifecycle: `_capture_summary_source`
  writes `summary-pending.json` (`_HOLD_TTL_S = 15*60`), `_release_summary_hold(sd, key=)`
  unlinks it (key-guarded, TRDD-RAEGS1D5 advisor R4).
- The DETACHED lane `scripts/summarize_previous_session.py` releases on its own success
  (lines 310, 356: `ehc._release_summary_hold(sd, key=key)`).
- The SYNCHRONOUS hook `scripts/hooks/on-session-start-post-clear-compact.py` composes and
  injects on its success path (`run_compact` exit `jcl.EXIT_OK`, ~line 326) but contains
  **zero** references to `_release_summary_hold` or `summary-pending` (verified by grep
  2026-09-27). It consumes the per-pane sidecar, writes the keyed handoff, injects — and
  leaves the hold standing. Nothing else releases it: `on-session-start.py` never touches
  the file; the heartbeat's `summary_hold_active` only READS it.
- The mismatch: the hold docstring says "the hold normally ends when the compacted context
  lands, seconds later" — true only when the detached summarizer lane ran. When the
  dedicated hook wins the race (the common case on a pane with a resolvable pane key), the
  composer is a different process from the holder, and the composer does not know the hold
  exists.

## Required behaviour

1. On the hook's success path (after a successful `run_compact` — exit `EXIT_OK`, text read
   and injected), release the hold: import `external_handoff_clear as ehc`, call
   `ehc._release_summary_hold(sd, key=key)` — `key` is already in hand
   (`handoff_files.session_key(transcript_path)`, ~line 250). The key guard makes a wrong
   release impossible: a hold naming a different transcript is a no-op by design.
2. Release on the hook's TEMPLATE-degradation path too (Jev failed, the fact-only template
   was injected): the owner's context was satisfied by SOMETHING composed from this
   transcript; leaving the hold active after a completed injection (any kind) is the same
   15-minute dead air. The only paths that must NOT release are the early returns before
   composition was attempted (no pane key, no sidecar, stale sidecar, source != clear) —
   there the hold may legitimately belong to another in-flight lane.
3. Release is best-effort and logged: wrap in try/except, `state.log_line("jev-post-clear-
   hook", ...)` on failure — a failed unlink must never break session start (the hook's own
   crash contract), and the TTL remains the backstop.
4. Update `_release_summary_hold`'s docstring: it currently names
   `summarize_previous_session.py::_main` as "the ONE production caller"; after this fix it
   has two. The guard's reason (never drop another lane's still-active hold) is unchanged —
   the key check carries it.

## Secondary (same card, small): the daemon clear lane stopped logging

`external-clear.log`'s last line before 2026-09-26 16:09 was 2026-08-25, despite the lane
taking the hold and firing the chain on 2026-09-26 08:30 and 2026-09-27 00:27. The chain
evidence exists in `clear-trigger.log` and state files, so the pipeline ran — the
`state.log_line(_LOG, ...)` calls in `external_handoff_clear.py`'s fire path are not
reaching the log on the current path (suspect: the `_fire` path's logging, or the daemon
invocation resolving a different log dir). Investigate while in the file; the fix is
whatever one-line resolution is real — do not widen scope.

## Gates

- Unit test: hold present with key K, hook success path with transcript key K → file gone.
- Unit test: hold present with key K2 (different transcript), hook success with key K →
  file still present (the key guard holds).
- Unit test: template-degradation path (run_compact fails) → file gone.
- Full suite green.

## Implementation notes for the worker

- Use `tldr` (tldr-code skill) to pull the exact function bodies
  (`_release_summary_hold`, the hook's `_main` success branch); `fastedit` for the edits;
  `jgrep` to find "code that takes or releases a hold file" if navigation surprises you.
- `scripts/hooks/on-session-start-post-clear-compact.py` `_main()` — the success branch is
  `if not timed_out and proc is not None and proc.returncode == jcl.EXIT_OK:` (~line 326);
  the template path is the fallback branch after it. Both end in `return 0` — release
  immediately before each.
- Parent card: TRDD-RAEGS1D5 (read its STATE block first; vocabulary binding).

## Adversarial review amendments (2026-09-27)

REVIEW FINDINGS 3+4 APPLIED — requirement 2 superseded. The template-degradation path must NOT release the hold unconditionally: the TTL exists so the DETACHED lane (retry-then-llm-ext, same transcript/key) can still land a real Jev summary after a wedged compose; releasing while that lane is alive converts its future output into an unread file. Template path releases ONLY after a detached-lane-liveness check (use the existing liveness mechanism, do not invent one); a live lane defers the release to the TTL backstop, logged. SUCCESS-path release unchanged (correct, uncontested). Scope split per review: the silent external-clear.log item is INVESTIGATE-AND-REPORT only — no code change inside this bugfix card. Also per review: workers run targeted pytest -k subsets only; the orchestrator runs the full suite once, serially, after all three land (three uncommitted parallel edits in one tree make concurrent full-suite runs red from each other).

## Adversarial review round 2 (2026-09-27)

LIVENESS PROBE DROPPED — round 2 confirmed no inspectable detached-lane liveness mechanism was ever verified (the lane spawns start_new_session=True, so a process check is plausibly not inspectable), and 'use the existing mechanism' delegated a 5-minute orchestrator verification to the worker. Honest fallback adopted: the template-degradation path does NOT release the hold at all — it leaves the TTL backstop (15 min) in place and logs one deferral line so a live detached lane can still land its real Jev summary. Net effect: the 15-minute dead-air bug is fixed on the SUCCESS path (the common case; tonight's repro), preserved-but-bounded on the degraded path (the TTL's documented purpose). Test (3) becomes 'template path → hold present, deferral logged'; test (4) dropped. Shared-file note: this card's edits to on-session-start-post-clear-compact.py and C7M4RXQ2's gate relaxation on the same file are SERIALIZED by the orchestrator — one writer at a time.
IMPLEMENTATION LANDED as c1fce671 (2026-09-27): hold released on the hook's success path and on the template-degradation path (liveness-gated per round 2), _release_summary_hold docstring corrected for the second production caller; tests extended (hold release both paths + liveness gate). Verified: 30 passed file-scoped per round-3 discipline (22.6s), exit 0. Card moves todo -> testing; ai_review after worker 1's C7M4RXQ2 startup branch lands (the shared-file serialization). Note: the worker's edits were found UNCOMMITTED on the tree at session resume — committed as-is after the green run, no re-dispatch.
POST-COMMIT REVIEW (2026-09-27) — c1fce671 stands conditionally, all four findings verified against source and disposed: (1) CONFIRMED — the commit MESSAGE overclaims the template path: it says 'template-degradation path: release too, gated on liveness' but the code deliberately does NOT release on the template branch (comment at ~408, verified rationale: no freshness-checkable liveness artifact exists for the just-spawned detached lane, so releasing would start the resume clock against a template a live lane is about to supersede — round 2's own protection). THE CODE IS RIGHT, THE MESSAGE IS WRONG. This append is the correction of record; the commit message must not be cited as the behaviour record. (2) REFUTED — second-releaser unlink crash: _release_summary_hold's unlink is inside try/except OSError: pass (external_handoff_clear.py:156-158), an already-released hold is a safe no-op for the lane's later call. (3) REFUTED — key divergence: both release sites derive their key via the same handoff_files.session_key() on the same transcript; it extracts the path's basename (session id), immune to /tmp vs /private/tmp prefix duality. (4) HOLDS BY CONSTRUCTION — the review's pointer-path invariant for worker 1: release fires only when full_text is not None (a completed body injection); pointer/defer/template paths never reach the release gate, so C7M4RXQ2's startup relaxation cannot make a pointer release the hold. STILL OPEN: the card's '## Secondary' daemon-clear-lane logging item — untouched this turn, must not block ai_review silently. Card stays in testing; file-scoped 30-green remains the only test evidence (full suite before ai_review per review).
ROUND-2-OF-REVIEW REMEDIATIONS APPLIED (2026-09-27, commit 9d604f88's review). (1) Disposition 1 UPGRADED from comment-only evidence to behavior-verified: the resumed turn re-reads the NEWEST keyed handoff file from disk (dispatch.py ~1830: glob agent-handoff-{key}-*.md, max by mtime — NOT the injected snapshot), so gated release at template time WOULD point the resumed session at the template written moments earlier; the never-release-on-template ruling is confirmed by dispatch.py's read behavior, not merely by the code's own comment. Corroborating: the lane's already-summarized skip ignores TEMPLATE_MARKER-stamped files (summarize_previous_session.py:216), so the detached lane still retries a real Jev compose after the hook's template — the retry lane is real, not defeated by the template write. Key-derivation input identity also verified: the hook spawns the lane with --transcript <this transcript> explicitly (hook ~434), the lane keys on that exact path (summarize_previous_session.py:146,201). (2) RESIDUAL NAMED: on the template path (Jev down — the 402 incident class), if the detached lane ALSO fails, the hold sits out the full 15-minute TTL with only a template in context — the defect magnitude this card was filed to kill, retained BY DESIGN on the failure-clustered path. Accepted residual, bounded by the TTL backstop. Named upgrade path: at lane spawn the hook could stamp spawned_pid + epoch into summary-pending.json (state.atomic_write, one os.kill(pid,0) check away), which would let the round-2 amended gated release be implemented as originally written. Not scheduled — record only. (3) WORKER-1 ACCEPTANCE GATE: the pointer-path-must-not-release invariant (release fires only behind full_text is not None) predates worker 1's in-flight brief; it is enforced as an acceptance gate when worker 1's C7M4RXQ2 diff lands — a pointer/defer/template path reaching the release call fails review. (4) CHANGELOG OBLIGATION at next publish: describe hold release as 'on completed summary injection (real Jev or unreadable-companion fallback), not on template degradation'.
