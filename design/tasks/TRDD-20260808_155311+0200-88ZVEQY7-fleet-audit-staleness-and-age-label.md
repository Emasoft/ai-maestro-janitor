---
trdd-id: 88ZVEQY7
title: Fleet github-config findings served 18 days stale with no age label — sweep silence must alarm
column: blocked
created: 2026-08-08T15:53:11+0200
updated: 2026-08-13T04:43:15+0200
blocked-by: [publish-and-github-reply-gate]
pre-block-column: todo
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#244, janitor#237, TRDD-EZ3PMQYX]
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

   **SIBLING CARD — TRDD-EZ3PMQYX, surfaced 2026-08-13 by `trdd-cross-card-blindspot`.** Its
   item 3 implements the SAME #237 ask ("flag carries evidence age") for the iTerm flag, which
   is the surface this card generalizes FROM. They do not conflict — they are one principle on
   two surfaces — but whichever ships first should establish the age-label mechanism and the
   second should REUSE it. Two independently-invented age formats for the same lesson is the
   avoidable outcome, and neither card could see the other until now.

## What

- The per-session surface (`detectors/fleet-github-config.py` / `summarize_for_slug`) prints
  the payload's generated-at AGE in every drift line, and REFUSES to surface a payload older
  than N× the sweep cadence — replacing the findings with ONE line naming the staleness
  itself ("fleet audit is N days stale — findings withheld; the sweep owner is not running").
- Diagnose WHY the sweep stopped on this host (launchd daemon task state, chore ownership
  handover, task failure counter) and fix or card the specific cause.
- The daemon-watchdog shim covers task_github_config_audit with the standard stale line.

## ⏵ STATE — 2026-08-13: shipped. The card's own root-cause claim was WRONG; the fix is right anyway.

### The stated cause ("the daemon's fleet sweep silently stopped running") is FALSE

Measured tonight, in this order, each step correcting the last:

1. The payload at `<global-state>/github-config-findings.json` is **22.2 days old** (was 17.8
   when filed) — so the symptom is real and worse.
2. But `github-config-audit`'s last-run stamp is **~1 hour** fresh. So the chore is not silent.
3. And neither daemon log carries a single `task 'github-config-audit'` line, nor a failcount —
   so our daemon never ran it either. For a while this looked like the sharpest possible
   finding: `Task.poll_background` writes `last_run` at daemon.py:1941 **before** the
   `if rc != 0` branch, so a task that fails every run keeps a perpetually fresh stamp and can
   blind any stamp-keyed watchdog. **That is true of the code and was NOT what happened here.**
4. The actual cause: the **ai-maestro server has absorbed this chore** (janitor#197) and
   publishes its own payload to `~/.aimaestro/github-config-findings.json` — measured **0.04 d
   old, 14 repos, 0 findings**. `_read_findings` already takes the freshest of the two, so the
   22-day local file simply LOSES. The stamp was honest; the fleet is clean; nothing is broken.

**So why did janitor#244 happen?** Because the surfaced line carried **no age**. The peer could
not tell a fresh verdict from an 18-day-old one, and nothing in the payload's own text said
which it was. That is precisely what this card fixes, and the fix is correct independently of
which writer owns the chore.

**Kept for the record** (step 3): the unconditional `last_run` write on a failed background
task is a real "signal that cannot fail" and deserves its own card — it did not bite here only
because the server took the chore over.

### Shipped

`payload_age_seconds` / `age_label` / `payload_is_stale` / `staleness_line` (pure, in
`github_config_audit.py`) + the detector gate. Judged on the PAYLOAD's `generated_at`, never on
the chore stamp: the stamp says a runner ran, the artifact says what it produced, and only the
second is evidence about this repo.

**Design corrected mid-flight by the existing tests.** My first cut asked "is it stale?" BEFORE
"does this payload say anything about us?", which made every project emit a staleness nag
whenever the sweep lagged — including repos the audit never mentioned. The staleness line must
REPLACE withheld findings, not appear where there were none. Five pre-existing channeling tests
caught it.

A fixture also had to change: `_run` wrote `generated_at: 1` as a don't-care sentinel, which
stopped being a don't-care once age meant something (epoch 1970 ⇒ correctly withheld), so those
assertions would have silently tested the staleness path instead of the path they name.

## Acceptance

- [x] Age in every surfaced GHCFG line (test on a synthetic payload) — `age_label` never omits
      the clause: unknown says "unknown", sub-0.1d says "fresh". An ABSENT age reads identically
      to a fresh one to a hurried reader, which is the janitor#244 failure itself.
- [x] Stale-payload refusal at N× cadence with the staleness line (test) — 4× the 6 h cadence
      = 24 h. Unit-tested AND end-to-end through the detector subprocess (withholds the finding,
      prints "WITHHELD / Nothing is claimed", and the verdict does not leak). Falsified:
      neutering `payload_is_stale` fails the gate test; probe reverted.
- [x] Root cause of the 18-day silence identified and recorded here — and it is NOT the one the
      card asserted; see above.
- [ ] #244 answered when it ships — queued behind the user's publish/GitHub gate.

## Approval log

- 2026-08-13T02:55:00+0200 — todo → blocked. Code + tests done (full suite 14,955 passed); the
  only remaining box is the outward GitHub reply, which is gated on the user's publish decision.
  Not left in `todo` claiming workable, and not marked complete while an acceptance box is open.
