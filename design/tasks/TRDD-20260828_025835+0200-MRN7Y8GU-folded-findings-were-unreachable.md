---
trdd-id: MRN7Y8GU
title: agent-context-integrity folded findings behind a hardcoded cap with no way to read them
column: complete
created: 2026-08-28T02:58:35+0200
updated: 2026-08-28T02:58:35+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
min-approval-requirement: none
---

# "…and 11 more" named a set nobody could enumerate

Reported by the ai-maestro hub 2026-08-28, hit within minutes of trying to MEASURE whether
TRDD-2501HHML's fix had helped them.

## The defect

`scripts/detectors/agent-context-integrity.py` printed `cap = 5` findings, hardcoded, then
folded the rest into `…and N more`. There was no flag.

**Worse than a display limit, and this is the part that made it a bug rather than a preference:**
on a repo whose agent-context files are all locally authored, the issue-raise loop deliberately
skips them (`verified_local` / janitor#214 — a finding whose file has an entirely local history
never opens a ticket). So for exactly that repo the capped print was the ONLY surface those
findings ever had. The folded ones were unreachable by ANY means.

A detector that reports a count it cannot show is asking to be disbelieved — and it makes
consumer-side measurement of any future fix impossible, which is precisely how it was found.

## Fix

`CLAUDE_PLUGIN_OPTION_AGENT_CONTEXT_MAX_PRINTED`, read through the same `state.coerce_int`
idiom as the sibling `..._MAX_FILES` knob. **Default unchanged at 5** — heartbeat stdout is
re-charged to EVERY turn, so the small budget is the point, not a display choice — but one run
with the knob raised prints them all.

## Acceptance

- [x] Default behaviour byte-identical (still 5, still folds).
- [x] Raising the knob folds nothing and prints every finding.
- [x] ruff + mypy clean; 9653 detector tests pass.

## Notes and lessons learned

- The test needed TWO repos, not two runs over one. The detector suppresses an unchanged tree
  via its last-hash stamp, so a second run on the same files is silent — the test would have
  passed for the wrong reason. The reporter had hit the same stamp and worked around it by
  moving it aside by hand; that detail in their message is what predicted the trap.
- Not built: per-finding rows in the findings ledger so `/janitor-findings` could page them.
  That is the better long-term surface, but it is a new write path; the knob closes the actual
  hole (unreachable findings) at a fraction of the risk.
