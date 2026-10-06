---
trdd-id: 8COB99QQ
title: memgrep update-mem-atom with piped stdin reports success but writes nothing
column: complete
status: archived
created: 2026-10-06T21:25:57+0200
updated: 2026-10-06T23:46:00+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:57+0200
implementation-commits: [84541ac7, 6f45acf8, 349acb2d]
---

# memgrep update-mem-atom with piped stdin reports success but writes nothing

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #322 closed https://github.com/Emasoft/ai-maestro-janitor/issues/322#issuecomment-6025974708. Landed on main as 84541ac7,6f45acf8,349acb2d. 349acb2d adds the no-op refusal to the hook advice, SKILL.md and spec WM-CLI-17.
NEXT ACTION: none; shipped in v3.8.0 and the issue is closed.


Source: GitHub issue Emasoft/ai-maestro-janitor#322 (opened 2026-09-29). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Piping a new body into update-mem-atom prints an updated message and exits 0, yet the file is unchanged, because stdin is ignored unless a body flag is given. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:21+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-06T23:46:00+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #322 closed.





## Acceptance

- [x] update-mem-atom with piped stdin and nothing to change no longer reports success; it refuses loudly. Proof: 84541ac7, 6f45acf8; scripts/memgrep/tests/cli.rs::update_atom_with_only_stdin_and_nothing_to_change_refuses_loudly.
- [x] An explicit body-from-stdin call still replaces the body. Proof: scripts/memgrep/tests/cli.rs::update_atom_body_dash_still_replaces_the_body_from_stdin.
- [x] The no-op refusal is documented (hook advice, SKILL.md, spec WM-CLI-17). Proof: 349acb2d.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/322#issuecomment-6025974708
