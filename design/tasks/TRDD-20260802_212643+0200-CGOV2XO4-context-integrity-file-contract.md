---
trdd-id: CGOV2XO4
title: Write the context-integrity file the ai-maestro wake gate reads
column: blocked
created: 2026-08-02T21:26:43+0200
updated: 2026-08-22T12:02:05+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
external-refs: [167, ai-maestro#151]
blocked-by: [ai-maestro#151]
pre-block-column: todo
implementation-commits: []
---

# Context-integrity file contract — janitor writes, ai-maestro server reads (janitor#167)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Filed from the ai-maestro Claude's design decision on janitor#167
(2026-08-02): the previously-blocking "CLI flag for contextPoisoned" is WITHDRAWN by its
owner — a refuse-a-wake verb is a denial-of-service primitive with no expressible
authorization (the janitor's scripts carry no AID), so the server side replaced it with a
FILE contract, the proven `server-liveness.json` pattern INVERTED:

- **`~/.aimaestro/context-integrity.json`** — the JANITOR writes, the SERVER reads.
- Shape (from the peer's comment; confirm the final schema on the issue before building):
  `{ "ts": <epoch-s>, ... }` plus the per-workdir poisoned reason.
- The janitor side is thin: `scripts/detectors/agent-context-integrity.py` ALREADY
  computes `poisoned_reason(findings, cap)` — "The contextPoisonedReason string for the
  ai-maestro wake gate (janitor#167)". What is missing is only the atomic write of the
  file (bounded, per-workdir, ts-stamped, atomic_write; clear/refresh semantics so a
  healed workdir stops being blocked — a stale poisoned claim is itself a DoS).

## ⛔ 2026-08-22 — THE BLOCKER NAMED A DEAD CHANNEL. Re-asked as `ai-maestro#151`.

`blocked-by` read `ai-maestro-schema-decision-janitor#167`. **janitor#167 has been CLOSED since
2026-08-12**, and — this is the part that matters — it closed on an unrelated claim: *"the
automatic scan exists … this issue's specific claim, that nothing scans automatically, no longer
holds."* The schema decision this card waits on was never delivered there and now never will be.

**The janitor's half was NOT the missing piece — verified, not assumed.** I expected to find that
the (a)/(b) answers below had never been sent, and that was wrong: a comment on janitor#167 does
carry them. So the sequence is: we answered, the decision did not come back, the channel closed
for other reasons, and the card kept waiting on an issue that had stopped being able to help.

**This is the SECOND card today whose blocker resolved without answering** (the first was
TRDD-JPL0JU86, waiting on AZ6QRK0D, which closed on a privacy-gate question and never made the
direction call). The shared failure is that `blocked-by` records WHERE an answer was expected,
never WHETHER it arrived — so a closed blocker reads as progress from the board, and only opening
the issue reveals it closed on something else. Worth checking the closure REASON, not just the
state, whenever a blocker clears.

Re-asked on the owned repo as **`Emasoft/ai-maestro#151`**, carrying (a) and (b) restated so the
issue stands alone, plus the concrete per-workdir proposal (one file per workdir instead of one
shared `findings[]` array — it makes the 23-writer problem structural rather than managed). The
card stays `blocked`, now against a LIVE question. No urgency was implied: it has been parked
since 2026-08-02 and can stay parked; it just should not be parked against a closed issue.

## 2026-08-13 — picked up, NOT built. Two verified findings changed the shape of the ask.

Building the sketched schema today would have shipped a cross-project data-loss bug. Both
findings below are read from code, not inferred.

### (a) The answer the peer asked for THREE times: the scan is SESSION-SCOPED, not fleet-wide

`scripts/detectors/agent-context-integrity.py::main` scans `state.project_root()` — one root,
the session's own — and it is registered in `dispatch.py:196` on the per-project heartbeat
(1800 s). There is no fleet enumeration anywhere in it.

So it is **the weaker outcome the peer named**: the flag is written from inside an
already-poisoned session and the gate blocks the NEXT wake. It is NOT a launch gate, and per
their own words neither side may describe it as one. Fleet-wide is *possible* later — the
machinery exists (`harness_backend.agent_workdirs` / `recall_agent_roots`) — but it is not what
the code does today, and the peer has been waiting on this sentence since 2026-08-02.

### (b) ONE SHARED FILE IS UNSAFE — the janitor is a concurrent multi-writer

The sketched `~/.aimaestro/context-integrity.json` holds a `findings[]` array spanning workdirs.
But the janitor is USER-scope: it runs in EVERY project, and each project's heartbeat runs this
detector independently. A live fleet scan the same night enumerated **23 running claude
instances**. So every project's janitor is a writer to that one path, and a whole-file write
**erases every other project's findings** — a poisoned workdir silently becomes clean because an
unrelated project happened to scan last. Read-modify-write does not save it: no lock spans those
processes, and a crashed janitor leaves stale foreign entries nobody can attribute.

It also cuts against this repo's per-project isolation invariant, and cross-project bleed is a
defect class already fixed here once (`janitor-per-project-channeling`).

**Proposal to match instead: one file PER workdir** —
`~/.aimaestro/context-integrity/<workdir-slug>.json`, each written atomically by exactly one
writer, the server globbing the dir. Self-clearing becomes trivial and local (a healed workdir
rewrites its OWN file with `findings: []`), no lock is needed, no writer can affect another's
claim, and a stale entry is attributable to one workdir.

### (c) The staleness window never blocked our half

It is a READER-side policy: the janitor writes `ts`, the server decides what age means. So
schema question (2) was never a blocker for the write side — only (1), the keying, is, and (b)
is a concrete argument for resolving it as per-file.

**Status: blocked on the cross-repo keying decision.** A reply carrying (a), (b) and (c) is
drafted and queued behind the user's GitHub-output gate; the janitor half is ~an hour once the
keying is agreed.

## Steps

1. Read janitor#167's full thread for the final agreed schema (the peer names the file
   and the inversion; nail field names + staleness window + multi-workdir keying).
2. Reply consensus on the issue BEFORE building (peer-consensus rule) — done at filing
   time; re-confirm if the schema moved.
3. Implement the write in agent-context-integrity.py (atomic, fail-open, self-clearing);
   pin with tests incl. the heal-clears-the-claim direction and the staleness bound.

## Verification

- Poisoned scan ⇒ the file appears with the reason + fresh ts; healed scan ⇒ the claim
  clears; a stale file past the agreed window is ignorable by the server (ts present).

## Notes and lessons learned
