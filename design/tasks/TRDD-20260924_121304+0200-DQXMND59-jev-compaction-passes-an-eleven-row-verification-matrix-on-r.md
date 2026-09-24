---
trdd-id: DQXMND59
title: Jev compaction passes a twelve-row verification matrix on real transcripts before release
column: todo
created: 2026-09-24T12:13:04+0200
updated: 2026-09-24T13:29:58+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: audit
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T12:13:04+0200
---

# Jev compaction passes a twelve-row verification matrix on real transcripts before release

Owner, 2026-09-24: "continue testing the jev compaction, make it flawless". Release gate for TRDD-RAEGS1D5. The matrix gates the release only after TRDD-BLGZTHQ9 and TRDD-U6C3YXEL have landed and been re-measured: until then V1's "no injected tool item is a truncated prefix" fails by design.

| id | what | pass condition |
|---|---|---|
| V1 | 7 real transcripts spanning sizes: ~0.3 MB, 6.4 MB (b2bf5b7b), 17 MB (fd5cc3e0), 49 MB (d30bf250), 96 MB (35e1e917), 183 MB (c8a95d7e), 258 MB (4eb7bf5d) | per run: exit 0, source jev, final hook stdout < 10,000 B, not sliced, wall < 60 s, newest real owner message present, no injected tool item is a truncated prefix, the path appears once |
| V2 | every pointer in the injected AND full copies expanded with the exact trailer command; every "--list --grep" instruction run as worded | exit 0 and non-empty original text for each; zero failures |
| V3 | the real SYNC hook (scripts/hooks/on-session-start-post-clear-compact.py) end to end with a real sidecar and SessionStart payload | its stdout is what gets injected; same limits as V1 |
| V4 | the DETACHED lane (scripts/summarize_previous_session.py --transcript) end to end | handoff file written in the scratch state dir; same limits |
| V5 | timing variance: the 258 MB run 3 times | every run under 60 s; report min/max |
| V6 | failure paths: bad key (401/402/403), 429 with Retry-After, 5xx, network down, a firewall-blocked batch | the documented retry-then-fallback behaviour; never a crash, never a silent empty injection; the template handoff when both fail |
| V7 | edge transcripts: empty file, one owner message, tool calls only, one 5 MB tool result, non-UTF-8 bytes, a truncated last line, base64 images | exit 0 or a clean, named decline; never an exception; never an over-budget output |
| V8 | determinism: the same transcript twice with cached scores | identical selection and card-list order |
| V9 | isolation: run from the scratch dir | no file written under the real repo's .janitor/state |
| V10 | the content read by hand for every V1 run | a resumed session can tell (a) the owner's last request, (b) what the session did, (c) what is next; every stated owner decision is inline or pointed at |
| V11 | the cards section (TRDD-O2FNJ4KW) | the cards the session worked are listed first; the other open ids are named as many as fit in the capped line (ids part 300 B, line about 340 B), then the rest are counted |
| V12 | the no-sidecar fallback (scripts/hooks/on-session-start.py) end to end: a clear flag, NO per-pane sidecar, and a foreign or legacy handoff as the newest file in the state dir | stdout is a pointer line naming that handoff, never its body (the path 737b4d6c changed; TRDD-4P4Y2KBR) |

## Approval log

- 2026-09-24T12:13:04+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
