---
trdd-id: 3T4DZWXA
title: Complete the rotator fold — integrate the user-scope OAuth wrapper (command + helpers) into the plugin
column: published
created: 2026-06-24T22:49:04+0200
updated: 2026-06-25T00:10:19+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 2
severity: MEDIUM
effort: L
labels: [oauth, rotator, naming-consistency, fold, refactor, self-contained]
task-type: refactor
parent-trdd: TRDD-f892e109
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: [install-script]
implementation-commits: [2a87a03]
published-version: 0.20.0
published-at: 2026-06-24T23:33:41+0200
external-refs: []
---

# TRDD-3T4DZWXA — complete the rotator fold: user-scope OAuth wrapper → plugin

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

### Status: published — SHIPPED in v0.20.0 (port commit 2a87a03, release 9a49dad); all gates green (full tests + CPV --strict 0/0/0/0). The one iteration: skill→command, because CPV's N11 forbids "claude" in skill NAMES; commands carry no such rule, so the command keeps the user's exact requested name (see [^9] on the OAuth memory page).

- **WHY (the gap):** the OAuth rotator was first built standalone in user-scope
  `~/.claude/account-rotator/` (TRDD-32acd15f, 2026-05-28). The 2026-05-31 fold
  (TRDD-f892e109) migrated the ENGINE (Python core, keychain state, daemon tick) into the
  plugin + `${CLAUDE_PLUGIN_DATA}/oauth-rotator/` but LEFT the user-facing WRAPPER — the
  `/refresh-claude-logins` command + the `.sh` helpers — behind in user-scope. User directive
  (2026-06-24): NO command/skill/rule outside the janitor may handle its OAuth; integrate the
  valid ones into the plugin, consistently `janitor-*`.

- **INVENTORY + classification** (full `~/.claude/account-rotator/` + `~/.claude/commands/`):
  - PORT (valid, no plugin equivalent):
    - `~/.claude/commands/refresh-claude-logins.md` → COMMAND `commands/janitor-refresh-claude-logins.md` (kept a COMMAND, not a skill — CPV's skill-name check forbids "claude"; commands carry no such rule).
    - `open-login.sh` (human SEED: clean real Chrome login) → `scripts/oauth_rotator/`.
    - `check-login.sh` (verify a profile holds a live session, read-only) → `scripts/oauth_rotator/`.
    - `lifetime-status.sh` (cookie-vs-OAuth lifetime table) → `scripts/oauth_rotator/`.
  - RETIRE (dead or already in the plugin — the USER deletes the user-scope copies):
    - `reauth.sh` (RETIRED shim → plugin `reauth.py` already owns this).
    - stale OLD copies: `rotator.py`, `slot_capture_token.py`, `slot_login.py` (plugin has current).
    - `com.emasoft.claude-account-rotator.plist` (RETIRED launchd, TRDD-f892e109).
    - `_probe_identity.py` (legacy probe).
    - `capture_via_login.sh` — orphaned (NOT called by refresh-claude-logins); examine, port only
      if it adds a capture path the plugin lacks, else retire.
  - LEAVE (NOT the janitor's OAuth):
    - user skills `oauth-implementation` (generic OAuth2 dev) + `anthropic-claude-development`
      (generic Claude-API dev).
    - `~/.claude/rules/janitor-footprint.md` (already the janitor's OWN shipped rule).
    - the legacy STATE/DATA (`state.json`, `slots/`, `profiles/`, `rotator.log`, chrome-profiles)
      — data, already covered by the canonical DATA dir + the read-fallback migration; not code.

- **PORTING ADJUSTMENTS (the load-bearing detail):** the user-scope scripts resolve the rotator
  by GLOBBING the cache dir (`ls .../ai-maestro-janitor/*/scripts/oauth_rotator/rotator.py | tail -1`).
  Once IN the plugin they live BESIDE `rotator.py`, so they must call the SIBLING
  (`"$(dirname "$0")/rotator.py"`), NOT glob the cache. Profile/state paths must use the canonical
  `${CLAUDE_PLUGIN_DATA}/oauth-rotator/` via `rotator.py print-profiles-root`, never the legacy
  `~/.claude/account-rotator/`.

- **REFERENCES to update** (`/refresh-claude-logins` → `/janitor-refresh-claude-logins`), 5 in-repo:
  `skills/janitor-auto-manage-oauth-on/SKILL.md`, `scripts/dispatch.py`,
  `scripts/detectors/oauth-cookie-reminder.py`, `.claude/project/memory/oauth-rotation-renew-reauth.md`,
  `scripts/oauth_rotator/cascade.py`. (grep -rn after, to catch any missed.)

- **USER-SCOPE CLEANUP (outside the project — the USER does this, I cannot write there):** after the
  port verifies, delete `~/.claude/commands/refresh-claude-logins.md` and the ported/retired
  `~/.claude/account-rotator/*.sh` + stale `.py` + the `.plist`. KEEP the legacy DATA until the
  canonical DATA dir is confirmed complete (it is the read-fallback).

- **PHASES (≤5 files each):**
  1. Port the 3 helper scripts into `scripts/oauth_rotator/` (path-adjusted) + author the
     `janitor-refresh-claude-logins` command (pointing at the in-plugin scripts).
  2. Update the 5 in-repo `/refresh-claude-logins` references.
  3. Tests (the ported scripts run + resolve paths; the command preflight) + CPV validate.
  4. Publish; then hand the USER the exact user-scope `rm` list.

- **DONE (Phases 1-3)**: ported open-login.sh / check-login.sh / lifetime-status.sh into
  `scripts/oauth_rotator/` (sibling-rotator path, canonical DATA dir; smoke-tested live — exit 0,
  both accounts resolved, zero cache-glob/legacy-path errors); authored the
  `janitor-refresh-claude-logins` COMMAND (a command, not a skill — CPV `--strict` flagged the
  skill-name reserved-word check on "claude"; commands carry no such rule, so the command form
  keeps the user's exact requested name); updated 15 refs across 5 files (incl. the memory reframe
  of the now-false "USER-scope, NOT janitor-shipped" label); added `tests/test_oauth_helper_scripts.py`
  (14 tests). 69 + 391 oauth/cascade tests green, ruff clean.
- **DONE (Phase 4)**: published v0.20.0 (pushed origin/main 9a49dad; GH release live). The fold
  is complete — the janitor now owns the whole REAUTH flow; nothing OAuth-related lives outside it.
- **REMAINING (USER ONLY — outside the project tree, I cannot delete there)**: remove the
  now-superseded user-scope originals — `~/.claude/commands/refresh-claude-logins.md` +
  `~/.claude/account-rotator/{open-login,check-login,lifetime-status,reauth,capture_via_login}.sh` +
  the stale `rotator.py`/`slot_capture_token.py`/`slot_login.py`/`_probe_identity.py` +
  `com.emasoft.claude-account-rotator.plist`. KEEP the legacy DATA (`state.json`, `slots/`,
  `profiles/`, `rotator.log`) — the read-fallback until the canonical DATA dir is confirmed complete.
- **POST-PUBLISH RECHECK (2026-06-25)**: a recheck of the shipped change refined the command's engine
  call `uv run "$ROT/rotator.py"` → `python3 …` (×3) — rotator.py is stdlib-only, so `uv run` only
  risked syncing the caller's cwd uv-project; `python3` matches the 3 sibling `.sh` and removes that
  risk. Renamed the stale test fn `…_skill` → `…_command`. 14 helper tests green; rides the next publish.

## Scope guards / non-goals
- Do NOT port the stale `.py` copies (plugin has current) or the retired shim/plist.
- Do NOT touch the user's generic `oauth-implementation` / `anthropic-claude-development` skills.
- Do NOT delete user-scope files (outside the project) — hand the USER the exact list.
- Path-correctness is the #1 risk: the ported scripts must resolve the plugin's OWN `rotator.py`
  and the canonical DATA-dir profiles, never the cache-glob or the legacy home.

## Why this exists
Completes the 2026-05-31 fold (TRDD-f892e109): the rotator's user-facing wrapper escaped the
migration and lived in user-scope, breaking the "everything janitor-* and janitor-owned"
invariant. This makes the janitor self-contained for the full REAUTH flow.
