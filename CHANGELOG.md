# Changelog

All notable changes to this project will be documented in this file.

## [0.35.0] - 2026-07-09

### Bug Fixes

- Init_state must not crash the OS-keepalive daemon on read-only "/"
- Staged_is_current compares whole closure, drops filecmp (TRDD-K3WQ7XM9)
- Isolate keychain tests to a real temp keychain via JANITOR_ROTATOR_KEYCHAIN (TRDD-K3WQ7XM9 FIX B)
- Mark the rotator tick HEADLESS so it never prompts on the primary read (TRDD-K3WQ7XM9 FIX B2)
- Safe Keychain Protocol — a denied-latch choke-point makes a prompt-flood impossible (TRDD-K3WQ7XM9 P1/P2)

### Documentation

- Add K3WQ7XM9 — daemon crash-loop repair (init_state/staged_is_current/test-isolation/keychain)
- K3WQ7XM9 bug #3 verified, bug #4 documented, keychain-test note
- Macos-keychain wikimem — safe keychain protocol + ACL-prompt-flood gotcha

### Tests

- Gate real-tmux E2E behind JANITOR_TEST_REAL_TMUX, skip by default (TRDD-K3WQ7XM9 FIX A)
- Strip leaked JANITOR_ROTATOR_HEADLESS + latch before every test

