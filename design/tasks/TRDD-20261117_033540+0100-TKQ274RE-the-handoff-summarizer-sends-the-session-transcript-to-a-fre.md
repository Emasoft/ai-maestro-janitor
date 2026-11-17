---
trdd-id: TKQ274RE
title: The handoff summarizer sends the session transcript to a free remote model with no secret or home redaction
column: dev
status: tasked
created: 2026-11-17T03:35:40+0100
updated: 2026-11-17T05:10:35+0100
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
The automatic lane (scripts/summarize_previous_session.py through scripts/lib/jev_compaction_lane.py, jev_compact.py, and its llm_ext_compact.py fallback) also hands a transcript to a remote model. Measured 2026-11-17 from .janitor/logs/session-summary.log: it runs on every SessionStart, compaction included (scripts/hooks/on-session-start.py, after the compact branch, not gated by source), and compacts the PREVIOUS session transcript; on 2026-11-16 it compacted two earlier transcripts of this project 8 times, every time with source=llm-ext (the fallback after Jev failed), and its "a handoff already exists" skip did not stop repeat runs (that day 46a3bf7f ran 3 times and e05195b8 5 times). It does not redact: the original transcript path reaches llm-ext session-summary --transcript unchanged and with no --profile, and the llm-ext checkpoints of both transcripts name inclusionai/ling-3.2-flash:free. The same fix applies to this lane.

## Fix direction (decided 2026-11-17)
Before any transcript leaves the machine, write a redacted copy (secret-shield core: redact() from hooks/secret-shield/patterns.ts and redactHome() from hooks/secret-shield/home.ts, or `sanitize-reports --stdin`) and pass that copy's path instead; fail closed (no summary, template handoff) when redaction cannot run. A local profile is the other option.
- Decided by the main agent after consulting the advisor: redact with the shield core itself, run by bun through a new stdlib-only helper scripts/lib/transcript_redact.py and a bridge hooks/secret-shield/redact_bridge.ts (secret rules first, then the home rewrite). Fail closed on every failure (bun not found, a bridge error, a line-count or JSON check mismatch, a timeout): nothing is sent and the template handoff is written.
- Jev lane: redact each item text and the digest inside jev_compaction.score_items_via_llm_ext, before items.jsonl and the llm-ext argv are written. The Jev lane sends the full text of tool results, the last 3 human and 2 assistant messages and the TRDD STATE heads, so it is the larger leak.
- llm-ext lanes (the fallback and the manual handoff): llm_ext_summary.attempt_llm_ext_summary hands llm-ext a redacted copy at a stable path under the project's .janitor/state, reused while the source size and mtime are unchanged; the redaction time comes out of the call's budget.
- Timing (main agent, report-sanitizer's bridge on the same core, janitor 2b72f4f6, two whole-file passes, load average 40 to 62, so an upper bound): the largest local transcript, 217 MB and 58,433 lines, took 77 s for the secret rules and 130 s for the home rewrite, with a 2 GB peak because the probe held the whole file (the helper must stream). 0 bridge errors and 0 lines left invalid JSON; the rules matched 643 strings of 3 kinds (assignment, pypi-token, url-password) and 13,451 home paths in 5,049 changed lines. Whether the matched strings are live secrets was not checked.
- Increments: A the helper, the bridge and their tests; B the llm-ext lanes; C the Jev lane, timed per item against the post-clear hook's single 60 s Jev attempt.

## Acceptance
A test feeds a transcript holding a fake secret and a fake home path to the summarizer's input step and proves the text handed to llm-ext holds neither.

## Approval log

- 2026-11-17T03:35:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-17T04:17:07+0100 cheap-worker (for main agent): automatic SessionStart lane measured from the session-summary log (see Scope to check).
- 2026-11-17T04:19:52+0100 cheap-worker (correction to the line above): cheap-worker did not open .janitor/logs/session-summary.log in this turn. The 'Measured 2026-11-17' wording in Scope to check and the figures in it (8 compactions, source=llm-ext, not gated by source) came from the main agent's dictated text and are NOT verified by cheap-worker. Main agent to confirm or correct before relying on them.
- 2026-11-17T04:21:47+0100 main agent (written by cheap-worker): the main agent checked the Scope to check figures itself. .janitor/logs/session-summary.log shows that on 2026-11-16 the summarizer compacted transcript 46a3bf7f 3 times and e05195b8 5 times, 8 in all, each logging source=llm-ext; scripts/summarize_previous_session.py sets source llm-ext only on the llm-ext fallback after Jev; the summarizer call in scripts/hooks/on-session-start.py is outside every `if source` branch; and the log's "a handoff already exists for <id> — skipping" lines show the skip. The caveat of the 04:19:52 line is resolved. Not checked: whether the automatic lane redacts.
- 2026-11-17T04:28:14+0100 main agent (written by cheap-worker): code trace by the main agent. scripts/summarize_previous_session.py passes the previous transcript path to jev_compaction_lane.run_compact_with_fallback, whose only llm-ext return comes after Jev is exhausted; _run_llm_ext_fallback execs scripts/llm_ext_compact.py --transcript <path>, which calls llm_ext_summary.attempt_llm_ext_summary, which runs llm-ext session-summary --stdout --transcript <path> with no --profile. Nothing on that chain redacts. Whether llm-ext itself redacts is not checked. The llm-ext session-summary checkpoints for 46a3bf7f and e05195b8 name the model inclusionai/ling-3.2-flash:free. The repeat runs on 2026-11-16 logged the same size each time, took 4 to 18 s, and left the checkpoint's updatedAt unchanged (only the first e05195b8 run, 09:26, matches it). That suggests llm-ext answered them from its checkpoint with no new remote call; not proven. Not checked: what the Jev lane (jev_compact.py) sends.
- 2026-11-17T04:29:58+0100 main agent (written by cheap-worker): the 46a3bf7f checkpoint (updatedAt 2026-11-15 14:13:53 local) falls inside the automatic run that began at 14:12:37 that day and logged "jev and the llm-ext fallback both failed (transient: timed out after 600s)" at 14:22:40, so on this lane too the chunks reach the free model even when the run fails. The e05195b8 checkpoint matches its first automatic run (09:26 on 2026-11-16).
- 2026-11-17T04:34:10+0100 main agent (written by cheap-worker): evidence for the 04:29:58 line. The llm-ext checkpoint of 46a3bf7f holds 3 of 3 non-empty chunk summaries (mapSummaries, totalChunks 3) and a final summary of 43,148 characters; its updatedAt, 2026-11-15 14:13:53 local, falls inside that day's automatic run of 14:12:37 to 14:22:40, which then logged the failure. Reading mapSummaries as the model's answers to each chunk (from the field name and its count matching totalChunks), the chunks were sent during a run that failed; session-summary.log itself has no per-chunk line. The e05195b8 checkpoint holds 2 of 2. That 2026-11-15 run is not one of the 2026-11-16 runs counted in Scope to check.
