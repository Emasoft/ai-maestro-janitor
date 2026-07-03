# Changelog

All notable changes to this project will be documented in this file.

## [0.30.0] - 2026-07-03

### Bug Fixes

- Compaction-id regexes, slug SSOT, daemon knobs, wedge-kill match, stale locks (TRDD-E9LMBNPE)
- Wave 2 — schedule token-usage-anomaly, maintenance-wins arm nudge, specific pane match, AWS exfil regex (TRDD-E9LMBNPE)
- Suppress repeat token-budget nudges + Phase-4 audit verdicts (TRDD-4MMXTJFB)
- Wave 3 — dead v2 STATE injector, 3 zero-division knobs, id-case corruption, perpetual map-drift false nudge, 2 context-flooding skill blocks (TRDD-4MMXTJFB)
- Bound L0-keepalive restage churn + isolate its tests from real state (TRDD-ZNN0UK5K)

### Documentation

- Mark 0NRVNDSZ published in v0.29.1 (window-aligned + subagent-recursive attribution)
- E9LMBNPE review-fix batch complete — waves 1+2 recorded, awaiting next release
- 4MMXTJFB records wave 3 — 9 token-waste review fixes ride the release (TRDD-4MMXTJFB)
- Clear MD004 NIT in 4MMXTJFB + add 2KQQAEPP github-issues-watch spec
- ZNN0UK5K — fseventsd 39GB runaway root-caused to L0-keepalive restage churn (TRDD-ZNN0UK5K)
- Fseventsd/keepalive test-isolation lessons + record the 4× recheck (TRDD-ZNN0UK5K)
- ZNN0UK5K permanent solution complete — A(test isolation)+B(bounded restage), FIX C already shipped (ThrottleInterval=30); file HK7IZ21Z runaway-detector EHT (TRDD-ZNN0UK5K)

### Features

- Per-category accounting + --window 5h|7d selectors + terminal graphs (TRDD-4MMXTJFB)
- Opt-in PostToolUse hook to cap Bash output + protect context (TRDD-ZNN0UK5K)
- Exempt token-saving tools (tldr/distill/lean-ctx) from the Bash-output cap (TRDD-ZNN0UK5K)

### Tests

- Fix over-broad user-mem privacy assertion (fixture-path collision)
- Sync 2 divergent _slug helpers to the SSOT (project_slug non-alnum dashing)
- Update source-breakdown test for real 4-category shares (TRDD-4MMXTJFB)

