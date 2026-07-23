---
trdd-id: 4ZTNMQL3
title: Every wikimem write must route through a memgrep write verb, then validate+lint
column: backburner
created: 2026-07-23T06:35:11+0200
updated: 2026-07-23T06:35:11+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: high
relevant-rules: [1]
eht: [WN7M829Y]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-23

**NOT STARTED.** Design captured; awaiting plan-mode sign-off with siblings DOJ2LE1G
(tooling), WN7M829Y (retroactive repair), VJCMZ2OP (migrate verb).

**ROOT CAUSE (verified):** the safe-write surface ALREADY exists — `memgrep add-atom /
new-page / add-lesson` synthesise valid syntax so "a malformed atom is impossible"
(`scripts/memgrep/src/main.rs:388-391`, TRDD-R02HTRUD). The malformed atoms the user caught
(`^agent-launch-agent-flag-dropped-v2`: unquoted `desc:`, body-less `[^N]` lesson, oversized
atom) exist because the SKILLS/AGENTS still HAND-EDIT markdown (hand-written atom/lesson
strings through `memory_txn_cli`) instead of calling those verbs, and do not run
`validate`/`lint` after. Tooling is not the gap; authoring discipline is.

**NEXT ACTION:** audit `skills/janitor-memory-{write,update,atomize,repair,split,merge,
conflict,harvest,consolidate}/` + `agents/…memory-subconscious-agent` for every place they
emit atom/lesson/page markdown by hand; rewrite each to call the memgrep write verb; append a
mandatory `memgrep validate <page> && memgrep lint <page>` step after every edit.

## The defect

Skills author wikimem content as raw markdown strings. A human (or Sonnet agent) writing
`^name [desc: value, keywords: …]` by hand omits the quotes on `desc:` (breaks grep and the
in-body filter), writes a `[^N]` lesson header with no prose body (`memgrep find --only-notes`
then returns nothing), and lets an atom grow past a readable size — exactly the three defects
seen in the wild.

## The fix (this TRDD's scope)

1. **Route every write through a verb.** No skill emits atom/lesson/page markdown by hand.
   - new page → `memgrep new-page`
   - new atom → `memgrep add-atom` (stores `desc` QUOTED, ≤200 chars, id/dates synthesised)
   - new lesson → `memgrep add-lesson` (anchors `[^N]` from the atom body)
   Hand-editing is reserved for in-place REPAIR of an existing page's prose, and even then the
   atom/lesson SYNTAX must match what the verbs emit.
2. **Validate + lint after EVERY change.** Each editorial step ends with
   `memgrep validate <page> && memgrep lint <page>`; a non-zero exit blocks the transaction.
3. **Proactively invite the CLI.** The skill prose tells the agent to recall/add/update via
   memgrep (`recall`, `add-atom`, `add-lesson`, `links`, `atom`) rather than reaching for
   Read/Grep/Edit on the raw page first.
4. **Pick the right SCOPE before writing.** The skill runs the write-gate question ("would
   this be true+useful for a stranger who clones the repo on another machine?") and routes
   LOCAL / PROJECT / USER accordingly — unsure → LOCAL.

Whether this ships as tightened SKILLS or as a new RULE under `~/.claude/rules/` is a
plan-mode decision; the enforcement content is identical either way.

## Verification

- Grep the memory skills: zero hand-emitted `^<name> [desc:` / `[^N]:` string literals remain
  (except documented examples inside code fences).
- A dry-run of each skill ends in a `memgrep validate && memgrep lint` invocation.
- Authoring a fresh atom via the tightened `write` skill produces a page that lints clean with
  a quoted `desc` and a body-bearing lesson.

## Notes and lessons learned
