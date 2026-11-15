---
trdd-id: DXBJMT1K
title: specgrep cannot address claude-md-canonical-form.md so that spec cannot be amended
column: backburner
status: tasked
created: 2026-11-15T12:20:37+0100
updated: 2026-11-15T12:20:37+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T12:20:37+0100
parent-trdd: FADYLSQB
---

# specgrep cannot address claude-md-canonical-form.md so that spec cannot be amended

## Problem

`specgrep` record listing shows only `wikimem-memgrep-spec.md` records. `specgrep claude-md-canonical` and `specgrep claude-md-canonical-form` both print "no spec record matches". specgrep is owned by ai-maestro (the user-level launcher runs scripts/specgrep.mjs from the recorded ai-maestro install). Consequence: the spec file claude-md-canonical-form.md cannot be addressed, so it cannot be amended through the mandated tool.

## Blocks

TRDD-FADYLSQB increment 6 (spec CM-1, CM-4, CM-5 and frontmatter must follow PRRD G7.3 and G10.3).

## Draft upstream request (for the owner to send to Emasoft/ai-maestro; the agent does not post)

Title: specgrep cannot address a spec file that has no CM-N style records
Body: specgrep lists records only for wikimem-memgrep-spec.md. A spec file whose requirements are headed CM-1, CM-4, CM-5 (claude-md-canonical-form.md) returns "no spec record matches" for every query, so its text and frontmatter cannot be edited through specgrep while PRRD G7.3 and G10.3 forbid any other editor.
Request: either (a) a per-document edit verb that takes a spec file name and an --at-line/--expect/--replace triple without needing a record id, or (b) record parsing of CM-N headings so those files list as records.
Expected: specgrep show and specgrep edit work on claude-md-canonical-form.md.

## Approval log

- 2026-11-15T12:20:37+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
