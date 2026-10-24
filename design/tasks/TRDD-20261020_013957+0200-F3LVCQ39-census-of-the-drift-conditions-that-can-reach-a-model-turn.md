---
trdd-id: F3LVCQ39
title: Census of the drift conditions that can reach a model turn
column: dev
status: tasked
created: 2026-10-20T01:39:57+0200
updated: 2026-10-24T13:10:20+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-24

CENSUS MEASURED, NOT YET MERGED. Four read-only batch reports, a dedupe-lifetime report and an open-checks report are in gitignored reports/board/20261024_*-F3LVCQ39-*.md (evidence only). Each was reviewed; none can be merged as written, because repeat rates were read per detector and classes were assigned by whether the agent tools can reach the file. Markers: ✓ = read in the code this session; ? = from a worker report or a partial read.

CORRECTIONS TO THE BODY (the body below is superseded where it disagrees):
- ✓ "47 AGENT-VISIBLE ... print on EVERY fire" is false. Every detector stdout passes through `_dedupe_drift_text` (scripts/dispatch.py:1191, called at :1570 and :1591). For a detector not in `_SELF_DEDUPING_DETECTORS` (:1161, five names), a line already printed today is suppressed; the key is detector, local day, and the line with elapsed-time digits blanked (`_dedupe_drift_line`, `_drift_dedupe_key`). So an identical line reaches the agent at most once per local day; a line whose count or percentage changes prints again, and `_dedupe_drift_text` adds its own summary line when the suppressed count rises.
- ✓ Only 45 of the 47 reach stdout: `_exclude_control_plane_output` (dispatch.py:889) also blanks model-fallback and oauth-login-needed.
- ✓ "ADVISORY ... do not reach a model turn at all" is false. Quiet mode is the default (`_heartbeat_is_quiet`, dispatch.py:876; off only when CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE is truthy). In quiet mode `_quiet_filter` (:977) still prints an advisory line that matches `_URGENT_LINE_RE` and not `_NEGATED_SEVERITY_RE`, unless the detector is in `_REMOTE_TEXT_DETECTORS` or `_OTHER_ACTOR_DETECTORS`. Dropped lines become LOW ADVISORY-* findings-ledger entries (observed in this session's SessionStart output; the record() call was not read) that the SessionStart hook can inject: `surface_block` (findings_ledger.py:579) shows at most 10 lines and 1024 bytes, severity first, so LOW entries may stay folded.
- The line numbers in the body are stale: `_ADVISORY_DETECTORS` is now at dispatch.py:785 (?), `_CONTROL_PLANE_ONLY_DETECTORS` at :884 and `_exclude_control_plane_output` at :889 (✓); the body :857-858 citation for the LOW ledger record is stale and was not re-located.
- ? The body figure "about 71 identical drift lines a day" is fires per day (103 fires in 34.8 h, 2.96 an hour) counted as one identical line per fire, which the daily dedupe does not allow on the stdout path; which channel those two conditions used was not checked. The repetition cost must be re-measured as lines delivered.
- The body sample for oauth-login-needed is false: ? a dispatch.py comment near `_SELF_DEDUPING_DETECTORS` and the batch-3 report say the detector prints nothing (TRDD-1J9B7MWO), and ✓ its stdout is excluded anyway (dispatch.py:889). ? The host-load sample calls the remedy owner-only; the census row puts it in UNCLASSIFIED, decided by whether the load comes from processes the agent started.
- The acceptance items still say three classes and "the 47 agent-visible ones"; read them as the four classes and channels A to C below until they are amended; the per-condition line prefix and repeat behaviour in item (1) are to be recorded as the agent sees them.

SCOPE, stated as channels into a model turn. (A) stdout of the 45 detectors after the dispatcher pipeline: censused; the worker parse finds all 47 names in the four batches (?), but whether every print site of each detector has a row is not established, and the batch-1 review corrections are not applied yet. (B) the dispatcher own prints (a candidate list of about 15 sites from a grep, not yet read for stream or gating (?), including the suppressed-count summary line) and the advisory detectors urgent-word lines: not yet censused. (C) the SessionStart findings surface: not yet censused. (D) detector stderr: ? `_run_detector` does not capture it (the stderr argument of its subprocess.run call was not read), so it goes to the dispatcher stderr; whether that reaches the Bash tool output is not verified. (E) other hook injections (UserPromptSubmit memory notes, the post-compaction STATE injection, PreToolUse and PostToolUse messages): out of scope.

CLASS RULES, decided from the reviews. Four classes: AGENT-ACTIONABLE, OWNER-ONLY, INFORMATIONAL (no action by anyone; HARNESS tickets that say the janitor will repair it itself belong here), UNCLASSIFIED (names its decider, and is treated as agent-actionable under the fail-open rule). A class answers whether the session agent is the right decider, not whether its tools can reach the file: injection found in the agent own instruction files and a verified exfiltration candidate are never AGENT-ACTIONABLE. All PROJECT-proposal ticket lines take one class, set by one ruling on who may approve. Classification is per line pattern, not per detector, and cadence is recorded as the agent sees it.

SPUN OFF, one card each, not yet minted: (1) MODEL-FALLBACK findings can reach SessionStart despite the control-plane exclusion: model-fallback.py:323 records them (sev HIGH when the switch is not confirmed), and `surface_block` filters only NEVER_SURFACE_CODES, which holds only WINDOW-BURN (findings_ledger.py:95) (✓); that the ledger `record()` writes is the one SessionStart reads is ?. (2) ✓ The dispatcher daily dedupe silences the ticket-dispatch NEEDS A HUMAN line, which ticket-dispatch.py:155 says must surface every fire ("marked Nd ago" is blanked by the elapsed-time rule). (3) ✓ Two prose descriptions disagree on who approves a proposal: a rationale comment at issue_catalog.py:88 says only a human; the proposal template at ticket_proposal.py:315 says a human or the main Claude. (4) ✓ `_surface_unmaintainable` (memory-maintenance.py:546) has no caller. WITHDRAWN: the model-fallback rotate line on stdout (✓ excluded) and BRPROT-002 (✓ `linear_history_present` returns True only when a ruleset requires linear history, which matches the owner ruling; ? the detector raises only on True).

NEXT ACTION (superseded by the 10:58 line below): channels B and C are measured; the merged census and the data-in-code proposal follow the defect cards.

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

ACCEPTANCE. (1) Every one of the 78 registered detectors is listed with its class, and every distinct CONDITION reachable by the 47 agent-visible ones is listed with its line prefix, its repeat-while-unchanged behaviour, and its actionability classification with a reason. (2) The classification is recorded AS DATA in the code, not only in prose — a named set or a per-condition field that the dispatcher can read, so the escalation can consult it mechanically. (3) Every owner-only condition names the owner's remedy. (4) The unclassified bucket is explicitly non-empty or explicitly empty, with the reason either way. (5) A test asserts that a condition added without a classification is treated as agent-actionable (fail open). (6) The classification surface is a per-condition data structure the dispatcher reads, so a detector added after this census declares its own classification when it is added; one that is added without a classification is caught by the fail-open rule in (5) and surfaces as agent-actionable rather than silently unclassified.

NEXT ACTION: classify the 47 agent-visible detectors' conditions one at a time, reading each detector's condition text and the state it fires on, and record the result in the census table above. This is mechanical and can be done in batches by a worker with the file set named. When the table is complete, TRDD-5CGPEK4V's design can be written against real numbers, and its "THE POPULATION IS NOT YET CENSUSED" paragraph can be replaced by them.
2026-10-24 10:58 — CHANNELS B AND C MEASURED, REPORT NOT YET REVIEWED: reports/board/20261024_105742+0200-F3LVCQ39-census-channels-b-c.md (gitignored; worker count: 27 channel-B rows, 42 channel-C rows). Findings: (5) ✓ scripts/guard/branch_protection_apply.py runs with capture_output=False (dispatch.py:3574), so its stdout is inherited and reaches heartbeat stdout with no defang, quiet filter or daily dedupe. (6) ✓ _quiet_filter (called inside _dedupe_drift_text at :1590) records every dropped advisory line as a LOW ADVISORY-<DETECTOR> ledger row (:1012-1016) on every run; record() does not dedupe the row, per its docstring (findings_ledger.py:278-281). (7) ✓ the two iTerm alarm ledger rows (dispatch.py:3107-3110, :3395-3398) pass no actor argument, so they default to agent and surface at SessionStart without the HUMAN-ONLY prefix the stdout line carries (render_line adds the prefix only when actor is human, findings_ledger.py:244-245); the :3390-3394 comment about not duplicating into a push refers to the notify callback, not the SessionStart surface. (8) ? per the worker, record() with project_dir=None writes the ledger that surface_block(None) reads; which project the daemon's project_dir=None writes land in was not traced. NEXT: review the channel B and C report, then write the merged census.
2026-10-24 11:42 — DEFECT CARDS MINTED, all todo: (1) TRDD-B26WBXDW model-fallback ledger rows; (2) TRDD-A56E22AL ticket-dispatch NEEDS A HUMAN silenced by the daily dedupe; (3) TRDD-OCGIG3N8 who may approve a fix proposal (a proposal awaiting the owner's ruling; the PROJECT-proposal ticket lines stay UNCLASSIFIED until it is ruled); (4) TRDD-RXZHAD4B _surface_unmaintainable never called; (5) TRDD-4DP942BO branch_protection_apply output unfiltered; (6) TRDD-7WJPSM8W advisory ledger row on every run; (7) TRDD-HCPGY099 iTerm ledger rows lack the HUMAN-ONLY prefix.
2026-10-24 12:09 — CHANNEL B AND C REPORT REVIEWED by a second worker: reports/board/20261024_120857+0200-F3LVCQ39-channels-b-c-review.md (gitignored). Per that review (?, not re-read here): line numbers, stdout streams and summary counts check out in the rows it sampled, and it found no missed stdout print site in dispatch.py or the modules it calls; row C38 (a blanket AGENT-ACTIONABLE row covering injection and compromise detectors) and row C37 must be reclassified and row C1's membership fixed before merging; memory_dispatch_claim.expire_stale_claims prints MEMPASS lines through detector stdout, a channel A lead to check against the batch rows. NEXT: write the merged census (channels A to C) with every review correction applied, then the data-in-code proposal.
2026-10-24 12:49 — MERGED CENSUS WRITTEN, NOT YET REVIEWED: reports/board/20261024_124700+0200-F3LVCQ39-merged-census.md (gitignored). 196 rows: channel A 113, B 28, C 55; AGENT-ACTIONABLE 47, OWNER-ONLY 44, INFORMATIONAL 40, UNCLASSIFIED 65 (the total, the per-channel split and the class counts recounted here by grep on the row ids, all matching the worker). Only 10 rows were re-read in code by the worker; the rest carry a report's evidence (?). Spot check here: every row of agent-context-integrity, the exfil candidates, ai-context-poisoning, typosquat-watcher, binary-magic-scanner and repo-trust-score is OWNER-ONLY or UNCLASSIFIED except A51, whose pattern is the CAN-write capability line; A52 carries the AT INSTALL TIME pattern. NEXT: an adversarial review of the merged census, then the data-in-code proposal (acceptance items 2, 5, 6).
2026-10-24 12:54 — MERGED CENSUS REVIEWED by a worker that read about 40 rows against the code: reports/board/20261024_125145+0200-F3LVCQ39-merged-census-review.md (gitignored). Re-read here ✓: B16 writes an ASCII hyphen where HUMAN_ONLY_DIRECTIVE has an em dash (scripts/lib/findings_ledger.py:65-68); the B10 pattern worker\(s\) cannot match the f-string at scripts/dispatch.py:2026-2029; the A51 end anchor cannot match because the headline continues past file(s) (scripts/detectors/ai-context-poisoning.py:364-369); a ledger code is cut to 24 characters when recorded and when rendered (findings_ledger.py:315 and :235), so a channel-C row citing a longer code cannot match (which rows do is the review's list); C42 cites line 635 of a 624-line file. Per the review (?, not re-read here): B17 and B18 share the B16 hyphen defect; the A51 class AGENT-ACTIONABLE is wrong (the review says the line names no remedy, but the headline read here ends with "The realistic control is guarding the INVOCATION", so whether that control is the agent's or the owner's is still open); the A21 and A22 patterns are wrong; about 40 patterns write alternation as the word or; 5 cells are prose; 19 UNCLASSIFIED rows name a property of the line instead of a decider; the classes of A72, A91 and A92 are arguable. The review also argues (?) that a table of line patterns would hold each message a second time and drift from it; under the fail-open rule an unmatched line becomes AGENT-ACTIONABLE, so a drift is visible but wrong, and a test running each detector's real output against the table could catch it. NEXT: the data-in-code proposal for acceptance items 2, 5 and 6 decides where the class lives and how it reaches the dispatcher, under the frozen ledger line shape and the detector transport (✓ scripts/dispatch.py:1551-1557: each detector runs as a subprocess whose stdout is piped and read and whose stderr is not captured; ✓ scripts/lib/tickets.py:365-377: tickets.EMIT_ENV only switches on an in-band ticket-key marker line inside stdout, so it is not a second channel; ✓ design/specs/issue-codes.toml holds 90 [[issue]] entries with severity, kind and fix fields, and scripts/dispatch.py:1025-1045 already classifies a line by the first registered code in it; per a measurement fork (?), detectors also write the findings ledger directly in 9 files and through raise_issue in 14); row corrections to the gitignored census wait for that decision, because the proposal decides what form the corrected rows must take.
2026-10-24 13:10 — CLASS-SURFACE PROPOSAL: TWO REVIEW ROUNDS SPENT, GOES TO THE OWNER. Revision 1 (a new registry keyed by source name plus a line token) and revision 2 (a class field on design/specs/issue-codes.toml plus [[source]] defaults) were each measured and adversarially reviewed; both were found not ready. Re-read here ✓: scripts/build_issue_codes.py:40 writes a fixed 12-field tuple, so a new class field is silently dropped without generator changes; DEP-001 has emitter janitor:supply-chain (issue-codes.toml:403) but is raised by scripts/detectors/supply-chain-fingerprints.py, so an emitter-equals-printer rule would drop it; a raise_issue line is prefixed [ticket], not with the detector name (scripts/lib/issue_catalog.py:377); each entry's kind already routes a code to a domain (scripts/lib/tickets.py:19). Per the measurement (?, not re-read here): 20 of the 46 channel-A detectors in the census carry more than one class; 16 registered codes have a non-detector emitter; continuation lines carry no prefix and the dedupe works line by line (scripts/dispatch.py:1191-1225), so a class must be fixed per raw output block before the filters; ADVISORY ledger rows reach SessionStart through surface_block (hooks/on-session-start.py:1460). RECOMMENDED REVISION 3, not yet reviewed: key on the dispatcher's own detector-name argument, never on a line prefix or an emitter; assign the class per raw output block before the filters; read it from a per-condition table keyed by (detector, registered code or none), with a test that fails when a ticket code's class disagrees with its kind's domain; every detector whose output or ledger rows can reach a turn (advisory ones included) needs an explicit entry, and the dispatcher's own default is AGENT-ACTIONABLE. OPEN FOR THE OWNER: (1) a separate table (recommended) or a field on issue-codes.toml; (2) register new codes for the 20 multi-class detectors now (each changed line shows once more on the day it ships), or leave them on their fail-open default until TRDD-5CGPEK4V needs finer classes.


## Approval log

- 2026-10-20T01:39:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-24T10:44:03+0200 — column → dev by main-agent@ai-maestro-janitor. census measured; merging and channels B and C in progress
- 2026-10-24T10:44:03+0200 — moved todo -> dev by main-agent@ai-maestro-janitor: census measured; merging and channels B and C in progress.
