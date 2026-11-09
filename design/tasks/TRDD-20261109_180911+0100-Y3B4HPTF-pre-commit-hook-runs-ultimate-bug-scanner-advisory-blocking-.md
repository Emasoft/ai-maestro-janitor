---
trdd-id: Y3B4HPTF
title: Pre-commit hook runs ultimate-bug-scanner advisory, blocking only on silence
column: dev
status: tasked
created: 2026-11-09T18:09:11+0100
updated: 2026-11-09T18:55:59+0100
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
2026-11-09 — CORRECTION to the entry above, after a review of the entry itself: 'MEASURED and REFUTED' overclaimed. Three positive samples do not refute a universal, and the probe that mattered was missing — the hook's REAL file state, a mktemp-created 0-byte file handed to ubs, not a path ubs never opened. That probe now run: pre-created 0-byte file, staged CLEAN non-empty set → 865 bytes, rc=0; staged set with criticals → 3961 bytes, rc=1; empty staged set → 0 bytes, rc=0. So the predicate is not falsified across the states probed AND holds under the hook's exact file state. Also withdrawn: 'rc=0 means it completed' — that is an assumption about ubs' exit semantics, not a measurement; none of the measured codes (0 no criticals, 1 criticals, 2 env/usage, 3 nothing scanned) says the report was written. The residual stands as OPEN, not dismissed: an rc=0 run that writes no report on a NON-EMPTY staged set would be reported as nothing-to-scan. Status: code unchanged and correct on every state probed; the open residual needs an owner decision only if ubs' vendor contract cannot rule it out.
2026-11-09 — tightened again, after a review of the correction itself. Two wording defects in that entry. (1) It said the predicate 'holds under the hook's exact file state'; the probe showed only the PRECONDITION (a pre-created 0-byte file that ubs fills when it scans), not the consequence, and 'exit 0' did not discriminate WHICH arm fired — the `0|1` block has three arms that all exit 0. Now OBSERVED instead of inferred, by instrumenting the stage to print the report byte count and the counts line alongside the message: staged clean non-empty → 865 bytes, counts [0 0 0], parseable-clean arm; warnings-only → 2945 bytes, counts [0 1 1], parseable arm; criticals → 3961 bytes, counts [2 1 0], parseable arm plus the CRITICAL message; EMPTY staged set → 0 bytes, no counts, the empty-report arm; docs-only → 0 bytes, rc=3, the exit-3 arm. Across the probed states the empty-report arm fires ONLY at 0 bytes, and 0 bytes occurs ONLY for the empty staged set. (2) The residual's exit condition was delegated to the owner ('only if ubs' vendor contract cannot rule it out'); that is wrong — whether ubs can exit 0 without writing a report is decidable by reading ubs' documentation or source, which nobody has done. Correct status: decidable from ubs' docs, unread, exposure therefore unquantified. This is a research step, not an owner decision.
2026-11-09 — BLOCKER found by the review of the entry above, and it is real. That entry said 0 bytes "occurs ONLY for the empty staged set". False as written: state d (docs-only) is a NON-EMPTY index and it too reports 0 bytes. So the byte count is not the discriminator — rc PLUS the arm rc selects is. Corrected claim, scoped to what was measured: within the `0|1` block, across the five probed states, 0 bytes occurred only when ubs had nothing it would scan — the empty index (state h). State d is rc=3 and is routed to the `3)` arm before the empty-report check is reached at all, so the two 0-byte states are separated by rc, not by size; the sentence as written dropped that scoping and its own state-d row is the standing counterexample. Second, "ONLY" quantifies over all states and five samples cannot carry it — the unprobed class (rc=0, non-empty staged set, no report) is one this very entry admits as a residual. Scope the word: in the five probed states. Third, minor: the residual's status "decidable from ubs' docs" is itself an unverified premise — nobody has read them. Honest form: not determined; the path to determine it is ubs' documentation or source, unread; docs may settle it, source would, a closed distribution might settle neither. Consequence if it occurs: a misclassification of the printed diagnostic only — ubs' findings never gate, so the commit proceeds either way; it degrades a message, not a decision. No code change: all of the above is wording, and b72aff2a is untouched. One qualification on the probe itself: it was described as "the stage itself", and the INSTR line is unguarded on the `-z` branch where ubs_report is the empty string (wc -c < "" fails, error suppressed, benign). That branch was not in the probed set, so the probe covers every arm the claims here rest on, not that one. The one settling command the review named — an index holding only a .md file, confirming rc=3 with report_bytes=0 and that the `0|1` empty-report arm is never reached — is exactly state d above, already run.
2026-11-09 — one last gap closed, found by the review of the entry above. That entry named the residual as a single class, "rc=0, non-empty staged set, no report", and gave its consequence as "a misclassification of the printed diagnostic only … the commit proceeds either way". True for that class — but the `0|1` block has a FOURTH arm, the trailing `else` that exits 1, reached when the report file is non-empty, the parse failed and the file is not empty; that is rc=0 with a non-empty UNPARSEABLE report, an adjacent class the entry neither named nor claimed about. So the inventory was short by one, and "either way" held only because "no report" and "unusable report" are different states. Corrected inventory, both arms now MEASURED by driving the stage itself with a shim ubs under a fresh TMPDIR: rc=0 with a 36-byte non-JSON report → INSTR shows report_bytes=36 counts=[] and the stage prints "ubs reported exit 0 but wrote no parsable ubs report … BLOCKING", STAGE EXIT 1; rc=0 with a 0-byte report → INSTR shows report_bytes=0 counts=[] and the stage prints the empty-report message, STAGE EXIT 0. So: no report → advisory misprint; non-empty unparseable report → blocks, by design (fail-safe: an unreadable result is not a clean one). The omitted class errs toward blocking, so the record was never unsafe, only incomplete. One further word on the `-z` disclosure, from the same review: that unprobed branch is the mktemp-FAILURE path, so what the probe does not cover is an environment condition, not an ordinary data shape. No code change: the hook implements both arms correctly at b72aff2a, and this entry, like the three before it, changes only what the card asserts. With this, every arm of the `0|1` block, and the `3)` and `*` arms, are named in the record with the observation that selects each.
2026-11-09 — the closing sentence of the entry above is a fresh universal of the kind it was itself correcting, and the review caught it; withdrawn. It said "every arm of the `0|1` block, and the `3)` and `*` arms, are named in the record with the observation that selects each". That is false on its own page: arm 1, the `-z` mktemp-failure branch, is called "that unprobed branch" two sentences earlier, and the `*` arm carries no probed observation here. The sentence exists because the prior rounds kept producing universals, and deleting it is the fix — no replacement summary is added. Accurate form, if a reader needs one: every arm is NAMED; all except the mktemp-failure branch carry a probed observation. Two smaller corrections from the same review. (1) The shim measurements establish the STAGE's response to each input class, not that real ubs emits either class — the ordinary case, rc=0 with a valid report, is states a/b, measured earlier with the real ubs, and neither shim class is that. (2) The phrase "reached when the report file is non-empty, the parse failed and the file is not empty" restates non-empty twice; the class is: rc=0, report file non-empty, parse failed. Wording only; b72aff2a unchanged.
