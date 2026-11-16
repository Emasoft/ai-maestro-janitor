---
trdd-id: XNZFKX0L
title: A CRED-002 finding is withdrawn for a file the env-secret sweep did not read
column: todo
status: tasked
created: 2026-11-16T10:28:03+0100
updated: 2026-11-16T11:37:56+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T10:28:03+0100
---

# A CRED-002 finding is withdrawn for a file the env-secret sweep did not read

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-16
- NEXT ACTION: a worker is implementing the brief in reports_dev/xnzfkx0l/brief.md; read its report there, check that each new test names the tier that forces the re-read (a fixed mtime of 100.0 with covered [[1.0, ""], [1.0, ""]] is the FRESH tier), then commit the four files by name.
- 2026-11-16 design (advisor-reviewed): a CRED-002 finding is withdrawn only for a path whose CONTENT was scanned for the live secret values this pass. env_secrets._read_one records the path in a new SweepReport field (read) only in its success branch and only when the exact matcher ran (matcher is not None and matcher.table): the scanned counter also rises on a dump-shape-only read with no matcher, so it is the wrong signal, and a pass with no usable secret must not clear a finding. The detector changes only its withdrawal test (path in keys or path in trash_seen becomes path in the read set of either tier); keys stays, because hold() and raise_order need the failed keys. The trash tier shares _read_one, so its read list replaces trash_seen.
- 2026-11-16 tests must force the re-read: a flagged file inside the covered range is never listed, so a stays-flagged test would pass on the old code too; each test sets mtimes or writes a covered range that excludes the file, and each is shown to fail with the old test put back. Cases: a failed read (chmod 0), a file over MAX_FILE_BYTES (patched through the runpy wrapper), a given-up file (retries at MAX_FAIL_RETRIES), and a pass with no secret in the environment.
- 2026-11-16 open follow-up, not in this card: flagged holds paths only, so a pass whose secret set lacks the secret behind a finding (another session, or after a rotation) reads the file clean and withdraws it. Fixing that needs the secret name or fingerprint kept with each flagged path, a state-shape change.
- Follow-up card: TRDD-ZFD3KBM3 (the flagged list holds paths only).

In scripts/detectors/env-secret-on-disk.py, main() withdraws a CRED-002 finding for every flagged path that is "rescanned and clean now" (line 274: `if path in keys or path in trash_seen`). But `keys` (line 186) is built from report.processed AND report.failed, so a flagged file whose read FAILED this pass is withdrawn although it was not read. report.processed also holds files that were not read: a file over MAX_FILE_BYTES (the too_big branch of env_secrets._read_one) and a file whose reads failed too often (the give_up return of env_secrets._read_one). The trash tier of TRDD-ZANQ1QW0 increment 1 already excludes failed reads from trash_seen, but its processed_by_batch has the same too-big and give-up entries. Fix: withdraw a finding only for a path that was actually read this pass (a read-and-scanned set), in both tiers; a failed, too-big or given-up file keeps its finding. Test: one flagged file per case (failed read via chmod 0, too big, given up), each must stay in flagged after a pass. Found by the harness review of the ZANQ1QW0 increment 1 fixes on 2026-11-16. Related: TRDD-ZANQ1QW0, GitHub issue 354.

## Approval log

- 2026-11-16T10:28:03+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
