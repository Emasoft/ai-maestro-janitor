---
trdd-id: JFIOO9XO
title: wave-2 review CUREs — fail-closed inventory read repair-path policy REUSE falsifiability test and GatePolicy doc fix
column: testing
status: tasked
created: 2026-09-29T01:58:50+0200
updated: 2026-09-29T09:05:56+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-29

- LANDED: all four CUREs in commit bd445c71 (main-verified: cargo check 0/0, 336 unit + 171 cli). Card is in `testing` pending the release's live pass.
- ACCEPTED CEILING (owning line = the 2026-09-29 CURE-review entry in `## Review addenda`): update-mem-topic's blanket allow_body_rewrite lets bulk/scripted edits bypass the REUSE half (they cannot lose ids — DROP enforces — but can mutate a surviving id's body). Upgrade path: a --enforce-reuse flag or verb-scoped policy. A resuming session MUST read that addenda line before closing this card.

Four CUREs from the wave-2 landing review (both forks, 2026-09-29; commit 190573d8). (1) read_for_inventory fails OPEN: unwrap_or_default inventories a permission error or invalid UTF-8 page as EMPTY, so the DROP half certifies dropping every id on an unreadable page — the exact corruption class the gate exists for. Fix: NotFound inventories empty (split's not-yet-existing dest needs it), every other error refuses hard. (2) cmd_edit_cli (update-mem-topic) passes DEFAULT policy, so the card's sanctioned control-byte repair path (update-mem-topic --replace-all, the recorded repair for the AgentlensPro/ghbook 0x08 pages) refuses on the REUSE half when the repair lands inside an atom body. Fix: write_gated_with with allow_body_rewrite true — the DROP half still enforces. (3) The REUSE half has zero falsifiability: no test proves a surviving id with a changed body refuses under DEFAULT policy; a fingerprint collapse passes the suite silently disabling the half. Fix: one unit test (changed body under default refuses; same body under default passes). (4) GatePolicy doc comment says only update-mem-atom sets allow_body_rewrite but merge-mem-atom and split-mem-atom also set it — fix the comment. Verification: cargo check 0, full suite green, each fix covered by its own test where a test can discriminate.
2026-09-29: this card now gates TRDD-XI10BA5D's close — XI10BA5D's eht lists it (correction round 2026-09-29, discharging the wave-2 review's 'wired as eht' claim that was false in the frontmatter). Directional signal added per the close-out review (the gate was one-directional until now). Also flagged: XI10BA5D's verification check-box requires reading this card's CURE content against the wave-2 fixes (the uncited-lesson-def carry and merge See-also changes already landed in 190573d8 — parts of the CURE list may be discharged); note that step 6's refuse_introduced_one_sided_links runs inside prepare_batch_gated and thus INHERITS this card's fail-open read_for_inventory defect — verifying the inventory fix must re-check step 6's link-refusal path with it.

## Approval log

- 2026-09-29T01:58:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-09-29 — review-of-record verdict HOLDS; sequenced to dev before any step-6 dispatch.

## Review addenda

Review-of-record addenda (2026-09-29, HOLDS): CURE 2's blanket allow_body_rewrite on update-mem-topic is a SEMANTIC LOOSENING trading against GD24IL7O's stated purpose — it exempts ALL body changes through the verb, not just repairs; named alternatives were a --repair policy flag or fingerprint-compare of the atom id set. The dispatcher must present the tradeoff at implementation, not bury it. CURE 1's fix must make the refusal RETRYABLE in its message (STALE_MSG-style reread-and-retry) — a transient EACCES/ENOENT-on-race refusing a batch is correct fail-closed but must not teach a worker the gate is broken.
2026-09-29 LANDED (lean-worker, main-verified): all four CUREs in one commit; cargo check 0/0, 336 unit + 171 cli green (2 new refusal-asserting tests: unreadable_page_refuses_retryable_and_missing_page_inventories_empty, surviving_id_with_changed_body_refuses_under_default_and_passes_with_allow_body_rewrite); tradeoff comment landed verbatim at the cmd_edit_cli call site. Moving to testing.
2026-09-29 CURE-review (HOLDS): CURE 2's breadth is a STRUCTURED ACCEPTED CEILING, not a closed trade — bulk/scripted edits through update-mem-topic (the bulk-repair verb) now bypass the REUSE half silently (they cannot LOSE ids — DROP still enforces — but can mutate a surviving id's body, the citation-ambiguity harm). Upgrade path when needed: a --enforce-reuse flag or verb-scoped policy on update-mem-topic. This line is the owning artifact; the ceiling must not evaporate at close like atom-dup-id nearly did.
2026-09-29 (5fa4c57b review): that commit's K0PMVRN6 blank-line edit used the Edit tool on a governed card — a sanctioned-path bypass. Mitigations: whitespace-only, Read-first verified, targets exactly the b20611c8-added line, net-restores pre-b20611c8 state. The gated path WAS available (multi-line non-empty expect). Going forward: whitespace repairs go through AIM_PILLAR_ALLOW_WRITE=1 trddgrep edit with a multi-line non-empty expect. The STATE block's MUST wording is a decision-record pointer, not an enforced obligation — do not reuse MUST-in-STATE for real obligations.
