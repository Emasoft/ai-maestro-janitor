---
trdd-id: JFIOO9XO
title: wave-2 review CUREs — fail-closed inventory read repair-path policy REUSE falsifiability test and GatePolicy doc fix
column: testing
status: tasked
created: 2026-09-29T01:58:50+0200
updated: 2026-09-29T02:12:19+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-29T01:58:50+0200
---

# wave-2 review CUREs — fail-closed inventory read repair-path policy REUSE falsifiability test and GatePolicy doc fix

Four CUREs from the wave-2 landing review (both forks, 2026-09-29; commit 190573d8). (1) read_for_inventory fails OPEN: unwrap_or_default inventories a permission error or invalid UTF-8 page as EMPTY, so the DROP half certifies dropping every id on an unreadable page — the exact corruption class the gate exists for. Fix: NotFound inventories empty (split's not-yet-existing dest needs it), every other error refuses hard. (2) cmd_edit_cli (update-mem-topic) passes DEFAULT policy, so the card's sanctioned control-byte repair path (update-mem-topic --replace-all, the recorded repair for the AgentlensPro/ghbook 0x08 pages) refuses on the REUSE half when the repair lands inside an atom body. Fix: write_gated_with with allow_body_rewrite true — the DROP half still enforces. (3) The REUSE half has zero falsifiability: no test proves a surviving id with a changed body refuses under DEFAULT policy; a fingerprint collapse passes the suite silently disabling the half. Fix: one unit test (changed body under default refuses; same body under default passes). (4) GatePolicy doc comment says only update-mem-atom sets allow_body_rewrite but merge-mem-atom and split-mem-atom also set it — fix the comment. Verification: cargo check 0, full suite green, each fix covered by its own test where a test can discriminate.

## Approval log

- 2026-09-29T01:58:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-09-29 — review-of-record verdict HOLDS; sequenced to dev before any step-6 dispatch.

## Review addenda

Review-of-record addenda (2026-09-29, HOLDS): CURE 2's blanket allow_body_rewrite on update-mem-topic is a SEMANTIC LOOSENING trading against GD24IL7O's stated purpose — it exempts ALL body changes through the verb, not just repairs; named alternatives were a --repair policy flag or fingerprint-compare of the atom id set. The dispatcher must present the tradeoff at implementation, not bury it. CURE 1's fix must make the refusal RETRYABLE in its message (STALE_MSG-style reread-and-retry) — a transient EACCES/ENOENT-on-race refusing a batch is correct fail-closed but must not teach a worker the gate is broken.
2026-09-29 LANDED (lean-worker, main-verified): all four CUREs in one commit; cargo check 0/0, 336 unit + 171 cli green (2 new refusal-asserting tests: unreadable_page_refuses_retryable_and_missing_page_inventories_empty, surviving_id_with_changed_body_refuses_under_default_and_passes_with_allow_body_rewrite); tradeoff comment landed verbatim at the cmd_edit_cli call site. Moving to testing.
