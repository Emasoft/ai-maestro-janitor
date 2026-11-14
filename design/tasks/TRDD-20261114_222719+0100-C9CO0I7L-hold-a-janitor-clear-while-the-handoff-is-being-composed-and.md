---
trdd-id: C9CO0I7L
title: Hold a janitor clear while the handoff is being composed and trace the duplicated handoff sections (issue 356)
column: todo
status: tasked
created: 2026-11-14T22:27:19+0100
updated: 2026-11-14T22:27:19+0100
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
---

# Hold a janitor clear while the handoff is being composed and trace the duplicated handoff sections (issue 356)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: build the compose in-flight stamp and the two decision-site checks described below, one bounded change, tests written, run only before the push. Part 2 (duplicated handoff sections) is NOT a janitor bug: file an issue on Emasoft/llm-externalizer after one real reproduction; add no de-duplication workaround here.
- Status: not started. Parent work: TRDD-V8GWJVFN (F1 landed, which already prevents the 356 sequence on its own); GitHub issue 356. Related: TRDD-AIT2KNBU (F2+F3).

## Part 1 - hold the clear while /janitor-write-handoff composes

Verified: scripts/compose_agent_handoff.py runs synchronously up to _SUMMARY_BUDGET_S (15 minutes, about L53 and L79) and writes the handoff file once (about L102-103, marker plus text). While it runs there is no lock or stamp, and its docstring (L22-27) says deliberately no hold. Neither on-stop-token-meter.py _maybe_clear nor clear_trigger._agents_and_interrupt_ok reads anything about it. The fleet lease in llm_ext_summary (ec.await_fleet_lease) is machine-wide and cannot be attributed to a session.

Fix: compose_agent_handoff.py writes state_dir/handoff-compose-inflight.json {pid, started, key} with state.atomic_write before summarize_with_retry and removes it in a finally. New pure probe handoff_files.compose_inflight(sd, now): stamp present, pid alive (os.kill(pid, 0)), age under _SUMMARY_BUDGET_S plus 60 s. _maybe_clear defers like live agents (log "clear deferred: handoff compose running"), only below the ceiling like today; _agents_and_interrupt_ok cancels the chain (it re-fires at the next Stop). When the compose finishes and the Stop hook re-fires, the dedicated hook's _recent_model_handoff (on-session-start-post-clear-compact.py about L135) already finds a handoff written within 300 s of the transcript mtime and names it ("Handoff you wrote before the clear").

Test T7 tests/test_compose_inflight.py (real, no mocks): spawn a real sleep child, write the stamp with its pid, assert the probe is True; kill the child, assert False; stale started, assert False; real _maybe_clear with the stamp present logs deferred and spawn_shrink_chain is not reached (observe via the token-meter log, not a stub).

## Part 2 - duplicated sections in the handoff (issue 356)

Verified NOT produced by janitor code: compose_agent_handoff.py builds marker plus text once; handoff_files.write (about L127-161) does one atomic_write of the given text (its only merge logic is the identical-text no-op); llm_ext_summary.attempt_llm_ext_summary takes proc.stdout.strip() of llm-ext session-summary --stdout --transcript X as-is; summarize_with_retry never concatenates. The origin is therefore most likely the llm-ext session-summary output (outside this repo; NOT run: paid and slow). Unverified. Action: reproduce with one real llm-ext session-summary --stdout run on a long transcript, count lines matching ^## duplicates, then file an issue on Emasoft/llm-externalizer with the reproducer. Do NOT add a de-duplication workaround in the janitor (fail-fast rule).

Files for part 1: scripts/compose_agent_handoff.py, scripts/lib/handoff_files.py, scripts/hooks/on-stop-token-meter.py, scripts/clear_trigger.py.

## Approval log

- 2026-11-14T22:27:19+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
