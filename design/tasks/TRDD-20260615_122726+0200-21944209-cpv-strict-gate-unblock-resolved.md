---
trdd-id: 21944209-735e-4f0f-842d-28ff6c490a33
title: CPV strict-gate publish unblock — RESOLVED (retrospective record + report→TRDD conversion)
column: complete
created: 2026-06-15T12:27:26+0200
updated: 2026-06-15T12:27:26+0200
current-owner: janitor-session
assignee: janitor-session
priority: 5
severity: LOW
effort: S
labels: [publish, cpv, retrospective, bookkeeping]
task-type: docs
parent-trdd: null
relevant-rules: []
release-via: none
test-requirements: []
audit-requirements: []
review-requirements: []
impacts: []
last-test-result: not-run
external-refs: ["github.com/Emasoft/claude-plugins-validation/issues/65", "github.com/Emasoft/claude-plugins-validation/issues/67", "github.com/Emasoft/claude-plugins-validation/issues/112", "github.com/Emasoft/claude-plugins-validation/issues/113", "github.com/Emasoft/claude-plugins-validation/issues/115", "github.com/Emasoft/claude-plugins-validation/issues/116"]
---

# TRDD-21944209 — CPV strict-gate publish unblock — RESOLVED

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-15

**This TRDD is a TERMINAL, RETROSPECTIVE record.** The work it documents is
DONE. It exists so the three gitignored decision/synthesis reports below (which
the `report-to-trdd-drift` detector correctly flagged as un-converted) survive
the next resume as a git-tracked decision, per the
`reports-are-evidence-decisions-become-TRDDs` rule. Do **not** re-open or
re-execute any plan inside the cited reports — read this STATE block instead.

- **Current state:** the CPV `--strict` publish gate is GREEN. The janitor has
  shipped continuously since (now at **v0.8.10**, CI green, `--strict` exit 0).
  Nothing here is pending.
- **NEXT ACTION:** none. Terminal. (If `report-to-trdd-drift` ever re-fires for
  these three reports, it means this TRDD's body was edited to drop a cited
  basename — restore the verbatim citation in §Evidence.)
- **Load-bearing fact:** the detector matches a report→TRDD by testing whether
  the report's **basename appears verbatim** in any `design/tasks/*.md` body
  (`report-to-trdd-drift.py:118`). The three basenames are cited verbatim in
  §Evidence below precisely so all three go silent.
- **SUPERSEDED — do NOT carry forward:** the storage-restructure clusters A–E in
  `20260603_103403+0200-remediation-plan.md` were an EARLY, v0.6.0-era plan to
  reach a green gate by making CPV's classifier *suppress* the janitor's own
  attack-vocabulary findings. That specific plan was **not** the path taken. The
  gate was ultimately cleared by the **devitalize-or-remove** approach (never
  CPV-exempt; `tools/`→`scripts/` move; `INPUT_DEV`→`downloads_dev`; upstream CPV
  issues #112/#113/#115/#116), recorded in the LOCAL memory
  `project_janitor_publish_blocked_cpv_fps.md` (RESOLVED 2026-06-11, v0.7.0 +
  v0.7.1 published). Treat the remediation-plan's clusters as historical context,
  not a to-do list.
- **Durable artifacts to read before acting:** the LOCAL memory
  `project_janitor_publish_blocked_cpv_fps.md` is the canonical unblock recipe +
  recurrence guard. The three reports cited below are the underlying evidence.

## Why this TRDD exists

Three decision/synthesis reports under the gitignored `reports/` tree were
authored during the CPV strict-gate investigation (2026-05-31 → 2026-06-03) but
never converted to a TRDD. The `report-to-trdd-drift` heartbeat detector flagged
them on 2026-06-15. Per the TRDD rule, a decision that lives only in a gitignored
report is invisible to the next session; this TRDD captures the decision (and its
resolution) as a git-tracked artifact and cites each report as evidence.

## Evidence (the three reports — cited verbatim so the detector resolves them)

1. **`20260531_020025+0200-CONSOLIDATED.md`** (`reports/plugin-audit/`) — a full
   security + correctness audit of the janitor that returned **ZERO findings**
   (CLEAN). It contains **no decision** — it is a null-result audit. Cited here so
   the detector stops nagging; no action was ever warranted from it. The only
   forward-looking notes were process suggestions (confirm scan coverage, keep
   the `scripts/lib/*_patterns.py` attack-signature exclusion explicit, re-audit
   on the next daemon/global-state change) — none of which is a committed plan.

2. **`20260601_211827+0200-CONSOLIDATED-summary.md`** (`reports/cpv-fp-scan/`) —
   CPV v2.116.1 FP scan of v0.5.1. Outcome: 29 verified false positives, **1 true
   positive fixed** (`tests/test_oauth_rotator.py:341` ruff F841), **0 live
   secrets**. Decision (file net-new evidence on the already-open CPV issues
   #65/#66/#67 rather than open duplicates) was **acted upon** — two comments
   filed, no duplicate issues.

3. **`20260603_103403+0200-remediation-plan.md`** (`reports/cpv-remediation/`) —
   a detailed per-finding remediation plan for the v0.6.0 `skillaudit` strict
   gate (40 findings, classifier behaviour verified against the live CPV engine).
   Its headline conclusion — **zero FILE-CPV findings; the classifier is behaving
   per its TRDDs; the janitor's own security pattern-libraries necessarily contain
   the attack vocabulary they detect** — remains the correct understanding. Its
   proposed storage-restructure clusters were superseded by the
   devitalize-or-remove approach (see STATE block).

## Resolution

The CPV `--strict` publish gate was cleared on **2026-06-11** (v0.7.0 + v0.7.1
published; binaries on v0.7.1) and has stayed green through **v0.8.10**. The
durable unblock recipe and the tag-only-workflow recurrence guard live in the
LOCAL memory `project_janitor_publish_blocked_cpv_fps.md`. No upstream FILE-CPV
issue was warranted from these reports (the classifier matched its design TRDDs
on every finding); the actionable upstream items became CPV issues
(#112, #113, #115, #116).

## Approval log

- 2026-06-15T12:27:26+0200 — Authored as a Tier-0 retrospective/bookkeeping TRDD
  (docs task, own-scope) under the user's standing "everything solved, nothing
  pending, take the decisions yourself" mandate. Converts three flagged
  evidence-only reports into one git-tracked terminal record. No code change.
