---
trdd-id: RAEGS1D5
title: Jev compaction replaces the janitor's automatic compaction
column: dev
created: 2026-09-22T21:32:55+0200
updated: 2026-09-23T23:59:11+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-22T21:32:55+0200
npt: [541CBN36]
relevant-rules: []
implementation-commits: [051625a4, 0b883373]
eht: [CC0CZLMO, HWF3QFAB, 0UQSAFCW, 91D2VHW3, 1ETALGDG]
---

# Jev compaction replaces the janitor's automatic compaction

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-23

- 2026-09-24 CURRENT: landed since the morning: d4fa7685 (token budget keeps non-owner items), 23713d53 (per-item owner cap, decision items first on pointers). In flight: every decision item named in the FULL copy (compact pointers); the injected summary sized to the measured compose_handoff room. NEXT ACTION (full pre-publish path, per the owner's release scope below): land both, then cards 6 (88DOI824) and 7 (N9LDHF7N), then XI10BA5D (memgrep sole writer) and I63GQJTK (heartbeat progress line), then the final gate and the three real-session runs measured against section "Publish acceptance criteria".
- Cards 1-4 and card 5 (post-clear Jev injection, cooldown/recovery vetoes, hook-output caps) landed. NPT TRDD-541CBN36 closed 2026-09-23 after its last defect (OpenRouter 402/403 -> JevAuthError, 0b883373). The stale pane-key test was fixed in 051625a4; it had failed since the 2026-09-23 reader switch, and eba1f1ff landed on that red suite (process gap).
- Scope audit 2026-09-23 (reports/compaction-replacement/20260923_105904+0200-raegs1d5-scope-audit.md): 16 of 17 card-3/4 items done. Item 8 (fleet-lease renamed to compaction-lane, a lock on the automatic lane) DROPPED by owner decision 2026-09-23: the compaction only reads the closed session's transcript file, so no lock is needed; the manual llm-ext lane keeps its existing fleet lease unchanged.
- NO PUBLISH until a real-transcript Jev compaction passes on the FINAL tree (owner, 2026-09-23 evening: "don't publish until you tested the compaction of jev on a true session jsonl file from projects"). Derived by us, owner to confirm scope: the pass must fit the lane time limits (sync 60 s, detached 5-min budget), and the reference modules the gap analysis (reports/compaction-replacement/*-jev-reference-gap-analysis.md) marks as needed are adopted first (the owner said most reference functions are still not implemented). llm-ext cannot produce output on this machine until Emasoft/llm-externalizer-plugin#15 is fixed, so a Jev failure lands on the fact-only template; large sessions are rescued only by the 5-minute detached Jev attempt. SUPERSEDED (2026-09-23 morning), old next step: land the retry-then-llm-ext fallback (worker running), the extraction fix (task-notification records and heartbeat turns are not human; worker running), then TRDD for parallel batch scoring and the reference adoption; re-run the real-transcript test (4.7 MB took 10 s, 49 MB took 168 s on HEAD).
- Owner decisions 2026-09-23 (verbatim in "## Owner decisions 2026-09-23 (verbatim)" below): (1) NO LOCK on the automatic Jev lane — the owner's reason is that the compaction only reads the closed session's transcript; the residual risk of concurrent compactions hitting the OpenRouter rate limit is accepted and handled by retries. (2) Pane-key unification is NOT decided: the owner asked why; it was explained as optional tidy-up and proposed to leave it unless the owner asks; awaiting the owner. (3) If Jev is still not working after 5 minutes of failed retries, the llm-ext compaction MUST run as a fallback; this applies to ANY Jev failure, not only unrecognised errors, and no failure may pause compaction for 30 minutes. Retries must follow OpenRouter's documented error meanings (429 honouring Retry-After; 5xx/524/529/408 and transport errors retried with backoff within the 5 minutes). SUPERSEDED 2026-09-24 (implemented, 88aea2d9; scripts/lib/jev_compaction_lane.py::_NON_RETRYABLE_KINDS): 400/401/402/403/404/408/413/422 all fall back to llm-ext immediately (kind "auth"/"invalid") -- no 413-specific smaller-batch retry was adopted. (The owner's "no, absolutely" answered a double-negative question; it is read as "no 30-minute pause", which the owner's next sentence supports.)
- Supersession (owner, 2026-09-23): the llm-ext summary is allowed in the automatic lane ONLY as this fallback, which relaxes this card's "never generated prose" rule for the fallback case alone; /janitor-handoff-and-clear and /janitor-write-handoff are still never typed automatically.
- Follow-ups from the 402/403 fix: the JEV-AUTH-REJECTED headline says "key rejected" even for a 402 credits problem; the per-reason dedupe can re-fire if the 402 body text varies. Carded 2026-09-24: TRDD-JIYBKY27.
- OpenRouter's openapi.json documents these statuses for the decisions endpoint: 400, 401, 402, 403, 404, 413, 429, 500, 502, 503, 524, 529 (422 is not documented). SUPERSEDED 2026-09-24 (decision (b) landed, 88aea2d9): 400, 404, 408, 413 and 422 now raise JevValidationError -> stamped kind "invalid" (non-declining), and the probe-fail TTL is 5 minutes (PROBE_FAIL_TTL_S in scripts/jev_compact.py), not 30 -- verified against _stamp_kind_for_error in the source and against git log -S on scripts/jev_compact.py.




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

- 2026-09-22T21:32:55+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-23T06:08:54+0200 — column → dev by claude-main. Jev compaction work in progress: cards 1-4 landed (54ea73bc); post-clear injection fix and lease rename pending
- 2026-09-23T06:09:10+0200 — column → todo by claude-main. revert: orchestrator correction — 541CBN36 still owns an open defect, do not unblock RAEGS1D5 yet
- 2026-09-23T11:22:14+0200 — column → dev. NPT 541CBN36 closed; remaining scope: compaction-lane concurrency guard

## Design

- Card 1 loop/recovery guards (binding on this program, tracked under TRDD-L32WC0H7): **Recovery guard** — no Jev compaction fires while a rate-limit / API-error / compact resume is pending or was consumed less than N seconds ago (gate on the `dispatch._phase_compact_resume`, `_phase_clear_resume` and rate-limit-cleared state files); owner: "beware of ... truncating other operations, like resuming after api error or model expired time limit window".
- **Loop guard:** SessionStart with `source` in {`clear`, `compact`} never evaluates cache staleness (RESUME_SOURCES, pinned by a test); a failed compaction attempt records `evaluated` not `fired` (no cooldown burn, no hot retry); a hard cap of one automatic Jev compaction per session per `CLEAR_COOLDOWN` window, whatever the trigger.
No PRRD rule applies here (relevant-rules field left empty): checked prrdgrep's full board plus targeted searches for compact/clear/handoff on 2026-09-22, nothing constrains Jev compaction.

## Owner decisions 2026-09-23 (verbatim)

> 1. Should the automatic Jev compaction take a lock? Is it only reading the jsonl file, so if the agent is cleared and stopped, it should not write anymore in a closed session file. it should not be needed.I recommend no lock. 2. Should the janitor use one pane id everywhere? why? the janitor runs in many different terminal tabs or tmux sessions, so it should be one tab for each claude code instance. sometimes the tab will split in two panes to show the browser pane preview of the artifacts, but thats it. why using more pane? only one janitor per claude code, unless you are referring to the janitor daemon doing global chores, like rotating oauth keys or maintainance stuff? or the ai-maestro agents? 3. Should an unrecognised Jev error stop pausing compaction for 30 minutes? no, absolutely. if jev is not working after 5 minutes retries, the llm-ext compaction function must be called as a fallback.
> be sure to correctly understand the openrouter errors meaning and to retry accordingly for 5 minutes before falling back to llm-ext. but llm-ext must be used if jev is unavailable after 5 minutes.

## Owner directives 2026-09-23 evening (verbatim)

- Owner: "the jev powered compaction is still not working" — Evidence (ours): one cause is that the Jev commits were never released (v3.5.7 of 2026-09-17 carries no Jev code); a second, found the same evening, is extraction quality (below).
- Owner: "don't publish until you tested the compaction of jev on a true session jsonl file from projects" — Evidence (ours): HEAD tree, 4.69 MB transcript: exit 0, 9.6 s, 70/364 items, $0.0135; 49 MB transcript: exit 0, 168 s, 138/7075 items, $0.16 — over BOTH the 60 s sync and the 120 s detached timeouts, a release blocker; user-role records with origin.kind task-notification are extracted as human messages and dominate the digest.
- Owner: "but most of the functions of the reference repo are still not implemented! https://github.com/Waxmell114514/jev-compaction" — Evidence (ours): reference modules absent from our vendored jevctx: pipeline, segments, store, context, check, ledger, shadow; a gap analysis is running and will drive the rework.
- Owner: "llm-ext is the fallback in case jev fails" — confirms decision 3.
- Owner: "open an issue on the llm-externalizer repo (it should be Emasoft/llm-externalizer or Emasoft/llm-externalizer-plugin) and report all issues. but then focus on jev compacting and make it work" — filed Emasoft/llm-externalizer-plugin#15 (llm-ext session-summary spent 941 s on permanent 403s from harness-restricted free models and produced nothing, so the fallback cannot work on this machine until that is fixed).
- Owner: "wait to complete all before publishing." — Release scope decided: no publish until the Jev rework cards (incl. 6 segmentation, 7 decision log), the memgrep sole-writer card XI10BA5D and the heartbeat-progress card I63GQJTK are all done, then the final gate and the three real-session compactions pass on the final tree.

## Publish acceptance criteria (reviews of d4fa7685 and 23713d53, 2026-09-23)

- Measured on the FINAL tree, in the FINAL SessionStart hook stdout (not X.inject.md), on the 4.7 / 49 / 258 MB transcripts: hook stdout under 10,000 bytes and not cut by the compose_handoff byte slice; at least 3 non-owner items inline; the newest owner message present; wall time under 60 s (sync lane).
- In the FULL copy: at least 5 non-owner items; every decision-passing owner item inline or pointed to (0 absent), counted from the compact run's own item flags, never from a second scoring pass (the two disagree at the threshold).
- Corrections: the d4fa7685 message says its numbers were measured, but they came from the pre-review version; the 23713d53 message says LANE_COMPACTED_MAX_BYTES 6500 came "from the measured room", but 6500 is ABOVE the measured room (5,250 / 6,442 / 5,286 B), so the summary was sliced whenever the injected render exceeded the room (render sizes not measured) (being fixed: the room is computed first and passed as --inject-max-bytes). _OWNER_ITEM_TOKEN_CAP = 500 is unmeasured.
