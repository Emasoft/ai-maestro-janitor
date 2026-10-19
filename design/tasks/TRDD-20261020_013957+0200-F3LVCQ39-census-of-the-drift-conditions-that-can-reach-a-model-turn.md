---
trdd-id: F3LVCQ39
title: Census of the drift conditions that can reach a model turn
column: todo
status: tasked
created: 2026-10-20T01:39:57+0200
updated: 2026-10-20T01:39:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: audit
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T01:39:57+0200
---

# Census of the drift conditions that can reach a model turn

THE CENSUS THE PREVENTION CARD DEPENDS ON. TRDD-5CGPEK4V (the repetition-escalation mechanism) cannot be built until it is known which conditions can reach a model turn and which of them NO AGENT CAN ACT ON. That is a general capability and the code does not have it: the agent-actionable vs owner-only distinction exists only for a handful of rotator conditions, while every other detector's line is either printed or dropped by the quiet filter with no classification at all. This card is the census. It is the PREREQUISITE of 5CGPEK4V, and it was minted because 5CGPEK4V's own next action was a measurement its body pointed at and did not contain.

DIMENSION 1 — THE DETECTOR CLASSES, MEASURED from scripts/dispatch.py: 78 detectors are registered in _DETECTORS (dispatch.py:83). They fall into three classes by what the code DOES with their output, and only one of the three is a statement about ACTIONABILITY:
  - 29 ADVISORY: named in _ADVISORY_DETECTORS (dispatch.py:628). Their lines are dropped by the quiet filter and recorded into the findings ledger with sev="LOW" (dispatch.py:857-858), so they do not reach a model turn at all. INVISIBILITY HERE IS A PROPERTY OF THE PLUMBING, NOT OF THE CONDITION — it says nothing about whether the condition is owner-only, and it is not a reason to classify an advisory condition as owner-only. The classification this census produces is a SEPARATE axis, and the sample below is the proof: detectors whose lines DO reach a model turn can equally be owner-only, and the code has no way to tell.
  - 2 CONTROL-PLANE-ONLY: token-usage-anomaly and window-burn-rate, named in _CONTROL_PLANE_ONLY_DETECTORS (dispatch.py:727). Their output goes to a dedicated control log and NO agent text is returned (dispatch.py:730 _exclude_control_plane_output).
  - 47 AGENT-VISIBLE: everything else. These print on EVERY fire the condition holds, and their lines ARE read by a model turn.
NONE of the three classes says anything about whether an AGENT CAN ACT ON THE CONDITION. The classification the census needs is orthogonal to all three, and it does not exist in the code. That is the finding, and it is the reason 5CGPEK4V's design cannot be implemented as a diff until this census lands.

THE FULL TABLE (detector | the class the code gives it):

pr-reconciler | ADVISORY (quiet-filtered -> ledger LOW)
ci-status | AGENT-VISIBLE (prints every fire)
worktree-janitor | ADVISORY (quiet-filtered -> ledger LOW)
trdd-drift | ADVISORY (quiet-filtered -> ledger LOW)
trdd-reminder | ADVISORY (quiet-filtered -> ledger LOW)
report-to-trdd-drift | ADVISORY (quiet-filtered -> ledger LOW)
trdd-state-reconciliation | ADVISORY (quiet-filtered -> ledger LOW)
trdd-cross-card-blindspot | ADVISORY (quiet-filtered -> ledger LOW)
global-chore-blackout | AGENT-VISIBLE (prints every fire)
claimed-chore-stale | AGENT-VISIBLE (prints every fire)
task-pr-mismatch | ADVISORY (quiet-filtered -> ledger LOW)
stale-task | ADVISORY (quiet-filtered -> ledger LOW)
dirty-tree | ADVISORY (quiet-filtered -> ledger LOW)
stale-index-lock | ADVISORY (quiet-filtered -> ledger LOW)
subagent-report | ADVISORY (quiet-filtered -> ledger LOW)
version-update | AGENT-VISIBLE (prints every fire)
trashcan-purge | ADVISORY (quiet-filtered -> ledger LOW)
reports-purge | ADVISORY (quiet-filtered -> ledger LOW)
screenshot-purge | ADVISORY (quiet-filtered -> ledger LOW)
runaway-file-growth | ADVISORY (quiet-filtered -> ledger LOW)
remote-credentials | AGENT-VISIBLE (prints every fire)
stale-stash | ADVISORY (quiet-filtered -> ledger LOW)
github-issues-watch | ADVISORY (quiet-filtered -> ledger LOW)
gh-reply-watch | ADVISORY (quiet-filtered -> ledger LOW)
nested-git-safety | AGENT-VISIBLE (prints every fire)
tracked-ignored | AGENT-VISIBLE (prints every fire)
gitignore-coverage | ADVISORY (quiet-filtered -> ledger LOW)
repo-state | ADVISORY (quiet-filtered -> ledger LOW)
local-plugins-update | AGENT-VISIBLE (prints every fire)
project-plugins-update | AGENT-VISIBLE (prints every fire)
plugin-updates | AGENT-VISIBLE (prints every fire)
mcp-config-drift | AGENT-VISIBLE (prints every fire)
settings-scope-drift | AGENT-VISIBLE (prints every fire)
subagent-scope-drift | AGENT-VISIBLE (prints every fire)
claude-md-scope-drift | AGENT-VISIBLE (prints every fire)
claudemd-migration-queue | ADVISORY (quiet-filtered -> ledger LOW)
cross-scope-reference-drift | AGENT-VISIBLE (prints every fire)
workflow-security | AGENT-VISIBLE (prints every fire)
branch-protection | AGENT-VISIBLE (prints every fire)
fleet-github-config | AGENT-VISIBLE (prints every fire)
package-manager-policy | AGENT-VISIBLE (prints every fire)
ai-context-poisoning | AGENT-VISIBLE (prints every fire)
agent-context-integrity | AGENT-VISIBLE (prints every fire)
mcp-rugpull | AGENT-VISIBLE (prints every fire)
typosquat-watcher | AGENT-VISIBLE (prints every fire)
repo-trust-score | AGENT-VISIBLE (prints every fire)
historical-cache-scan | AGENT-VISIBLE (prints every fire)
binary-magic-scanner | AGENT-VISIBLE (prints every fire)
supply-chain-fingerprints | AGENT-VISIBLE (prints every fire)
provenance-audit | AGENT-VISIBLE (prints every fire)
janitor-self-integrity | AGENT-VISIBLE (prints every fire)
oauth-cookie-reminder | ADVISORY (quiet-filtered -> ledger LOW)
oauth-beacon-refresh | ADVISORY (quiet-filtered -> ledger LOW)
oauth-login-needed | AGENT-VISIBLE (prints every fire)
keychain-health | AGENT-VISIBLE (prints every fire)
memory-librarian | ADVISORY (quiet-filtered -> ledger LOW)
memory-maintenance | AGENT-VISIBLE (prints every fire)
orphaned-memory-maint | AGENT-VISIBLE (prints every fire)
ticket-dispatch | AGENT-VISIBLE (prints every fire)
memgrep-index-health | AGENT-VISIBLE (prints every fire)
memgrep-binary-stale | AGENT-VISIBLE (prints every fire)
project-map-drift | ADVISORY (quiet-filtered -> ledger LOW)
memory-scope-leak | AGENT-VISIBLE (prints every fire)
wikimem-syntax | ADVISORY (quiet-filtered -> ledger LOW)
project-memory-tracked | AGENT-VISIBLE (prints every fire)
reports-gitignore | AGENT-VISIBLE (prints every fire)
design-tracked | AGENT-VISIBLE (prints every fire)
memorize-nudge | ADVISORY (quiet-filtered -> ledger LOW)
peer-freeze-recovery | AGENT-VISIBLE (prints every fire)
orphaned-resume-flag | AGENT-VISIBLE (prints every fire)
hook-timeout-scan | AGENT-VISIBLE (prints every fire)
why-in-commits | ADVISORY (quiet-filtered -> ledger LOW)
janitor-install-scope | AGENT-VISIBLE (prints every fire)
window-burn-rate | CONTROL-PLANE-ONLY (-> control log, no agent text)
token-usage-anomaly | CONTROL-PLANE-ONLY (-> control log, no agent text)
model-fallback | AGENT-VISIBLE (prints every fire)
host-load | AGENT-VISIBLE (prints every fire)
system-daemon-runaway | AGENT-VISIBLE (prints every fire)

DIMENSION 2 — THE ACTIONABILITY CLASSIFICATION, AND WHY THE SAMPLE BELOW MATTERS. Asking "can an agent act on this?" of each of the 47 agent-visible detectors is the census's real work, and the first sample shows why it cannot be inferred from the code: several of these detectors EMIT the answer in their own line text and NOTHING in the code acts on it. Sampled from the agent-visible set:
  - ticket-dispatch prints "[ticket] {n} janitor proposal(s) await YOUR approval — nothing is fixed until one is approved" and "[ticket] {id} NEEDS A HUMAN after {attempts} attempts". The words NEEDS A HUMAN are in the LINE, and the LINE is what the agent reads; there is no field, set or predicate anywhere that tells the dispatcher the condition is owner-only.
  - oauth-login-needed prints "{n} account(s) need a one-time login" and "rotation has been IMPOSSIBLE for {h}h" — a credential the agent cannot supply.
  - remote-credentials prints "URGENT: git remote {name} embeds a secret in its URL" — the fix needs a human to rotate the credential, and possibly to decide the remote is being replaced.
  - host-load prints "HOST-001 load average {n} on {c} cores" — the remedy is the owner's (wait, or kill something).
So the OWNER-ONLY class is real, it is populated, and the code does not know about it. The words are in the prose; the classification is not in the data.

THE MEASURED REPETITION, so the census's stakes are numbers and not adjectives. The alert file's first_seen for the two live conditions is 2026-10-18 14:18 and 2026-10-19 16:00; this project's .janitor/logs/heartbeat-fires.log records 103 fires in the 34.8 h since the first of them, i.e. 2.96 fires/h, so about 71 identical drift lines a day at the OBSERVED rate. The 5-minute cadence ceiling is 288. The gap between those two numbers is the cost of the repetition on this project alone.

WHAT THE CENSUS MUST DELIVER, and what it must NOT decide. It must deliver, per detector and then per distinct CONDITION (a detector can raise several): the condition's name, the exact line prefix the agent sees, whether the condition repeats while unchanged, and a CLASSIFICATION into AGENT-ACTIONABLE / OWNER-ONLY / UNCLASSIFIED, with the reason. It must NOT decide the escalation mechanism — that is 5CGPEK4V's job, and it needs this census as its input, not as its output. THE CLASSIFICATION MUST FAIL OPEN: a condition with no recorded classification is AGENT-ACTIONABLE, because silence toward an unclassified condition is how a real problem gets hidden.

ACCEPTANCE. (1) Every one of the 78 registered detectors is listed with its class, and every distinct CONDITION reachable by the 47 agent-visible ones is listed with its line prefix, its repeat-while-unchanged behaviour, and its actionability classification with a reason. (2) The classification is recorded AS DATA in the code, not only in prose — a named set or a per-condition field that the dispatcher can read, so the escalation can consult it mechanically. (3) Every owner-only condition names the owner's remedy. (4) The unclassified bucket is explicitly non-empty or explicitly empty, with the reason either way. (5) A test asserts that a condition added without a classification is treated as agent-actionable (fail open).

NEXT ACTION: classify the 47 agent-visible detectors' conditions one at a time, reading each detector's condition text and the state it fires on, and record the result in the census table above. This is mechanical and can be done in batches by a worker with the file set named. When the table is complete, TRDD-5CGPEK4V's design can be written against real numbers, and its "THE POPULATION IS NOT YET CENSUSED" paragraph can be replaced by them.


## Approval log

- 2026-10-20T01:39:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
