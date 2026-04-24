# Changelog

All notable changes to this project will be documented in this file.

## [0.3.5] - 2026-04-24

### Bug Fixes

- Rename monitors→detectors in workflows; run all 8 detectors
- Harden dispatch + detectors against set -u, races, and paste injection
- Drop unused gitignore_filter dep; anchor pre-push glob; polish

### Documentation

- Sync with 8 detectors, correct heartbeat_cron, trim skills

### Miscellaneous

- Update uv.lock
- Ignore .rechecker/ runtime state
- Ignore reports/ and reports_dev/ for agent output hygiene
- Ignore .tldrignore; resync uv.lock for requires-python >=3.11

