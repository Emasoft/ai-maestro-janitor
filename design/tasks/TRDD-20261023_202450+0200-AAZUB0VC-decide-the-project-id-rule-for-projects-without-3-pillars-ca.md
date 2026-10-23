---
trdd-id: AAZUB0VC
title: Decide the project-id rule for projects without 3-pillars cards
column: todo
status: tasked
created: 2026-10-23T20:24:50+0200
updated: 2026-10-23T20:24:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T20:24:50+0200
---

# Decide the project-id rule for projects without 3-pillars cards

Spec design/specs/wikimem-layout-spec.md WL-FACT F18 (VERIFY-4, TRDD-W17F82DN) shows that a project without 3-pillars cards has no stored project-id, and that neither the origin URL nor the root commit is unique on its own. Decide the rule the resolver and page-id sync use, base it on F18 and on any VERIFY result still open, and write it into the spec normative section with a version bump. Acceptance: the rule is in the spec; each case F18 names (no origin, no commits, several roots, copies of one project, forks, same-name repos) has a stated outcome; JI6I6JG1 can then be released.

## Approval log

- 2026-10-23T20:24:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
