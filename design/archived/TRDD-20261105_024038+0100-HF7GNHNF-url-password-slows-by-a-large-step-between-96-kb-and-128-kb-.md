---
trdd-id: HF7GNHNF
title: URL_PASSWORD slows by a large step between 96 KB and 128 KB of URL-shaped text
column: complete
status: archived
created: 2026-11-05T02:40:38+0100
updated: 2026-11-13T20:46:00+0100
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
approval-datetime: 2026-11-05T02:40:38+0100
implementation-commits: [7d54b062, b3363706, 0495dbcb]
---

# URL_PASSWORD slows by a large step between 96 KB and 128 KB of URL-shaped text

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-13

- STATE: fix landed (7d54b062, b3363706, 0495dbcb). Done-when 3 ratio half measured 2026-11-13 on the plugin engine at low load: OLD red 3/3, NEW linear 3/3. Closing as complete. No NEXT ACTION on this card.
- METHOD: `claude plugin test` (the plugin engine; system Bun never shows the step), hooks.json {"modules":["./secret-shield/register.ts"]}, scratch copies only (no repo writes). OLD = hooks/secret-shield at 7d54b062^, NEW = hooks/secret-shield at HEAD ff10cabf (git archive, other tests removed, same meas.test.ts in both, cmp-identical). Shapes: a = grown() (url-shaped, no password), b = a + short URL password tail, ctl = x-only, no URL. Sizes 64/96/128/512/1024 KB, all sizes interleaved in every round, warm-up, best of 15 ms, 3 runs per build. A first NEW-only run (64 vs 512 KB, same method) gave the same ratios.
- LOAD during runs: 1-min 3.9-7.6, 5-min 6.6-7.1 (gate: both under 50 — met).
- OLD (red 3/3): 96 to 128 KB jump 12.9-15.2x on a and b (ctl 1.3); 64 to 512 KB ratio 86-115 (rule: under 12, or big run under 2 ms); b at 512 KB 90-98 ms vs ctl 3.1-3.9 ms, at 1 MB 191-212 ms vs ctl 6.4-7.9 ms. All 3 OLD runs exit 1: engine test timeout "timed out after 5000 ms"; the numbers were still printed.
- NEW (linear 3/3, exit 0 each): 96 to 128 KB about 1.3x; 64 to 512 KB ratio 7.6-7.7 (8x size step = linear), same as ctl 7.5-7.6; b at 512 KB 8.0-10.9 ms vs ctl 3.0-4.2 ms. In the NEW-only run: a 7.55-7.72, b 7.72-7.78, ctl 7.69-7.82, big run 9.1-9.7 ms.
- PASSWORD HIDDEN: on shape b NEW hides it at all 5 sizes up to 1 MB in every run (hidden=true); OLD also hides it (slow, not leaky); shape a (no password) hidden=false in both, correct. The first-iteration expect(hits url-password == 1) passed at 512 KB.
- SUITE: full secret-shield suite (5 test files from HEAD) under `claude plugin test`: 642 pass, 0 fail.
- CAVEATS (still true): the 96 to 128 KB step was not bisected finer here (the 63,808 / 63,824 character bisect of 2026-11-05 stands); OLD shape a is also slow, so the slowdown is the URL_PASSWORD scan on url-shaped text, not the matched password; mechanism (a fast and a slow engine mode) is still inferred, not measured; ratio evidence runs 64 KB to 1 MB, timing absolute values depend on the host.
- EVIDENCE (not tracked): reports_dev/sonnet-worker/20261113_204106+0100-hf7gnhnf-assess.md (NEW run, 642/0), reports_dev/sonnet-worker/20261113_204503+0100-hf7gnhnf-redrun.md (OLD vs NEW, tables), reports_dev/orchestrator/HF7GNHNF-closed-draft.md (earlier draft of this block).

Owner decision 2026-11-05 (quoted on TRDD-2V7OAUPE): measure and fix this here, no upstream report. Measured 2026-11-04 under claude plugin test (TRDD-OD5Z90YL, Known before starting): redact() on the grown() shape b of tests/patterns.test.ts takes about 3 ms at 96 KB, 75 ms at 128 KB, 188 ms at 256 KB and 615 ms at 512 KB (load about 67); the password stays hidden at every size up to 1 MB. A diagnosis run started 2026-11-05 (report in reports_dev/sonnet-worker, name ends -urlpw-diagnosis.md). TRDD-OD5Z90YL stays the ReDoS harness; this card is the fix.
## Done when
 - [x] The cause is named with a measurement that rules out the alternatives.
 - [x] A test fails on the current URL_PASSWORD and passes after the fix.
 - [x] On the grown() shapes, redact() meets the ratio rule of TRDD-Q6LPJTPO (under 12 across an 8x size step, or under 2 ms at the larger size) up to 512 KB, and the password stays hidden at every measured size.

## Approval log

- 2026-11-05T02:40:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-05T05:26:43+0100 — column → testing. code landed in 7d54b062 and b3363706; Done-when 3 ratio half needs a low-load measurement
- 2026-11-13T20:46:00+0100 — COMPLETE by main-agent@ai-maestro-janitor. OLD red 3/3, NEW linear 3/3 on plugin engine at low load; suite 642/0.

## Notes

- 2026-11-05 — Cause measured (raw data: reports_dev/sonnet-worker/20261105_035047+0100-urlpw-diagnosis.md, not tracked). Under claude plugin test, a greedy loop over a group (not over a single character class) gets about 35 times slower per character once one run passes about 63,800 iterations, then stays linear. URL_PASSWORD has three group loops: the user loop, the password loop, and the query scan inside the port-skip lookahead. The password loop and the query loop were each shown to cause the step on their own; the user loop's step was not measured (its miss was, see TRDD-AGOEWF2E). Bisect: last fast run 63,808 characters, first slow 63,824. Ruled out: total text size and URL count (padding fixed at 32 KB with the URL count grown shows no step); backtracking and the regex itself (the same regex and text are linear under Node v26 and under system Bun 1.3.14); the lookbehind and the case flag (dropping either leaves the step). A loop over a class has no step. Inferred, not measured: the engine is the JavaScriptCore inside Claude Code 2.1.318 (its binary names Bun v1.4.4), and the step is a switch from a fast regex mode to a slow one. Candidate fix measured in scratch: unroll all three loops so the group iterates only at a colon. A differential fuzz of 3,000,000 strings under system Bun found 0 differences in match position and groups; under claude plugin test (load 100 to 133) the grown() shape at 512 KB dropped from 211 ms to 7.2 ms. A password made mostly of colons still steps (by 65,536 colons), so the fix also needs an explicit bound that fails closed (TRDD-AGOEWF2E).
- 2026-11-05 — Correction to the note above (review of 64d0a827): once unrolled, the password loop and the query loop iterate only at a colon, but the user loop iterates once per marker (a token hidden earlier inside the user part). So the bound that fails closed must count the markers in the user part as well as the colons in the password. Only the listed alternatives are ruled out; the mechanism (a fast and a slow engine mode) is inferred.
- 2026-11-05 — Done-when 2 met, by a main-agent run under claude plugin test (load 49): the tests of b3363706 against patterns.ts of the commit before 7d54b062 give 561 pass, 8 fail, all 8 of them URL-password tests; the same tests on b3363706 give 569 pass, 0 fail.
- 2026-11-05 — Done-when 3 is split. The password is hidden at every measured size from 32 KB to 1 MB on grown() shape b in every run (worker report urlpw-fix2). The ratio half is open: at load 185-270 the 512 KB to 64 KB ratios ran from 3.4 to 96 on old and new code alike, and a control shape with no URL gave 8.6 to 69, so load dominates. Measure it with the small and big runs interleaved in one test, best of 15 or more, or at low load.
- 2026-11-05 — Corrections to the 7d54b062 commit message: red on old (7 fail), the 1.2M-string fuzz and the FP diff were the worker's runs, and the fuzz and FP diff ran in system Bun, not in the plugin engine; "0 differences" holds at or under the bound only; "the regex and backtracking are ruled out" is an inference (system Bun also misses from about 360K); the over-hide disclosure was incomplete and was completed in b3363706 (the fragment case; placeholder and marker-only passwords are now left alone above the bound).
- 2026-11-05 — Correction to the b3363706 commit message: "load 233" was a 5-minute average and "about 115" a 1-minute one. On the same scale the failing run and the two passing runs had about the same load (215-233), so the data shows one timing failure in three runs under sustained load, not a failure only at higher load.
- 2026-11-05 — Precision on the Done-when 2 note: the old tree was the pre-7d54b062 patterns.ts with export const URL_PASSWORD_BOUND = 4096 appended (the tests import it; it changes no behaviour). The 561/8 run was at load 49 and the 569/0 runs at a 1-minute load of about 115. 0495dbcb adds a test for the colon-count route above the bound.
- 2026-11-05 — NEXT ACTION for Done-when 3: a scratch test that interleaves the 64 KB and 512 KB runs of grown() shapes a and b in one loop, best of 15, run at a 1-minute load under 50; this host often sits at 100-270.
- 2026-11-05 — Correction to the precision note: the 561/8 run had a 1-minute load of 49 and a 5-minute load of 172. The NEXT ACTION gate is: both the 1-minute and the 5-minute load under 50, with the load recorded during the run.
