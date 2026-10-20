---
trdd-id: NPNXI430
title: The outside-publish finding must fit its own ledger cap and stay findable
column: todo
status: tasked
created: 2026-10-20T18:17:06+0200
updated: 2026-10-20T18:17:06+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T18:17:06+0200
---

# The outside-publish finding must fit its own ledger cap and stay findable

An eighth adversarial review of the outside-publish finding in scripts/detectors/repo-state.py found FOUR substantive defects, all CONFIRMED by measurement. This card owns their fix.

H-1 THE LEDGER msg STILL OVERFLOWS ITS 120-CHAR CAP FOR A LONG BRANCH NAME. The msg is 'N commit(s) on BRANCH since release TAG are not in any release reachable from BRANCH'. The branch is REPEATED and is repo-controlled and unbounded (git rev-parse --abbrev-ref HEAD, no length bound). MEASURED: with branch='feature/really-long-branch-name-for-some-clients' and tag='v3.8.11' the message is 174 characters, 54 over the cap, cut mid-word again. EVERY fixture in the suite uses a short branch name (main, side, feature, hotfix), so the overflow is invisible to the suite - the same 'a test that cannot fail against its defect' shape this card has learned nine times. The branch must be bounded EXPLICITLY (a hard slice) so the total is provably under 120.

H-2 'THE LOG IS UNBOUNDED' IS FALSE in three places. state.log_line calls rotate_log_if_big(name) with max_bytes = 1_048_576 on every append, and scripts/dispatch.py prunes .log and .log.1 by age. The log is ROTATED at 1 MiB and AGE-PRUNED. The false claim is in the detector comment, the test comment, and the card. The 'unscanned by the urgency override' half IS true (grep finds no reader of repo-state.log).

M-1 'COMMIT SUBJECTS RUN TO 168 CHARACTERS (p50 110)' IS FALSE AND UNTRACEABLE. MEASURED over the repo's full history (git log --format=%s, 5795 commits): min 21, p50 90, p99 265, max 643, and 950 of 5795 subjects exceed the 120-char cap. The true and stronger statement is the 950/5795 figure, which is what the comment is actually arguing. The 168/p50-110 figure appears in three places in code and tests and nowhere in the card, so the card and the code disagree about what the code says.

M-2 THE SUBJECTS WERE MOVED OUT OF THE ONLY DOCUMENTED RECOVERY PATH. /janitor-findings - the one user-facing way to browse findings - reads ONLY <project>/.janitor/state/findings-ledger.ndjsonl. Nothing in the codebase reads .janitor/logs/repo-state.log. So the owner sees the count and the branch but not the subjects, and must know to hand-read a log no command, skill or doc mentions. The test's own DOCSTRING still says 'They go to the findings LEDGER' and 'the ledger msg field (cap 120) holds them in full' - both now false, so the test and its stated contract disagree. THE REVIEW'S CENTRAL OBJECTION, and it is right: the subjects belong in the ledger, with an EXPLICIT LENGTH BUDGET (a subject is unbounded - max 643 chars - so a subject can never fit a 120-char field, which is why each subject must be truncated to a fixed width and the COUNT and TAG kept exact), not exiled to a log nobody reads. A finding whose detail is in an unreadable place is a finding nobody can act on.

L-1 THE STDOUT LINE AND THE LEDGER msg NOW DESCRIBE THE MEASUREMENT DIFFERENTLY. stdout says 'are NOT made through publish.py' (a claim about AUTHORSHIP); the ledger says 'are not in any release reachable from BRANCH' (a claim about REACHABILITY). The ledger's version is the accurate one - this is the same authorship-vs-measurement distinction rounds 4 and 5 settled for this line's parenthetical, reappearing because the two surfaces diverged.

L-2 THE SUBJECTS ARE WRITTEN TO THE LOG ON EVERY FIRE. The file is bounded by size but the WRITE is per-fire, and combined with M-2 a rotated-away subject list is unrecoverable. Consider once-per-(tag,count) episode.

L-3 THE NEW state.log_line CALL IS OUTSIDE ANY try/except. It matches the file's local convention and the detector runs as a SUBPROCESS under dispatch's _run_detector, so S6.1 holds at that level, but the detector's stdout would be lost if the log dir were unwritable.

ACCEPTANCE: (1) the ledger msg is provably under 120 characters for ANY branch name and ANY tag, with the branch explicitly bounded; (2) the subjects are recoverable from the LEDGER - the channel /janitor-findings browses - each subject truncated to a stated fixed width, with the count and the tag exact; (3) a test pins the msg length under a LONG branch name and a long tag, and that test FAILS on the current form; (4) the 'unbounded' and '168/p50 110' claims are corrected in ALL their copies (detector, test, card) and the file is SWEPT for the other copies of each; (5) the test's docstring matches what the test now asserts; (6) the stdout line and the ledger msg describe the SAME measurement; (7) every new claim about a number is MEASURED in the session that writes it, and the measurement is quoted with its scope (full history vs last 300 commits).

MUTATION-VERIFY each new assertion: restore the buggy form and confirm the test fails ON THE LENGTH or ON THE SURVIVAL, not merely on the rule staying silent.

## Approval log

- 2026-10-20T18:17:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
