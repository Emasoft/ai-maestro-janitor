---
trdd-id: RPHJ64W1
title: Pick the best corpus projects for redacting Claude transcripts, log files and git history
column: todo
status: tasked
created: 2026-11-05T02:35:23+0100
updated: 2026-11-05T02:35:23+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-05T02:35:23+0100
---

# Pick the best corpus projects for redacting Claude transcripts, log files and git history

Owner directive, 2026-11-05, verbatim: "decide yourself on anything else, but decide on verified facts. do not assume anything as true. give the security maximum priority and also use the plugin/projects i gave you to also implement automatic redaction of jsonl transcripts of claude, of log files, and of git history. there are plenty of those projects with the ability of doing that. examine, compare, and pick the best solutions."

Scope: three targets. (1) Claude Code JSONL session transcripts already on disk (~/.claude/projects/*/*.jsonl). (2) Log files (the janitor's own logs, plus other logs to be listed by the research). (3) Git history.

Sources: the 108 repos in _corpus_dev/secret-patterns/repos (untrusted; see clone.log, neutralized.txt, removed.txt there). Existing pieces to verify before reuse: hooks/secret-shield (rows.ts, register.ts), jr-redact (TRDD-2V7OAUPE), the trufflehog scan in the pre-push hook.

Constraints: security first. Every claim about a project rests on reading its code, never its README. Rewriting git history is irreversible: tools may block secrets before they enter history and may scan history, but any history rewrite runs only on an exact command the owner approves (CLAUDE.md RULE 0). In-place redaction of transcripts and logs must never leave a broken or half-written file: validate, then replace atomically.

## Done when
 - [ ] A comparison report names, per target, the best project or approach and why, each claim cited to file:line in the corpus.
 - [ ] One implementation card exists per target, each citing this card.

## Approval log

- 2026-11-05T02:35:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
