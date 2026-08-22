---
trdd-id: 739N4CUF
title: Close the janitor to-server OAuth-rotation ownership gap — never yield a chore the server has disabled
column: refused
approval-tier: 2
created: 2026-07-23T18:32:18+0200
updated: 2026-08-22T10:52:00+0200
external-refs: [janitor#134, ai-maestro#111, ai-maestro#95]
current-owner: main-session
task-type: bugfix
scope: project
relevant-rules: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-23

- **THE BUG (verified live 2026-07-23 ~18:2x):** the janitor daemon YIELDS all OAuth chores to the
  ai-maestro server whenever the server's liveness file is fresh (binary switch, TRDD-LU0C5KAR,
  owner directive 2026-07-17). But the server's OWN OAuth rotator (`~/ai-maestro/lib/oauth-rotator/
  *.ts`) is **gated OFF by default** — it runs only if `~/.aimaestro/oauth-rotator-tick.enabled`
  exists, and that flag is ABSENT. The server-liveness file even advertises `capabilities: []`
  (empty). Net result: the janitor won't rotate (it defers) and the server won't rotate (its tick
  is disabled) → **rotation is ownerless**. This is the recurring "the rotator fails when it is
  needed most" the owner has hit repeatedly; the latest cost a live scenario + its agents.
- **WHY THE CURRENT DESIGN ALLOWS IT:** TRDD-LU0C5KAR made ownership BINARY on server LIVENESS and
  declared the `capabilities` list "informational" — "a running server that does not execute an
  absorbed chore is a server bug, never a janitor guard." That rationale is defensible in
  isolation, but empirically it produces a silent ownerless gap: the server being ALIVE is not the
  same as the server DOING the chore, and here the server truthfully advertises `capabilities: []`.
- **NEEDS OWNER APPROVAL (Tier 2):** this proposal REVERSES an explicit owner directive (the binary
  switch). It must not be implemented until the owner approves. Captured now so the decision + the
  design are tracked and ready.
- **NEXT ACTION:** owner decides between the options below; on approval, implement the chosen one.

## Proposed fix (owner picks)

**Option A — capability-gated yield (durable, recommended).** The janitor yields an OAuth chore
ONLY when the live server actually advertises it can do that chore (a non-empty, matching
`capabilities` token) — NOT merely because the server is alive. When the server is alive but
advertises `capabilities: []` (or omits the oauth-rotation token), the janitor RUNS the OAuth
chores itself. This makes "alive" and "owns the chore" distinct, closing the gap by construction.
It is a targeted refinement of `harness_backend.server_runs_chores()` / the per-chore gate, not a
wholesale removal of the binary switch — the switch still governs chores the server DOES advertise.

**Option B — notify-only safety net (minimal, non-reversing).** Keep the binary switch, but when
the janitor yields to a server whose OAuth capability is absent AND rotation state is stale, raise
a HIGH `notify.py` desktop notification ("rotation is ownerless — the server's OAuth tick is
disabled") so the human is told immediately instead of the gap staying silent. Does not reverse the
directive; surfaces the gap rather than closing it.

**Option C — both:** A (close the gap) + B (tell the human when a yield would otherwise be silent).

## Acceptance criteria

1. With a fresh server-liveness advertising `capabilities: []` and no `oauth-rotator-tick.enabled`,
   the janitor daemon RUNS the OAuth rotator tick itself (Option A) and/or emits a HIGH notify
   (Option B) — proven by an isolated test that seeds those exact conditions.
2. With a server advertising the oauth-rotation capability, the janitor still YIELDS (the binary
   switch's valid case is preserved — no regression).
3. File locks still prevent janitor+server double-rotation during any handoff window.
4. pyright 0 new / ruff clean / full `pytest tests/` green / `~/.claude` untouched (S1a/S1b/S1e).

## Approval log

- 2026-07-23T18:32:18+0200 — Authored as a PROPOSAL (Tier 2). Reverses/《refines》the owner's
  2026-07-17 binary-switch directive (TRDD-LU0C5KAR), so it waits for owner approval. Root cause
  verified live: server OAuth tick gated off (flag absent) + janitor binary-yields = ownerless
  rotation. Related: TRDD-GZXTSJSR (proactive login nudge — the keep-tokens-fresh half).
- 2026-08-22T10:52:00+0200 — REFUSED as MOOT, which is not the same as declined on its merits,
  and the difference matters enough to write down. **Option A shipped** — under the owner's
  janitor#134 ruling (2026-08-05), months before this proposal was ever reviewed:
  `harness_backend.claimed_chores()` yields a chore only when the live server actually advertises
  it, which is exactly what this card proposed. So the card sat asking for a decision whose
  subject had already been decided and built by another route. **Refusing it does not unship
  anything**, and no one reading this should revert that code.
  What survived was the ai-maestro-side half — "advertise `capabilities` accurately and treat a
  claim as a commitment to execute" — and that is now FILED, on the existing open
  `Emasoft/ai-maestro#111`, together with the measured switching latencies (server appears →
  janitor yields ≤60 s; server vanishes → janitor reclaims ~150 s, covered meanwhile by the
  cross-process locks). Filed as a comment on the open issue rather than a new one, because #111
  and #95 already cover this subject and a third would be noise on a peer's tracker.
  The USER's 2026-08-22 ruling (#5) pointed the other way — "server running ⇒ the janitor stops
  its global functions" — and was deliberately NOT implemented literally, because a binary
  alive-switch is precisely what produced #111. The reasoning was posted there rather than acted
  on unilaterally. If the owner still wants the binary form after reading it, that is a NEW card
  against that incident, not this one.
