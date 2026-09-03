---
trdd-id: GK35MOXU
title: Adopt the PreModelSwitch/PostModelSwitch hooks as the first-party model-change trigger for the external clear
column: dev
created: 2026-09-01T19:26:25+0200
updated: 2026-09-03T10:05:00+0200
implementation-commits: [df26fa12, 73b242a8, 83e7242d]
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-2F3I2P18]
---

# The harness now EMITS the model-change event — stop polling for it

## Why (USER directive, 2026-09-01: "you said there is no model change event? wrong")

TRDD-2F3I2P18 detects a model/effort switch by POLLING `agentlenspro statusline-history raw`
and diffing the two newest rows. That was correct for the CC version it was written against.
**Claude Code 2.1.251 (installed: 2.1.252) added `PreModelSwitch` and `PostModelSwitch` hook
events** — the harness now tells us, at the instant of the switch, with no subprocess, no
agentlens dependency, no 2-row parse, and no per-session ambiguity.

## The design (mirror the reload-acked pattern exactly)

1. Add a `PostModelSwitch` hook to the plugin's `hooks/hooks.json` that appends/advances a
   `.janitor/state/model-switch-acked.ts` stamp (a generation int, exactly like
   `reload-acked.ts`) — cheap, no model turn.
2. Extend `external_clear.reload_invalidated`'s family with the same stamp (or fold it into
   `_read_reload_state` as a third name): unprocessed fresh ack ⇒ dead prefix ⇒ fire; the
   fire path's `consume_reload_events` consumes it. All the 2F3I2P18 semantics (tri-state,
   probe-does-not-consume, 10-min freshness) carry over verbatim.
3. Keep `prefix_invalidated` (statusline poll) as the FALLBACK for sessions on CC < 2.1.251
   and for effort-only switches IF the hook does not fire on effort change — VERIFY whether
   `/effort` fires PostModelSwitch before assuming either way; 2.1.251 also notes `/effort`
   now saves per-model defaults, so a model switch may imply an effort switch.
4. `PreModelSwitch` (can block/confirm) is deliberately NOT used to block — the janitor never
   vetoes the user's switch; it only reacts.

## Also from the same release — use in the resume gate

`SessionStart` resume hooks now receive **session staleness and the estimated re-cache cost**.
`should_clear_on_resume` currently infers coldness from transcript mtime + agentlens; the
hook payload is first-party ground truth. Wire it: on-session-start persists the two fields to
`.janitor/state/`, the resume gate prefers them when present.

## Acceptance

- [ ] PostModelSwitch hook ships in hooks/hooks.json and stamps the ack file (verified by a
      real `/model` switch on this machine, not just a unit test) — the SCRIPT shipped in
      `df26fa12` (subprocess test bumps 1→2) but the hooks.json REGISTRATION is DEFERRED:
      CPV's hook-event allowlist (v5.4.0 pin AND upstream main, checked 2026-09-01) predates
      CC 2.1.251 and rejects the event as CRITICAL, blocking the publish. Filed upstream:
      claude-plugins-validation issue 222. Re-add the hooks.json entry once a CPV release
      knows the event; the script is inert until registered, so nothing half-works meanwhile
- [x] the external-clear gate fires on the stamp with the consume-on-fire semantics
      (`df26fa12`: third stamp name in `_read_reload_state`; probe/consume tests)
- [ ] measured whether `/effort` fires the hook; fallback poll retained or retired accordingly,
      with the finding written into the card
- [ ] SessionStart staleness + re-cache cost persisted and preferred by the resume gate —
      HALF DONE: the resume hook now defensively persists every stale/cache/cost payload
      scalar to `session-staleness.json` (field names are the harness's, undocumented; one
      live 2.1.251+ resume payload on disk will name them). The gate-side consumer binds to
      the real names then
- [ ] pytest + ruff + mypy green

## Notes and lessons learned

- The lesson that produced this card: a trigger design claim ("no event exists, we must poll")
  has a shelf life of one harness release. Re-read the changelog BEFORE building a poller.
- **The paid-detector (`83e7242d`)**: the invariant that makes a clear free is "no turn ran
  since the prefix died", not "the prefix died recently" — a mid-conversation `/model` switch
  is re-paid by the very next turn (heartbeats included), so a fresh-but-paid event is
  consumed silently, exactly like a stale one. Firing on it would clear a WARM session.
- **Bounded residual of the 10s paid-slack (`f05ab464`, review-fork, no action)**: an idle
  switch followed by a trivial turn completing within 10s leaves the event armed on a warm
  session; if every veto passes, the cost is ONE spurious handoff-and-clear at idle (capped
  by consume-on-fire + the fired cooldown, and llm-ext costs zero Claude-side tokens). The
  10s value is an unmeasured knob — recalibrate when the live verify observes a real
  switch's append timing. Boundary proven at exactly the constant (9s fires, 11s paid).
- **Pre-existing cross-session ceiling (review-fork, no action)**: the ack stamps are
  per-PROJECT and the watcher clears the one RECORDED pane, so with two sessions in one
  project, session B's switch can trigger a clear aimed at session A. Same holds for the
  reload stamps since birth; a per-session stamp keyed on session id is the upgrade if it
  ever bites.

## Approval log

- 2026-09-03T10:05:00+0200 — UNBLOCK (blocked → dev) by janitor-main-session acting for USER
  (delegation 2026-09-03 09:58). `blocked-by: claude-plugins-validation#222` is CLOSED
  (COMPLETED) — verified `gh issue view 222 --repo Emasoft/claude-plugins-validation --json state`
  → `CLOSED`. Restored to `pre-block-column: dev` per
  `reports/board-drain/20260903_091543+0200-blocked-cards-audit.md`.
