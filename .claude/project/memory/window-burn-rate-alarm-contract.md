---
name: window-burn-rate-alarm-contract
description: "when does the janitor's burn alarm actually fire / why did window-burn-rate alarm about an account I am not using / why does one 7d reading alarm every day for a week / how does the burn line say which account it is about / where do per-model weekly windows like Fable come from / why is the usage-probe cache full of dead files / a usage percentage looks wrong for my own session / how old is the usage number I am being shown / two tools disagree about my usage percentage / does the usage-probe cache ever get cleaned / is a stale probe entry ever served to a reader / why did the alarm stay silent when it should have fired / did a payload-shape change accidentally mute a real burn / why did the same 7d window alarm seven days in a row / where do per-model weekly burn windows come from / burn ratio threshold default 1.5 / what is the token-quietness invariant for this alarm"
ocd: 2026-08-01
lmd: 2026-08-01
metadata:
  node_type: memory
  type: project
  tier: component
---

# window-burn-rate-alarm-contract


^ATOM-9I2M-VE2F [desc:"the four gates a burn trip must pass, and why each exists: not-idle, above min_util, ratio >= bar, and a key that identifies ONE window instance", keywords: when_does_window-burn-rate_actually_fire why_did_the_burn_alarm_stay_silent why_did_one_reading_alarm_every_day_for_a_week burn_alarm_fired_about_an_account_I_am_not_using which_account_is_this_burn_line_about live_versus_alternate_account_in_a_drift_line a_burn_trip_must_pass_four_gates the_account_is_not_proven_idle_gate util_pct_must_be_above_min_util the_key_identifies_one_window_instance_by_reset_epoch model-scoped_windows_like_7d_fable_evaluated_on_the_same_terms only_a_definite_no_session_suppresses_the_alarm, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**A burn trip must pass four gates** (`token_burn.evaluate_trips`), and three of them exist because
the alarm was wrong without them (2026-08-01, issue #160):

1. **The account is not PROVEN idle.** `session_is_open(usage, now) is False` skips it. A pace and an
   exhaustion time are derived from a window AVERAGE, so projecting them asserts the account keeps
   spending — false for an idle one. Only a DEFINITE "no session" suppresses; `None` (unknown) still
   alarms, so a payload-shape change cannot mute a real burn, and a genuinely burning window always
   has an open session because the request that spends it is what opens it.
2. **`util_pct >= min_util`** — the floor, so a fresh barely-used window never alarms.
3. **`burn_ratio >= ratio`** (default 1.5) — computable, and above the even-pace bar.
4. **The key identifies ONE WINDOW INSTANCE**: `<label>-<window>-<reset epoch>`. The detector's
   dedupe used to prefix a calendar DAY, so a single 94% reading re-alarmed on all seven days of the
   same unchanged 7d window and read as a recurring event. Keyed on the reset epoch it re-arms
   exactly when the window does.

Model-scoped windows (e.g. `7d/Fable`) are evaluated on the SAME terms. The alarm remains gated by
the TOKEN-QUIETNESS invariant — surface only in the CULPRIT project's own sessions — unchanged by
any of this. Attribution is the sibling atom below.


^ATOM-TS67-OTS6 [desc:"a usage figure must name the account it measured and the sample it came from — an unlabelled number is read as being about the reader's own session", keywords: which_account_is_this_burn_line_about the_janitor_reported_a_percentage_that_is_wrong_for_me live_versus_alternate_account_label how_old_is_the_usage_number_I_am_being_shown two_tools_disagree_about_my_usage_percentage every_emitted_usage_figure_carries_its_subject_and_sample_age a_bare_number_is_silently_completed_with_the_readers_own_account three_correct_numbers_three_different_subjects api_oauth_usage_is_rate-limited_served_from_one_throttled_cache sample_age_makes_two_readings_joinable_against_a_history unknown_liveness_prints_no_marker_rather_than_guess a_cross-agent_debugging_session_was_wasted_on_a_wrong_subject, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**Every emitted usage figure carries its SUBJECT and its SAMPLE AGE.** Burn lines print `(live)` or
`(alternate)`, threaded from `rotator_usage._probe`, which knows `live_email` from the rotator state
index; unknown liveness prints NO marker rather than guess. `/janitor-token-report --live` adds
`sampled Nm ago` from `sample_age_s`.

Both exist because a bare number is silently completed by the reader with THEIR account and NOW. On
2026-08-01 a line read `⚠ <prefix> 7d window 94% … projected exhaustion 08-01 18:06`. The 94% was an
IDLE alternate; the reader's own account was at 5h 5% / 7d 36%, and a third tool reporting 5.9% (the
live 5h window) looked like it contradicted the janitor. Three correct numbers, three different
subjects. The cost: a work item deferred on a figure that did not apply, a full cross-agent
debugging session, and a second team beginning to "fix" software that had no defect.

`/api/oauth/usage` is rate-limited, so every consumer is served from ONE throttled cache
(`usage_probe`, 600s TTL): a reader may poll as fast as it likes and still be handed a sample
minutes old, and two tools polling at different moments get the SAME one. The age is what makes two
readings joinable against a usage history instead of assumed simultaneous.


^ATOM-MO6J-F77J [desc:"the usage-probe cache is keyed on the ACCESS TOKEN, which rotates — so entries strand and must be retired on a bar above both re-use horizons", keywords: why_is_the_usage-probe_directory_full_of_files dozens_of_probe_json_files_for_a_few_accounts does_the_usage_cache_ever_get_cleaned is_a_stale_probe_entry_ever_served usage_probe_cache_key the_probe_cache_key_is_a_digest_of_the_access_token access_tokens_rotate_every_8_hours_and_strand_old_entries dead_entries_are_unreachable_never_served_by_a_lookup prune_retired_deletes_entries_past_a_24h_bar the_bar_must_stay_above_both_re-use_horizons a_prune_that_ate_a_live_entry_would_defeat_the_throttle 48_entries_for_3_accounts_only_2_still_usable, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**The probe cache key is a digest of the ACCESS TOKEN, and access tokens rotate** (~8h per account
observed), so every rotation mints a new key and strands the previous entry forever. Measured
2026-08-01: 48 entries for 3 accounts, 24 past any horizon that could serve a read, the oldest 6 days
old and describing a 7d window that had already reset — only 2 still usable.

The dead entries are UNREACHABLE, not dangerous: a lookup only ever computes the key for the CURRENT
token, so a stale one is never served. The real risk is latent — any future code that SCANS the
directory rather than computing a key would read one account's stale 97% as another's current value.

`prune_retired` deletes entries past a 24h bar together with their `.cooldown` and `.lock` siblings
(leaving those would just move the leak) and rides `write_cache`, because a write is the one event
that can mint a new key — so the directory can only grow at the moment it is also swept. The bar
MUST stay above both re-use horizons (`ttl_seconds` 600s, `stale_seconds` 1800s); a prune that ate a
live entry would turn a cache hit into a fresh request against the endpoint the module exists to
throttle. That ordering is pinned by a test, not by comment.

## See also

- [[janitor-beat-tasks-and-limitations]] — what one heartbeat fire actually costs, measured — the input to this alarm.


- [[janitor-architecture]] — the hub this component sits under: the heartbeat /
  daemon split, the detector roster, and the TOKEN-QUIETNESS invariant that gates
  where this alarm may surface.
- [[agentlens-diagnostics-integration]] — the other reader of account window
  utilization; the 2026-08-01 incident was two correct tools measuring different
  accounts, not a disagreement about one.
- USER scope — the `/api/oauth/usage` payload shape itself (the `limits[]` array,
  the now-null flat per-model fields, the `resets_at: null` idle signal) is
  machine- and project-agnostic and lives there, not here.

## Notes and lessons learned
