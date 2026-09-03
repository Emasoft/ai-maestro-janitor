---
trdd-id: L32WC0H7
title: session-liveness ESC nudge loops on a dead credential and the cold-cache gate types /clear into an empty session
column: todo
created: 2026-09-03T15:25:14+0200
updated: 2026-09-03T15:25:14+0200
current-owner: ai-maestro-janitor main session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
relevant-rules: []
related-trdds: [UA4FAX67, WKTD5JTC, P7WU40G9, O7UCNNN2, G043V3V0, 9ZPU69UC]
npt: []
eht: []
---

# session-liveness ESC nudge loops on a dead credential and the cold-cache gate types /clear into an empty session

## Symptom (owner report, 2026-09-03)

An armed session showed sixteen consecutive `Running scheduled task … ⎿ Interrupted · What
should Claude do instead?` rows between 12:26 and 15:10, then `❯ /clear [name]` sitting typed
in the prompt of a 0 % context session. Nothing was recovered; the owner had to run `/login`.

## Root condition (not a janitor defect, but the precondition)

From ~11:46 every API turn of the session stalled. `.janitor/state/rate-limited.flag` was
stamped 11:56:14; `daemon.log` carries `notify[OAUTH-PRIMARY-UNREADABLE]` 73 times since
03:04 (the rotator could not read the primary credential, so no rotation happened). The
heartbeat stub never ran again after 11:36:56 (`dispatch.log` last write) — every fire hung
inside the model request with zero output. `/login` at ~15:12 ended it.

## Defect 1 — the `frozen` esc_nudge is self-resetting and fires forever

Evidence, `daemon.log` (all `[frozen] attempt=0`): 12:22:06, 12:42:47, 13:03:25, 13:24:42,
13:45:45, 14:06:52, 14:27:27, 14:48:06, 15:10:49 → a fire every ~21 min, never escalating.

Mechanism, verified in code + transcript:

1. A hung turn appends nothing, so after `STALE_S` (15 min at */5) `transcript_stale` trips
   (`fleet_scan.py:1116`); `rate-limited.flag` present ⇒ `diagnose_instance` → `frozen`
   (`session_liveness.py:448`) ⇒ `recovery_action_for` → `esc_nudge`.
2. `esc_nudge` sends **two** ESCs 2 s apart (`terminal_trigger.py:97 HARD_INTERRUPT_ESC_COUNT
   = 2`, `fleet_inject.iterm_esc_only_osascript`). ESC #1 kills the hung turn; the REPL goes
   idle; the `*/5` cron fires **immediately** (it was overdue); ESC #2 kills that fresh fire.
   Transcript proof: `[Request interrupted by user]` 10:42:49Z, `scheduled_task_fire`
   10:42:49Z, `[Request interrupted by user]` 10:42:50Z. That is why the rows come in pairs.
3. The fire the ESC provoked advanced the transcript ⇒ next beat the pane reads `healthy`
   ⇒ the recovery episode resets ⇒ the next stall is `attempt=0` again. The ladder, its
   cooldown and the `GIVING UP … after 4 attempts` guard (which did engage for AgentlensPro,
   0→4) never engage here: **the recovery's own side effect resets its counter**.
4. Each ESC-provoked fire also counted as "the session took a real turn Ns ago — the user is
   back" and cancelled the pending `/clear` chain six times (`clear-trigger.log` 13:24:47 →
   15:10:54), so the two chores fought each other for three hours.

## Defect 2 — the cold-cache gate reads a pre-`/clear` context size and leaves `/clear` typed

- `external-clear.log` (global-state): `fired: trigger=cache-certain-expired` at 14:15, 14:20,
  14:35, 14:45, 15:00 on this root, while the session sat at 0 %.
- The gate's `context_tokens` = `cold_cache_compact.context_tokens_for(newest)` =
  `token_meter.latest_context_size` = the newest usage-bearing assistant message in the
  transcript tail (`token_meter.py latest_context_entry`). After the 12:22 `/clear` the
  session produced **no** assistant message, so the reading is the pre-clear size. There is
  no `/clear`-boundary check anywhere in `token_meter.py`. `cache_expired` was genuinely
  true (no completed turn since 11:46), so the gate passed on a wrong `context_tokens`.
- `inject_until_sent` (`terminal_trigger.py:766-770`) re-asks `still_wanted` at the top of
  every loop iteration, **after** `type_fn()` may already have typed the command on a prior
  iteration, and the cancel return does not call `clear_fn()` (only the settle-failure branch
  at :872-880 does). Result: `/clear` left in the prompt field.

## Fix plan (one TRDD, four bounded edits — all in `scripts/lib/`)

- [ ] **F1 `fleet_recovery` / `session_liveness`** — an esc_nudge episode must persist
      across the transcript refresh it causes: key the attempt counter on the
      `rate-limited-since.ts` epoch (the stall episode), not on "transcript went fresh", and
      cap `frozen`-with-flag nudges per episode (reuse `GIVING UP` at 4). Derived: a pane
      whose flag epoch never changes and whose turns keep stalling is a credential problem →
      emit ONE finding (`OAUTH-DEAD-CREDENTIAL` or reuse `OAUTH-PRIMARY-UNREADABLE`) instead
      of a keystroke.
- [ ] **F2 `terminal_trigger.iterm_esc_lines` callers** — the esc-only recovery plan sends
      ONE ESC when a cron is armed for the pane (the second ESC is what kills the provoked
      fire). Keep `HARD_INTERRUPT_ESC_COUNT=2` for the command-typing path (the rewind rule
      in `claude-code-esc-input-semantics` still holds). Derived: a unit test that the
      esc-only plan for an armed root contains exactly one `character id 27`.
- [ ] **F3 `token_meter.latest_context_entry`** — stop the reverse walk at a
      `type: system, subtype: local_command` entry whose content is a `/clear` (or at a
      session-start-after-clear marker) and return 0 tokens; `external_handoff_clear._decide`
      then refuses on `context_tokens < min_context` as designed. Derived: `TRDD-G043V3V0`'s
      `entry_epoch` consumers must treat the new 0 reading as live, not stale.
- [ ] **F4 `terminal_trigger.inject_until_sent`** — when `still_wanted` cancels after a
      `type_fn()` already ran, call `clear_fn()` before returning (or return a distinct
      `cancelled-after-type` reason that the chain caller clears). Derived: the iTerm
      `clear_fn` (C-a/C-k/C-u trio, :299) must be exercised in that path by a test.
- [ ] **F5 verify on the live pane**: stall a turn deliberately (bad token), confirm ONE
      nudge, a finding, no pair of interrupts, no `/clear` residue.

## Acceptance

- [ ] A stalled-credential session shows at most ONE `Interrupted` row per liveness episode,
      then a human-facing finding; never a 21-min ESC cadence.
- [ ] No cron fire is killed by the nudge's own second ESC (transcript never shows
      interrupt → fire → interrupt within 3 s).
- [ ] The cold-cache gate logs `declined: context below floor` on a post-`/clear` session
      with no assistant message.
- [ ] A cancelled `/clear` injection leaves the prompt field empty.
- [ ] `uv run pytest` + `ruff` + `mypy` green.

## Notes and lessons learned
