---
trdd-id: EQ792YPX
title: Janitor ensures recommended Claude Code settings in ~/.claude/settings.json (two merge modes)
column: dev
created: 2026-07-17T01:30:31+0200
updated: 2026-07-17T01:30:31+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
release-via: publish
relevant-rules: [7]
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-17

**Goal.** On every SessionStart, the janitor keeps two groups of Claude Code settings in sync in
the USER-global `~/.claude/settings.json`, with TWO distinct merge modes:

- **Group A — 8 env keys → the `env` block, ADD-IF-MISSING** (never overwrite an existing value; a
  key is "missing" iff absent from the settings.json `env` block). Deduped from the user's list
  (`CLAUDE_CODE_FORK_SUBAGENT` appeared twice):
  `ENABLE_BACKGROUND_TASKS=1`, `ENABLE_TOOL_SEARCH=false`, `CLAUDE_CODE_FORK_SUBAGENT=1`,
  `CLAUDE_AUTO_BACKGROUND_TASKS=1`, `CLAUDE_CODE_RETRY_WATCHDOG=1`, `CLAUDE_AFK_COUNTDOWN_MS=120000`,
  `CLAUDE_AFK_TIMEOUT_MS=15000`, `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS=2000000`.
- **Group B — 1 top-level key → ENFORCE (set-if-missing-OR-different, overwrite when the value
  differs):** `askUserQuestionTimeout = "120"` (verbatim string, as the user wrote it).

**Design.** New `scripts/lib/settings_ensurer.py` (constants + `enabled()` opt-out +
`ensure_recommended_settings(*, home=None)`); wired into `scripts/hooks/on-session-start.py` beside
`install_rules`; `ensure_settings_enabled` userConfig opt-out in `.claude-plugin/plugin.json`; a
`settings_ensurer_lock()` in `scripts/lib/global_state.py` (mirrors `oauth_rotator_lock`);
`tests/test_settings_ensurer.py` + a call in `tests/test_hooks_execute.py`.

**NEXT ACTION:** implement the module, then wire the hook + plugin.json + lock, then tests, then
`uv run python scripts/publish.py --minor` (dry-run first for the CPV `--strict` NIT gate).

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
- **`askUserQuestionTimeout` value is stored verbatim as string `"120"`** (as the user specified).
  Verify against the CC settings doc that the key is top-level and sanity-check the type; store
  verbatim regardless.

## Approval log

PROJECT-scope feature, in-scope for the janitor's own repo, explicitly requested by the USER in
this session ("the janitor must automatically add the following settings to ~/.claude/settings.json
…"). Tier-0 (own-repo feature the owner directly asked for). No cross-team/governance surface.

## Verify

`uv run pytest tests/test_settings_ensurer.py tests/test_hooks_execute.py -q`; the isolation proof
`find ~/.claude -name settings.json -newermt "5 minutes ago"` EMPTY during the run; full
`uv run pytest -q` + `ruff check` + `cargo test` green; then ship via `scripts/publish.py --minor`.
