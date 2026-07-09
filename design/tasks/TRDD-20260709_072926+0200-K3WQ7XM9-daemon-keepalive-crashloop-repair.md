---
trdd-id: K3WQ7XM9
title: Daemon crash-loop repair — init_state, staged_is_current, keepalive test-isolation, keychain re-prompt
column: dev
created: 2026-07-09T07:29:26+0200
updated: 2026-07-09T07:29:26+0200
current-owner: janitor
assignee: janitor
priority: 1
severity: HIGH
effort: L
task-type: bugfix
release-via: publish
test-requirements: [unit, lint]
relevant-rules: []
impacts: [ci-pipeline]
external-refs: []
---

# Daemon crash-loop repair (post-0.34.0)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-09

**Context:** v0.34.0 shipped the rotator keychain-timeout fix (`c717743`) — real, done.
But the janitor **daemon crash-loops** on every version (0.34.0→0.33.0→0.31.0 all
quarantined by the crash-loop breaker). Root-caused this session to bugs SEPARATE from the
keychain hang. This TRDD collects the full repair.

**Bugs (severity order):**

1. **`init_state()` crashes the launchd daemon — FIXED (`d939110`, unpushed).**
   Under the L0 OS-keepalive (launchd) the daemon has NO `CLAUDE_PROJECT_DIR`, cwd=`/`, so
   `state.project_root()` → `/`, `state_dir()` → `/.janitor/state`, and `init_state()`'s
   `state_dir().mkdir()` raised `OSError(Errno 30) Read-only file system: /.janitor`. The
   daemon crashed at its first `state.log_line` (via `init_state`) BEFORE the task loop,
   every boot → launchd relaunched → crash-loop breaker quarantined each version. Fix
   landed: `init_state` now creates `log_dir()` first (daemon overrides it via
   `JANITOR_LOG_DIR`) and `state_dir()` best-effort (catch OSError). Verified traceback:
   `daemon.main → state.log_line → init_state → state_dir().mkdir → /.janitor read-only`.

2. **`launchd_keepalive.staged_is_current()` FALSE-POSITIVE — TODO.**
   During repair, `staged_is_current(0.34.0)` returned **True** while the DATA-staged
   `daemon.py` was an OLD version (staged `def main` at 1155 vs 0.34.0's 1291). So
   `install()` skipped restaging and the keepalive kept booting the OLD (buggy) daemon.
   Because of this, fix #1 will NOT reach the launchd path until staged_is_current is
   corrected AND a new version is published+restaged. Read
   `scripts/lib/launchd_keepalive.py::staged_is_current` + `keepalive_stage.py` — find why a
   stale closure compares equal (likely comparing the wrong file set / a frozen dir / mtime
   vs content). Fix so a stale closure reliably reports NOT current → restage runs.

3. **Keepalive test-isolation escape (RECURRENCE of a host-crash bug) — VERIFY/FIX.**
   The production `daemon-keepalive.boot.log` contains `pytest-of-emanuelesabetta/pytest-1572/
   test_corrupt_stage_is_restaged0/...` paths — keepalive tests wrote to REAL DATA state.
   This is the class in project-memory note **`janitor-keepalive-test-isolation-fsevents`**
   (TRDD-ZNN0UK5K, 2026-07-03): frozen `Path.home()` module constants invisible to a test's
   `monkeypatch.setenv("HOME")` → tests escape isolation → corrupt the real staged closure →
   every real boot finds it "corrupt/incomplete" and re-copies → fseventsd firehose → the
   host once hit 39GB/97%-CPU and CRASHED. That was "fixed" 2026-07-03 (call-time
   `keepalive_boot._state_dir()` + `launchd_keepalive.data_dir()`). READ that memory note,
   then VERIFY the fix still holds OR find the regression/another frozen constant. Proof of
   a clean fix (the note's method): run `pytest tests/` and confirm
   `find ~/.claude/janitor-global-state ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins -newermt "<suite start>"`
   shows NO real-state files written during the run. Isolation levers are
   `JANITOR_GLOBAL_STATE_DIR` + `JANITOR_DATA_DIR` (NOT `CLAUDE_PLUGIN_DATA`). Also clear the
   old pollution from the real boot log if safe.

4. **Keychain re-prompts ~100× with no "Always Allow" — INVESTIGATE, attempt mitigation.**
   USER reported the keychain dialog opened ~100× with NO "Always Allow" button; they
   started cancelling. Cause: the daemon's `security` reads come from a **uv-cached python
   whose path changes every version** (`~/.cache/uv/.../python`) AND/OR it reads the
   ACL-restricted `Claude Code-credentials` live item (created by Claude's own `/login` with
   a Claude-only ACL). macOS can only offer "Always Allow" for a STABLE binary identity, so
   it re-prompts forever. 0.34.0's timeout makes this non-fatal (5s fail-fast) but the PROMPT
   still appears. Attempt a mitigation: e.g. the daemon should prefer the `-livebak` mirror
   (rotator-written, `-T`-accessible) and AVOID the `-w` secret read of the ACL-restricted
   primary when a presence probe (no `-w`, may not prompt) suffices; or a stable-python /
   ctypes SecKeychain path (the memory note flags ctypes as "deferred hardening"). If a clean
   fix is too big, DOCUMENT precisely what's needed + whether it requires a USER keychain
   action, and leave it for a follow-up TRDD.

**NEXT ACTION (for the fix-agent):** fix #2 and #3 (the crash-loop drivers), attempt #4,
run the full `pytest tests/` (12233 tests must pass + no real-state pollution), commit each
fix with a WHY body (`Agent: ai-maestro-janitor` trailer). Do NOT push (the orchestrator
publishes). Report file + one line back.

**THEN (orchestrator):** publish 0.35.0 (`publish.py --minor`; push needs `--no-verify` — the
pipeline validates, only the network push is hook-gated), fleet-upgrade
(`claude plugin update ai-maestro-janitor@ai-maestro-plugins`), restage keepalive from 0.35.0,
verify the launchd daemon boots + reaches the task loop (fresh `daemon.log` `task … starting`
entries, stable pid, no crash-loop), and un-quarantine as needed.

**Load-bearing facts / gotchas:**
- The daemon works when spawned by a session heartbeat (has `CLAUDE_PROJECT_DIR`); it ONLY
  crashes on the launchd path. Proven: a cache-path daemon run with `CLAUDE_PROJECT_DIR` ran
  `marketplace-refresh` (80s) cleanly.
- Real-state write-guard (conftest S1b): a daemon self-update mid-suite can false-positive on
  `.py`-closure churn — but a keepalive-test escape is REAL pollution. Distinguish carefully.
- lean-ctx blocks `python3 -c`, heredocs with `def`, `$(...)`-in-args, bare `ssh`/`timeout`.
  Use script files.

## SUPERSEDED — do NOT carry forward
- Earlier this session I attributed the crash-loop to the keychain hang. WRONG — the keychain
  hang (fixed in 0.34.0) is a DIFFERENT symptom; the crash-loop driver is bug #1 (`/.janitor`)
  compounded by #2/#3. Also I called the write-guard `.py`-closure exit-3 a pure false
  positive; it was partly REAL test pollution (#3).

## Implementation commits
- `d939110` — fix #1 (init_state resilient to read-only `/`).
