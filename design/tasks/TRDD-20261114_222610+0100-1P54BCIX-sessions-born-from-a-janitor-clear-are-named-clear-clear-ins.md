---
trdd-id: 1P54BCIX
title: Sessions born from a janitor clear are named clear clear instead of the project or TRDD name (issue 357)
column: testing
status: tasked
created: 2026-11-14T22:26:10+0100
updated: 2026-11-16T09:05:43+0100
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
approval-datetime: 2026-11-14T22:26:10+0100
implementation-commits: [7d1c8b43]
---

# Sessions born from a janitor clear are named clear clear instead of the project or TRDD name (issue 357)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- DONE: fix 7d1c8b43 (local main, not released: v3.8.13 does not contain it). Not pushed.
- NEXT ACTION: after the next release containing 7d1c8b43 is installed (claude plugin update), verify live that a session born from a janitor /clear gets the project folder name (or the project plus one TRDD id and title when the newest handoff lists exactly one in-flight card) as its session name, instead of "/clear clear"; also verify that a session ALREADY named "/clear clear" is renamed on its next prompt. Then close GitHub issue 357 on Emasoft/ai-maestro-janitor with the evidence. Do not close the card or the issue before that live check.
- OPEN: field proof only. Everything else is committed and gated.
2026-11-16 CORRECTION: the DONE line "fix 7d1c8b43 (local main, not released: v3.8.13 does not contain it)" is stale. 7d1c8b43 is an ancestor of 81575d5c2 (git merge-base --is-ancestor) and shipped in ai-maestro-janitor--v3.9.0 (first tag by git tag --contains); it is installed with 3.9.6. Only the live field check in NEXT ACTION stays open.

## Facts (GitHub issue 357)

Symptom: janitor-created sessions were named "/clear clear". 41 of 81 sessions in one project carried it.

Root cause (verified by reading the Claude Code 2.1.325 binary and by transcript census): Claude Code titles an untitled session from its first prompt. A session born from the janitor /clear has the /clear command record as its first prompt, so it was titled "/clear clear" at its first metadata re-append. The native /clear then CARRIES the old session's custom title and agent name into the new session (custom-title and agent-name records are lines 1-2 of every new transcript, before the SessionStart hook output), so one poisoned session poisoned every later clear. Sessions with a good title carry it unchanged. The issue's probable cause (the name derived from the typed command by the janitor) was wrong: nothing in the janitor emitted a title.

Fix 7d1c8b43: the UserPromptSubmit hook (scripts/hooks/on-prompt-submit.py, new scripts/lib/session_title.py) returns hookSpecificOutput.sessionTitle when the input session_title starts with "/", or is empty AND the transcript head (first 64 KB or 200 lines) shows the session began with the /clear command. A fresh user session keeps Claude Code's own title. Name = project folder name, or "<project> TRDD-<id> <title>" when the newest janitor handoff (under an hour old) lists exactly one in-flight card; sanitised to 60 chars of [A-Za-z0-9 ._:#()-], never a leading "/". Any error leaves the hook output unchanged and logs one line. No keystrokes are typed into the pane.

REJECTED design (the first investigation's proposal): typing /rename into phase B of the clear chain. It needs an optional-command mechanism in run_chained_inject, a pane read-back, and costs a model-turn race; the hook route needs none. The hook route was measured live first (scratch plugin, Claude Code 2.1.325): after /clear the first prompt carried session_title null, the next carried the hook's name, and /status showed it as the session name.

Gates at commit: 51 tests passed (the new hook-title tests failed first); ruff, mypy (543 files), pyright clean.

Unverified: why the good title chain broke on 2026-11-01 is explained (parent was a session already titled "/clear clear" since 2026-10-04), but the exact trigger of the very first "/clear clear" auto-title (it appeared mid-session after a resume-era task notification) is inferred, not reproduced. Name collisions when two panes of one project carry the same inherited name were not run (Claude Code suffixes the name per the binary).

## Approval log

- 2026-11-14T22:26:10+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
