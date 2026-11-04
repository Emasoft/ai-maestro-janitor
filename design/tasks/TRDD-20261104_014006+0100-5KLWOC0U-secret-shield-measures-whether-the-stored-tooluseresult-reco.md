---
trdd-id: 5KLWOC0U
title: secret-shield measures whether the stored toolUseResult record keeps secrets
column: design
status: tasked
created: 2026-11-04T01:40:06+0100
updated: 2026-11-04T01:46:24+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T01:40:06+0100
---

# secret-shield measures whether the stored toolUseResult record keeps secrets

## Problem
Two live probes on Claude Code 2.1.318 (2026-11-04, TRDD-337UVA3J) showed, for Bash on 2.1.318, that the text of a tool result, normal or error, reaches the model redacted: the session.append hook rewrites the tool_result row at door tool-result, and the probe's transcript view of the stored tool_result row showed the marker, though which field that view reads is not known. Not measured: the session jsonl also stores a separate structured record of each call (toolUseResult: stdout, stderr and similar fields). If that record keeps the raw text, a secret reaches whichever readers use that field; candidate readers, to be confirmed in step 2: the file on disk, /export, the resume display, and the janitor's own transcript readers, including compaction that sends the jsonl to an outside model provider.
## Do
1. Measure it. The probe tool deletes its session jsonl when it ends, so read the file inside the probe: a separate final probe step, run after the steps that print the fakes so that their rows are already written, finds the probe's own session file (the newest jsonl in the probe's project folder) and prints its name. It then runs a JSON-aware pass over each line, for example jq with paths(strings | test(...)), that prints only key paths and counts, never the matched text. It reports two things: the key paths holding the full fake-token pattern (pypi-AgE followed by 50 or more token characters), and, as a positive control, the key paths holding the shield's pypi-token marker. The control must find the marker in the tool_result content. If it does not, the measurement is void: the step read the wrong file, or the row was not yet written. A bare prefix also matches the command text in tool_use. Because the fake is built at run time, any full-pattern hit outside tool_use is a leak. The earlier steps run a Bash command that prints a fake token on stdout, and one that prints a fake on stderr and exits non-zero, with secret-shield loaded. Do the same for one MCP tool error if a test MCP server is available. Never print a token: the parent session's redactor does not catch PyPI tokens.
2. List every reader of that field, in Claude Code and in this repo.
3. Find whether any mod event can redact it, citing the mods docs or type definitions by file:line.
4. If it cannot be redacted, record that as a known miss, and decide with the owner whether TRDD-2V7OAUPE waits for it.
## Done when
The probe result is recorded with the field names, the readers are listed, and either a redaction path is implemented and tested, or the miss is recorded with its readers.
Found during TRDD-337UVA3J (review of 072255ea).

## Approval log

- 2026-11-04T01:40:06+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
