---
trdd-id: L32WC0H7
title: session-liveness ESC nudge loops on a stalled heartbeat fire and the cold-cache gate types /clear into an empty session
column: testing
created: 2026-09-03T15:25:14+0200
updated: 2026-09-25T17:46:33+0200
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
implementation-commits: [9cc22049, 5ae6b9b0, 09c33156, e74ead11, 02f13540, bc9f62b8, 7784344b]
assignee: ai-maestro-janitor main session
created-by: ai-maestro-janitor main session
---

# session-liveness ESC nudge loops on a stalled heartbeat fire and the cold-cache gate types /clear into an empty session

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-23

- 2026-09-23 — card 1 of docs_dev/jev-compaction-spec.md (trigger + loop guards, recovery guard, iTerm timeout targeting) landed on 2026-09-22. The commits TAGGED L32WC0H7 are 5ae6b9b0, 09c33156, e74ead11, 02f13540, bc9f62b8, 7784344b; related recovery-flag work was tagged RAEGS1D5 (2f463d3b, 1b5ceec8, 6eba6f58, 9dfc409b), so that list is not proven complete against the spec's card-1 items. Back at testing; remaining: (1) the buildable row-count test of Acceptance box 1, (2) F5 observed live after the next release.
- When card 1 lands, return this card to `testing` until F5 (one real stalled fire recovering with a single nudge) is observed in the field — that acceptance is unchanged.
- **Prior thread (2026-09-17), still open:** F0–F6 are implemented; the card was HELD AT `testing` — NOT `complete` — because
  F5 and the six live acceptance criteria below need a real stalled fire on this host, which
  cannot be manufactured. **Unblock condition:** publish, then observe one stalled fire recover
  with a SINGLE nudge, AND land the row-count test named on the 2026-09-23 line above; then move to `complete`. This matches the ten other cards left at
  `testing` on 2026-09-03 for the same reason (see `janitor-publish-pipeline` ATOM-VA75-PD8K:
  the release is what makes a live box observable, so publish is mid-pipeline, not the finish
  line). A `complete` column over an unchecked acceptance box is the "board is lying" failure
  this session spent the night removing — do not re-close it early.
- F0–F6 implemented in commit `9cc22049` (probes: mutation-tested per item, see
  `reports/l32wc0h7-fixes/20260903_234218+0200-f0-f6.md` +
  `reports/l32wc0h7-fixes/20260904_000130+0200-hard-restart-tests.md`). Full suite green
  (16351 passed, 1 skipped, 0 failed), ruff + mypy clean. F5 (live-pane observation) is
  explicitly NOT done — cannot be manufactured outside a real stalled fire; observe it in
  the field once this ships.
- **CONSEQUENCE worth carrying forward:** F1 caps every `frozen` diagnosis at `esc_nudge`
  — no diagnosis anywhere in the ladder now routes to `force_restart`/`resurrect`
  (`test_no_diagnosis_ever_routes_to_a_kill_rung` pins this). The janitor therefore cannot
  kill a stalled session at all anymore. This is DELIBERATE (a stall whose root cause is
  unsettled must never escalate to a kill), nothing was silently deleted — but it means the
  hard-restart/kill rung is now dead code on this path. TRDD-56d24c02 owns the USER decision
  on whether/when to restore a kill path; do not re-add the escalation here without that.

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
- NEXT ACTION (2026-09-23): F1-F6 are done. Write the row-count test of Acceptance box 1 (N simulated stalled fires through the beat seam, assert at most one ESC plan), then observe F5 after the next release.
  (F0's pane capture was only ever corroboration, never a gate.)
2026-09-25 16:00 — the row-count test of Acceptance box 1 LANDED: tests/test_liveness_episode_row_count.py (10 simulated stalled beats x 8 diagnoses through the real task_session_liveness seam, rate-limited.flag on disk per F1; asserts at most one ESC plan per episode, attempts <= MAX, GIVING UP as the finding). Remaining open: ONLY the F5 field observation (and the composite no-GIVING-UP-on-fresh-transcript live signature) after the next release. Column stays testing.
2026-09-25 16:20 — review fix: F1 is now genuinely pinned. The row-count test's beats all kept one diagnosis, so the healthy+flag guard branch was never taken. New test_counter_survives_the_esc_provoked_healthy_beat drives frozen->healthy->frozen with the flag on disk: the counter SURVIVES the ESC-provoked healthy beat and advances on the next frozen beat. Mutation probe: deleting the F1 guard fails this test; restored, it passes. Also on the card: the 3 over-cap USER-scope descs (verify-cross-repo-cited-sha x2, debugging-methodology...full-3-atom) now hard-refuse on next write-verb touch — the curator must shorten them; recorded as the migration owed with the 23QM8H5F landing.
2026-09-25 17:10 — second review round: all commits sound. Notes recorded: (1) the oscillation test pins F1 COMBINED with the identity guard (beat 2 shares pid/tty) — the mutation probe is what isolates the F1 branch as load-bearing; (2) the flag-ABSENT healthy reset is already pinned by test_recovered_instance_resets_its_attempt_budget (test_daemon_session_liveness.py:292), the reviewer's one ask, no new test needed; (3) the oscillation test's global time.time patch (+901s for beat 3) is cosmetic today but a caveat for any future wall-clock assertion.

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

- [x] **F0 the stall shape is answered by code, corroborate only:** `retry_wedged` requires
      the on-screen attempt number to ADVANCE across polls (`fleet_scan.py:1141-1146`,
      `session_liveness.retry_wedge_state_update`); a window wall shows `Retrying in 5h …
      attempt 1/5` unchanged for hours, so `frozen` wins by construction and the daemon has
      never once diagnosed `retry_wedged` (`daemon.py:2077-2080`). Derived: the guard is right
      (a static frame must not count) — so the fix is F1's episode cap, not a looser regex.
      Corroboration: the pane capture armed 17:24 (`<scratchpad>/pane-capture.txt`); a poll
      that saw no banner proves nothing (the nudge erases the frame). Derived cleanup:
      `session_liveness.is_session_frozen` has NO callers (the live predicate is
      `fleet_scan.diagnose_root` → `diagnose_instance`) — delete it together with the tests
      that pin it in `tests/test_session_liveness.py`, no-legacy rule.
      — DONE: `is_session_frozen` deleted (zero callers confirmed by grep), 5 pinning tests
      removed; `tests/test_session_liveness.py` 21 passed.
- [x] **F1 `daemon.py:1582-1588`** — do NOT unlink the recovery counter on a `healthy`
      diagnosis while `rate-limited.flag` still exists: only `dispatch.py` clears that flag,
      and it does so on EVERY stub run that finds it (`_phase_rate_limit_recovery`,
      `dispatch.py:1124-1131` — observed: the 11:56 flag was gone after this session's three
      stub runs at 17:14–17:27, nothing else could have removed it inside the 24 h sweep),
      so flag-present + healthy = the heartbeat has NOT actually run and the episode is
      still open. Do NOT key the episode on `rate-limited-since.ts`
      (re-stamped by `:1990` and `:2126` on every attempt — self-defeating). Precedent:
      TRDD-8DR0X08A (`fleet_scan.py:690-696`) fixed the identical self-reset for queue lines;
      cite it in the code comment. Derived 1: with `include_hard=True` (`daemon.py:1698`) a
      persisted counter reaches `force_restart` at attempt 3 (`fleet_recovery.py:87-88`)
      BEFORE give-up at 4, and `_run_hard_restart` spends the attempt even in dry-run
      (`:1310`) — cap `frozen` on this shape at `esc_nudge` (never a kill for a stall whose
      cause is unsettled) and, after `MAX_ATTEMPTS`, emit ONE finding
      (`HEARTBEAT-FIRES-STALL`) instead of any keystroke. Derived 2: early signal that F1 is
      wrong = a `GIVING UP` line on a session whose transcript is fresh.
      — DONE: `daemon.py::task_session_liveness` now checks `rate-limited.flag` before
      unlinking the counter; `frozen` capped unconditionally at `esc_nudge`
      (`fleet_recovery.action_for`); `HEARTBEAT-FIRES-STALL` finding emitted on give-up.
      Pinned by `test_healthy_with_rate_limited_flag_still_present_keeps_the_episode_open`
      and `test_no_diagnosis_ever_routes_to_a_kill_rung`; mutation probe confirmed
      (removing the flag-check un-reverts to `assert False == exists()`).
- [x] **F2 `fleet_inject.build_esc_plan` / `iterm_esc_only_osascript`** — an ESC-only plan
      is ONE ESC per press; the policy loop (`pane_policy._flush_wedge`, budget 1+queued
      with re-read) adds a second press only if the screen still needs it. The 2 ESCs are
      0.6 s apart (`terminal_trigger._ESC_SETTLE_S`; the 2.0 s is a pre-delay) and every
      `Step(keys="ESC")` routes through `build_esc_plan` (`pane_actuate.py:99-100`), so today
      the wedge path double-presses too. Keep `HARD_INTERRUPT_ESC_COUNT=2` for command
      `esc_first` plans (`fleet_inject.py:217-221`). Derived: the frozen non-wedge step is
      `Expect.ANY` (`pane_policy.py:225`, sent once, no re-read) — a single ESC may leave a
      hung-tool turn alive; accepted, the next beat re-evaluates and F1 escalates honestly.
      Test: the esc-only osascript contains exactly one `character id 27`.
      — DONE: `iterm_esc_only_osascript` calls `iterm_esc_lines(count=1)`; `build_esc_plan`
      passes `esc_count=1` to tmux/wtype/xdotool. Pinned by
      `test_esc_only_osascript_sends_exactly_one_esc` and
      `test_esc_only_plan_tmux_and_gui_channels_also_send_one_esc`; mutation probe confirmed.
- [x] **F3 `token_meter.latest_context_entry`** — return 0 (KNOWN-empty) when the tail
      window covered the file start (`size <= _TAIL_BYTES`, 512 KB, `token_meter.py:46`) and
      holds no usage-bearing assistant entry; keep None when the window did NOT reach the
      start (a big transcript whose tail is one >512 KB tool_result must not be vetoed
      into silence — the 2026-08-04 ruling's concern). Consumers already read 0 as no-op
      (`token_meter.py:339-353`, `cold_cache_compact.py:322-328`, `reload_shrink.py:93`).
      — DONE: `latest_context_entry` returns `(0, None)` for a known-empty tail
      (`size <= _TAIL_BYTES`), stays `None` for an unmeasurable big-file tail. Pinned by
      `test_latest_context_size_no_assistant_usage_in_a_small_file_is_zero` and
      `test_latest_context_size_no_assistant_usage_in_a_huge_file_stays_none`; mutation
      probe confirmed.
- [x] **F4 `terminal_trigger.inject_until_sent`** — on ANY non-submit exit after `type_fn()`
      ran (the `still_wanted` cancel `:766-770`, the give-up `:762-764` reached via the
      "user typed; backing off without clearing" iteration `:873-876`, a blinded probe
      `:735-746`): re-read the pane; if `prompt_field_shows_only(text, command)` call
      `clear_fn()`, otherwise leave it and log (owner 2026-08-02: never delete the user's
      keystrokes). Test: the iTerm `clear_fn` (C-a/C-k/C-u, `:299`) runs on the cancel path.
- [x] **F6 `clear_trigger._user_came_back` (`:449`)** — it uses
      `fleet_scan.transcript_activity` (substantive age, heartbeat-INCLUDING per
      `fleet_scan.py:749-757`) while `came_back_since` (`:333`) claims heartbeat-excluding;
      so ANY fire on an armed session cancels a pending `/clear`, stalled or not. Swap to
      `fleet_scan.human_activity_age` (what `external_handoff_clear.py:282` already feeds the
      gate) and fix the docstring. Derived: `human_activity_age_from_tail` filters only
      `queue-operation` and `scheduledFireId` records, so the ESC's own
      `[Request interrupted by user]` user record still reads as a human turn — each of this
      incident's six cancels landed 2–7 s after that record, so the swap alone would NOT
      have prevented them. Add an interrupt-record exclusion there (human presence is
      already guarded separately by the HID typing probe in `inject_until_sent`), and note
      that F2 removes the provoking ESC pair anyway.
      — DONE: `_user_came_back` swapped to `fleet_scan.human_activity_age`;
      `_is_interrupt_record` added to `human_activity_age_from_tail` to exclude
      `[Request interrupted by user]` records. Pinned by
      `test_interrupt_record_never_counts_as_a_human_turn` and
      `test_interrupt_record_with_real_reply_still_counts_the_reply`; mutation probe
      confirmed.
- [ ] **F5 verify on the live pane**: reproduce a stalled fire, confirm ONE nudge, a
      finding after the cap, no pair of interrupts, no `/clear` residue, and a `/clear`
      chain that survives a heartbeat fire.
      — NOT DONE: needs a live stalled fire on this host, which cannot be manufactured. The
      fix ships in the next release; observe it then.

## Acceptance

- [ ] A session whose fires stall shows at most ONE `Interrupted` row per liveness episode,
      then a human-facing finding; never a 21-min ESC cadence.
      — NO TEST TODAY, and the box splits in two. The ROW COUNT is buildable now: drive N
      simulated stalled fires through the beat seam and assert at most one ESC plan, the
      same shape as `test_daemon_hard_restart.py::test_no_diagnosis_ever_routes_to_a_kill_rung`
      (8 diagnoses x 6 attempts x 2 flags). Only the second clause — the 21-minute
      wall-clock cadence — is field-only. Do not read this annotation as "untestable";
      it is a test someone can write this week. Audited 2026-09-04; the
      underlying counter-reset fix is covered by
      `test_daemon_session_liveness.py::test_healthy_with_rate_limited_flag_still_present_keeps_the_episode_open`,
      but nothing asserts the row count or the cadence bound. Observe with F5.
- [x] No cron fire is killed by the nudge's own second ESC (transcript never shows
      interrupt → fire → interrupt within 3 s). — 2026-09-04:
      `test_fleet_inject.py::test_esc_only_osascript_sends_exactly_one_esc` and
      `::test_esc_only_plan_tmux_and_gui_channels_also_send_one_esc` assert exactly ONE
      ESC press across the iTerm, tmux and wtype/xdotool channels — the second ESC that
      killed the fresh fire no longer exists to send.
- [x] The cold-cache gate logs `context 0 < <min> — nothing worth reclaiming` on a
      post-`/clear` session with no assistant message, and still fires on a large
      transcript whose tail window did not reach the file start. — 2026-09-04, two
      halves: `test_context_size_guard.py::test_latest_context_size_no_assistant_usage_in_a_small_file_is_zero`
      pins the KNOWN-empty 0 (and `..._in_a_huge_file_stays_none` the None branch), and
      `test_external_clear.py:155` / `:495` assert the literal
      `"nothing worth reclaiming"` reaches `v.why` when context is under the floor.
- [x] A cancelled `/clear` injection leaves the prompt field empty; a user's own typed text
      is never cleared. — 2026-09-04:
      `test_terminal_trigger_readback.py::test_still_wanted_cancel_clears_a_leftover_exact_match_command`
      and `::test_still_wanted_cancel_never_clears_the_users_own_text` cover both halves.
- [x] A pending `/clear` chain is not cancelled by a heartbeat fire, only by a human turn.
      — 2026-09-04: `test_fleet_scan_human_activity.py::test_interrupt_record_never_counts_as_a_human_turn`
      (our own nudge's interrupt is not human activity) plus
      `test_external_handoff_clear.py::test_a_real_turn_after_the_verdict_retires_the_clear`
      and `::test_a_turn_in_the_verdicts_own_second_is_not_a_comeback` (only a real turn
      strictly after the verdict cancels).
- [ ] No `GIVING UP` line ever appears for a session whose transcript is fresh (the F1
      early-warning signal); no `[frozen] attempt=1` follows `attempt=0` without an
      `Interrupted` pair (the F2 signal).
      — NO TEST, by nature: a composite absence-over-a-live-log property. Audited
      2026-09-04; F1 and F2 are each covered individually
      (`test_daemon_session_liveness.py::test_healthy_with_rate_limited_flag_still_present_keeps_the_episode_open`,
      `test_daemon_hard_restart.py::test_frozen_exhausted_stays_esc_nudge_then_crash_loop`)
      but their joint early-warning signature is only observable in production. Observe
      with F5.
- [x] `uv run pytest` + `ruff` + `mypy` green. — 2026-09-04 on the tree committed as `9cc22049`:
      `16351 passed, 1 skipped, 8 subtests passed` (`PYTEST=0`), `ruff check scripts tests` all
      checks passed, `mypy scripts/ --ignore-missing-imports` clean over 504 source files.
      CPV v5.16.2 `--strict` on the same tree: `CPV=0`, `CRITICAL=0 MAJOR=0 MINOR=0 NIT=0`.

## Approval log

- 2026-09-04T00:13:30+0200 — COMPLETE. Reviewed by the janitor main session under the
  owner's standing delegation of the review columns. F0–F6 verified against the code and
  the green full suite; F5 (live observation) explicitly left open and stated on the card.
- 2026-09-16T12:33:53+0200 — column → todo. no session working it for 7-13 days while column claimed testing; re-columned honest (triage 2026-09-16)
- 2026-09-17T05:54:34+0200 — column → testing by main session (owner standing permission 2026-09-03). F0-F6 code-complete and shipped in v3.4.14; F5 needs one real stalled-fire observation post-publish, cannot be manufactured.
- 2026-09-22T21:44:04+0200 — column → dev. card 1 (trigger and loop guards) in progress 2026-09-22
- 2026-09-23T19:06:42+0200 — column → testing. card 1 of the Jev spec landed 2026-09-22; only the F5 live stalled-fire observation remains, per this card's STATE

## Notes and lessons learned
