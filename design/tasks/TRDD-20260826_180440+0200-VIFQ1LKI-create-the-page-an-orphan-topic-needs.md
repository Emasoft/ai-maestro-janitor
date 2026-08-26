---
trdd-id: VIFQ1LKI
title: Create the topic page an off-topic atom needs when none exists
column: backburner
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T18:04:40+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, atomize]
parent-trdd: 87RKBYJ8
blocked-by: [QDYQLM5V]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# Duty 15 — if an off-topic atom's topic has NO page yet, CREATE that page

Split out of **TRDD-87RKBYJ8** per its own rule.

**The duty, verbatim:** If an off-topic atom's topic has **no page yet**, CREATE that page.

## Genuinely blocked, and the blocker is named

`blocked-by: [QDYQLM5V]` (duty 14, the MOVE). This duty is the else-branch of that one: 14 moves
an off-topic atom to the page that owns its topic, and 15 handles the case where no such page
exists. Building the create path before the move path means building a page-minting rule with no
caller and no way to test the decision that reaches it.

Recorded as `blocked-by` rather than left as an undated note, because the kanban rule is explicit
that a card sitting still needs a named blocker that is itself open — otherwise it is stalled, not
parked.

## ⚠ SURVEY before minting a page

The standing memory rule says so directly for methodology pages, and the reason generalises: a new
page whose subject is already covered under a different name is the near-synonym failure duty 10
exists to undo. So creation is the LAST resort, after a recall across ALL THREE scope roots —
composed into an array, because a single-root recall returns a confident empty indistinguishable
from a real absence (measured twice on 2026-08-26; `ATOM-W99A-N60G`).

## Acceptance

- [ ] Page creation requires a recorded 3-root survey showing no existing page owns the topic
- [ ] The new page is minted through the write verbs with correct scope routing (UNSURE → LOCAL)
      and a `description:` carrying the SYMPTOM phrasings, not the jargon of the subject
- [ ] The moved atom arrives via QDYQLM5V's verified two-page move — this card mints the target,
      it does not re-implement the move
- [ ] A test drives an off-topic atom whose topic has no page and asserts a page is created; a
      second test drives one whose topic DOES have a page under a different name and asserts NO
      page is created
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
