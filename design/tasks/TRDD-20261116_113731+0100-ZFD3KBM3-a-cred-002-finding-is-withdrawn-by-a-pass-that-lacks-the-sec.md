---
trdd-id: ZFD3KBM3
title: A CRED-002 finding is withdrawn by a pass that lacks the secret behind it
column: todo
status: tasked
created: 2026-11-16T11:37:31+0100
updated: 2026-11-16T13:11:12+0100
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
approval-datetime: 2026-11-16T11:37:31+0100
---

# A CRED-002 finding is withdrawn by a pass that lacks the secret behind it

The env-secret-on-disk detector keeps state["flagged"] as a list of paths only. After TRDD-XNZFKX0L a finding is withdrawn when the file content was scanned for the live secret values this pass and no hit came back. ? INFERRED, not yet verified: the secret set is the environment of the process running the pass, so a pass whose set lacks the secret behind a finding (a pass run from another session, or after the secret was rotated) would read the file clean and withdraw a finding that still holds a leaked value.

Verify first: read env_secrets.load_matcher (or whatever builds the Matcher) and the detector main() to confirm which environment a pass reads, and whether two sessions on one project share the state file. If the gap is real, keep the secret name or its salted fingerprint with each flagged path, and withdraw a finding only when that same secret was in this pass set. That is a state-shape change: an old flagged list of bare paths must keep working (treat a bare path as a finding of unknown secret, withdrawn only by a pass that holds every secret). Tests: a finding made with secret A stays flagged after a clean pass that holds only secret B.

Related gap, older than TRDD-XNZFKX0L and kept by it: a flagged file that is deleted (not moved to .trashcan) is never read again, so its finding is never withdrawn and the CRED-002 issue stays open. Decide in the same change whether a flagged path that no longer exists withdraws its finding (a file moved into .trashcan is read there under its new path and flagged on its own).

Evidence scope of TRDD-XNZFKX0L (that card is archived and frozen, so it is recorded here): NOTE by main-agent@ai-maestro-janitor, scope of acceptance box 1: in the trash tier only the over-the-limit case has its own test (test_a_flagged_trash_file_over_the_read_limit_is_not_withdrawn); a failed or given-up trash read keeps its finding by construction (both tiers share _read_one, and withdrawal reads only read_now). The 5-failed mutation proof ran before the given-up test gained its retries assertion; the give-up-branch mutation ran on the final test file.

## Approval log

- 2026-11-16T11:37:31+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Decisions

2026-11-16 implemented (main agent; brief reports_dev/zfd3kbm3/brief-v2.md, advisor-reviewed): "flagged" is an object, path to the sorted fingerprints of its secrets (Hit.fingerprint, the salted hash of the whole value; one salt per installation). A recorded fingerprint is dropped only when the path was fully scanned this pass (read_now), the pass held that same secret, and no hit for it came back. A fingerprint the pass does not hold is kept. A path not in read_now (failed, cut, too big, given up) only adds the fingerprints of its hits. The path is withdrawn when its list is empty.
Legacy rule (supersedes the body's "withdrawn only by a pass that holds every secret"): a bare-path entry of the old list loads as the sentinel ["unknown"], which is never in a live set, so no read withdraws it; hits add beside it, so the unknown secret is not forgotten; it closes only when the file is gone. The live state on this host held 0 such entries (measured 2026-11-16).
Vanished file (the related gap in the body): a flagged path whose os.lstat raises FileNotFoundError is withdrawn only when no copy exists under <project>/.trashcan/<child>/<path relative to the project>, the path safe-delete builds (scripts/safe_delete.py, lines 281 to 312). Any other OSError, or a trash folder that cannot be listed, keeps the finding. A path outside the project gets no lookup.
Known limits: a rotated secret never returns to a live set, so its finding closes only when the file is gone; one malformed fingerprint list makes _read_cursor start from a fresh state, as any malformed field already did; an older janitor version run on demand would write "flagged" back as a bare-path list, which this version then loads as unknown entries.
