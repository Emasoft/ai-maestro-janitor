---
trdd-id: RAEGS1D5
title: Jev compaction replaces the janitor's automatic compaction
column: dev
created: 2026-09-22T21:32:55+0200
updated: 2026-09-23T11:22:42+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-22T21:32:55+0200
npt: [541CBN36]
relevant-rules: []
implementation-commits: [051625a4, 0b883373]
---

# Jev compaction replaces the janitor's automatic compaction

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-23

- Cards 1-4 and card 5 (post-clear Jev injection, cooldown/recovery vetoes, hook-output caps) landed. NPT TRDD-541CBN36 closed 2026-09-23 after its last defect (OpenRouter 402/403 -> JevAuthError, 0b883373). The stale pane-key test was fixed in 051625a4; it had failed since the 2026-09-23 reader switch, and eba1f1ff landed on that red suite (process gap).
- Scope audit 2026-09-23 (reports/compaction-replacement/20260923_105904+0200-raegs1d5-scope-audit.md): 16 of 17 card-3/4 items done. Item 8 (fleet-lease renamed to compaction-lane, a lock on the automatic lane) DROPPED by owner decision 2026-09-23: the compaction only reads the closed session's transcript file, so no lock is needed; the manual llm-ext lane keeps its existing fleet lease unchanged.
- NEXT ACTION: design, propose and implement the owner's 2026-09-23 fallback directive — if Jev still fails after up to 5 minutes of retries, the llm-ext compaction runs as a fallback; no 30-minute compaction pause for unrecognised Jev errors.
- Owner decisions 2026-09-23: (1) no lock on the automatic lane; (2) unifying terminal_pane_key with pane_key_from_terminal is optional tidy-up, not pursued unless asked; (3) unrecognised Jev errors must not pause compaction for 30 minutes — after up to 5 minutes of Jev retries, fall back to llm-ext compaction.
- Follow-ups from the 402/403 fix, not yet carded: the JEV-AUTH-REJECTED headline says "key rejected" even for a 402 credits problem; the per-reason dedupe can re-fire if the 402 body text varies.
- OpenRouter's openapi.json documents these statuses for the decisions endpoint: 400, 401, 402, 403, 404, 413, 429, 500, 502, 503, 524, 529 (422 is not documented). Today 400, 404 and 413 fall into the client's catch-all and are stamped kind "unavailable" (a 30-min decline) — decision (b) above would fix all of them.




## Owner's directive (verbatim)

> go a. and it must replace all compaction. handoff is a different thing, and only left to
> explicit requests. handoff-and-clear must never be called automatically. the compaction
> includes already the clear before injecting the compacted context with jev. when restarting,
> if the cache is stale/expired, it must clear and inject the jev compacted summary of the
> session. but beware of infinite loops or truncating other operations, like resuming after
> api error or model expired time limit window.

## Vocabulary (binding)

- Jev compaction — the ONLY automatic shrink the janitor performs: (1) decide, (2) type
  /clear, (3) in the new session's SessionStart, compose the compacted context of the
  old session from its on-disk transcript with Jev scoring, (4) inject it, (5) resume.
- Compacted context — the injected artifact: the fact record (in-flight TRDD STATE heads,
  open files, running agents — already produced without any model) + Jev-selected VERBATIM
  items of the old transcript + pointers for everything else. Never generated prose.
- Handoff — the model-authored artifact of /janitor-handoff-and-clear / /janitor-write-handoff.
  Manual only. No automatic path may type either skill.
- /compact — the harness's summarizer. The janitor never types it again.

## Scope of this card (cards 3 + 4 of docs_dev/jev-compaction-spec.md)

Card 3 — the compacted context replaces the llm-ext summary: item extraction from the old
transcript (human messages, assistant text blocks, paired tool_use/tool_result), the digest
(last three human messages + in-flight TRDD STATE heads), two-Noul-question scoring with an
EITHER-passes keep rule, oversized-item pointers, the compacted-context output file format
(header, fact record, verbatim items in budget, elided pointers), the injection swap in the
SessionStart path, the composition point (jev_compact.py compact subprocess replacing
summarize_with_retry), the fleet-lease rename to compaction-lane, and deletion (with tests)
of resolve_llm_ext / run_llm_ext_summary / attempt_llm_ext_summary / summarize_with_retry and
their three test files (54 tests) plus a prose sweep for llm-ext/llm_ext in the automatic lane.

Card 4 — all janitor compaction is Jev compaction: removal of scripts/compact_trigger.py,
tests/test_compact_trigger.py, the _phase_proactive_idle_compact /compact path in dispatch.py,
and scripts/hooks/on-stop-proactive-compact.py's /compact firing (each becomes a Jev
compaction decision or is deleted if redundant, prefer delete); clear_trigger.spawn_shrink_chain
drops its write-handoff phase (chain becomes /clear -> SessionStart compose+inject -> resume,
with a grep sweep proving no automatic path still types /janitor-write-handoff or
/janitor-handoff-and-clear); /janitor-compact-context becomes "Jev-compact this session now"
with --handoff removed, merged with /janitor-externalized-compaction into one skill; the
on-restart lane (SessionStart source in {startup, resume} with a stale/expired cache) becomes
a Jev compaction under card 1's guards; the harness's own autoCompactEnabled: true setting is
left untouched — the janitor does not change it.

Card 1 (trigger/loop guards) and card 2 (vendored jevctx + provider + scorer CLI) are NPTs
tracked on their own cards (card 1 = TRDD-L32WC0H7, continued; card 2 = its own TRDD, set as
this card's npt).

## Gates before "done" (every card, per spec)

uv run pytest (full), uv run ruff check scripts tests, uv run mypy scripts/
--ignore-missing-imports, uvx --with pyright pyright; tldr impact on every changed symbol;
prose sweep with grep -rn for removed names over skills/ rules/ hooks/ README. Reports to
reports/compaction-replacement/. Workers never commit; the orchestrator stages by name and
commits per card with the WHY in the message.

## Approval log

- 2026-09-22T21:32:55+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-23T06:08:54+0200 — column → dev by claude-main. Jev compaction work in progress: cards 1-4 landed (54ea73bc); post-clear injection fix and lease rename pending
- 2026-09-23T06:09:10+0200 — column → todo by claude-main. revert: orchestrator correction — 541CBN36 still owns an open defect, do not unblock RAEGS1D5 yet
- 2026-09-23T11:22:14+0200 — column → dev. NPT 541CBN36 closed; remaining scope: compaction-lane concurrency guard

## Design

- Card 1 loop/recovery guards (binding on this program, tracked under TRDD-L32WC0H7): **Recovery guard** — no Jev compaction fires while a rate-limit / API-error / compact resume is pending or was consumed less than N seconds ago (gate on the `dispatch._phase_compact_resume`, `_phase_clear_resume` and rate-limit-cleared state files); owner: "beware of ... truncating other operations, like resuming after api error or model expired time limit window".
- **Loop guard:** SessionStart with `source` in {`clear`, `compact`} never evaluates cache staleness (RESUME_SOURCES, pinned by a test); a failed compaction attempt records `evaluated` not `fired` (no cooldown burn, no hot retry); a hard cap of one automatic Jev compaction per session per `CLEAR_COOLDOWN` window, whatever the trigger.
No PRRD rule applies here (relevant-rules field left empty): checked prrdgrep's full board plus targeted searches for compact/clear/handoff on 2026-09-22, nothing constrains Jev compaction.
