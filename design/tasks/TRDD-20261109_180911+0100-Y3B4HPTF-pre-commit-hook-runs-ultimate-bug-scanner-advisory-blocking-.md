---
trdd-id: Y3B4HPTF
title: Pre-commit hook runs ultimate-bug-scanner advisory, blocking only on silence
column: dev
status: tasked
created: 2026-11-09T18:09:11+0100
updated: 2026-11-09T18:38:18+0100
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
2026-11-09 — round-two review found the empty-index escape hatch was load-bearing PROSE (`grep -q "No changed files to scan"`, the only thing separating a legitimate no-op from an unreadable result in the rc=0/1 arm; a reword would have blocked every no-op commit). Fixed in b72aff2a using the measured fact that an empty staged set leaves the report file at 0 bytes, so `[ ! -s "$ubs_report" ]` decides it. Proven with a shim writing an EMPTY report and arbitrary wording: recognised as empty-index, exit 0. The findings block now states its units (up to 3 sample locations per rule; counts are RULE GROUPS, not instances).
2026-11-09 — two deliberate decisions stated rather than changed: (1) rc=2 (a missing ast-grep/ripgrep/jq/typos-cli/typos-lsp) BLOCKS, on the sibling pre-push hook's own precedent (a missing trufflehog is a refusal, never a skip) and Stage 1's 'no silent bypass'; the message names the binaries and offers --no-verify for an environment fault the committer cannot fix, leaving that trade to them. (2) an unrecognised exit code BLOCKS and is DESCRIBED as unrecognised, not as 'could not run'. Both are one-line changes if the owner prefers a warning instead.
2026-11-09 — round-three review raised one probe gap on b72aff2a: whether `[ ! -s "$ubs_report" ]` could excuse a scan that ran. MEASURED and REFUTED: a staged CLEAN non-empty set writes 865 bytes; a staged set with criticals writes 3961 bytes; only the empty staged set writes nothing (0 bytes / no file). The predicate therefore separates the three real states correctly. The companion concern (a scan that crashed after mktemp succeeds) is also closed: an empty report with a non-zero exit goes to the catch-all arm and BLOCKS (probe: exit 2 + empty file → exit 1). Residual, documented not fixed: a hypothetical ubs that exits 0 after failing to write would be reported as nothing-to-scan; rc=0 means it completed, so this is unobserved. Prose coupling is GONE (no string match remains).
