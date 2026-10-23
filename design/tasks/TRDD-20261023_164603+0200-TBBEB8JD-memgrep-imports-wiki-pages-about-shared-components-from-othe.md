---
trdd-id: TBBEB8JD
title: memgrep imports wiki pages about shared components from other projects
column: backburner
status: tasked
created: 2026-10-23T16:46:03+0200
updated: 2026-10-23T16:54:52+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T16:46:03+0200
relevant-rules: [13, 14, 19, 20, 21, 24]
---

# memgrep imports wiki pages about shared components from other projects

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-23
- Requested by the owner on 2026-10-23 (the seventh message recorded on TRDD-KLT5F93P, quoted below). Nothing is built yet.
- NEXT ACTION: wait for the TRDD-KLT5F93P answers that decide what an imported copy is (its scope, whether it stays in sync, who may edit it), then write the design here and propose it before any code.
- The docs ship WITH the option, not before it. Help text for an option that does not exist is a false instruction, and recommending copies today produces copies that drift apart, because copy sync does not exist yet (see the agent note under the sixth message on TRDD-KLT5F93P).

## Owner request, verbatim
"you may ask why some wikimem pages should be duplicated in different projects. but the answer is simple: different projects often share identical components or libraries. this means that any memory or discovery relative to one project can easily become relevant to all the other projects sharing the same component. so not only having wikimem pages with the same id in different projects is allowed, but it is recomended. in fact, we should add to memgrep an option to look/search for wikimem pages related to components of the current project that exists in other projects, and duplicate/import them into the current project. this will save the hassle of having to rebuild a documentation for something that was already documented in other projects. add this to the skills reccomendations and to the memgrep help use cases examples help."

## What it must do (from the request)
- Search other projects for wiki pages about components the current project also uses.
- Copy those pages into the current project, keeping each page's id.
- Document the use case in memgrep's top-level help EXAMPLES block (scripts/memgrep/src/main.rs, the EXAMPLES string near line 550) and in the recommendations of the memory skills (skills/janitor-memory-recall/SKILL.md and skills/janitor-memory-write/SKILL.md).

## Open questions (agent-written, not the owner's words)
1. Which projects to search. memgrep has no list of this machine's projects. The janitor's fleet scan sees only projects that have a running Claude session, and Claude Code's per-project folders under the home directory record only a slug, which cannot be turned back into a path reliably.
2. How a page is recognised as being about a component of the current project. One option: the dependency names in the current project's manifests (package.json, Cargo.toml, pyproject.toml) matched against the other project's component pages (title, tags, globs).
3. What scope the imported copy gets, and whether its edits travel. The owner's fifth message makes pages of other projects read-only from here, while the third and sixth messages want every copy kept in sync, so an edit to the imported copy must either be refused or reach the original.
4. Whether another project's LOCAL (machine-private) pages may be imported at all.
5. Whether an imported page is re-checked for private data (home paths, usernames, hostnames) before it lands in a git-tracked PROJECT folder.

## Approval log

- 2026-10-23T16:46:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
