---
trdd-id: L32WC0H7
title: session-liveness ESC nudge loops on a stalled heartbeat fire and the cold-cache gate types /clear into an empty session
column: todo
created: 2026-09-03T15:25:14+0200
updated: 2026-09-03T17:34:26+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03 17:32

- Draft 1 (15:25) blamed a dead OAuth credential; draft 2 (~17:20) blamed Remote Control.
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
- Advisor verdict (Fable 5.1, 17:4x) folded in: diagnosis holds; the counter reset is
  CONFIRMED in code (`daemon.py:1582-1588` unlinks the counter on any no-recovery
  diagnosis, and `fleet_scan.substantive_age_from_tail` discounts only `queue-operation`
  lines, so the ESC's own `[Request interrupted by user]` record refreshes liveness even
  without a provoked fire — the TRDD-8DR0X08A self-reset shape again). F0 is largely
  answered by code: `retry_wedged` needs the attempt number to ADVANCE across polls
  (`fleet_scan.py:1141-1146`); a window wall reads `attempt 1/5` for hours, so `frozen`
  wins by construction (`daemon.py:2077-2080` records zero `retry_wedged` diagnoses ever).
- NEXT ACTION: implement F1 → F6 as written below (each is one bounded edit + one test);
  the pane capture is corroboration, not a gate.

## Symptom (owner report, 2026-09-03)

An armed session showed sixteen consecutive `Running scheduled task … ⎿ Interrupted · What
should Claude do instead?` rows between 12:26 and 15:10, then `❯ /clear [name]` sitting typed
in the prompt of a 0 % context session. Nothing was recovered; the owner had to run `/login`.

## Root condition — the heartbeat fire stalls with no terminal error recorded (janitor is a bystander)

- Fire timeline across today's four transcripts, "ran" = a `[s:<session>] fire epoch=`
  stamp in `.janitor/logs/heartbeat-fires.log` matched by EXACT session id within 90 s
  (the log is per-project and per-session-tagged, so sibling projects cannot pollute it;
  today's sessions were sequential): 36 NO-STUB. Stalls cluster: 08:05Z, 08:20Z–08:34Z,
  09:13Z, 09:51Z–09:55Z, 10:22Z, and every fire of this session from 10:26Z to 14:58Z (27).
  The two "ran" fires of this session (15:21Z, 15:27Z) reached the model and the stub was run
  by hand in those turns — a fire that reaches the model executes; the stalled ones never do.
  Interactive turns in the same session work throughout.
- A heartbeat prompt carries no `UserPromptSubmit` attachments even when healthy, so "zero
  hook attachments" is NOT a stall signature (draft 2's error). Remote Control is refuted
  because fires both ran and stalled under the SAME bridge state: session 527e1fd0 attached
  at 22:15Z on 09-02 (its only `remote_session_change`, url set) and then ran 98 fires and
  stalled 5 (08:05Z, 08:20Z–08:34Z) with no state change in between. A missing change event
  means "unchanged", never "absent" — the 09:31Z url-null row is read as a detach but no
  field says so, so that cluster is not used as a leg on its own.
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

## Defect 2 — the cold-cache gate reports a post-`/clear` empty context as unknown and leaves `/clear` typed

- `external-clear.log` (global-state): `fired: trigger=cache-certain-expired` at 14:15, 14:20,
  14:35, 14:45, 15:00 on this root, while the session sat at 0 %.
- `/clear` starts a FRESH transcript (first stamp 10:22:10Z, 0 assistant entries before it).
  With no assistant message after the clear, `token_meter.latest_context_size` returns
  **None**, and the daemon-lane gate `should_clear_externally` (`external_clear.py`, ruling
  at `:1542-1545`, veto at `:1589-1592`; fed from `external_handoff_clear.py:286`) treats
  None as "unmeasurable — does NOT veto" by owner directive 2026-08-04; only a KNOWN-small
  context vetoes. With
  `cache_expired=True` (genuinely: no completed turn since 11:46) the gate fired. The defect
  is that a post-`/clear` transcript with zero assistant entries is a KNOWN-empty context
  reported as unknown.
- `inject_until_sent` (`terminal_trigger.py:766-770`) re-asks `still_wanted` at the top of
  every loop iteration, **after** `type_fn()` may already have typed the command on a prior
  iteration, and the cancel return does not call `clear_fn()` (only the settle-failure branch
  at :872-880 does). Result: `/clear` left in the prompt field.

## Fix plan (advisor-reviewed 17:4x; each item = one bounded edit + one test)

- [ ] **F0 the stall shape is answered by code, corroborate only:** `retry_wedged` requires
      the on-screen attempt number to ADVANCE across polls (`fleet_scan.py:1141-1146`,
      `session_liveness.retry_wedge_state_update`); a window wall shows `Retrying in 5h …
      attempt 1/5` unchanged for hours, so `frozen` wins by construction and the daemon has
      never once diagnosed `retry_wedged` (`daemon.py:2077-2080`). Derived: the guard is right
      (a static frame must not count) — so the fix is F1's episode cap, not a looser regex.
      Corroboration: the pane capture armed 17:24 (`<scratchpad>/pane-capture.txt`); a poll
      that saw no banner proves nothing (the nudge erases the frame). Derived cleanup:
      `session_liveness.is_session_frozen` has NO callers (the live predicate is
      `fleet_scan.diagnose_root` → `diagnose_instance`) — delete it, no-legacy rule.
- [ ] **F1 `daemon.py:1582-1588`** — do NOT unlink the recovery counter on a `healthy`
      diagnosis while `rate-limited.flag` still exists: only `dispatch.py` clears that flag
      (`fleet_scan.py:966-969`), so flag-present + healthy = the heartbeat has NOT actually
      run and the episode is still open. Do NOT key the episode on `rate-limited-since.ts`
      (re-stamped by `:1990` and `:2126` on every attempt — self-defeating). Precedent:
      TRDD-8DR0X08A (`fleet_scan.py:690-696`) fixed the identical self-reset for queue lines;
      cite it in the code comment. Derived 1: with `include_hard=True` (`daemon.py:1698`) a
      persisted counter reaches `force_restart` at attempt 3 (`fleet_recovery.py:87-88`)
      BEFORE give-up at 4, and `_run_hard_restart` spends the attempt even in dry-run
      (`:1310`) — cap `frozen` on this shape at `esc_nudge` (never a kill for a stall whose
      cause is unsettled) and, after `MAX_ATTEMPTS`, emit ONE finding
      (`HEARTBEAT-FIRES-STALL`) instead of any keystroke. Derived 2: early signal that F1 is
      wrong = a `GIVING UP` line on a session whose transcript is fresh.
- [ ] **F2 `fleet_inject.build_esc_plan` / `iterm_esc_only_osascript`** — an ESC-only plan
      is ONE ESC per press; the policy loop (`pane_policy._flush_wedge`, budget 1+queued
      with re-read) adds a second press only if the screen still needs it. The 2 ESCs are
      0.6 s apart (`terminal_trigger._ESC_SETTLE_S`; the 2.0 s is a pre-delay) and every
      `Step(keys="ESC")` routes through `build_esc_plan` (`pane_actuate.py:99-100`), so today
      the wedge path double-presses too. Keep `HARD_INTERRUPT_ESC_COUNT=2` for command
      `esc_first` plans (`fleet_inject.py:217-221`). Derived: the frozen non-wedge step is
      `Expect.ANY` (`pane_policy.py:225`, sent once, no re-read) — a single ESC may leave a
      hung-tool turn alive; accepted, the next beat re-evaluates and F1 escalates honestly.
      Test: the esc-only osascript contains exactly one `character id 27`.
- [ ] **F3 `token_meter.latest_context_entry`** — return 0 (KNOWN-empty) when the tail
      window covered the file start (`size <= _TAIL_BYTES`, 512 KB, `token_meter.py:46`) and
      holds no usage-bearing assistant entry; keep None when the window did NOT reach the
      start (a big transcript whose tail is one >512 KB tool_result must not be vetoed
      into silence — the 2026-08-04 ruling's concern). Consumers already read 0 as no-op
      (`token_meter.py:339-353`, `cold_cache_compact.py:322-328`, `reload_shrink.py:93`).
- [ ] **F4 `terminal_trigger.inject_until_sent`** — on ANY non-submit exit after `type_fn()`
      ran (the `still_wanted` cancel `:766-770`, the give-up `:762-764` reached via the
      "user typed; backing off without clearing" iteration `:873-876`, a blinded probe
      `:735-746`): re-read the pane; if `prompt_field_shows_only(text, command)` call
      `clear_fn()`, otherwise leave it and log (owner 2026-08-02: never delete the user's
      keystrokes). Test: the iTerm `clear_fn` (C-a/C-k/C-u, `:299`) runs on the cancel path.
- [ ] **F6 `clear_trigger._user_came_back` (`:449`)** — it uses
      `fleet_scan.transcript_activity` (substantive age, heartbeat-INCLUDING per
      `fleet_scan.py:749-757`) while `came_back_since` (`:333`) claims heartbeat-excluding;
      so ANY fire on an armed session cancels a pending `/clear`, stalled or not. Swap to
      `fleet_scan.human_activity_age` (what `external_handoff_clear.py:282` already feeds the
      gate) and fix the docstring.
- [ ] **F5 verify on the live pane**: reproduce a stalled fire, confirm ONE nudge, a
      finding after the cap, no pair of interrupts, no `/clear` residue, and a `/clear`
      chain that survives a heartbeat fire.

## Acceptance

- [ ] A session whose fires stall shows at most ONE `Interrupted` row per liveness episode,
      then a human-facing finding; never a 21-min ESC cadence.
- [ ] No cron fire is killed by the nudge's own second ESC (transcript never shows
      interrupt → fire → interrupt within 3 s).
- [ ] The cold-cache gate logs `context 0 < <min> — nothing worth reclaiming` on a
      post-`/clear` session with no assistant message, and still fires on a large
      transcript whose tail window did not reach the file start.
- [ ] A cancelled `/clear` injection leaves the prompt field empty; a user's own typed text
      is never cleared.
- [ ] A pending `/clear` chain is not cancelled by a heartbeat fire, only by a human turn.
- [ ] No `GIVING UP` line ever appears for a session whose transcript is fresh (the F1
      early-warning signal); no `[frozen] attempt=1` follows `attempt=0` without an
      `Interrupted` pair (the F2 signal).
- [ ] `uv run pytest` + `ruff` + `mypy` green.

## Notes and lessons learned
