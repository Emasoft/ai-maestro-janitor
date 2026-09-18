---
trdd-id: PH8SAQKS
title: Do not type a forced compact when the harness auto-compact is about to fire under autoCompactEnabled
column: testing
created: 2026-09-17T19:13:01+0200
updated: 2026-09-18T06:36:11+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T19:13:01+0200
priority: high
severity: major
eht: [ZXKJZLZK, OJK1MBU2, K0BIY8K2, PPQG9JVP]
implementation-commits: [9d72d6e7, 73254e33, 763b28e3]
---

# Do not type a forced compact when the harness auto-compact is about to fire under autoCompactEnabled

Issue 306 guard 2, the incident's ACTUAL window: the context guard typed /compact at 14:28:15 into a busy pane; once a keystroke is queued in Claude Code's input, no later still_wanted check can unsend it; the harness auto-compact started at 14:28:46 and the queued /compact ran on the compacted context. TRDD-4JEBTT2C (guards 1/3/4, commits 5da508b8 + 642e55fc) narrows the race between decision and typing but leaves this one open. Needed: read the session's autoCompactEnabled and CLAUDE_CODE_AUTO_COMPACT_WINDOW (user settings), compare the measured context to the harness threshold minus a margin, and when the harness will compact on its own send only the "prepare" nudge, never the /compact keystroke. Acceptance: a test where the measured context sits inside the margin under autoCompactEnabled=true results in no /compact send; outside it, the send proceeds. Origin: TRDD-4JEBTT2C final adversarial review 2026-09-17.

## Approval log

- 2026-09-17T19:13:01+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T20:42:58+0200 — dev → testing: cold_cache_compact.harness_will_autocompact + 2 call sites wired, compact_trigger.py PRECOMPACT_LAST_TRIGGER_FILENAME constant + terminal_trigger.read_landed_stamp rename; 10 new tests, pytest 67 passed, ruff/mypy/pyright clean; adversarial review round 1 fixed the margin-vs-raw-window bug (janitor-main-session via lean-worker)
- 2026-09-17T20:52:59+0200 — correction (coordinator): round-1 guard was unbounded above and dead-by-construction at both dispatch.py/on-stop-proactive-compact.py call sites (ctx there always >= min_context_tokens(), guard 2's own would-be upper edge); added an upper bound = min_context_tokens() to harness_will_autocompact, unwired those two call sites, wired guard 2 into compact_trigger.py::main() instead (the one caller that measures ctx before any floor gate); rewrote cold_cache_compact tests to derive band edges from the production functions; 4 new compact_trigger.py subprocess tests; gate re-run 72 passed / ruff+mypy+pyright clean (janitor-main-session via lean-worker)
- 2026-09-17T20:56:39+0200 — round-2 adversarial review: fork flagged guard 2 now covers every compact_trigger.py caller incl. --hard (accepted as directed by the round-2 fix instruction, documented in the docstring), an inverted-band edge case relying on check order (fixed: explicit invariant comment + test_guard2_inverted_band_fails_safe), re-measurement divergence vs the caller's own ctx reading (accepted/documented, same class of residual risk GUARD 1 already discloses), and a shared-oracle test tradeoff (accepted, named). Gate re-run 73 passed / ruff+mypy+pyright clean; file modes unchanged. Card stays in testing (janitor-main-session via lean-worker)
- 2026-09-17T21:05:16+0200 — round-3 correction (coordinator, review of 9d72d6e7): exempted --hard from guard 2 in compact_trigger.py::main() (band can sit below the >=85% emergency trip point on a small window; --hard's own automated caller was already removed per TRDD-11GAS4LC/7MGJYLY5, so this only protects a manual /janitor-compact-context --hard); moved the stdout token to cold_cache_compact.GUARD2_STDOUT_TOKEN (single source, both callers now import it) and taught both dispatch.py and on-stop-proactive-compact.py to log an explicit guard-2 line (no cooldown stamp, unchanged); inventoried every compact_trigger.py invoker (2 programmatic callers taught, 2 skills already document NO_ITERM as prose, no code change needed there). Minted follow-up observation card TRDD-OJK1MBU2 (spike, backburner, priority medium). Gate re-run 76 passed / ruff+mypy+pyright clean; file modes unchanged. Card stays in testing (janitor-main-session via lean-worker)
