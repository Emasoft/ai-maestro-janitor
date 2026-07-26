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

^retry-converts-a-bug-into-silence [desc: an_automatic_retry_hides_a_real_race_by_reporting_the_second_run, keywords: tests pass on retry so we ignore them, CI is green but the bug is real, flaky test masked a race condition, we added retries and the failures went away, type: project, ocd: 2026-07-24, lmd: 2026-07-24]
An auto-retry does not make a test deterministic; it reports the run that happened to pass. A
genuine race — an unawaited write, a shared fixture, a clock assumption — keeps failing in
production while CI reports green, and the retry count is the only remaining evidence.

^order-dependence-looks-like-flakiness [desc: shared_mutable_fixtures_make_a_deterministic_failure_look_random, keywords: suite is green locally and red in CI, test only fails when run with others, passes in isolation, random test failures, type: project, ocd: 2026-07-24, lmd: 2026-07-24]
A test that passes alone and fails in the suite is usually not flaky but order-dependent: a
shared fixture, a module-level singleton, or a database row another test left behind. It is fully
deterministic once the order is fixed — run with a pinned seed to prove it before calling it
flaky.

## Notes and lessons learned

[^1]: [id:ATOM-FLAKY-3T5N, status:valid, keywords:"passes_in_isolation random_test_failures", ocd:2026-07-24, lmd:2026-07-24] DO NOT label a test flaky because it fails intermittently in the suite, BECAUSE order-dependence is deterministic and fixable while "flaky" implies it is not, and the label ends the investigation. DO re-run it in isolation and with a pinned order first.
