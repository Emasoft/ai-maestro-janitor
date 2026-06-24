---
trdd-id: 14IY6MAD
title: rotator cmd_auto tests write to the REAL operational rotator.log — isolate ROOT/LOG_FILE to tmp
column: complete
created: 2026-06-24T17:19:21+0200
updated: 2026-06-24T17:22:27+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 2
severity: MEDIUM
effort: S
labels: [oauth-rotator, tests, isolation, hygiene, trustworthiness]
task-type: bugfix
parent-trdd: TRDD-1IKF0A6D
relevant-rules: []
release-via: publish
test-requirements: [unit, lint]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-14IY6MAD — rotator tests pollute the production rotator.log

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

### ✅ IMPLEMENTED + VERIFIED (2026-06-24 17:22) — ships next publish.py
Added the `_isolate_rotator_root` autouse fixture (redirects `rotator.ROOT` + `rotator.LOG_FILE`
to `tmp_path` for every test). VERIFIED isolation empirically: the production log's `@x`
pollution-line count held at **284 → 284** across a full `test_oauth_rotator.py` run (zero new
pollution), **61/61 green**, ruff clean. The pyright "`_isolate_rotator_root` not accessed" is the
standard pytest-autouse false positive (pyright can't see pytest's autouse call) — not a publish
gate (gate is ruff + yamllint) and consistent with the file's other tolerated pyright noise. NEXT:
publish.

### The bug (observed live 2026-06-24 while verifying the triad post-v0.18.1)
The genuine operational log
`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator/rotator.log`
was found interleaved with dozens of FAKE rotation lines using the test-fixture emails
`live@x` / `alt@x` / `far@x`, timestamped exactly when the publish test suite ran (16:59 +
17:04 — the `--dry-run` and the real `publish.py`). Root cause: `test_oauth_rotator.py`'s
cmd_auto tests call the REAL `rotator.cmd_auto()`, which emits each decision via
`_decide()` → `_log()` → `LOG_FILE = ROOT / "rotator.log"` (the real data dir). The
`_setup_auto` helper monkeypatches `load_state`/`save_state`/`read_slot`/`write_slot`/
`_switch_blob` (so state.json + keychain are SAFE) but NOT `_log`. The author already knew
`_log` "writes for real" — the cmd_tick test at line ~224 patches `_log` to a no-op with that
exact comment — but `_setup_auto` was missed. So EVERY `pytest` run (CI, every publish gate)
appends test garbage to the production log, burying the real ROTATE/RENEW/REAUTH history and
undermining the one durable trail used to diagnose the rotator. state.json + keychain are NOT
affected (verified: `_setup_auto` patches both; keychain tests use a `-TEST-<pid>` service).

### The fix
A module-level `autouse=True` fixture in `test_oauth_rotator.py` that redirects
`rotator.ROOT` AND `rotator.LOG_FILE` to a per-test `tmp_path` for EVERY test. `_log` uses
both globals at call time (`ROOT.mkdir`, the trim tmp `ROOT/"rotator.log.trim.tmp"`, and
`LOG_FILE`), so both are redirected. `_log` stays fully FUNCTIONAL (it writes to the tmp ROOT),
so the dedicated `_log` tests (lines ~1060-1108, which re-patch `LOG_FILE` to their own tmp
INSIDE the test body, after the fixture) keep working unchanged — path redirection, NOT a
no-op, is required precisely because those tests assert on log content. migrate/keychain/slot
tests patch their own paths or the resolver functions, so they're unaffected.

### Verification
- Snapshot the real rotator.log mtime, run the FULL `test_oauth_rotator.py`, assert the real
  log's mtime is UNCHANGED (proof of isolation).
- 61/61 rotator tests still green; ruff clean.

### Scope guard / non-goals
Test-only change (one autouse fixture). Does NOT touch rotator.py runtime behavior, the live
log, or any other test's explicit patches. The already-polluted production log is left to
age out via `_log`'s own 256 KB self-trim — it lives outside the project tree and is
daemon-owned (actively appended every 60s), so manually editing it would race the daemon and
violates "no changes outside the project"; the trim rotates the test lines out naturally.

### Ship
TDD green + ruff clean → `publish.py` (USER present). Small follow-on to v0.18.1.
