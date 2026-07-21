# Changelog

All notable changes to this project will be documented in this file.

## [0.60.1] - 2026-07-21

### Bug Fixes

- Stop the arm→nudge loop that ratcheted the fleet into GLOBAL maintenance
- The write-guard's "only we touch this state" premise is no longer true
- The live-actor probe silently answered False on an import error
- Resolve the live-actor probe from the REAL home, not the sandbox

