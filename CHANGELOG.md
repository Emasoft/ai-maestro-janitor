# Changelog

All notable changes to this project will be documented in this file.

## [0.34.0] - 2026-07-09

### Bug Fixes

- Never consume the -livebak mirror as live identity (TRDD-7PYTX4E9 F1/F3/F5)
- Tick-liveness alert + session-context live-identity beacon (TRDD-7PYTX4E9 F2/F4)
- Bound the 3 unbounded macOS `security`slot calls (headless hang)

### Documentation

- 82OP4EN9 published in v0.33.0 + activation record
- Add TRDD-7PYTX4E9 — rotator daemon blind-spot (silent mirror fallback masquerades as live identity)
- 3XS3PDCF — harvest precheck UNBLOCKED (coexistence model live in v0.33.0)
- 3XS3PDCF — harvest precheck implemented (10f899b); precheck set complete
- 3XS3PDCF — conflict precheck implemented (f2056ca); all six chores gated
- 7PYTX4E9 — F1-F5 implemented (af68a6e + c740a5a), tests 331/331 green, not yet published

### Features

- Harvest content-precheck — suppress no-op harvest spawns (TRDD-3XS3PDCF)
- Conflict content-precheck — suppress no-op conflict spawns (TRDD-3XS3PDCF)

### Tests

- Exclude daemon fleet-recovery dir from the S1b write-guard
- Skip real_state keychain tests when the macOS keychain is prompting (unblock publish)
- Mock _primary_live_item_absent in the stale F1-era restore test
- Exclude daemon spawn-history + keepalive restage-stamp from the S1b write-guard

