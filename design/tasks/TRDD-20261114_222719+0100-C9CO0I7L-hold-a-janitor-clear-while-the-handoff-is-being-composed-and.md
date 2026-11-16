---
trdd-id: C9CO0I7L
title: Hold a janitor clear while the handoff is being composed and trace the duplicated handoff sections (issue 356)
column: testing
status: tasked
created: 2026-11-14T22:27:19+0100
updated: 2026-11-16T10:27:51+0100
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
approval-datetime: 2026-11-14T22:27:19+0100
implementation-commits: [ef433a58]
---

# Hold a janitor clear while the handoff is being composed and trace the duplicated handoff sections (issue 356)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: live check owed. One janitor clear that reaches a decision site while /janitor-write-handoff composes must log 'clear deferred: handoff compose running' (token-meter) or cancel the chain with that reason; auto clear is off on this host, so this waits on a host or session with it on. Part 2 (duplicated handoff sections) is NOT a janitor bug: file an issue on Emasoft/llm-externalizer after one real reproduction; add no de-duplication workaround here.
- Status: Part 1 landed in ef433a58 (column testing); Part 2 not started. Parent work: TRDD-V8GWJVFN (F1 landed, which already prevents the 356 sequence on its own); GitHub issue 356. Related: TRDD-AIT2KNBU (F2+F3).
- 2026-11-16 Part 1 landed in ef433a58: a per-session stamp handoff-compose-inflight-<key>.json held by compose_agent_handoff.py; handoff_files.compose_inflight(state_dir, key); the Stop-hook _maybe_clear defers below the ceiling, and the chain's _agents_and_interrupt_ok returns not-ok, which _still_wanted (clear_trigger.py:1001-1003) turns into a cancel; the next Stop's _maybe_clear re-evaluates (tested). Both sides key through session_key() (composer from CLAUDE_CODE_SESSION_ID, clear side from <session-id>.jsonl); the state dir is the project root from CLAUDE_PROJECT_DIR on all three sides (composer via the skill's --project-root, hook at on-stop-token-meter.py:217). Known limits: at or above the clear ceiling a clear still fires; two composes in one session share one stamp. Test deviation: tests/test_compose_inflight.py stubs only clear_trigger._spawn_chain, the pane-typing point the sibling tests also stub. Live check owed: auto clear is off on this host, so no real clear has exercised the hold. Part 2 stays: reproduce once with llm-ext and file on Emasoft/llm-externalizer.
- 2026-11-16 key check: this session's CLAUDE_CODE_SESSION_ID key equals its transcript stem key (5d861615), also after a compaction. Chain side: the Stop-hook caller passes transcript_path (on-stop-token-meter.py:201) and spawn_shrink_chain sets JANITOR_TRANSCRIPT_PATH for the chain (clear_trigger.py:1285); the dispatch, reload and reload-skills callers were judged from their comments only (inferred). No test covers the chain-side key.
- 2026-11-16 — Part 1 (commit ef433a58) is first released in v3.9.7 (git tag --contains ef433a58 lists v3.9.7 and ai-maestro-janitor--v3.9.7, the two tags of the same release, and no earlier tag). Still owed: the live check (auto clear is off on this host) and Part 2.
- 2026-11-16 Part 2 closed, no issue filed (supersedes the Part 2 action in NEXT ACTION; only the Part 1 live check is still owed): the repeated section set is not a duplicate. The 2026-11-14 handoff in the llm-externalizer project (.janitor/state/agent-handoff-4d6eccc3-20261114_191341+0100-87078.md, 140 lines) has "--- Part 1 of 2 ---" at line 2 and "--- Part 2 of 2 ---" at line 66, and the two parts summarize different stretches of the session (part 2 opens by saying it continues from a compacted earlier part). llm-ext joins its per-chunk summaries that way on purpose: joinChunkSummaries (scripts/llm-ext/src/session_summary/driver.ts:1293 in the llm-externalizer repo, whose separator dates from de8cc80b of 2026-08-11, so the 2026-11-14 run already used it) concatenates them under that separator so that no second model call can drop a fact. Follow-up filed as TRDD-G3DB7NCW: a resuming reader should take Next Step from the LAST part; nothing in the janitor's resume text says so.

## Part 1 - hold the clear while /janitor-write-handoff composes

Verified: scripts/compose_agent_handoff.py runs synchronously up to _SUMMARY_BUDGET_S (15 minutes, about L53 and L79) and writes the handoff file once (about L102-103, marker plus text). While it runs there is no lock or stamp, and its docstring (L22-27) says deliberately no hold. Neither on-stop-token-meter.py _maybe_clear nor clear_trigger._agents_and_interrupt_ok reads anything about it. The fleet lease in llm_ext_summary (ec.await_fleet_lease) is machine-wide and cannot be attributed to a session.

Fix: compose_agent_handoff.py writes state_dir/handoff-compose-inflight.json {pid, started, key} with state.atomic_write before summarize_with_retry and removes it in a finally. New pure probe handoff_files.compose_inflight(sd, now): stamp present, pid alive (os.kill(pid, 0)), age under _SUMMARY_BUDGET_S plus 60 s. _maybe_clear defers like live agents (log "clear deferred: handoff compose running"), only below the ceiling like today; _agents_and_interrupt_ok cancels the chain (it re-fires at the next Stop). When the compose finishes and the Stop hook re-fires, the dedicated hook's _recent_model_handoff (on-session-start-post-clear-compact.py about L135) already finds a handoff written within 300 s of the transcript mtime and names it ("Handoff you wrote before the clear").

Test T7 tests/test_compose_inflight.py (real, no mocks): spawn a real sleep child, write the stamp with its pid, assert the probe is True; kill the child, assert False; stale started, assert False; real _maybe_clear with the stamp present logs deferred and spawn_shrink_chain is not reached (observe via the token-meter log, not a stub).

## Part 2 - duplicated sections in the handoff (issue 356)

Verified NOT produced by janitor code: compose_agent_handoff.py builds marker plus text once; handoff_files.write (about L127-161) does one atomic_write of the given text (its only merge logic is the identical-text no-op); llm_ext_summary.attempt_llm_ext_summary takes proc.stdout.strip() of llm-ext session-summary --stdout --transcript X as-is; summarize_with_retry never concatenates. The origin is therefore most likely the llm-ext session-summary output (outside this repo; NOT run: paid and slow). Unverified. Action: reproduce with one real llm-ext session-summary --stdout run on a long transcript, count lines matching ^## duplicates, then file an issue on Emasoft/llm-externalizer with the reproducer. Do NOT add a de-duplication workaround in the janitor (fail-fast rule).

Files for part 1: scripts/compose_agent_handoff.py, scripts/lib/handoff_files.py, scripts/hooks/on-stop-token-meter.py, scripts/clear_trigger.py.

## Approval log

- 2026-11-14T22:27:19+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
