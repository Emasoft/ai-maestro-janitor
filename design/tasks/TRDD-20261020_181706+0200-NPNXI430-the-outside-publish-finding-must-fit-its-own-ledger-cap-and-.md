---
trdd-id: NPNXI430
title: The outside-publish finding must fit its own ledger cap and stay findable
column: todo
status: tasked
created: 2026-10-20T18:17:06+0200
updated: 2026-10-24T05:16:36+0200
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
2026-10-24T05:20+0200 — VERIFY against e01c13da (read-only worker, reports/board/20261024_051252+0200-NPNXI430-verify.md; the main session re-read repo-state.py:136-185, 836-850, 920-942): H-1, H-2, M-1, M-2 and L-2 are fixed; 44 tests in tests/test_repo_state.py pass. STILL OPEN: L-1, the stdout line at repo-state.py:844 still says 'are NOT made through publish.py' (an authorship claim) while the ledger now reads 'N commit(s) on BRANCH since release TAG: <subjects>'; L-3, the state.log_line calls at :927 and :940 sit outside any try/except; acceptance (3) has no long-tag test case; acceptance (4), the comment near :848 that says the ledger holds the subjects 'in full' is stale (each is cut to 40 characters); the 'all five single-guard mutations survive' claim was not re-run. _ledger_msg cuts the tag at 40 characters, which its own comment frames as bounding, not as never-truncated; real tags are far shorter. Card stays in todo for those items.
2026-10-24T05:35+0200 — CORRECTION to the 05:20 line (review of a6f9612b; the main session re-read the code): (a) the stale comment is at repo-state.py:857, not :848, and it says the ledger msg 'holds them in full'; it is stale, because _ledger_msg cuts each subject to 40 characters. (b) '44 tests pass' was reported by the worker; the main session did not run the tests. (c) the tag cut is OPEN, not benign: the _ledger_msg docstring says the COUNT and the TAG 'are never the parts at risk', but the code does tag[:_TAG_MAX] with _TAG_MAX 40, so the docstring and the code contradict each other. (d) H-2 is shown fixed in the detector comment (:936); in tests/test_repo_state.py the 'unbounded' lines (292, 342, 1165, 1185) are about branch names, subjects or repeats, not about the log, so no false copy was found there; the card's own copy was not edited. (e) L-2 is fixed: the subject log write (:940) sits inside the 'if line:' block after dedupe.emit_once, so it runs once per episode. (f) L-1 has shifted: the ledger msg no longer makes the reachability claim the card called accurate, so the fix is to make the stdout line describe the measurement (commits since the release TAG that are in no release) without claiming who made them.
2026-10-24T05:50+0200 — SECOND CORRECTION (review of b8f414d8; read by the main session): (d) H-2 is PARTIAL, not fixed: the detector comment (:936) is fixed, the card's own copy was not edited, and the test file was checked only by a grep for the word 'unbounded' (line 1185, read in full at 1183-1186, is about a repeat loop, not the log). (e) the subject log write (:940) is inside the 'if line:' gate of dedupe.emit_once, whose key at :814 joins the word outside, the tag, the count and the day number (emit_once returns the message the first time a key is seen, scripts/lib/dedupe.py:65-66), so the subjects are logged once per tag, count and day, not once per episode; L-2's ask (once per tag and count) is met only up to the daily bucket. (f) the stdout fix must describe the whole measurement, including the version-bump exclusion, with no authorship claim. (c) the tag mismatch can be fixed in the docstring rather than the code: the inline comment already describes the 40-character bound.
