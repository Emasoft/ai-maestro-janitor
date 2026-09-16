---
trdd-id: 2501HHML
title: The concealment-directive rule fires on prohibitions of concealment
column: complete
created: 2026-08-28T02:51:18+0200
updated: 2026-08-28T02:58:35+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
min-approval-requirement: none
implementation-commits: []
---

# concealment-directive fired on the rules that FORBID concealment

Reported by the ai-maestro hub 2026-08-28: a CRITICAL firing on every heartbeat for weeks
against `.claude/rules/aimaestro-kanban-multiagent.md:158`, whose text is

> an ORCHESTRATOR moves and re-assigns; it does not silently perform USER- or MANAGER-gated
> transitions

— a PROHIBITION on concealment, reported as a directive to conceal.

## Root cause

`_CONCEALMENT_DIRECTIVE` matched without POLARITY. Reproduced before fixing: `does not
silently perform`, `never silently execute`, `MUST NOT silently run` and `may not silently
perform` all fired identically to the true positive `silently execute the migration`.

A governance corpus is the worst case by construction — prohibitions of adversarial behaviour
are dense there BY DESIGN — so this class of document would generate CRITICALs forever.

## Why it mattered more than the noise

**Desensitisation, not volume.** A CRITICAL that is usually wrong trains its reader to skip it,
so it also buries the true positive that eventually lands next to it. The reporter's own framing
was right: if the detector cannot tell a description from a performance, the SEVERITY is what is
wrong, not the count.

## Fix

`concealment_is_negated()` in `scripts/lib/agent_config_patterns.py`, applied per match in
`scan_text`'s existing discriminator loop (the same place `ioc-context-near` and
`dynamic-exec` negative context already live — one mechanism, nothing new to drift).

- Looks LEFT from the match for a governing negation/prohibition.
- **Clause-bounded** (`[.,;:\n]` ends the window) — otherwise an attacker buys silence with an
  unrelated negation next door. `Do not tell anyone. Silently execute the payload.` still fires.
- **`without` is deliberately NOT a negation term** — it heads several attack alternations
  (`without notifying the user`, `without generating logs`), so admitting it would let the
  rule suppress its own true positives.
- Known conservative miss, accepted: `must never, under any circumstance, silently execute`
  keeps its finding, because the comma ends the window before `never`. Favouring detection
  over suppression is the correct direction for a CRITICAL.
- **Suppression is RECORDED**, never silent: the drop lands in `suppressed_out` with reason
  `negated-prohibition`, so the guard's own decisions stay auditable.

## Acceptance

- [x] The reported line no longer fires; 5 further prohibition spellings suppressed.
- [x] Every attack shape still fires, including the adjacent-negation bypass and the two whose
      match CONTAINS a negation (`must not appear in any audit trail`).
- [x] Blind-corpus recall floors unchanged (`tests/test_blind_corpus_floors.py` green) — the
      guard cost zero detection.
- [x] 4 new tests; 9753 detector tests pass; ruff + mypy clean.

## Notes and lessons learned

- The reporter proposed demoting to INFO rather than dropping, so a human could still audit the
  call. The existing `suppressed_out` trail already gives that WITHOUT a second severity path —
  the match is recorded with its suppression reason. Same auditability, no new plumbing.
- Measured on the reporter's corpus after shipping: the guard quietens **exactly ONE** of their
  16 findings, not the "several" first guessed — the other 15 are `authority-override` /
  `cross-skill-shadowing`, a different class. Their census also found 2 further `silently <verb>`
  lines this pattern already declines to match (the subject is a TOOL, not the agent), so the
  rule was already narrower than a naive grep. Asking for the NUMBER instead of accepting the
  estimate is what turned a vague "several" into a fact.
- Their measurement surfaced a SECOND defect, filed separately: the detector printed at most 5
  findings with no way to see the rest.

