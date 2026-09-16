---
trdd-id: 3KDN6O9Z
title: window-burn alarm mis-blamed a workspace — gate the agentlens cause on materiality
column: published
created: 2026-07-16T20:12:44+0200
updated: 2026-07-16T20:24:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
release-via: publish
implementation-commits: [6a56d63]
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-16

**What was wrong.** The `window-burn-rate` detector's alarm named the WRONG culprit. The burn TRIP
itself was correct (`ipazia.emasoft` 5h window at 58% / 4% elapsed = 13.8× pace — a real burn that
did rate-limit). But the CAUSE clause preferred agentlensPro's `investigate_burn` top finding
UNCONDITIONALLY: `clause = _agentlens_cause_clause() or _top_consumer_clause(...)`. The top finding was
`IMAGE_BLOB_RESIDENT (2% of window, medium) in ~/Code/EMASOFT-ORCHESTRATOR-AGENT` — so a finding
explaining 2% of the window was surfaced as "the cause" of a 58% burn, falsely blaming the
orchestrator. The user caught it: "the orchestrator project is not making screenshots right now." The
native fleet attribution correctly showed the real top consumers (ai-maestro 21%, ASSISTANT-MANAGER
19%, skill-suggester 16.9× spike).

**The fix (commit below).** A MATERIALITY GATE in `_agentlens_cause_clause`: the agentlens cause may
override the native attribution only when its `shareOfWindow ≥ CLAUDE_PLUGIN_OPTION_WINDOW_BURN_CAUSE_MIN_SHARE`
(default 0.15). Below that, or with no reported share, the cause is dropped → the honest native
top-consumer attribution is used.

**Current state:** DONE. `test_window_burn_rate.py` 18 pass (5 new), ruff clean.

**NEXT ACTION:** none — part of the batched publish.

## Bug autopsy (guardrail)

"has a top finding" ≠ "that finding is the cause of THIS burn." `investigate_burn` returns a ranked
findings list; the top one can be a minor contributor. The original code trusted rank without
weighing magnitude, so a 2% finding beat a 58% burn's real driver. The materiality gate encodes
"a cause must explain a material fraction of the window to be named the cause." The native attribution
is always available as the honest fallback, so dropping an immaterial cause never loses signal.

## Change

- `scripts/detectors/window-burn-rate.py::_agentlens_cause_clause` — drop the cause when
  `cause.share is None or cause.share < min_share` (default 0.15, env-tunable
  `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_CAUSE_MIN_SHARE`). The trip logic + native attribution are
  untouched.
- `tests/test_window_burn_rate.py` — the exact IMAGE_BLOB_RESIDENT 2% case → dropped; no-share →
  dropped; 18% material → kept; threshold tunable.

## Verify

`uv run pytest tests/test_window_burn_rate.py -q` (18 pass) + full `pytest` + `ruff` green. Live proof:
a burn whose only agentlens finding is <15% of window now reports the native top consumer, not the
tiny finding's workspace.
