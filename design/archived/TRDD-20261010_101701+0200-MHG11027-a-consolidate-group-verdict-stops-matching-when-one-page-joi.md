---
trdd-id: MHG11027
title: A consolidate group verdict stops matching when one member page is edited
column: complete
status: archived
created: 2026-10-10T10:17:01+0200
updated: 2026-10-18T04:19:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T10:17:01+0200
implementation-commits: [d491dcca, 52250a20]
---

# A consolidate group verdict stops matching when one member page is edited

Found 2026-10-10 by the main session reading the USER consolidate refusal ledger (global-state/memory-maint-consolidate-USER-<hash>.refusals.json in the plugin data dir). Split from TRDD-K5F7US68, whose fix made a one-page key impossible; this is the opposite end.

MEASURED on the released 3.8.11: the 2026-10-10 pass (56 seconds, 9 tool calls, 0.18 million tokens) recorded five group keys naming 97, 45, 8, 6 and 2 pages. The ledger also holds keys of 95, 44 and 43 pages from 2026-10-08, 23 from 2026-10-06, 42 from 2026-10-04 and 43 from 2026-10-02, with the same reason text each time (no two pages share a subject; the debugging-methodology family is a deliberate split). So the same coarse same-tier/same-type bucket was judged at least five times in nine days, one agent spawn each.

WHY (read from TRDD-K5F7US68's record, not re-read in code today): a refusal covers a pair only when its key holds both pages, and an exact-group key covers the group as it was; when one page is added the group is no longer covered and is listed again. The USER corpus grows daily.

ALSO SEEN: a key of 97 pages written in under a minute names pages the agent cannot have read in full. The fix on main for TRDD-K5F7US68 tells the agent to name only pages read in full; with groups this size that turns one coarse verdict into many partial ones, which this card must weigh.

NOT KNOWN: whether candidates_for should list a same-tier/same-type bucket of 97 unrelated pages as a consolidate candidate at all (TRDD-3XS3PDCF rejected a keyword gate as unsound); whether a group refusal should cover any SUBSET of its pages so that only pairs involving a new page are unjudged.

SMALLEST FIX TO WEIGH: a refused group key covers every pair inside it for the 7 days, so a later, larger group is listed only for pairs that include a page outside every refused key. Read group_has_unjudged_pair first: it may already do this, in which case the re-dispatch has another cause and that must be found.

## Acceptance

- [x] The reason a refused group is listed again is shown from code and from one reproduced case on a scratch ledger
- [x] After the fix, adding one page to a refused group lists only pairs that involve the new page, pinned by a test
- [x] uv run pytest, ruff, mypy and pyright pass

## Approval log

- 2026-10-10T10:17:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T04:19:22+0200 — COMPLETE by main-agent@ai-maestro-janitor. three boxes verified 2026-10-18: cause shown from the removed whole-group content_hash, reproduced by the fix's tests failing on 52250a20^, full gate green at 828097d1; cause corrected from 'page joins' to 'member edited'.

## Corrections

2026-10-10 10:36, from the review of 9f22b963: the MEASURED paragraph overstates. What the ledger printed supports: the LARGE bucket (95 then 97 pages) was refused twice, on 2026-10-08 and 2026-10-10. The keys of 2026-10-02 (43 pages), 2026-10-04 (42) and 2026-10-06 (23) are smaller groups; the 43 and 42 fit the SECOND bucket (44 or 43 pages on 10-08, 45 on 10-10), which was therefore refused about four times in eight days; the 23-page key fits neither. The reason texts differ from date to date; 'the same reason text each time' is withdrawn. Whether the two keys of 44 and 43 pages on 2026-10-08 are one bucket or two is not known. That re-listing is CAUSED by a page joining the group is an inference from the 95 to 97 growth; the card's first acceptance box is where it gets shown.

## STATE

2026-10-17 IMPLEMENTED, UNCOMMITTED pending orchestrator commit: memory_refusals.page_hash (sha256 minus frontmatter lmd lines) + record() stores per-member pages + live_members(); memory_content_precheck.group_has_unjudged_pair and refusal_covered_pages use live_members. 7 new tests + 1 deliberately updated; 203 passed in the 4 named test files; ruff, mypy, pyright (-p project) clean. Field criterion: after one recording pass, editing one member of a ~97-page key leaves at most N-1 unjudged pairs, checked from the ledger. Expect one extra consolidate pass per scope because old entries without pages cover nothing. Next cost lever: the 7-day TTL.
2026-10-18 — SUPERSEDES the 2026-10-17 'UNCOMMITTED' line: committed as d491dcca + 52250a20. CAUSE CORRECTED (title changed from 'when one page joins'): before 52250a20, a refusal stayed live only while the content_hash of the WHOLE group matched (the removed docstring: 'edit any page in a refused group and the whole group's refusal stops matching'), so editing or deleting ONE member revived every pair of the group. A page JOINING did not invalidate the stored refusal. Box 1 reproduced on scratch ledgers (tmp_path): the fix's tests run against 52250a20^ in a temp worktree gave test_editing_one_member_revives_only_that_members_pairs FAILED (all pairs (a,b)... returned, expected only (a,d),(b,d),(c,d)) and test_deleting_one_member_revives_only_that_members_pairs FAILED, while test_adding_a_page_leaves_only_its_pairs_unjudged PASSED on the old code too. So the field growth 95 -> 97 pages did not by itself cause the re-listing; member edits did (inferred: the ledger does not record edits). Box 2: test_adding_a_page_leaves_only_its_pairs_unjudged pins it; it does not distinguish old from new code. Box 3: full gate at 828097d1 (contains both commits): ruff, mypy, pyright clean, pytest 18615 passed, 2 skipped. Field criterion (one recording pass, then an edit leaves at most N-1 unjudged pairs) is optional and not an acceptance box.
