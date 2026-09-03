---
trdd-id: L32WC0H7
title: session-liveness ESC nudge loops on a stalled heartbeat fire and the cold-cache gate types /clear into an empty session
column: todo
created: 2026-09-03T15:25:14+0200
updated: 2026-09-03T17:58:00+0200
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

# session-liveness ESC nudge loops on a stalled heartbeat fire and the cold-cache gate types /clear into an empty session

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03 17:58

- Draft 1 (15:25) blamed a dead OAuth credential; draft 2 (17:32) blamed Remote Control.
  Two adversarial reviews + settling reads refuted both: **no TERMINAL API error is recorded
  in any transcript** (a retry wait writes nothing), fires kept stalling AFTER `/login`, and
  the cross-session fire timeline shows NO-STUB fires with RC detached (08:05Z–08:34Z,
  09:51Z) and ran fires with RC attached — RC does not discriminate.
- What the daemon's own pane reads DID see on this pane: `retry attempt 1 on screen` at
  11:47:43 and 11:56:18 (`rotation-esc`), i.e. the 11:5x stalls were CC 429 retry waits.
  Whether the post-`/login` stalls (15:2x–16:5x) are the same shape is UNSETTLED.
- **SUPERSEDED — do NOT carry forward:** "dead credential"; "Remote Control breaks cron
  fires"; "the daemon stamps rate-limited.flag on every pane" (it stamps only panes whose
  screen showed the retry banner — `daemon.py:2126` after the pane read; this pane did).
- NEXT ACTION: read the pane capture the session armed at 17:57 for the next stalled fire
  (`<scratchpad>/pane-capture.txt`, 45 s cadence, ~22 min): a `Retrying in … attempt N/M`
  row ⇒ F0's janitor branch (why `retry_wedged` lost to `frozen`); no row ⇒ CC-side stall
  with no banner, file upstream with the transcript shape. F1–F4 do not depend on it.

## Symptom (owner report, 2026-09-03)

An armed session showed sixteen consecutive `Running scheduled task … ⎿ Interrupted · What
should Claude do instead?` rows between 12:26 and 15:10, then `❯ /clear [name]` sitting typed
in the prompt of a 0 % context session. Nothing was recovered; the owner had to run `/login`.

## Root condition — the heartbeat fire stalls with no terminal error recorded (janitor is a bystander)

- Fire timeline across today's four transcripts (stub `fire epoch=` stamps as the "ran"
  proof): 110 ran, 36 NO-STUB. Stalls cluster: 08:05Z–08:34Z, 09:13Z, 09:51Z onward, and
  every fire of this session (27) until the stub was run by hand at 17:14:58. Interactive
  turns in the same session work throughout.
- A heartbeat prompt carries no `UserPromptSubmit` attachments even when healthy, so "zero
  hook attachments" is NOT a stall signature (draft 2's error). Remote Control does not
  discriminate either: NO-STUB fires occur with RC detached and ran fires with RC attached.
- The 11:5x cluster IS explained: the daemon read `retry attempt 1 on screen` on this pane at
  11:47:43 and 11:56:18 (`rotation-esc`), rotated, and stamped `rate-limited.flag`
  (`daemon.py:2126`, only for panes whose screen showed the banner — correct). A CC retry
  wait writes no transcript entry and no `isApiErrorMessage`, which is exactly the observed
  shape. The 08:05Z cluster and the post-`/login` stalls (15:2x–16:5x) have no pane read
  and stay UNSETTLED — F0 captures the next one. `OAUTH-PRIMARY-UNREADABLE` has been logged
  since 03:04 through hours of healthy turns — it discriminates nothing.

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
3. **INFERRED, not read in code:** the fire the ESC provoked advanced the transcript ⇒ next
   beat the pane reads `healthy` ⇒ `daemon.py:1583` clears the attempt counter ⇒ the next
   stall is `attempt=0` again. The ladder, its cooldown and the `GIVING UP … after 4
   attempts` guard (which did engage for AgentlensPro, 0→4) never engage here: **the
   recovery's own side effect resets its counter**. Read `daemon.py:1300-1320` and `:1575-1595`
   before designing F1 against this.
4. Each ESC-provoked fire also counted as "the session took a real turn Ns ago — the user is
   back" and cancelled the pending `/clear` chain six times (`clear-trigger.log` 13:24:47 →
   15:10:54), so the two chores fought each other for three hours.
5. Not every `Interrupted` row is the nudge: the 13:28:11Z fire was interrupted at 13:35:17Z
   with no daemon ESC logged (liveness deferred on HID activity at 15:31/15:42/15:44) — the
   owner's own ESC. Nine of the pairs match a FIRED line to the second; attribute only those.

## Defect 2 — the cold-cache gate reads a pre-`/clear` context size and leaves `/clear` typed

- `external-clear.log` (global-state): `fired: trigger=cache-certain-expired` at 14:15, 14:20,
  14:35, 14:45, 15:00 on this root, while the session sat at 0 %.
- `/clear` starts a FRESH transcript (first stamp 10:22:10Z, 0 assistant entries before it).
  With no assistant message after the clear, `token_meter.latest_context_size` returns
  **None**, and the pure gate (`external_clear.py:1364-1380`) treats None as "unmeasurable
  — does NOT veto" by a standing owner ruling; only a KNOWN-small context vetoes. With
  `cache_expired=True` (genuinely: no completed turn since 11:46) the gate fired. The defect
  is that a post-`/clear` transcript with zero assistant entries is a KNOWN-empty context
  reported as unknown.
- `inject_until_sent` (`terminal_trigger.py:766-770`) re-asks `still_wanted` at the top of
  every loop iteration, **after** `type_fn()` may already have typed the command on a prior
  iteration, and the cancel return does not call `clear_fn()` (only the settle-failure branch
  at :872-880 does). Result: `/clear` left in the prompt field.

## Fix plan (F0 settles the outside cause; F1–F4 are janitor edits in `scripts/lib/` + `daemon.py`)

- [ ] **F0 settle the stall shape (no code):** read the pane capture armed at 17:57 (or
      re-arm: an `osascript` read of this iTerm session's `contents` every 45 s while a fire
      is stalled). A `Retrying in … attempt N/M` row ⇒ the stall is CC's retry wait and the
      janitor defect is why `retry_wedged` lost to `frozen` (`capture_pane_text` None? regex
      miss on 2.1.259's wording? the advance-across-polls guard never confirming because the
      ESC resets it?) — fold that into F1. No banner, spinner only ⇒ a CC-side stall with no
      visible cause: file upstream with the fire-then-silence transcript shape. Either way
      the janitor must survive a fire that never runs (F1).
- [ ] **F1 `daemon.py` / `fleet_recovery`** — an esc_nudge episode must persist across the
      transcript refresh it causes: key the attempt counter on the `rate-limited-since.ts`
      epoch (the stall episode), not on "transcript went fresh"; cap `frozen` nudges per
      episode (reuse `GIVING UP` at 4); after the cap emit ONE finding
      (`HEARTBEAT-FIRES-STALL`) instead of a keystroke. Derived: the `rate-limited.flag`
      stamp itself is correct (only banner-matched panes) and stays; what must change is
      that a flag older than one episode cannot re-arm the ladder from `attempt=0`.
- [ ] **F2 `terminal_trigger.iterm_esc_lines` callers** — the esc-only recovery plan sends
      ONE ESC when a cron is armed for the pane (the second ESC is what kills the provoked
      fire). Keep `HARD_INTERRUPT_ESC_COUNT=2` for the command-typing path (the rewind rule
      in `claude-code-esc-input-semantics` still holds). Derived: a unit test that the
      esc-only plan for an armed root contains exactly one `character id 27`.
- [ ] **F3 `token_meter.latest_context_size`** — a transcript that has user/system entries
      but NO assistant entry at all is a KNOWN-empty context: return 0, not None, so the
      gate's known-small veto (`external_clear.py:1380`) applies. Keep None for a truly
      unreadable file — the owner ruling that None must not veto stays intact. Derived:
      `TRDD-G043V3V0`'s `entry_epoch` consumers must treat the 0 reading as live, not stale.
- [ ] **F4 `terminal_trigger.inject_until_sent`** — when `still_wanted` cancels after a
      `type_fn()` already ran, call `clear_fn()` before returning (or return a distinct
      `cancelled-after-type` reason that the chain caller clears). Derived: the iTerm
      `clear_fn` (C-a/C-k/C-u trio, :299) must be exercised in that path by a test.
- [ ] **F5 verify on the live pane**: reproduce a stalled fire (F0's setup), confirm ONE
      nudge, a finding, no pair of interrupts, no `/clear` residue.

## Acceptance

- [ ] A session whose fires stall shows at most ONE `Interrupted` row per liveness episode,
      then a human-facing finding; never a 21-min ESC cadence.
- [ ] No cron fire is killed by the nudge's own second ESC (transcript never shows
      interrupt → fire → interrupt within 3 s).
- [ ] The cold-cache gate logs `declined: context below floor` on a post-`/clear` session
      with no assistant message.
- [ ] A cancelled `/clear` injection leaves the prompt field empty.
- [ ] `uv run pytest` + `ruff` + `mypy` green.

## Notes and lessons learned
