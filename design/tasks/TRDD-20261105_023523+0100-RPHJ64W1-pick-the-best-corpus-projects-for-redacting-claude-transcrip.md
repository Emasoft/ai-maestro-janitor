---
trdd-id: RPHJ64W1
title: Pick the best corpus projects for redacting Claude transcripts, log files and git history
column: todo
status: tasked
created: 2026-11-05T02:35:23+0100
updated: 2026-11-05T03:06:07+0100
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

Constraints: security first. Every claim about a project rests on reading its code, never its README. Rewriting git history is irreversible: tools may block secrets before they enter history and may scan history, but any history rewrite runs only on an exact command the owner approves (RULE 0 of the owner's global rules). In-place redaction of transcripts and logs must never leave a broken or half-written file: validate, then replace atomically.

## Done when
 - [x] A comparison report names, per target, the best project or approach and why, each claim cited to file:line in the corpus.
 - [x] One implementation card exists per target, each citing this card.
 - [x] Every candidate listed in _corpus_dev/secret-patterns/neutralized.txt or removed.txt is excluded or its use is justified; _corpus_dev/ is gitignored and local to this machine, so the report or this card records the commit of each repo it cites.

## Approval log

- 2026-11-05T02:35:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-05 — Authority for this card: the owner directive quoted in the body; trddgrep recorded the main agent as issuer.

## Notes

- 2026-11-05 — Comparison done: per target, the pick is CARD T (TRDD-11KWFU5L, transcripts), CARD L (TRDD-119JBB8C, logs) and CARD G (TRDD-FXR55XCN, git history). Neutralized-list check: 13 of the 16 repos on neutralized.txt are still in the corpus and marked NEUT in the report; three of them carry neutralized files and feed a pick as ideas only, no code: mogesjohnson_history-scrub and nikolareljin_leak-lock (CARD G), thesubtlety_agent-scrub (no licence, read for its in-place design only). The report is gitignored, so each card carries its own copy of the facts it relies on.
- 2026-11-05 — Box 3: the report records each repo's last commit DATE only, so the commits of the repos the picks cite are recorded here (git rev-parse HEAD of the local clones, 2026-11-05): maccydee_scrub-transcripts c5e1644c029a8e67700eeda0106886378d55df13; shubhajeet1207_redact (SpyMonk) a8dd65beefdb3571ad3c529ec46af39b78b4bc1c; devops247-online_shellclear c114a83c219ad5cc21da0282334a0b6eb8602adf; baditaflorin_agent-redact 70070037786110b4b913e87bd7d283c90fa89424; mogesjohnson_history-scrub 83d71243ce9eabe643a3550d5c5eda586d629455; nikolareljin_leak-lock 104ea59009db7b6c478d8c9a75482799708323a1; thesubtlety_agent-scrub 52609c48f26b9393c569028d22779cf51e78d157. Box 1 covers the picks: every pick was read and cited to file:line; the other 72 rows of the report were classified from README and grep only.
