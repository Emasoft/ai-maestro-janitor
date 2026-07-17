# Changelog

All notable changes to this project will be documented in this file.

## [0.52.0] - 2026-07-17

### Bug Fixes

- Stop the fleet-recovery injection loop — substantive liveness + wedged short-circuit (TRDD-8DR0X08A)

### Documentation

- FENWWB4E + 4649ZLE0 + N9YAH5E7 shipped in v0.51.0 -> published
- Add TRDD-8DR0X08A — fleet-recovery injection loop (self-refreshing probe)
- 8DR0X08A implemented (db9c2f0) -> testing; F4 cadence-aware staleness added; ships v0.51.1

### Refactor

- Binary server-liveness switch — server running owns ALL absorbed chores (TRDD-LU0C5KAR)

