---
name: cron-timezone-drift
description: "the nightly job ran twice / scheduled task fired an hour early / job skipped a day in March / cron runs at the wrong time twice a year"
ocd: 2026-07-22
lmd: 2026-07-22
metadata:
  node_type: memory
  type: project
  tier: component
---

What a local-time schedule does at a DST boundary, and why UTC is not automatically the answer.

^dst-duplicates-and-skips-an-hour [desc: a_local_time_schedule_runs_twice_in_autumn_and_not_at_all_in_spring, keywords: the_nightly_job_ran_twice scheduled_task_fired_an_hour_early job_skipped_a_day_in_March cron_runs_at_the_wrong_time_twice_a_year duplicate_rows_from_the_nightly_batch, type: project, ocd: 2026-07-22, lmd: 2026-07-22]
A job pinned to 01:30 local runs TWICE on the autumn transition (01:30 occurs twice) and NOT AT
ALL on the spring one (01:30 never occurs). Both are silent: nothing errors, the batch simply
double-inserts or vanishes. Any schedule between 00:00 and 03:00 local is in the blast radius.

^utc-is-not-a-free-fix [desc: moving_a_schedule_to_utc_fixes_correctness_and_breaks_business_alignment, keywords: we_moved_cron_to_UTC why_did_the_report_arrive_at_3am schedule_drifts_against_business_hours, type: project, ocd: 2026-07-22, lmd: 2026-07-22]
Scheduling in UTC removes the duplicate/skip failure but detaches the job from local business
hours, so a "close of business" report drifts by an hour twice a year against the humans reading
it. Correct for machine-ordering jobs; wrong for human-facing ones, which need a local schedule
plus explicit idempotency.

^idempotency-beats-scheduling [desc: make_the_job_safe_to_run_twice_instead_of_trying_to_schedule_it_perfectly, keywords: how_do_I_stop_double_processing job_must_not_run_twice make_the_batch_idempotent, type: project, ocd: 2026-07-22, lmd: 2026-07-22]
The durable fix is not a cleverer schedule but a job that is safe to run twice: a natural key, an
upsert, or a processed-window marker. Scheduling can then be chosen for human convenience rather
than correctness.

## Notes and lessons learned

[^1]: [id:ATOM-CRON-2B8V, status:valid, keywords:"nightly_job_ran_twice duplicate_rows_from_batch", ocd:2026-07-22, lmd:2026-07-22] DO NOT fix a DST double-run by shifting the schedule to a quieter hour, BECAUSE the duplicate is a property of local-time arithmetic and follows the job wherever it is moved. DO make the job idempotent, then schedule it for whoever reads its output.
