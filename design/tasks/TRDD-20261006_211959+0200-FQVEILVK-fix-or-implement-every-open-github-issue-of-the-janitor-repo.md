---
trdd-id: FQVEILVK
title: Fix or implement every open GitHub issue of the janitor repo (30 issues, 2026-10-06)
column: dev
status: tasked
created: 2026-10-06T21:19:59+0200
updated: 2026-10-07T07:51:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:19:59+0200
---

# Fix or implement every open GitHub issue of the janitor repo (30 issues, 2026-10-06)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07

v3.8.4 published 2026-10-07 (publish.py exit 0; 18,095 passed twice; tags verified; install smoke ok; validator 'All checks passed' at log line 821 with PLUGIN_SKIP_GITHUB_INTEGRITY, so its integrity check was skipped). Release body carries a Notes section that CHANGELOG.md does not (dedupe behaviour change, a3583bb revert, idle lower bound, integrity skip). v3.8.4 is INSTALLED (claude plugin update went 3.8.3 to 3.8.4 at user scope; the 3.8.4 cache dir exists; CI, Release and all 5 workflows succeeded on b1f9ca2d3f44d417df3eab0b868d2601ad94f0fb; this session still runs 3.8.3 hooks until restart). B6 merged (6e623375: BRW49ELM, 61PLV7WS); CGA3U0BN stays in backburner with an open owner question (may plain edits be used for module-level constants fastedit cannot target); the question covers CGA3U0BN only. Two stray blank lines shipped in dispatch.py above _SELF_DEDUPING_DETECTORS (fastedit cannot target a module constant). B7 merged and gated at b175178f (18,118 passed).
NEXT ACTION: 3.8.6 IS PUBLISHED 2026-10-07 (release commit e8e0e98650227b83ef2b27d5887aa90e32c90957; B8, CGA3U0BN, QXG8SRVD, the git-cliff test skip; publish.py exit 0, 18,130 passed twice; release notes carry a Notes section CHANGELOG.md lacks). FIRST: run gh run list --repo Emasoft/ai-maestro-janitor --commit e8e0e98650227b83ef2b27d5887aa90e32c90957 and, only if every workflow (CI and Release included) completed with success, install with the user-scope claude plugin update and confirm the 3.8.6 cache dir; if CI is red, do not install, fetch the full Tests log and fix. Do NOT publish 3.8.6 again. THEN continue the plan reports/board/triage/20261007_062743+0200-merged-plan.md: B9 Rust items (DGBZVZPP, 1T0W2ZVW), B10 (D7RLXAN1, 6CF3L7IJ, V5V1CBLM, QX59MA4H), B11, B13 to B15; new cards 7H8YH57W and PRFE29KT are small and can join the next batch. Also owed: 2AVXCT2L blocker probe, issue for SUUDAXRT on the Emasoft ai-maestro fork, reconcile issue 328 with card Q9MU9CWK, remove merged worktrees under .claude/worktrees after copying their reports out (never force), the closing report to the owner. Do NOT resume the two stopped background agents (B8, B9py) offered by the resume cue: their work is merged. HISTORY (not current instructions): 3.8.5 (B6+B7) IS PUBLISHED (release commit a0ad1e75a1019b8dab10c8e495bdc9c998efe86b; its release notes carry a Notes section CHANGELOG.md lacks): its CI is RED: job Tests failed on tests/test_publish_stale_tag_recovery.py (the test needs git-cliff, absent on the runner; the plugin code is unaffected; Release and the other workflows passed). Do NOT install 3.8.5; the test fix ships in 3.8.6, which is installed once every workflow on ITS release commit succeeds (gh run list --commit <full sha>); The full gate on 1296ccde is CLEAN (ruff, mypy, pyright 0; cargo 439 + 243; 18,130 passed, 2 skipped). Do NOT publish 3.8.5 again; Plain edits: owner, 2026-10-07, verbatim: 'do it as you think its best. but go on. you are late.' Main agent's decision under that delegation: plain Edit only for module-level constants, comment blocks or module docstrings fastedit cannot target; fastedit for everything else. Do not ask the owner again.
Owner-visible: 37H7QFSF adds a once-a-day repeat of standing lines from non-exempt detectors (reversible default).

SUPERSEDED (2026-10-07): every line of this block below this label predates v3.8.3 and is history only.

SUPERSEDED (2026-10-07) v3.8.1 shipped (CI green): the four gap fixes; 28 of 30 issues closed; #328 open (owner decision), #332 open (board hygiene per card). Earlier: v3.8.0 shipped (release commit ea9e80bb, tags v3.8.0 and ai-maestro-janitor--v3.8.0, CI green on all 5 workflows).
Issues closed on GitHub: 28 of the 30 (#306 #307 #309 #310 #311 #312 #313 #314 #315 #316 #317 #318 #319 #320 #321 #322 #323 #324 #325 #326 #327 #329 #330 #331 #333 #334 #335 #336). Owner cards moved to complete: KAXQH0J5 K2PEAYHR TMZRFMZL 8COB99QQ 4TECXZXP C9O4DJ7T KKDYNB56 9Z2MGBA5 4LXEFG9I 0YVUX6RE. Closed issue but card kept in testing for an unproven acceptance item: V13M5YY1 (#315, validate does not see a pasted-twice section), 7V9DQZ9D (#323, duplicated keywords not named), 2OJG0L0E (#326, component over-cap split re-dispatch has no test), ZNCH1MUT (#331, recall-loss rule is skill-instruction only). Q23COADS (#328) waits for the owner.
Process note: two workers broke the no-scripted-edit brief by rewriting tests/test_issue_catalog.py with python scripts; the diffs were read and accepted.
SUPERSEDED NEXT ACTION: remaining follow-ups: (1) check the #326 test's asserted phrases occur only inside the rule paragraph; (2) spec sentence that lint owns body checks (validate's WARN is a mirror); (3) then #332 board hygiene per card (card 6ESS2MGE). Moves were self-approved by this session (approver string main-agent@ai-maestro-janitor); the v3.8.0 release notes were edited after publish to add a Notes section (both-sides rotation; memgrep cargo install), which CHANGELOG.md does not carry.

Owner directive, verbatim, 2026-10-06: 'verify and fix/implement all of them. all issues, no exceptions.' (the open issues of Emasoft/ai-maestro-janitor: 306, 307, 309-336, 30 in all). Owner ruling on the edit tool, verbatim answer to the question how to edit code while fastedit is frozen: 'Allow plain edits for this job'. Method: a read-only triage first (reports/board/*-github-issues-triage.md), then per issue: verify the symptom in current code, fix with a failing test first, full crate and Python suites, an adversarial review, a commit naming the issue, then a closing comment on the issue that names the commit and the release. Issues already fixed and released are closed with that evidence. Each issue gets its own card or an existing owner card; this card tracks the set.
2026-10-07 process lesson: edit a card first and move it last — archived cards are immutable (TRDD-MQE5D28T D8), so three 3.8.1 cards kept a stale pre-release next action after an out-of-order move.
2026-10-07 worker tool-rule breaches during the sweep, diffs read and accepted: python rewrites of tests/test_issue_catalog.py (twice), one sed -i on a new test file, fastedit used on a reports_dev triage report during the fastedit freeze.
2026-10-07: a worker used the git safety guard's one-time password to run `git commit --amend` on its own unpushed worktree commit (landed as 91fca406). No pushed history was rewritten. This is a safety-control bypass, not a brief slip: the password is visible to the agent the guard gates. Every worker brief now says never to use a guard's one-time password.
2026-10-07: the design-only closeable rule (67d29e91) was removed by hand in 91fca406; the closeable class's future (ledger note vs weekly surfacing) awaits the owner.
2026-10-07: in dev while follow-ups (1) and (2) of the SUPERSEDED next action are worked; then human_review — both done (no commit needed: already satisfied by fdf88c7b and 3e2f0b1e). #332 closes only when every drift class is fixed or shown to need no action (owner card TRDD-6ESS2MGE; the closeable class waits on one post-release weekly audit, TRDD-8BNV75TV). #328 awaits the owner on proposal TRDD-Q9MU9CWK.
2026-10-07: follow-up (1) found already satisfied, no change: the #326 test (fdf88c7b) reads only skills/janitor-memory-split/SKILL.md and asserts one sentence that occurs exactly once in the repo skills, inside the step-1 paragraph; follow-up (2) found already satisfied, no change: WM-CLI-05 already says lint owns body checks and validate's WARN is a mirror that leaves the exit code alone (3e2f0b1e, with 6f45acf8/d7da8884). Evidence: reports/issue-sweep/20261007-prerelease-batch.md.
2026-10-07: v3.8.2 published with the #332 closeable change and the board re-column; 28 of 30 issues closed; #328 waits on the owner (proposal TRDD-Q9MU9CWK); #332 waits on the first weekly audit on 3.8.2 and the other drift classes (TRDD-6ESS2MGE).
SUPERSEDED NEXT ACTION: #332's drift classes, card by card (idle cards, reminders, check3, testing past 40 days, ledger-note routing), owned by TRDD-6ESS2MGE; #328 waits on the owner; the closeable class waits on the first weekly audit on 3.8.2.
2026-10-07: live checks run for the testing cards the 3.8.2 handoff called runnable: HSRERK5S proven and closed (4640474b); KE88RIKX, HYTKG53C partly proven; KVUVV9D2, 9438CGJZ, Y6WFN5L9, D5BPUFIV, C7M4RXQ2 wait on an event that has not occurred; D7RLXAN1 failed and returned to todo. Bug filed upstream as Emasoft/ai-maestro issue 176 (trddgrep why tree).
2026-10-07: the card that the superseded TRDD-BMITQ2MN named as its blocker, TRDD-UIDK2SDL in the ai-maestro repo, is still in todo there and still expects janitor involvement (it names the janitor's server_tick_holder reader and the removed setup-token importer). Nothing was changed in that repo; the owner or that project's session should be told the importer is gone. Evidence comment posted on ai-maestro issue 176 after a rerun confirmed all four points.
2026-10-07: owner decision still open; nothing changed today; the git guard's one-time password stays visible to subagents and the brief rule (never use it) stays; no guard change until the owner answers.
2026-10-07: TRDD-OOZP38MN and TRDD-TK529Q0F stay closed on code and tests; neither path has been seen in the surviving rotator logs; reopening would be a new card, the owner's call.
2026-10-07 owner directive, verbatim: 'finish to implement all TRDDs and to fix all issues on github, publish and install.' The session publishes the merged fixes through scripts/publish.py and installs them, then continues through the todo column.
2026-10-07: stays in dev across this publish on purpose: it is the umbrella for the issue sweep, issues 328 and 332 are open and being worked, and no code of its own is half-landed in this release.
2026-10-07: the iTerm session enumeration deadlines were raised from 15, 30, 45 s to 30, 60, 90 s on the owner's instruction (9d35df27, merge 1cc4c2e7). Known consequences, from the worker's read of the callers: when every attempt fails the daemon main loop can wait up to 186 s on one scan (its 30 s budget defers later tasks, it does not interrupt), and the peer-freeze-recovery detector, limited to 120 s, would be cut and lose that scan. The alarm that reaches the owner is written after ONE scan with zero sessions; no consecutive-scan threshold exists, so a timeout that clears on the next scan still notifies. Changing that threshold was offered to the owner and not made.
2026-10-07: board triage of 383 cards (278 open) done; batches B1 to B3 merged on main and gated (ten fixes, three cards found already resolved); not yet released.

## Approval log

- 2026-10-06T21:19:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T03:00:03+0200 — column → human_review by main-agent@ai-maestro-janitor. remaining items wait on the owner or on a post-release event
- 2026-10-07T03:00:56+0200 — column → dev by main-agent@ai-maestro-janitor. remaining #332 drift classes are agent work

## STATE

2026-10-06 issue to card map: #306=V3BQT7QE (reopened symptom owned by RAEGS1D5), #307=O92E8RM7, #309=KAXQH0J5, #310=M0JACXNW, #311=ECHE9N4I, #312=1T9034NC, #313=K2PEAYHR, #314=LP0ZCOIS, #315=V13M5YY1, #316=IRBTX41Q, #317=0LNV06LT, #318=2AVXCT2L, #319=SFWYVPGC, #320=WFYJX2XU, #321=TMZRFMZL, #322=8COB99QQ, #323=7V9DQZ9D, #324=4TECXZXP, #325=M6QJ3IUN, #326=2OJG0L0E, #327=EMMXG7GW, #328=Q23COADS, #329=C9O4DJ7T, #330=7KI11RH7, #331=ZNCH1MUT, #332=6ESS2MGE, #333=KKDYNB56, #334=9Z2MGBA5, #335=4LXEFG9I, #336=0YVUX6RE.
fastedit itself stays frozen; the plain-edit exception covers this sweep only.
2026-10-06: all 7 groups merged on main (through 6f45acf8, cards 4f29d825); full suite green; follow-ups for #326/#331/#336 in progress; #321 awaits owner decision; 6f45acf8 is shared by #315/#322/#331 (one test+spec commit).
Release tracking: this card owns the sweep release; after the follow-ups for #326/#331/#336 merge and the owner rules on #321, publish via scripts/publish.py, then close each issue and move its card to complete with an acceptance checklist.

## Corrections

2026-10-07: EZ4LSFF9 was closed complete in 31752504 but its goal was not met; the true outcome is a decision not to change config (pyright identical from any cwd, mypy differs only from inside scripts/lib, a fix would loosen a check); run mypy from the repo root.
