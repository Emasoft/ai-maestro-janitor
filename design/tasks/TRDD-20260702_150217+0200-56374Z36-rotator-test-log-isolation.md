---
trdd-id: 56374Z36
title: Rotator test-isolation leak — tests write the PRODUCTION rotator.log + bootstrap browser-launch guard
column: complete
created: 2026-07-02T15:02:17+0200
updated: 2026-07-02T15:36:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: S
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: [028409f]
approval-tier: 0
---

# Rotator test-isolation leak — tests pollute the production rotator.log

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **SYMPTOM (verified 2026-07-02):** the PRODUCTION `~/.claude/plugins/data/…/oauth-rotator/rotator.log`
  is full of `auto-bootstrap: opening a browser … for seeded@x.com / deadrefresh@x.com / ok@x.com /
  e@x.com / stuck@x.com / seed@x.com` lines at 03:44/03:59/04:02/10:58/11:58 — exactly the times test
  suites ran (overnight work + the v0.28.2 publish pytest). The production `state.json` is CLEAN
  (verified by the approved cleanup script — only the 2 real accounts; zero fixture slots/profiles/
  keychain entries). So the leak is the **LOG PATH only**: some rotator test isolates state (HOME /
  rotator-home env) but the LOG WRITER resolves the real data-dir path.
- **IMPACT:** (a) misleading forensics (this session initially misdiagnosed "production state
  polluted"); (b) possibly REAL browser launches during tests if the launch path isn't stubbed —
  verify; (c) log noise drowns real rotation decisions.
- **USER approval:** "yes, approved all 3" (2026-07-02) — item 2. Tier-0 execution (own scope).
- **PRECEDENT (wikimem oauth-rotation-renew-reauth lesson [^7]):** this bug CLASS was fixed once
  already — TRDD-14IY6MAD (v0.18.2): the cmd_auto tests leaked `live@x`/`alt@x` lines the same way
  (`_setup_auto` patched state+keychain but not `_log`); fix = module autouse fixture redirecting
  `rotator.ROOT` + `rotator.LOG_FILE` to tmp. Today = the SAME class from a DIFFERENT module (the
  `_bootstrap_seeded_slots` tests). Durable fix: centralize the autouse fixture (conftest-level) so
  EVERY rotator test module is covered and a future module can't re-introduce the leak.
- **NEXT ACTION:** (1) grep tests/test_*rotator*/oauth* for fixture emails (`@x.com`) → find which
  test drives auto-bootstrap; (2) trace the rotator's log-writer path resolution — make it honor the
  SAME env override the state uses (one root resolution, not two — the TRDD-5EUYV08H lesson:
  a shared SSOT with two input paths is not an SSOT); (3) assert in a test that a fixture-home run
  writes ZERO bytes to the real log (isolation regression test); (4) BOOTSTRAP GUARD: auto-bootstrap
  must never launch a browser for an implausible account (deny-list obvious fixture domains e.g.
  `@x.com`/`example.com`, and/or only launch for accounts present in the REAL state at daemon
  runtime — belt for whatever tests miss); (5) optional: one-time truncate/rotate of the polluted
  production log after the fix ships (keep a copy in the fixture-quarantine dir).
