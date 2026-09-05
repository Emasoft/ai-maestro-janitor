---
proposal-id: c4fed1f2-c0c2-45ab-8b61-2916f0dfff22
proposes: revise
target-rule: null
target-kind: silver
proposed-by: unknown
routed-via: null
status: open
created: 2026-09-05T10:45:19+0200
updated: 2026-09-05T10:45:19+0200
---

# Proposal: A card in `testing` may be BUILT and waiting on a LIVE EVENT nobody can cause (a

## Rationale

<explain WHY this change is proposed>

## Proposed text

```
A card in `testing` may be BUILT and waiting on a LIVE EVENT nobody can cause (a rate-limit wall, a real compaction, an automated clear); that is a legitimate use of `testing`, NOT a stall. Every such acceptance box MUST start with `LIVE:` and name the event and the ARTEFACT that proves it — a log-line pattern or a JSON key, never a path, because report paths are gitignored and machine-local — so the board can tell an actively-tested card from one waiting for the world. A box that describes the WORK instead of the WAIT is how a live-event wait hides (TRDD-5OR85VHP, 2026-09-05).
```

## MANAGER decision

<populated by MANAGER on review: accept | reject | forward-to-user>
