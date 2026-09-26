---
trdd-id: M2NF7HJ8
title: compose_template_handoff NEXT ACTION dangles when cards is empty — handoff reads like an empty stub
column: todo
created: 2026-09-27T01:02:10+0200
updated: 2026-09-27T01:07:20+0200
current-owner: ai-maestro-plugin-orchestrator
task-type: bugfix
relevant-rules: []
---

# The template handoff's NEXT ACTION points at a section it did not write

## Symptom (Restart #2 handoff, 2026-09-26 08:30 local)

The auto-composed handoff's NEXT ACTION reads: "Read the `## STATE` block of the first
in-flight card below, then continue its NEXT ACTION." — but the handoff has no in-flight
cards section (only "## Other open cards: 202CCFA2"). The owner's experience: a handoff
that LOOKS like an empty stub even when its body carries 29 verbatim messages and the full
Jev account. "the behaviour at restart is still bad.. ... a empty txt injected" (owner,
verbatim).

## Root cause (verified in source 2026-09-27)

`scripts/lib/external_clear.py::compose_template_handoff` (~line 1632): the NEXT ACTION
block (lines ~1662–1667) is emitted UNCONDITIONALLY, while the `## In-flight cards` section
is conditional (`if cards[:n_cards]:`, ~line 1668). When `inputs.cards` is empty — the
normal state of a board with no `dev`/`testing` card in flight — the prose points at a
section that does not exist.

Known and documented before, never fixed: the empty-cards case is exactly what
`jev_compaction_lane.py::_collect_board_heads`'s docstring flags ("review finding on
TRDD-RAEGS1D5 C1: an empty `cards=[]` makes compose_template_handoff's fixed NEXT-ACTION
prose point at nothing") — that finding drove collecting REAL titles, but the dangling
prose itself was left in place.

## Required behaviour

1. Make NEXT ACTION conditional on the same predicate as the section: when
   `cards[:n_cards]` is non-empty, emit the current text unchanged. When empty, emit a
   truthful one instead — e.g. "No in-flight cards on the board — this handoff is an index;
   hold for instructions, or pick from Other open cards / Recent commits below if one of
   them is why you cleared." (Exact wording is the implementer's; the constraint is: no
   reference to a "first in-flight card below" when none follows, and the line must still be
   one runnable instruction.)
2. Same treatment inside the `render()` closure (`n_cards` variant, ~line 1651) — both
   renderings (live and preview) must change together; a fix in one is a half-fix.
3. Do not touch the byte budget: the empty-cards NEXT ACTION must be SHORTER than or equal
   to the current text (the conditional currently costs 4 fixed lines; the replacement must
   not exceed them), so `max_bytes` trimming behaviour is unchanged.

## Gates

- Unit test: `HandoffInputs` with `cards=[]` → output contains no "first in-flight card"
  text; contains the fallback line; still well-formed (starts with the `# Handoff —` header).
- Unit test: `cards=[(id, col, title), ...]` → output byte-identical to the current
  rendering (snapshot the current output first — this is a regression fence, the non-empty
  path must not change).
- Full suite green.

## Implementation notes for the worker

- `tldr slice` the function first (tldr-code skill); edit with `fastedit`; use `jgrep` if
  you need to find every caller of `compose_template_handoff` before deciding the wording
  (known callers: `summarize_previous_session.py:307`,
  `on-session-start-post-clear-compact.py:404`, `external_clear.py:820` — verify none parse
  the NEXT ACTION line itself; all three inject it as prose).
- Parent card TRDD-RAEGS1D5 STATE block for vocabulary.

## Adversarial review amendment (2026-09-27)

REVIEW MINOR APPLIED — commit bae2ccea's subject overclaims: 'all three verified in source + live repro 2026-09-27' is true per-card only for K8YF2WQ5 (live repro tonight); C7M4RXQ2's repro evidence is from 2026-09-25, M2NF7HJ8's symptom from the 2026-09-26 handoff. Per-card evidence dates stand as written in the bodies. Also per review: workers run targeted pytest -k subsets only; the orchestrator runs the full suite once, serially, after all three land. No other amendment — the NEXT ACTION fix design itself survived review.

## Adversarial review round 2 (2026-09-27)

Cross-card disclaimer: round-1's commit-subject overclaim (bae2ccea) is shared by ALL THREE cards; the correction was recorded only on M2NF7HJ8 — the per-card evidence dates in C7M4RXQ2's and K8YF2WQ5's bodies are the authoritative record, and both now carry their own round-2 section. This card's own fix design is unchanged.
