---
trdd-id: 3BSPFS7R
title: memgrep update-mem-atom body replace drops lesson citations and two sibling defects
column: complete
status: tasked
created: 2026-10-18T06:01:14+0200
updated: 2026-10-19T17:40:52+0200
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
implementation-commits: [f0f760e3]
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
- [x] Body replace keeps or warns about `[^N]` citations (lint clean after the repro)
- [x] update-mem-topic ignores the superseded copy when counting matches
- [x] `--supersedes <ATOM>` works or errors with a hint
- [x] Real tests for all three
Evidence 2026-10-18 (f0f760e3): box 1 by tests/cli.rs update_atom_body_replace_refuses_to_drop_a_lesson_citation_and_names_it (lint clean after the escape) and the two-atom neighbour test; box 2 by update_topic_ignores_the_superseded_body_copy_when_counting_and_replacing and update_topic_refuses_text_that_exists_only_in_the_superseded_section; box 3 by update_atom_supersedes_with_a_value_errors_with_a_hint (hint, no value form); box 4: the 4 behaviour tests fail on the pre-fix source. Deferred: the hint also fires on an unrelated unknown argument when --supersedes is present; a NEW dangling [^N] in a body is left to the pre-write lint gate. The installed memgrep is unchanged until a release.
Close list 2026-10-18 (review of ff66f6f9): (1) memory note ATOM-26TJ-AML8 quotes the two refusals as paraphrases in backticks; replace them with the real fragments 'write refused: the new body of atom ... drops footnote citation(s)' and 'the old text occurs in ... only inside superseded copies' (recall from the real text already ranks the page first, measured). (2) Once a release carries f0f760e3, update the note's 'ship with the release after that commit' to name the version, through the correction protocol.

## Approval log

- 2026-10-18T06:01:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T06:48:59+0200 — column → dev by main-agent@ai-maestro-janitor. working the three #337 items
- 2026-10-18T06:58:33+0200 — column → testing by main-agent@ai-maestro-janitor. built and tested at f0f760e3; unreleased, and the installed memgrep still runs the old code
- 2026-10-19T17:40:52+0200 — Close list executed: (1) note ATOM-26TJ-AML8 now quotes the real fragments verbatim (commit on current branch); (2) installed memgrep upgraded 5497043 → e5cf088 via `cargo install --path scripts/memgrep`, release 0.2.0 carries f0f760e3, `memgrep validate` clean. Both deferred items closed. Card moves to complete.
