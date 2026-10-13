---
trdd-id: S41TV0I7
title: Pending memory-maint records of kinds the drain cannot judge have no way out of the queue
column: verify_assumptions
status: tasked
created: 2026-10-10T08:17:30+0200
updated: 2026-10-11T13:19:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T08:17:30+0200
---

# Pending memory-maint records of kinds the drain cannot judge have no way out of the queue

Split from TRDD-K5F7US68 box 5 on 2026-10-10. FACTS: memory_dispatch_claim.is_drained drops an aged-out pending record only when candidates_for gives a known empty answer; candidates_for answers unknown for enrich and relocate (they shell out to memgrep lint) and retro-lesson has no candidate function, so a record of those kinds stays claimable for ever. This repo holds two from 2026-09-03: retro-lesson PROJECT (its root is the live PROJECT corpus through the old path alias) and enrich LOCAL (root is the old path's slug directory, which still exists). claim_one takes the oldest matching record first, so the next enrich fire in this project would work the old slug directory. A 30-day expiry for every kind was proposed and dropped after review on 2026-10-10: it contradicts the rule in is_drained that an unknown answer keeps the record, and nobody has read how enrich and retro-lesson are re-emitted. TO DO FIRST: read the emit paths of enrich, relocate and retro-lesson in scripts/detectors/memory-maintenance.py and say whether a dropped record is regenerated when work remains; then decide between an expiry, a strict candidate answer for those kinds, or a recorded keep. Acceptance: the two 2026-09-03 records are either consumed, expired by a rule with a test, or kept with a reason that names the code read.

## Approval log

- 2026-10-10T08:17:30+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T08:41:40+0200 — column → verify_assumptions. an open design choice and unread emit paths; not ready for todo
2026-10-10 08:41 CORRECTION to the body: 'stays claimable for ever' is too strong; the scheduler prunes pending files by count, keeping the newest 20 (read by a worker in memory-maintenance.py, not by the main session), so an old record leaves when more than 20 pile up. 'The next enrich fire would work the old slug directory' is reasoned from oldest-first claiming plus the chore match, not observed.

## Investigation

2026-10-11T13:13:43+0200 — INTERIM KEEP, not closure: read-only inventory found pending 1788453141-8f370851 (retro-lesson PROJECT) and 1788466161-334e46ee (enrich LOCAL), both with existing directory roots. No records were claimed, expired or removed. Main-session code trace: scripts/memory_dispatch_claim.py is_drained preserves unknown candidate answers; scripts/detectors/memory-maintenance.py _first_due_intervention and _run require cadence/content/recent-noop/in-flight gates and stamp before execution; scripts/lib/memory_content_precheck.py enrich_has_work and relocate_has_work depend on linter results and refusals. Age alone cannot establish safe expiry or guaranteed regeneration. Both adversarial reviews accepted preservation only under uncertainty: existing roots do not prove authority, outstanding work is unverified, oldest-first claiming may still select the old LOCAL root, whose authority remains unverified, and supersession/count pruning can remove records independently of the drain. Card remains verify_assumptions; next action is read-only verification of each record's root authority and completion evidence before any terminal disposition.
2026-10-11T13:16:41+0200 — ROOT CHECK: the PROJECT pending root resolves to this repository's current PROJECT corpus. The LOCAL pending root differs from this session's LOCAL root, but matches resolve_local_dir_for for this same repository's alternate launch path; alias_same_repo, record_matches_alias_local and alias_local_exists each returned True. scripts/lib/memory_scopes.py project_slug and resolve_local_dir_for deliberately key on literal launch paths without resolving symlinks, so difference alone does not prove obsolescence. The old LOCAL directory contains 46 Markdown files (not a classification of durable pages). No queued work was consumed or discarded; outstanding chore relevance remains unverified. Retain both records under the interim preservation decision; no terminal transition.
2026-10-11T13:19:49+0200 — CURRENT-CANDIDATE CHECKS, no dispatch consumed: retro_lesson_has_work on the current PROJECT root returned False with no saved fingerprint supplied. The enrich candidates CLI printed nothing for the retained LOCAL root; bare memgrep lint then exited 0 with zero findings on that same root, using installed build 5497043 dated 2026-10-07. These observations show no candidates under those current predicates, not when or whether the historical dispatches were completed; they do not establish the installed linter's rule coverage. Preserve both pending records under the reviewed KEEP decision; no expiry rule or queue mutation is introduced. The card remains open, and these results are not a closure claim.
