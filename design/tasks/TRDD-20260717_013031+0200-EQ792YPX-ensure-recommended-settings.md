---
trdd-id: EQ792YPX
title: Janitor ensures recommended Claude Code settings in ~/.claude/settings.json (two merge modes)
column: published
created: 2026-07-17T01:30:31+0200
updated: 2026-07-17T02:21:39+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
release-via: publish
relevant-rules: [7]
eht: [2C8XFOW9]
implementation-commits: [523ec4a, 91bb4ec]
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-17

**Goal.** On every SessionStart, the janitor keeps two groups of Claude Code settings in sync in
the USER-global `~/.claude/settings.json`, with TWO distinct merge modes:

- **Group A — 8 env keys → the `env` block, ADD-IF-MISSING** (never overwrite an existing value; a
  key is "missing" iff absent from the settings.json `env` block). Deduped from the user's list
  (`CLAUDE_CODE_FORK_SUBAGENT` appeared twice):
  `ENABLE_BACKGROUND_TASKS=1`, `ENABLE_TOOL_SEARCH=false`, `CLAUDE_CODE_FORK_SUBAGENT=1`,
  `CLAUDE_AUTO_BACKGROUND_TASKS=1`, `CLAUDE_CODE_RETRY_WATCHDOG=1`, `CLAUDE_AFK_COUNTDOWN_MS=20000`,
  `CLAUDE_AFK_TIMEOUT_MS=300000`, `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS=2000000`.
  NB: `CLAUDE_AFK_TIMEOUT_MS` (5 min) OVERRIDES the Group-B `askUserQuestionTimeout` when set (CC
  env-vars doc), and `CLAUDE_AFK_COUNTDOWN_MS` (the warning countdown) is capped at that timeout so
  it must stay ≤ it.
- **Group B — 1 top-level key → ENFORCE (set-if-missing-OR-different, overwrite when the value
  differs):** `askUserQuestionTimeout = "60s"` (verbatim string — the trailing "s" for seconds is
  why it is a string). This is a SAFE FALLBACK; `CLAUDE_AFK_TIMEOUT_MS=300000` (Group A) overrides
  it to 5 min whenever set, so 60 s applies only if that env var is unset.

**Design.** New `scripts/lib/settings_ensurer.py` (constants + `enabled()` opt-out +
`ensure_recommended_settings(*, home=None)`); wired into `scripts/hooks/on-session-start.py` beside
`install_rules`; `ensure_settings_enabled` userConfig opt-out in `.claude-plugin/plugin.json`; a
`settings_ensurer_lock()` in `scripts/lib/global_state.py` (mirrors `oauth_rotator_lock`);
`tests/test_settings_ensurer.py` + a call in `tests/test_hooks_execute.py`.

**SHIPPED v0.47.0** (2026-07-17). Code: `settings_ensurer.py` (+ `global_state.settings_ensurer_lock`,
hook wiring, `ensure_settings_enabled` userConfig), commits 523ec4a (feat) + 91bb4ec (the SUPERSECURE
verify-before-swap write: `_verified_atomic_write` writes tmp → re-reads it from disk → proves valid
JSON + exact round-trip + only-intended-edits via the pure `_verify_invariants`, and swaps ONLY then;
any failure leaves the live file untouched). 20 unit tests + 1 hook end-to-end; full suite green;
isolation proof passed (real ~/.claude/settings.json untouched by the test run).

**FOLLOW-UP (spun out): [[TRDD-2C8XFOW9]]** — restart sessions after a settings change so it actually
applies (settings.json is read at CC startup). HIGH-BLAST-RADIUS; held for USER confirmation +
blocked on ai-maestro#75 (server restart command + a settings.json-edit API for workdir-restricted
agents). This is the EHT of this TRDD.

**NEXT ACTION:** none here — shipped. The apply-on-restart work continues under TRDD-2C8XFOW9.

**Load-bearing facts / gotchas:**
- **Restart-to-apply:** `settings.json` (env block AND top-level) is read at Claude Code STARTUP,
  so added/changed settings take effect on the NEXT launch, not the current session. The
  SessionStart notice must say so.
- **Frozen-`Path.home()` anti-pattern (the one that can corrupt the user's REAL config):** the
  settings path MUST be resolved AT CALL TIME (`_settings_path(home=None)`), never as a module-level
  constant. A module constant is computed at import, BEFORE a test's `monkeypatch.setenv("HOME")`,
  so the test would write the user's REAL `~/.claude/settings.json`. See wikimem
  `janitor-keepalive-test-isolation-fsevents` — that exact class of leak once corrupted staged
  state and crashed the host.
- **Anti-clobber:** malformed/unparseable `settings.json` → abort with an empty summary + a log
  line, NEVER write (we must never destroy a user config we could not parse). Missing/empty file →
  create `{}`. Preserve every other top-level key (`enabledPlugins`, `hooks`, …).
- **Only-write-on-delta:** compute missing/different keys first; if none, return without writing —
  so after the FIRST session on a machine, every later session is a pure read (no write, no race).
- **Concurrency:** `settings_ensurer_lock()` (non-blocking flock on
  `<global-state>/settings-ensurer.lock`, skip-if-held) serialises janitor-vs-janitor writes.
  Idempotency already prevents key loss (all writers add the SAME keys / the SAME enforced value),
  so the lock is defensive belt-and-suspenders that also guards any future non-idempotent change.
  A flock cannot protect against a NON-janitor writer (the user's editor) — the only defense there
  is the narrow only-on-delta write window + the atomic `os.replace` (never a torn file).
- **`ENABLE_TOOL_SEARCH="false"` is GLOBAL** — it disables tool-search for every project/session
  (token-economy L2). Intended; Group A respects an existing user override (add-if-missing).
- **`askUserQuestionTimeout` value is stored verbatim as string `"60s"`** (the trailing "s" for
  seconds is why it is a string). Verified against the CC settings doc: top-level key, accepts
  `"60s"`/`"5m"`/`"10m"`/`"never"`, default `"never"`, USER-scope only, needs CC ≥ 2.1.200. It is a
  FALLBACK — `CLAUDE_AFK_TIMEOUT_MS` (Group A) overrides it when that env var is set.

## Approval log

PROJECT-scope feature, in-scope for the janitor's own repo, explicitly requested by the USER in
this session ("the janitor must automatically add the following settings to ~/.claude/settings.json
…"). Tier-0 (own-repo feature the owner directly asked for). No cross-team/governance surface.

## Verify

`uv run pytest tests/test_settings_ensurer.py tests/test_hooks_execute.py -q`; the isolation proof
`find ~/.claude -name settings.json -newermt "5 minutes ago"` EMPTY during the run; full
`uv run pytest -q` + `ruff check` + `cargo test` green; then ship via `scripts/publish.py --minor`.
