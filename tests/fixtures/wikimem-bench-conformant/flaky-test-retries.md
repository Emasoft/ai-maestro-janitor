---
name: flaky-test-retries
description: "tests pass on retry so we ignore them / CI is green but the bug is real / flaky test masked a race condition / suite is green locally and red in CI"
ocd: 2026-07-24
lmd: 2026-07-24
metadata:
  node_type: memory
  type: project
  tier: component
---

Why an automatic retry is a reporting change, not a fix.

^retry-converts-a-bug-into-silence [desc: an_automatic_retry_hides_a_real_race_by_reporting_the_second_run, keywords: tests_pass_on_retry_so_we_ignore_them CI_is_green_but_the_bug_is_real flaky_test_masked_a_race_condition we_added_retries_and_the_failures_went_away, type: project, ocd: 2026-07-24, lmd: 2026-07-24]
An auto-retry does not make a test deterministic; it reports the run that happened to pass. A
genuine race — an unawaited write, a shared fixture, a clock assumption — keeps failing in
production while CI reports green, and the retry count is the only remaining evidence.

^order-dependence-looks-like-flakiness [desc: shared_mutable_fixtures_make_a_deterministic_failure_look_random, keywords: suite_is_green_locally_and_red_in_CI test_only_fails_when_run_with_others passes_in_isolation random_test_failures, type: project, ocd: 2026-07-24, lmd: 2026-07-24]
A test that passes alone and fails in the suite is usually not flaky but order-dependent: a
shared fixture, a module-level singleton, or a database row another test left behind. It is fully
deterministic once the order is fixed — run with a pinned seed to prove it before calling it
flaky.

## Notes and lessons learned

[^1]: [id:ATOM-FLAKY-3T5N, status:valid, keywords:"passes_in_isolation random_test_failures", ocd:2026-07-24, lmd:2026-07-24] DO NOT label a test flaky because it fails intermittently in the suite, BECAUSE order-dependence is deterministic and fixable while "flaky" implies it is not, and the label ends the investigation. DO re-run it in isolation and with a pinned order first.
