---
trdd-id: 3BSPFS7R
title: memgrep update-mem-atom body replace drops lesson citations and two sibling defects
column: dev
status: tasked
created: 2026-10-18T06:01:14+0200
updated: 2026-10-18T06:48:59+0200
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
approval-datetime: 2026-10-18T06:01:14+0200
parent-trdd: FQVEILVK
---

# memgrep update-mem-atom body replace drops lesson citations and two sibling defects

Source: janitor#337 items 1 to 3 (memgrep 0.2.0, 5497043). Item 4 (recall hook fires on task notifications) shipped in v3.8.0 (ecb8cc7f, #326): tell the reporter. Item 5 is UNVERIFIED. Related, not owning: TRDD-XI10BA5D, TRDD-XI9UYD4E, TRDD-8COB99QQ.

## Reproduction (reproduced 2026-10-18 with the installed memgrep, isolated scratch dir via WIKIMEM_LOCAL_SCOPE_PATH under /tmp)
1. After `--lesson --supersedes` the atom body ended `[^1]`; after `update-mem-atom --body -` the body line no longer contains `[^1]`, and `memgrep lint` printed `INFO [lesson-uncited] ... (WMLESS-002)`.
2. `update-mem-topic --old-file/--new-file` on a phrase shared with the superseded copy returned "old text matches 2 locations - make it unique or pass --replace-all".
3. `update-mem-atom ... --supersedes <ATOM>` failed with a clap argument error.

## Fix sites (HEAD source read; nothing changed these lines)
- scripts/memgrep/src/memory.rs:4126 `cmd_update_atom_cli`, body replace path :4185-4260 (explicit body only, no code re-appends `[^N]` citations): preserve or warn about citations anchored on the atom (~:4185-4290).
- scripts/memgrep/src/mem_replace.rs, `update-mem-topic` match counting: skip text inside `SUPERSEDED BODY:` / `## Superseded`.
- memory.rs:4146-4150: `--supersedes` is a bool "only applies together with --lesson"; accept an optional value or add a hint to the error.

## Acceptance
- [ ] Body replace keeps or warns about `[^N]` citations (lint clean after the repro)
- [ ] update-mem-topic ignores the superseded copy when counting matches
- [ ] `--supersedes <ATOM>` works or errors with a hint
- [ ] Real tests for all three

## Approval log

- 2026-10-18T06:01:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T06:48:59+0200 — column → dev by main-agent@ai-maestro-janitor. working the three #337 items
