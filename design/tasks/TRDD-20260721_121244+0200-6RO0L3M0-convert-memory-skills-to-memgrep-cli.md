---
trdd-id: 6RO0L3M0
title: convert the 3 memory skills to memgrep-CLI-driven — mechanical to the tool, judgment stays prose
column: todo
created: 2026-07-21T12:12:44+0200
updated: 2026-07-21T13:40:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
scope: project
parent-trdd: R02HTRUD
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**UNBLOCKED — A1 shipped a133ff0** (`add-atom`/`new-page`/`add-lesson` verified live). Proceed.

**NEXT ACTION:** rewrite `skills/janitor-memory-write/SKILL.md`, `janitor-memory-recall/SKILL.md`,
`janitor-memory-update/SKILL.md` so every MECHANICAL step is a memgrep CLI call and only JUDGMENT
prose remains. `-recall` is already memgrep-driven (least change). The verb CLI surface is:
`memgrep new-page --path --tier --name --description --type [--globs --functionality]`;
`memgrep add-atom --page --keywords [--desc --type]` (body on stdin, prints `<id>\t<page>`);
`memgrep add-lesson --page --atom --keywords [--desc]` (DO-NOT/BECAUSE/DO on stdin).

## Problem

The 3 skills carry the mechanical rules as PROSE the agent must hand-apply — and the prose itself
drifted (three different lesson schemas: write=4-key, update=3-key, the RULE=5-key). Once memgrep
enforces the mechanical rules ([[TRDD-R02HTRUD]]), the skills must STOP telling the agent to
hand-author and instead invoke the tool.

## The MECHANICAL vs JUDGMENT split (the spec for this refactor)

- **CREATE (`janitor-memory-write`) → memgrep** (`new-page`, `add-atom`, `add-lesson`): atom/lesson/
  frontmatter syntax, unique id, ocd/lmd, `desc:` presence, mandatory `## Notes` section, `wikimem/`
  location, reindex, link-law reciprocal, duplicate-page WARN.
  **→ stays skill prose (judgment):** subject routing (case vs methodology), scope routing
  (LOCAL/PROJECT/USER by content), find-the-home-first (never duplicate), the SHAPE decision
  (hub/aspect/component, expand vs reduce), name-the-page-by-topic, what is worth memorizing,
  index-by-the-QUESTION (memgrep enforces keywords EXIST; the agent still must choose GOOD symptom
  keywords).
- **RECALL (`janitor-memory-recall`) → already memgrep-driven** (recall/find/links/--where). Keep the
  judgment prose: two-axis case+methodology recall, index-by-symptom, the don't-over-read navigation
  contract, the `user-mem/` privacy boundary.
- **UPDATE (`janitor-memory-update`) → memgrep + txn:** `supersede` (clean fact + auto-demote to a
  lesson with WHY), lesson metadata gen, lmd bump, link-law reciprocal, `rename` (repoint inbound
  links), reindex, `links --broken` gate.
  **→ stays skill prose (judgment):** find the page, case/methodology routing, whether an edit
  SUPERSEDES, the WHY content of a correction, the RESHAPE decisions (expand/reduce/merge).

## Derived tasks

- Keep the skills' references (`wikimem-model.md`, `atom-authoring.md`, `subject-routing.md`) — they
  hold the judgment rules; prune only the mechanical-syntax parts the tool now owns.
- Update every worked example to show the memgrep call, not a hand-authored `.md`.

## Verification

Each rewritten skill's mechanical steps are memgrep calls; a dry authoring pass produces a page that
`memgrep lint` ([[TRDD-VPTQ4067]]) passes with zero findings. No skill instructs a raw Write/Edit of a
wikimem page anymore (grep the 3 skills for "Write tool"/"Edit tool" → none on the authoring path).

## Notes and lessons learned
