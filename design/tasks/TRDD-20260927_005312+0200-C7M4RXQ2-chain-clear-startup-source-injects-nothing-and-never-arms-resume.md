---
trdd-id: C7M4RXQ2
title: Chain-clear birthing a startup-source process injects nothing — post-clear handoff and resume flag gated on source=clear only
column: todo
created: 2026-09-27T00:53:12+0200
updated: 2026-09-27T00:53:12+0200
current-owner: ai-maestro-plugin-orchestrator
task-type: bugfix
relevant-rules: [S2.1]
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
