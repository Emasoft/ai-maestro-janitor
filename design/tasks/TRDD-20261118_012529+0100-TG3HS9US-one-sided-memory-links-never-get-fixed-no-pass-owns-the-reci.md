---
trdd-id: TG3HS9US
title: One-sided memory links never get fixed, no pass owns the reciprocal link repair
column: todo
status: tasked
created: 2026-11-18T01:25:29+0100
updated: 2026-11-18T01:27:07+0100
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
approval-datetime: 2026-11-18T01:25:29+0100
---

# One-sided memory links never get fixed, no pass owns the reciprocal link repair

Source: GitHub issue #362 (https://github.com/Emasoft/ai-maestro-janitor/issues/362), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: the LOCAL memory corpus of the filing project has 5 link-one-sided findings (WMLINK-002), confirmed real by the issue comment (the target page does not mention the source page). The five page pairs are named in the issue; they are pages of the filing project's LOCAL corpus and are not copied here. By the issue five memory passes on 2026-11-15 and 2026-11-16 (repair, atomize, conflict) saw them and each left them for another pass. By the issue a harvest pass created a new page and reported both link ends wired, but only one end exists. By the issue the same harvest pass abstained because the write gate forbids a bare wikilink to a harness note while a code-span rendering passes the gate but fails the mirror-preservation verifier, so harvest can never stamp its watermark.

## Suspected cause

By the issue: atomize and conflict route the finding to repair, and repair refuses because the only fix writes a second page; no pass owns the LINK LAW repair. The harvest report claim of both ends wired does not match the file, and it is unknown whether the reference-mem-topic verb wrote one end only or the agent skipped a call. The write gate and memory_edit_verify.mirror_preservation_ok disagree about a source note that links to another harness note. Expected by the issue: one pass owns the reciprocal-link fix and may add the backlink through the gated verbs, or the one-sided rule exempts pairs the curator may not write; harvest checks both ends before reporting both ends; the gate and the verifier agree on mirroring a link to a harness note. Issue 349 (closed) was a different cause.

## Files named by the issue

memory_edit_verify.mirror_preservation_ok (module under scripts/lib); the memgrep reference-mem-topic verb; the harvest, repair, atomize and conflict memory skills; per-project memory pass reports under reports_dev/janitor-memory-subconscious-agent/.

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:29+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
