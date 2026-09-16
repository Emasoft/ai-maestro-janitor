---
trdd-id: HTFUWAU9
title: CI Smoke hook loop must fail on a Traceback like the detector loop does
column: complete
created: 2026-09-10T19:31:42+0200
updated: 2026-09-16T10:40:13+0200
current-owner: ai-maestro-janitor-f2
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
npt: []
eht: []
---

# CI Smoke hook loop must fail on a Traceback like the detector loop does

## Why

`.github/workflows/ci.yml`'s Smoke job (~lines 265-267) runs each
`scripts/hooks/*.py` under `timeout 30` with no stdin payload and only fails
the step on exit `124` (timeout). A hook that crashes at import time, or that
exits non-zero for any other reason, passes the step silently. The Smoke
job's separate detector loop (~lines 283-305) already greps captured output
for `Traceback (most recent call last)` and fails the step on a match — the
hook loop has no equivalent guard.

This gap was concrete, not hypothetical: 12 hook files
(`on-prompt-submit-user-mem`, `on-session-start-cold-cache-clear`,
`on-session-start-trdd-state`, `on-stop-token-meter`, `on-subagent-start`,
`on-subagent-stop`, `post-compact-resume`, `post-edit-memory-correction`,
`post-model-switch`, `pre-compact-handoff`,
`pre-tool-agent-generator-guard`, `pre-tool-context-usage`) were mode `644`
until commit `46cf9a7b` fixed their executable bit. Before that fix, `timeout
30 ./hook` exited `126` (permission denied) on every one of them, on every
Smoke run, and the loop did not fail on `126` — so 12 hooks had never
actually executed on the CI runner despite the job reporting green. This
card (TRDD-TWF7DXXR) found the mode-bit bug in the same CI log, but nothing
in the workflow would have caught it structurally; only a manual code read
did.

## Baseline — closed-stdin smoke of the 12 previously-non-executable hooks

Run 2026-09-10, `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_ROOT` set to the repo
root, `timeout 30 ./hook.py </dev/null` each, post-46cf9a7b (mode bits
fixed):

| hook | rc | Traceback? |
|---|---|---|
| on-prompt-submit-user-mem | 0 | no |
| on-session-start-cold-cache-clear | 0 | no |
| on-session-start-trdd-state | 0 | no |
| on-stop-token-meter | 0 | no |
| on-subagent-start | 0 | no |
| on-subagent-stop | 0 | no |
| post-compact-resume | 0 | no |
| post-edit-memory-correction | 0 | no |
| post-model-switch | 0 | no |
| pre-compact-handoff | 0 | no |
| pre-tool-agent-generator-guard | 0 | no |
| pre-tool-context-usage | 0 | no |

12/12 rc=0, 0 hangs, 0 Tracebacks. This is the baseline the acceptance
criteria below are measured against — a clean run on 46cf9a7b's fixed
permissions, before the workflow gains a Traceback guard.

## Acceptance

- [x] The Smoke job's hook loop mirrors the detector loop's shape: capture
      each hook's stdout+stderr, and fail the step when the captured output
      contains `Traceback (most recent call last)`, regardless of exit code.
- [x] The set of exit codes a hook may legitimately return under a
      closed-stdin, no-payload invocation is decided and documented in the
      workflow (a comment) — e.g. is a non-zero, non-Traceback exit
      (deliberate "hook declines to act, no input") acceptable, or should the
      loop also gate on exit code?
- [x] ~~First CI run after landing is expected to be a no-op against the~~ STRUCK 2026-09-16: the premise was inverted by events — the first CI run carrying this guard (3.5.1, 60bedabc, run 35069593528) FAILED on rc=126 for two hooks whose executable bit a worker rewrite had dropped; the guard was right and the hooks were broken. Original expectation continues below:
      12-hook baseline above (all still rc=0, no Traceback) — a regression
      there would mean the fix's own guard is wrong, not that the hooks
      broke.
- [x] The Smoke hook loop fails the step on rc 124 (hang), rc 126/127 (not executable / not found) and on a Traceback in captured output, regardless of rc — .github/workflows/ci.yml Smoke step (commit 30994579).
- [x] The loop survives a hook that legitimately declines with a non-zero exit under bash -e (commit 87fc61f2).
- [x] Proven live: CI run 35069593528 (3.5.1) failed the Smoke job on rc=126 for two hooks that had lost their executable bit; fixed in 18dbb9dd, and tests/test_detector_executable_bits.py now guards the index mode of every hook (0ec065c1).

## Approval log

- 2026-09-10T19:31:42+0200 — Authored at `todo`, Tier 0 (in-scope CI
  hardening, no baseline/rule deviation). Found while running TRDD-TWF7DXXR's
  closed-stdin hook smoke; see that card's STATE block for the pointer back.
- 2026-09-16T10:38:49+0200 — COMPLETED by the session acting as approver. The card sat in todo although its code had landed on 2026-09-10/11 (30994579, 87fc61f2); today's 3.5.1 CI failure was the live proof the guard works.
- 2026-09-16T10:40:13+0200 — COMPLETE by session-as-approver. landed 30994579+87fc61f2; proven live by run 35069593528.
