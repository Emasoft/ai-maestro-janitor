---
trdd-id: 0UVFDPQP
title: Secret-name assignments after other text on the same line stay visible in the shield core
column: todo
status: tasked
created: 2026-11-18T05:41:36+0100
updated: 2026-11-18T07:20:16+0100
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
approval-datetime: 2026-11-18T05:41:36+0100
---

# Secret-name assignments after other text on the same line stay visible in the shield core

## Problem

The core assignment pass (hooks/secret-shield/patterns.ts, redactAssignments, the line regex at about line 533) is anchored to a whole line: a secret-name assignment is hidden only when it is the whole line (optionally after export, a declaration keyword or a quote). An assignment after other text on the same line is left visible.

Measured 2026-11-18 by main-agent with plain redact() on 15 shapes, one value built at run time (scratch probe scripts_dev/midline/probe.ts, not in git). Hidden: a bare line, export at a line start, a YAML key at a line start, a JSON pair, URL credentials. Left visible: a CLI long flag with = (--password=<v>), a CLI long flag with a space (--password <v>), an environment prefix after a semicolon, an environment prefix after other words (sudo API_KEY=<v> node app.js), an assignment after text and a colon (config: api_key=<v>), a quoted assignment after text (set token="<v>" now), a JSON string carrying an environment assignment, mysql -p<v>, Bearer "<v>" (quoted), two assignments on one line (user=bob password=<v>).

Also measured 2026-11-18T07:17:30+0100 by main-agent with plain redact() and with redactJsonLine on a JSON string (scratch probes, not in git, value built at run time): an assignment that opens the line but has other text after its value on the same line (password=<v> end) stays visible, in plain text and after an escaped newline inside a JSON string; the whole-line form password=<v> is hidden, after an escaped newline in a JSON string too, so the text after the value is the cause, not the escapes. The KNOWN-MISSES entry of 55bb9abf (assignment-after-text-on-the-same-line) lists only text before the assignment, so this shape needs its own entry and test, and the mid-line pass of plan step 2 must also cover text after the value.

## Why it matters

Transcripts and project files are full of command lines; the owner needs 2 TB of projects and JSONL transcripts redacted. redactJsonLine (TRDD-BAQB9SYO step 1) inherits the gap: 8 of its 134 measured cells are left whole, all mid-line name-assignment or the quoted Bearer value.

## Plan

1. Add a KNOWN-MISSES entry for the mid-line assignment shapes and a test that asserts the miss (it turns red when fixed).
2. Design a mid-line assignment pass: a secret name at a word start (after whitespace, a semicolon, &&, a pipe, an opening quote or bracket), then = or : and a value; the CLI flag forms --<secret-name>=<v> and --<secret-name> <v>; the quoted Bearer value. Keep the existing isSecretName, looksSecret and strongValue gates.
3. Before landing, measure old against new on the plugin cache and the code tree: count new hits, read a sample of them for false matches, and time it at 256 KB against the 100 ms limit.
4. report-sanitizer re-pins the core after it lands.

Related: TRDD-BAQB9SYO (transcript lane, redactJsonLine), TRDD-L1I0FP5T (shared rule core), TRDD-5VZTPXBJ (escape boundary).

## Approval log

- 2026-11-18T05:41:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
