---
trdd-id: Y3B4HPTF
title: Pre-commit hook runs ultimate-bug-scanner advisory, blocking only on silence
column: dev
status: tasked
created: 2026-11-09T18:09:11+0100
updated: 2026-11-09T18:30:10+0100
current-owner: user
created-by: user
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-09T18:09:11+0100
---

# Pre-commit hook runs ultimate-bug-scanner advisory, blocking only on silence

## Decision

`git-hooks/pre-commit` gains a third stage that runs `ubs --staged`
(ultimate-bug-scanner) on every commit. It is ADVISORY ON FINDINGS and
BLOCKING ON SILENCE: findings never block; a scanner that did not actually
run does.

## Why findings cannot gate (measured 2026-11-09)

`ubs` reports findings per RULE, with each rule's `samples[]` array capped
(one rule observed at `count=26` with 3 samples). There is therefore no
stable per-instance identity to diff a "new finding" against:

- count comparison misses remove-one/add-one of the same rule;
- line/code identity blocks ordinary edits (line drift) and renames.

Blocking on ANY finding is unusable regardless: 73 criticals + 300 warnings
already exist at HEAD.

## Why silence must block

The sibling `pre-push` hook treats a missing trufflehog as a refusal, never
a skip, and Stage 1 says "no silent bypass". An absent or failing scanner
must not look like a clean scan.

## Measured exit-code semantics (ubs 5.4.17)

- rc=0: no CRITICAL. May still carry warnings — rc=1 requires >=1 critical,
  so warnings alone return 0. Counts are read from the JSON report, NOT
  inferred from the exit code.
- rc=1: at least one critical.
- rc=2: environment/usage error.
- rc=3: nothing scanned (no supported source file staged). Not a pass.
- Empty staged set: rc=0, NO report written, output `No changed files to
  scan.` — a legitimate no-op, distinguished by that message.
- `ubs --staged` reads the INDEX, not the worktree (verified: unstaged edit
  reported clean; after `git add`, findings appear).

## Implementation notes

- `|| ubs_rc=$?` is LOAD-BEARING, not decoration: `ubs --staged` exits 1 on a
  critical, so removing the guard makes the advisory a blocking gate.
- The report path is `mktemp "${TMPDIR:-/tmp}/ubs-commit-XXXXXX"` with NO
  suffix: BSD `mktemp` substitutes only trailing X's, so a `.json`-suffixed
  template fails there.
- Counts come from the JSON report (banner-prefixed; parsed after the first
  `{`) via stdlib `python3` — no uv, no venv, no project file needed.
- The report is removed on every path except the critical-findings path, where
  it is KEPT and its path printed.
- Deliberately NOT set: `UBS_ALLOW_NO_SCAN` (it turns rc=3 into rc=0).

## Correction — core.hooksPath

The header comment claimed `install_hook` sets `core.hooksPath=git-hooks`.
In a working clone the value is ABSOLUTE
(`/Volumes/EmaUITEK4TBSSD/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/git-hooks`).
Comment corrected 2026-11-09.

## Verified

`bash -n` clean; all eight states exercised in throwaway repos: clean (0),
warnings-only (0), critical (0, report kept), docs-only rc=3 (0), empty index
(0), ubs absent (1), rc=2 (1), rc=1 with no parseable report (1). Temp-report
leak count after the matrix: exactly 1, the kept critical report. The live
hook exits 0 with this change staged.

## Approval log

- 2026-11-09T18:09:11+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-11-09 — adversarial review of ad33dbde found the report parse failed toward a confident clean (a JSON object without `totals` became "0 0 0" via `or {}`). Fixed in c34bd069: both `totals` and `scanners` are now required, the counts line must be exactly three fields, findings print as severity/rule_id/file:line, an unrecognised exit code blocks while naming --no-verify, and a mktemp failure no longer blocks. Re-verified on the shipped file across 10 states in a fresh TMPDIR.
2026-11-09 — verification note: the eight-state claim in the first card body was made partly against an extracted copy of the stage body; the post-fix matrix (clean 0, warnings-only 0, critical 0 with findings printed, docs-only rc=3 0, empty index 0, ubs absent 1, rc=2 1, rc=4 unknown 1, report without totals 1, mktemp failure 0) ran the shipped file via /tmp/ubs-h/s3.sh extracted from the committed hook, with a fresh TMPDIR, and the leak count was exactly 1.
