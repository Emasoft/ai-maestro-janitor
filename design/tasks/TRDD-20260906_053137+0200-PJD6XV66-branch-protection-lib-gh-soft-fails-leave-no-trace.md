---
trdd-id: PJD6XV66
title: branch_protection_lib's direct gh calls fail soft with no trace, so a loaded suite cannot tell a timeout from a logic bug
column: testing
created: 2026-09-06T05:31:37+0200
updated: 2026-09-08T16:05:00+0200
implementation-commits: [eb4bce28, 20e63eb8, 64255016]
current-owner: janitor-main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
relevant-rules: []
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-06

Filed from a measured full-suite run (`reports/board-drain/20260906_052127+0200-full-suite-gate.txt`,
start loadavg 11.6, `-x -n auto --dist loadgroup`): 10 failed / 2055 passed in 7m23s. Seven of the
ten were `tests/test_branch_protection_guard.py::test_apply_*` asserting on stdout that came back
EMPTY with exit 0 and stderr `''`. The decline stamps the guard writes on its tmp state dir
(`last-outcome-guard-branch-protection.ts`, still present under pytest's kept basetemp) read
`declined:no-default-branch` on every one of them — `detect_default_branch()` returned None.
That function, `viewer_is_admin()` and `list_existing_rulesets()` call `subprocess.run(["gh",…],
timeout=_t(10))` directly and return None/False on TimeoutExpired, OSError, non-zero rc AND empty
stdout, writing nothing anywhere — and their `if not gh_available(): return None` line declines
the same way before any subprocess runs. Timeout is the least likely of the five in that run:
the suite exports scale 10 into the child, so its `_t(10)` was 100 s; a non-zero rc / empty
stdout from the python `gh` stub, an OSError on spawn (EAGAIN under load is a HYPOTHESIS, not
measured), or `which("gh")` missing the stub remain — unranked; the trace this card adds is
what will rank them. This is the exact shape TRDD-9EAQS97B (8bcd2975) closed for
`state.run_subprocess`, left open on these three direct callers — and why TRDD-7NSRD8OV could
only say the guard family "breaks the single-cause story": the cause was unobservable by
construction. Both tests rerun green in isolation (4.81 s).

Landed in eb4bce28 (2026-09-08): a stderr trace line `⟦branch_protection_lib⟧ <fn> <reason>: gh`
on every soft-fail branch (`gh-not-on-path` / `timeout after Ns` / `oserror:<Type>` /
`rc=<n> stderr=…` / `empty-stdout`), return values unchanged, plus
`tests/test_branch_protection_lib_soft_fail_trace.py` (5 real-subprocess tests; the timeout
one carries `no_timeout_scale`). Verified first-hand: ruff, mypy, pyright clean; the three
branch-protection test files pass isolated — 83 in 21.7 s at loadavg 58. The 2026-09-06 gate
run of the same three files reported 7 failed / 76 passed in 2367 s (39 min). What that pair
of runs PROVES: the failures are not a deterministic regression. What it does NOT prove: that
they were the load class 7NSRD8OV tracks — that is a proxy read, and the gate capture
(`reports/board-drain/20260906_052127+0200-full-suite-gate.txt`) recorded only 2 of the 7
FAILED names, so 5 are unnamed. Both named ones assert a FIRE on stdout, which a soft-failed
`gh` read turns silent, and their assertion messages were empty. Landed 20e63eb8 + 64255016:
every FIRE assertion in `test_branch_protection.py` / `test_branch_protection_guard.py`
carries `r.stderr`, so the next loaded failure prints the `⟦branch_protection_lib⟧` trace
and names its own cause. (20e63eb8 also repointed `test_detector_roster_completeness.py` at
the hub's part links after the 9e115e6e memory split emptied the hub of group bullets and
blocked the 3.4.15 publish at gate [3/11].) NEXT ACTION: none — waits on the publish gate.

## Symptom

A full-suite run under load fails `test_branch_protection_guard.py` tests with
`assert '[guard] applied …' in ''` — exit 0, empty stdout, empty stderr. Isolated reruns pass.
Nothing on disk or in the test output names a timeout, a bad rc, or an empty gh reply.

## Cause

`branch_protection_lib.detect_default_branch` / `viewer_is_admin` / `list_existing_rulesets`
swallow every failure of their direct `subprocess.run(["gh", …])` call into None/False. The
guard's `_decline("no-default-branch")` then exits 0 by design (TRDD-COQN6KVA), so the only
artifact is the decline stamp, which names the GATE but not what made gh fail.

## Acceptance

- [x] every soft-fail branch of the three gh readers prints one `⟦branch_protection_lib⟧` line
      to stderr naming the function, the reason and `gh`; the success path prints nothing
- [x] a real-subprocess test pins all five reasons (gh-not-on-path added on review) and the
      silent success path
- [x] ruff, mypy, pyright, and the branch-protection test files green (eb4bce28)
- [ ] full-suite publish gate green (shared box with every `testing` card)

## Notes

Not a fix for the load flake itself — that is 7NSRD8OV's card. This card makes the next
loaded failure self-attributing, which is the precondition for fixing it causally.
