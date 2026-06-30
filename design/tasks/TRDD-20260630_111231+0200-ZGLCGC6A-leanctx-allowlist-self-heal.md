---
trdd-id: ZGLCGC6A
title: Armed sessions self-heal the lean-ctx shell allowlist additively — never bypass shell security
column: complete
created: 2026-06-30T11:12:31+0200
updated: 2026-06-30T11:12:31+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 3
severity: HIGH
effort: S
labels: [lean-ctx, shell-allowlist, heartbeat, session-start, security, self-heal]
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
test-requirements: [unit, lint, typecheck]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: [config-schema]
attempts: 1
last-test-result: pass
last-test-at: 2026-06-30T11:12:31+0200
implementation-commits: []
external-refs: []
---

# TRDD-ZGLCGC6A — lean-ctx allowlist self-heal for the janitor heartbeat

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-30

### Current state — ✅ IMPLEMENTED + TESTED (2026-06-30, committed locally, NOT pushed)
- New module `scripts/lib/leanctx_allowlist.py`:
  - PURE `required_tokens()` → `["dispatcher-stub.py","uv","python3","git","memgrep","-d"]`.
  - I/O `ensure_janitor_allowed()` — runs `lean-ctx allow <tok>` per token (10 s
    cap each, capture, `check=False`). FAIL-OPEN: gated OFF → `[]`; lean-ctx not
    on PATH → `[]`; per-call `SubprocessError`/`OSError` swallowed. SECURITY-SAFE:
    ONLY the additive `allow` subcommand; never a shell-security toggle; argv list
    (no shell string).
  - Gate: `CLAUDE_PLUGIN_OPTION_LEANCTX_AUTOALLOW` (default ON) via
    `state.is_truthy_env`; lazy dual-form `state` import (hook vs detector/test
    sys.path) so the pure accessor stays dependency-free.
- `scripts/lib/__init__.py` re-exports `leanctx_allowlist` (pyright/mypy
  `from lib import …` cleanliness; matches the rules_installer/state convention).
- `scripts/hooks/on-session-start.py` calls `ensure_janitor_allowed()` right after
  the rules-install step, wrapped fail-open (failure logs + continues; never
  breaks session start). Logs `lean-ctx allowlist self-heal: ensured …` when it
  acted.
- `skills/janitor-arm/SKILL.md` heartbeat-prompt block gains ONE sentence: if a
  shell-allowlist wrapper blocks the stub, the ONLY fix is additive
  `lean-ctx allow dispatcher-stub.py` — NEVER `shell_security=off` / redefine
  `shell_allowlist`.
- `.claude-plugin/plugin.json` gains the `leanctx_autoallow` boolean userConfig
  (default true) that backs the option env var.
- Tests `tests/test_leanctx_allowlist.py` (7): exact token list, fresh-copy
  isolation, option-off no-op, lean-ctx-absent no-op, present-path (all 6
  `allow <tok>` in order via a REAL fake `lean-ctx` on a temp PATH), non-zero-exit
  best-effort, timeout best-effort. No mocks.
- **7 new tests pass; full suite green; ruff + pyright clean on all changed files.**

### NEXT ACTION — orchestrator ships it
- DO NOT push/publish from this session — the orchestrator runs `publish.py`.

## Problem

`lean-ctx` is a machine-global shell-allowlist wrapper (`~/.config/lean-ctx/config.toml`,
`shell_allowlist_extra`, merged additively over built-in defaults) that gates the
Bash tool. On a machine running it, the heartbeat cron's bare `dispatcher-stub.py`
invocation (and a few dash-flags the dispatcher passes, e.g. `-d`) are BLOCKED until
the allowlist permits them. Armed sessions then either stall or — worse — attempt
DANGEROUS bypasses (`shell_security=off`, redefining `shell_allowlist=[]`), which
open the Bash tool to everything.

The correct, safe fix is purely ADDITIVE: `lean-ctx allow <cmd>` (idempotent —
"already allowed" on repeat). Shell security must NEVER be disabled.

## Solution

Make EVERY armed session self-heal the allowlist the additive way, automatically,
and tell the heartbeat prompt never to bypass security.

1. `scripts/lib/leanctx_allowlist.py` — pure token list + fail-open, security-safe
   `ensure_janitor_allowed()`.
2. `scripts/hooks/on-session-start.py` — call it after rule-install, wrapped
   fail-open.
3. `skills/janitor-arm/SKILL.md` — one sentence in the heartbeat-prompt block:
   the additive `lean-ctx allow dispatcher-stub.py` is the ONLY correct fix.
4. `.claude-plugin/plugin.json` — `leanctx_autoallow` boolean option (default ON).

## Acceptance criteria

- `required_tokens()` returns exactly the janitor token set, immutable to callers.
- `ensure_janitor_allowed()` is a no-op when the option is off OR lean-ctx is
  absent; otherwise runs `lean-ctx allow <tok>` per token; NEVER raises; NEVER
  disables shell security.
- SessionStart calling it can never break session start.
- The heartbeat prompt instructs the additive fix and forbids the bypasses.
- Tests cover all of the above with a real fake lean-ctx (no mocks); full suite +
  ruff + pyright pass.

## Notes and lessons learned
