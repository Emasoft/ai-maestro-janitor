---
trdd-id: TKQ274RE
title: The handoff summarizer sends the session transcript to a free remote model with no secret or home redaction
column: todo
status: tasked
created: 2026-11-17T03:35:40+0100
updated: 2026-11-17T03:35:40+0100
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
approval-datetime: 2026-11-17T03:35:40+0100
---

# The handoff summarizer sends the session transcript to a free remote model with no secret or home redaction

## Problem
Measured 2026-11-17: a manual /janitor-write-handoff run (scripts/compose_agent_handoff.py, via scripts/lib/llm_ext_summary.py, the call `llm-ext session-summary --stdout --transcript <path>` near line 359) sent this session's own transcript, 26 chunks of up to 25,000 tokens with prune level aggressive, to the free OpenRouter model inclusionai/ling-3.2-flash:free (read from the llm-ext checkpoint file of that run). The run then ended SUMMARY_FAILED, so nothing was written, but the chunks had already left the machine. The janitor passes no --profile and runs no redaction first; `llm-ext session-summary --help` names no redaction step, and the aggressive prune drops tool-result payloads, not the user, assistant or tool-call text. A transcript can hold secrets that reached the conversation and the account name inside home paths.

## Scope to check
The automatic lane (scripts/summarize_previous_session.py through scripts/lib/jev_compaction_lane.py, jev_compact.py, and its llm_ext_compact.py fallback) also hands a transcript to a remote model; check whether it redacts first.

## Fix direction (to decide)
Before any transcript leaves the machine, write a redacted copy (secret-shield core: redact() from hooks/secret-shield/patterns.ts and redactHome() from hooks/secret-shield/home.ts, or `sanitize-reports --stdin`) and pass that copy's path instead; fail closed (no summary, template handoff) when redaction cannot run. A local profile is the other option.

## Acceptance
A test feeds a transcript holding a fake secret and a fake home path to the summarizer's input step and proves the text handed to llm-ext holds neither.

## Approval log

- 2026-11-17T03:35:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
