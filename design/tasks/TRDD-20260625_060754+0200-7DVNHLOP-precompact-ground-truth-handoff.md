---
trdd-id: 7DVNHLOP
title: PreCompact hook — write a filesystem-grounded handoff so post-compaction re-grounds in VERIFIED state
column: dev
created: 2026-06-25T06:07:54+0200
updated: 2026-06-25T06:07:54+0200
current-owner: spark
assignee: spark
priority: 2
severity: HIGH
effort: M
labels: [compaction, handoff, anti-hallucination, hooks, watchdog]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint, typecheck]
audit-requirements: []
review-requirements: [code-review]
runtime-targets: [macos, linux]
impacts: [ci-pipeline]
attempts: 1
test-failures: 0
last-test-result: not-run
implementation-commits: []
---

# TRDD-7DVNHLOP — PreCompact ground-truth handoff hook

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-25

**Current state (components):**
- `scripts/hooks/pre-compact-handoff.py` — NEW. On PreCompact, writes a deterministic,
  filesystem-derived handoff to `<project>/.janitor/state/precompact-handoff.md`. Best-effort,
  always `exit 0`. DONE.
- `scripts/hooks/post-compact-resume.py` — minimally extended: prepends a
  "read precompact-handoff.md FIRST" pointer to the resume directive when the handoff exists,
  so the post-compaction `[janitor-resume]` cue steers the next turn to the handoff. DONE.
- `hooks/hooks.json` — registered `pre-compact-handoff.py` on the `PreCompact` event. DONE.
- `tests/test_precompact_handoff_hook.py` — NEW, real subprocess + helper tests, no mocks. DONE.

**NEXT ACTION:** orchestrator runs the test suite (`uv run pytest tests/test_precompact_handoff_hook.py`),
then commits. Spark does NOT run git/commit/push (orchestrator owns that).

**Load-bearing facts / gotchas (VERIFIED against the official Claude Code hooks docs
2026-06-25 — https://code.claude.com/docs/en/hooks):**
- PreCompact stdin JSON carries the COMMON fields: `session_id`, `transcript_path`, `cwd`,
  `permission_mode`, `hook_event_name` ("PreCompact"). The `/compact`-vs-auto distinction is the
  hook **matcher** value (`manual` | `auto`); the docs do not guarantee a `trigger` field in the
  payload, so the hook reads it opportunistically (`payload.get("trigger")`) and never depends on it.
- PreCompact output: it supports the TOP-LEVEL `decision` pattern (`decision:"block"` + `reason`)
  and common fields incl. `systemMessage`. It does **NOT** support
  `hookSpecificOutput.additionalContext` — PreCompact CANNOT inject text into the compacted
  context. (This is the design pivot: the faithfulness instruction is delivered through the
  EXISTING `[janitor-resume]` loop, which DOES reach the next turn, not through PreCompact output.)
- Exit code: 0 = proceed; `decision:"block"` OR exit 2 BLOCKS compaction. We MUST never block —
  the hook always `exit 0` and never sets `decision`. It MAY emit a best-effort `systemMessage`
  for the summarizer in the same turn.

**SUPERSEDED — do NOT carry forward:**
- ✗ "emit additionalContext from PreCompact" — PreCompact does not support it (verified). Replaced
  by: write to disk + steer the next turn via the post-compact-resume directive pointer.

**Durable artifacts to read before acting:**
- `reports/precompact-hook/<ts>-precompact-handoff-hook.md` — the verified contract + design + test evidence.
- `scripts/hooks/post-compact-resume.py` + `scripts/dispatch.py::_phase_compact_resume` — the resume loop this integrates with.

## The failure this fixes

After a compaction, the agent treated the compaction SUMMARY as ground truth and confidently
asserted stale/wrong facts (an OAuth account's health %, "published vs not", whole narratives)
that it NEVER re-verified — the summary promoted day-old hypotheses to "fact". A compaction summary
is lossy and can PROMOTE a transient wrong hypothesis to stated fact.

The fix gives the next turn an AUTHORITATIVE, un-hallucinatable re-grounding point: a handoff
derived from FILESYSTEM/GIT truth (git HEAD + recent commits, `git status --short`, plugin version,
the newest in-flight TRDD STATE blocks copied verbatim), not from transcript prose. The next turn is
told — via the resume cue — to read that handoff FIRST and treat every technical claim in the
summary as UNVERIFIED until checked against it.

## Design

1. **`pre-compact-handoff.py`** (PreCompact): builds the handoff ONLY from on-disk truth and writes
   it atomically to a STABLE path `<state>/precompact-handoff.md`. Sections: header (UTC+local
   timestamp, trigger, plugin version), `git HEAD` + last ~12 commits oneline, `git status --short`,
   the newest in-flight TRDD(s) (by `updated:`) with their `## ⏵ STATE` blocks copied VERBATIM, and a
   standing faithfulness instruction block. Best-effort: any sub-step that fails degrades to a
   "(unavailable)" line; the hook always `exit 0`. It additionally emits a `systemMessage` pointing
   at the handoff for the summarizer in the current turn.
2. **Delivery of the faithfulness instruction to the NEXT session**: through the existing resume
   loop. `post-compact-resume.py` records the resume directive; we prepend
   `read .janitor/state/precompact-handoff.md FIRST (filesystem-grounded truth; treat the summary as
   UNVERIFIED) — ` to the directive when the handoff file exists. `dispatch.py::_phase_compact_resume`
   then emits it as the single `[janitor-resume]` cue on the next heartbeat. No change to dispatch is
   needed — it already surfaces the directive verbatim (after `sanitize_for_drift_line`).
3. **Registration**: `hooks/hooks.json` gains a `PreCompact` entry for `pre-compact-handoff.py`,
   running ALONGSIDE the existing PostCompact `post-compact-resume.py` (different events; both fire).

## Forward-fix caveat

Plugin `hooks/hooks.json` changes go live only after publish + cache-update + `/reload-plugins`
(and a hooks change requires the next session to pick up the new registration). This is a FORWARD
fix — it will not retro-fix the current session's next compaction.

## Constraints honored

- Hook error NEVER blocks compaction or crashes the session — best-effort, `exit 0`, never
  `decision:"block"` (like the other janitor hooks).
- stdin JSON parsed with `python3` (no `jq`).
- No mocks in tests; no gate relaxed.
- Spark does NOT run git/commit/push.
- Edited ONLY: `scripts/hooks/pre-compact-handoff.py` (new), `scripts/hooks/post-compact-resume.py`
  (minimal), `hooks/hooks.json`, `tests/**`, `design/tasks/**`.
