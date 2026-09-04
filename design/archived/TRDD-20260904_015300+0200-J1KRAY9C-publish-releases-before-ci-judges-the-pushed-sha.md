---
trdd-id: J1KRAY9C
title: publish.py creates the GitHub release before CI has judged the pushed sha
column: complete
created: 2026-09-04T01:53:00+0200
updated: 2026-09-04T02:40:00+0200
current-owner: main-session
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

# publish.py creates the GitHub release before CI has judged the pushed sha

## Symptom

`publish.py` bumps, tags, pushes, creates the GitHub release, and runs an
install smoke test, all before CI runs on the pushed commit. A release can go
live and get installed while CI is still red on the exact sha it points at.

## Evidence

- Measured 2026-09-04: release 3.4.14 was tagged, released, installed to user
  scope, and the janitor daemon respawned onto it, all before CI reported
  failure on that same commit (run 33814952562, Lint job, 7 pyright errors).
- Making the gate a superset of CI narrows the window but cannot close it: the
  gate runs on a local tree, CI runs on the pushed commit under different
  load. A load-dependent `git_utils` probe timeout the same night passed the
  gate and failed locally afterwards, demonstrating exactly that gap.

## The design question

If the release waits for CI green, what happens when CI goes RED after the
push? The tag and commit are already public. Options are a dangling tag with
no release, an auto-revert, or a wait-then-fail state.

Also note: this would make `publish.py` block for CI's duration (~10 min).
That is not in conflict with the working rule "after publish.py, do NOT sit
and watch CI" — that rule governs the operator's attention, not the
pipeline's ordering — but it does change the ergonomics.

## The proposed fix targets the wrong boundary — measured 2026-09-04

The card assumes the GitHub *release* is what exposes a bad build to
consumers. It is not. The install path never touches the release:

- `stage_install_smoke` (and any consumer) installs via
  `claude plugin install ai-maestro-janitor@ai-maestro-plugins` — through the
  MARKETPLACE, not through a GitHub release asset.
- The live marketplace entry (read 2026-09-04 from
  `Emasoft/ai-maestro-plugins:.claude-plugin/marketplace.json`) is
  `{"source": {"source": "url", "url": ".../ai-maestro-janitor.git"}}` — a
  plain git URL with **no ref, tag, or release pin**. It resolves to the
  repo's default branch. Its `version` field is catalog metadata, not a
  fetch pin.
- That catalog is refreshed by `.github/workflows/notify-marketplace.yml`,
  which triggers `on: push: branches: [main]` for `plugin.json`, `hooks/**`,
  `commands/**`, `agents/**`, `skills/**`, `scripts/**` — i.e. on the PUSH.
- `release.yml` triggers on the tag push and only re-validates; the release
  object itself is created locally by `stage_gh_release`.

So the exposure window opens at `stage_commit_and_push`
(`scripts/publish.py:3169`), one stage BEFORE `stage_gh_release`
(`:3170`). Inserting a CI-green wait between them would delay an artifact
nobody installs from while the marketplace already serves the pushed main.
It would close nothing and would read as if it had.

This also re-frames the 3.4.14 incident correctly: the daemon respawned onto
3.4.14 because main had moved, not because a release existed.

## What would actually close it

Only an ordering that keeps the bad sha OFF main until CI has judged it:
push a feature branch, wait for CI green THERE, then fast-forward main and
tag. That inverts the pipeline's shape (and CLAUDE.md routes every push
through `publish.py`, so `publish.py` would own the branch push, the wait,
and the merge). It changes what publishing IS, so it is the user's call —
carried forward as TRDD-1B7ZYKHR, not decided here.

## Acceptance criteria

- [x] The ordering decision is made and recorded.
      — DECIDED 2026-09-04: **reject** "the release step waits for CI green".
      Evidence above: the release is not on the install path, so the
      reordering closes no window. Recording the rejection is the point —
      an ineffective fix that looks effective is worse than the known gap.
- [x] If adopted, the release step waits for CI green on the pushed sha.
      — NOT ADOPTED, per the decision above. `publish.py` is unchanged.
- [x] The red-CI-after-push behaviour is defined and implemented.
      — MOOT under the rejection: with no wait inserted there is no new
      red-CI-after-push state to define. The real design question (what to do
      when CI goes red on a branch before main moves) belongs to
      TRDD-1B7ZYKHR.

## Approval log

- 2026-09-04T02:40:00+0200 — COMPLETED by janitor-main-session under the USER's
  standing delegation ("you are in charge... you can do the review columns of
  the kanban in my stead", 2026-09-03). No code changed; the successor
  TRDD-1B7ZYKHR carries the redesign and waits on the USER.
  NOTE: the Fable advisor was NOT consulted on this decision —
  `agentlenspro model-headroom fable` reported Fable at 100% of its weekly
  window (exit 1), which the advisor rule names as a sanctioned skip. No
  verdict was obtained; this decision rests on the measured facts above.
