---
trdd-id: JK2MLS8Z
title: The post-clear diagnostic measures context after the resumed session has read files and two handoff links do not resolve
column: testing
status: tasked
created: 2026-10-10T03:50:00+0200
updated: 2026-10-17T11:00:45+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:50:00+0200
implementation-commits: [cc01a57a]
---

# The post-clear diagnostic measures context after the resumed session has read files and two handoff links do not resolve

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN, step vi); not investigated beyond what is written here. scripts/handoff_clear_verify.py --phase after failed context_collapsed on three clears in a row: 2026-10-09 about 23:30, 2026-10-10 01:03 (535352 to 250654 tokens) and 03:08 (365149 to 239923, 65890 above the floor of about 174033). Each time the check ran minutes after the clear, after the resumed session had read the compacted copy and several cards, so it does not measure the context right after the clear; whether the clear itself reached the floor is unknown. On 03:08 handoff_links_resolve also failed for the first time: 2 of 41 links, both elided ids of tool results of the cleared session (reports/continuity-build/20261010_030813+0200-handoff-clear-verify.md, gitignored). To do: take the after-figure from the first assistant record of the new session, not from the time the check runs; find why two elided ids do not resolve.

## Approval log

- 2026-10-10T03:50:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 03:51 SCOPE NARROWED (one atomic task per card): this card keeps only the timing of the context measurement; the two unresolved handoff links moved to TRDD-AFW0CA65. The date 'about 23:30 on 2026-10-09' for the first of the three failures is taken from the drain card's text, not re-read.

## Corrections

2026-10-10 12:37 NOTE: the diagnostic's check 1 (cron_recreated) prints 'destroyed by /clear, recreated by re-arm' for ANY change of cron id, and every re-arm changes the id; on 2026-10-10 that wording was read as an observation and produced a wrong card line on TRDD-8SC3YEIG (withdrawn in 5d65a4ba). The check should say only that the id changed.
2026-10-17 BUILT in cc01a57a (column todo → testing). The collapse verdict now uses the first usage-bearing assistant record of the new session's transcript, picked by start time within 15 min after before['ts'], exactly one, ambiguous → SKIP; the live figure is no longer used in the after-phase. SessionStart injection is reported only (not in the threshold). cron_recreated wording fixed per the 2026-10-10 note. Full suite 18597 passed; ruff/mypy/pyright clean; report docs_dev/20261017_105736+0200-JK2MLS8Z-build.md. UNVERIFIED: that /clear always starts a new transcript file (seen once: 6feb5bae → 2bef3bfd); the hook-attachment layout (one transcript). FIELD PROOF: the next real clear's after-phase report shows context_source=transcript:first-assistant and a PASS when the first record is at the floor. Known nits left: candidate.stat() in _new_session_transcript is not guarded against a file vanishing mid-scan; two docstrings (_first_record_time, _session_start_injected_tokens) still describe the earlier never-accepted/allowance behaviour.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

- **2026-10-17: BUILT in cc01a57a, column testing** (moved from todo directly; the build ran in this session). After-phase judges the clear by the new session's first assistant record (start-time pick within 15 min after before['ts'], exactly one, ambiguous → SKIP); injection reported only. NEXT: field proof — the next real clear's after-phase report shows context_source=transcript:first-assistant and PASS at the floor. KNOWN LIMITATION: before['ts'] is taken by external_handoff_clear._snapshot_before (scripts/external_handoff_clear.py:560) BEFORE the chain spawns, and inject_until_sent may wait for the owner to go quiet (up to its giveup) before typing /clear; a wait over 15 min puts the successor outside the window → SKIP (safe, never a false PASS, but the clear goes unjudged). If field reports show such SKIPs, anchor the window on a stamp written at /clear submit. CORRECTION to cc01a57a's message: 'while the late reading failed' is not evidenced for the 2026-10-17 02:21 clear; late-reading FAILs are evidenced for the 2026-10-11 and 2026-10-14 clears (reports 20261011_012620, 20261014_031913). UNVERIFIED: /clear always starting a new transcript file (seen once); the hook-attachment layout (one transcript). NITS LEFT: unguarded candidate.stat() (a vanished file aborts the after-phase loudly); two stale docstrings, fixed in a follow-up commit.
