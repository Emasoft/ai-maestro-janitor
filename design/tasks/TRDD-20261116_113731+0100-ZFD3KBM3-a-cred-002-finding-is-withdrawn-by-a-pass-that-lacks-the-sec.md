---
trdd-id: ZFD3KBM3
title: A CRED-002 finding is withdrawn by a pass that lacks the secret behind it
column: todo
status: tasked
created: 2026-11-16T11:37:31+0100
updated: 2026-11-16T11:37:31+0100
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

## Approval log

- 2026-11-16T11:37:31+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
