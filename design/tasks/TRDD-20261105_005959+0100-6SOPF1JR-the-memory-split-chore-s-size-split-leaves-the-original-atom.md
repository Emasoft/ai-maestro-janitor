---
trdd-id: 6SOPF1JR
title: The memory split chore's size split leaves the original atom's desc and keywords claiming the half that moved
column: todo
status: tasked
created: 2026-11-05T00:59:59+0100
updated: 2026-11-05T01:05:54+0100
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
approval-datetime: 2026-11-05T00:59:59+0100
---

# The memory split chore's size split leaves the original atom's desc and keywords claiming the half that moved

## Problem

skills/janitor-memory-split/references/split-plan-details.md gives two atom-split paths that treat the original atom differently.
 - For a plain two-way size split it runs memgrep split-mem-atom, which "leaves the first atom's marker untouched".
 - For a topic split it makes --orig-desc and --orig-keywords mandatory. The reason it gives: the original atom's keywords were written to serve both subjects, and recall ranks on keywords alone, so the first atom keeps answering queries about the topic that left.

A size split also moves part of the prose out of the original atom, so the same reasoning applies. The size path does not ask for it.

## Observed

In eee842b6, the split chore size-split ATOM-Q2B2-FBQP on the PROJECT page oauth-rotation-renew-reauth-operations.md. The oauth-cookie-reminder and /janitor-refresh-claude-logins rows moved into the new ATOM-Q1KX-4HQM. Q2B2 kept its old desc and 10 keywords, and 5 of those keywords described the moved rows. 961a33c9 narrowed Q2B2 afterwards through memgrep update-mem-atom; memgrep's floor of 10 keywords forced 5 new ones to be taken from the remaining row's text.

## Done when

1. When the two halves hold distinct subjects (a judgement made per split, as in the topic-split triage), the size-split path of the split skill sets the original atom's desc and keywords for the part it keeps, either with --orig-desc and --orig-keywords on split-mem-atom or by re-deriving them right after the split. Both atoms are held to the same keyword floor.
2. A test, or a recorded run on a scratch copy, uses a fixture atom with a known keyword set per half: after a size split that separates distinct subjects, the original atom keeps no keyword from the moved half's set.

## Approval log

- 2026-11-05T00:59:59+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

 - 2026-11-05 — The asymmetry is deliberate for an atom that holds one subject: after a size split, the original's keywords still serve both halves. The defect is narrower. A size split can separate distinct subjects, as in eee842b6, where Q2B2 ("OAuth detectors") held three, and the size path has no step that then re-keys the original. memgrep split-mem-atom accepts --orig-keywords and --orig-desc on any split (its --help, checked 2026-11-05). Done-when 1 applies when the halves are distinct subjects. Done-when 2 is checked on a fixture atom with a known keyword set per half: after the split, the original keeps no keyword from the moved half's set.
