---
trdd-id: 498LEWZ4
title: Dedupe the post-compact context injection and add open-issues to the rich handoff
column: dev
created: 2026-07-10T01:01:01+0200
updated: 2026-07-10T01:01:01+0200
current-owner: janitor-session
assignee: janitor-session
priority: 2
severity: MEDIUM
effort: S
labels: [token-economy, compaction, handoff]
task-type: feature
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
must-pass-tests-before-merge: true
publish-target: ai-maestro-plugins
publish-channel: stable
test-requirements: [unit, lint]
review-requirements: []
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# Dedupe the post-compact context injection and add open-issues to the rich handoff

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-10

**IMPLEMENTED + VERIFIED locally.** Two changes, both user-requested (verbatim ask:
improve `/janitor-write-handoff` with "a intelligent summary of what issues were still
to be solved and why … it can refer to external memories (wikimem or claude code native)
to save tokens"; and "revise the after compacting hooks, since they are adding too much
to the context. it can be deduplicated and made more essential").

- Full suite 12336 passed, 1 skipped; lint clean.
- **Live smoke on this project: full injection 36,179 bytes → digest 1,177 bytes
  (3.3%)** — a ~35 KB context saving per compaction, matching the 35.3 KB
  SessionStart:compact injection measured on the real 2026-07-10 00:06 compaction.

**NEXT ACTION:** publish (rides the next release).

## Problem

The post-compact turn received the same content up to THREE times:

1. `pre-compact-handoff.py` (PreCompact) writes `precompact-handoff.md` carrying the
   in-flight TRDD `## STATE` blocks VERBATIM (≤3 × 160 lines) + a faithfulness preamble.
2. `on-session-start-trdd-state.py` (SessionStart, source=compact) injected the SAME
   STATE blocks again (≤4 × 140 lines) — measured 35.3 KB on a real compaction
   (session c8a95d7e, 2026-07-10 00:06).
3. The `[janitor-resume]` directive then steers the model to READ the handoff file —
   the STATE content enters context a second (sometimes third) time.

Separately, the opt-in rich handoff (`/janitor-write-handoff`) captured plan + gotchas
but had no section for the OPEN issues — what is still unsolved and WHY — which is
exactly the knowledge a lossy summary destroys first.

## Decisions

- **D1 — the FILE is the single carrier; hook injections are pointers.** A file costs
  nothing until read; a hook injection is forced into every post-compact context. So on
  `source=compact`, when a FRESH `precompact-handoff.md` exists (mtime ≤ 15 min — the
  PreCompact hook writes it seconds before SessionStart:compact fires), the hook injects
  a one-line warning + pointer + a one-line-per-TRDD digest instead of full STATE blocks.
- **D2 — full injection stays as the FALLBACK.** No fresh handoff (janitor PreCompact
  hook disabled, failed, or a foreign compaction path) → today's full STATE injection is
  unchanged. Failures fall toward MORE grounding, not less.
- **D3 — staleness rejects, never trusts.** A handoff older than 15 min belongs to a
  PREVIOUS compaction; pointing the model at it would re-ground on outdated truth.
  Stale → full injection.
- **D4 — the rich handoff gains a mandatory "Open issues — unresolved + WHY" section**
  with pointer-not-paste economy: each open issue is one line of WHAT + one line of WHY
  it is still open + a POINTER to the durable context (TRDD-<id8>, wikimem page name +
  `memgrep recall` symptom, native memory note, GitHub issue #) instead of restating it.

## Files

- `scripts/hooks/on-session-start-trdd-state.py` — digest mode + freshness gate.
- `skills/janitor-write-handoff/SKILL.md` — the open-issues section + memory-pointer
  guidance.
- `tests/test_trdd_state_hook.py` — digest/fallback/staleness cases (existing full-
  injection tests keep passing: their temp projects have no handoff → fallback path).
- `tests/test_write_handoff_skill_spec.py` — markdown-spec guards binding the skill text
  to the requested behavior.

## Notes and lessons learned
