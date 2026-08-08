---
trdd-id: 88ZVEQY7
title: Fleet github-config findings served 18 days stale with no age label — sweep silence must alarm
column: todo
created: 2026-08-08T15:53:11+0200
updated: 2026-08-08T15:53:11+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#244, janitor#237]
---

# Fleet github-config findings: staleness + age label

## Why (janitor#244, autonomous peer — root cause verified against the live payload)

The peer received `GHCFG-001: NO_PR_REVIEW, NO_REQUIRED_CHECKS` on a repo whose
baseline-pr-and-checks ruleset was verifiably live and correct. Their wrong-surface hypothesis
(classic-vs-rulesets) is DISPROVED by the classifier source — `classify_repo` unions rule types
across active rulesets and explicitly gates review/checks findings on readable rulesets. The
REAL cause, measured: `global-state/github-config-findings.json` was generated **2026-07-21 —
17.8 days before the finding was surfaced** — predating that repo's pr-and-checks rulesets
entirely. Two defects:

1. **The daemon's fleet sweep silently stopped running** (last-run stamp = the same 07-21
   epoch). Nothing alarmed on the silence — the absence-of-signal-is-not-health class, again
   (daemon_watchdog.emit_if_daemon_stale exists for exactly this; either it does not cover
   this task or its line never surfaced — determine which during implementation).
2. **Findings are surfaced with no age**: a verdict served without the age of its evidence
   cannot be checked by the reader (#237's lesson, generalized from the iTerm flag to the
   fleet audit). The peer nearly mutated a compliant repo on an 18-day-old claim — stopped
   only by their own verify-before-acting discipline.

## What

- The per-session surface (`detectors/fleet-github-config.py` / `summarize_for_slug`) prints
  the payload's generated-at AGE in every drift line, and REFUSES to surface a payload older
  than N× the sweep cadence — replacing the findings with ONE line naming the staleness
  itself ("fleet audit is N days stale — findings withheld; the sweep owner is not running").
- Diagnose WHY the sweep stopped on this host (launchd daemon task state, chore ownership
  handover, task failure counter) and fix or card the specific cause.
- The daemon-watchdog shim covers task_github_config_audit with the standard stale line.

## Acceptance

- [ ] Age in every surfaced GHCFG line (test on a synthetic payload)
- [ ] Stale-payload refusal at N× cadence with the staleness line (test)
- [ ] Root cause of the 18-day silence identified and recorded here
- [ ] #244 answered when it ships
