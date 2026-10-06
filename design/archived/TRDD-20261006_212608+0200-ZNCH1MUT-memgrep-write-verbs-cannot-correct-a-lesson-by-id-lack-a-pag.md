---
trdd-id: ZNCH1MUT
title: memgrep write verbs cannot correct a lesson by id, lack a page description verb and have an undocumented stdin contract
column: complete
status: archived
created: 2026-10-06T21:26:08+0200
updated: 2026-10-07T00:25:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:08+0200
implementation-commits: [6eabe6b7, 15344f01, 6f45acf8, a0506578, 8586f043]
---

# memgrep write verbs cannot correct a lesson by id, lack a page description verb and have an undocumented stdin contract

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #331 closed https://github.com/Emasoft/ai-maestro-janitor/issues/331#issuecomment-6025977220. Landed on main as 6eabe6b7,15344f01,6f45acf8,a0506578,8586f043. Follow-ups for #331 landed on main (a0506578 memgrep crate 0.1.0 to 0.2.0; 8586f043 repair skill page-description rewrite must prove no recall loss, a skill instruction only with no automated test).
NEXT ACTION: move to complete once v3.8.1 is released and CI is green. Ships in v3.8.1.
FOLLOW-UP LOCATION: landed on main as 6eabe6b7,15344f01,6f45acf8,a0506578,8586f043 (the follow-up worktree is merged).
NOTE: the #331 repair-skill rule (a page-description rewrite must prove no recall loss) is a skill instruction only, with no automated test.

Source: GitHub issue Emasoft/ai-maestro-janitor#331 (opened 2026-10-05). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Four gaps share one cause, the write verb contract. A lesson cannot be superseded under its own id, no verb sets a page description, the stdin behaviour is undocumented, and a repair shrinks the recall surface. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:08+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T00:25:05+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.1; acceptance items proven; self-approved by this standalone session.





## Acceptance

- [x] A lesson can be corrected under its own id (update-mem-atom --status). Proof: 6eabe6b7; scripts/memgrep/tests/cli.rs::update_atom_status_supersedes_a_lesson_by_its_own_id.
- [x] A page description can be extended through a verb. Proof: 6eabe6b7, 15344f01; scripts/memgrep/tests/cli.rs::update_topic_can_extend_the_page_description.
- [x] The stdin contract is documented. Proof: 349acb2d (hook advice, SKILL.md, spec WM-CLI-17), a0506578 (crate 0.2.0).
- [x] A repair rewrite of a page description cannot shrink the recall surface. Proof: 164bd7ea, daa6a60b (pytest pins the repair recall-surface rule and that the SKILL.md pointer names an existing heading of references/repair-background.md, renamed Description trims keep recall); 8586f043, bdbf5b16.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/331#issuecomment-6025977220
