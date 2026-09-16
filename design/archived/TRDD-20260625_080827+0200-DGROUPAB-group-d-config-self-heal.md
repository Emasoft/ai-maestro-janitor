---
trdd-id: DGROUPAB
title: Immortality GROUP D — keepalive interpreter fallback + staged-closure restage guard
column: published
created: 2026-06-25T08:08:27+0200
updated: 2026-07-04T05:14:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: MEDIUM
effort: M
labels: [immortality, os-keepalive, config-self-heal, group-d, resilience]
task-type: infra
parent-trdd: TRDD-324223a6
relevant-rules: []
release-via: publish
delivery: pull-request
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
implementation-commits: [2b2a996]
---

# TRDD-DGROUPAB — immortality GROUP D (config self-heal): ship only D-α + D-β

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

### Status: dev — a grounded READ-ONLY evaluation proved GROUP D is ~85% ALREADY COVERED. Only TWO genuinely-missing pieces remain (D-α, D-β); everything else in the D1/D2/D3 draft is already self-healed or not-applicable to a PLUGIN-based janitor. Do NOT build a fresh "config self-heal subsystem" — that would re-implement GROUP A/B + rules_installer.

- **THE EVALUATION (durable artifact — read before acting):**
  `reports/immortality-group-d/20260625_080445+0200-group-d-scope-eval.md` (file:line evidence).
  - **D1** (settings.json/hooks.json janitor block clobbered → reinstall): **NOT-APPLICABLE** —
    plugin-based janitor has NO janitor-authored block in the user's settings.json; Claude Code
    owns plugin-hook registration. The ONE config the janitor authors (`.claude/rules/*.md`)
    ALREADY has the exact detect-and-atomic-reinstall loop via `rules_installer.install_rules`
    (byte-exact idempotency + `os.replace`), run each SessionStart.
  - **D2** (corrupted CLAUDE_PLUGIN_ROOT/PATH → re-derive): **ALREADY the standing design** —
    every survival path hard-codes from `Path.home()` and distrusts `$CLAUDE_PLUGIN_ROOT`/
    `$CLAUDE_PLUGIN_DATA`; the cron fires the stub by baked-in absolute path. (Residual = D-α.)
  - **D3** (fresh machine / relocation → re-bootstrap): **ALREADY lazy-mkdir-everywhere** + the
    self-locating stub re-resolves newest cache each fire + OS-keepalive re-stages. (Residual = D-β.)

- **NEXT ACTION — implement the two residuals (the WHOLE of the real GROUP D):**

  **D-α — OS-keepalive interpreter fallback (HIGH value, S effort).** The OS-keepalive service
  execs `daemon_keepalive_entry.py` via its `#!/usr/bin/env python3` shebang ONLY (launchd plist
  ProgramArguments / systemd ExecStart). On a fresh machine / minimal GUI-login PATH / a host
  where launchd resolves `python3` differently than the user shell, the exec silently fails and
  the DEEPEST immortality layer never starts — no fallback (unlike the session-spawn path which
  already does `uv run` → `sys.executable`). Fix: resolve a concrete interpreter at INSTALL time
  and bake an absolute interpreter path + the fixed verbatim entry script into ProgramArguments/
  ExecStart (preferred — launchd/systemd then need no PATH), OR a tiny POSIX-`sh` wrapper that
  tries `uv run --script` → `python3` → a discovered `python3.x` then exec's the entry. CONSTRAINT:
  CPV-persistence-clean — resolve only the INTERPRETER; the script path stays the fixed verbatim
  entry (no dynamic code load). Acceptance: with `python3` removed from the service PATH, the
  daemon still starts under the keepalive. Files: `scripts/keepalive_install.sh`,
  `scripts/lib/launchd_keepalive.py`, `scripts/daemon_keepalive_entry.py` (+ tests).

  **D-β — verify-or-restage the DATA-staged daemon closure (MEDIUM value, M effort).** The
  OS-keepalive trusts its DATA-staged closure: `staged_is_current` only byte-compares `daemon.py`
  vs the cache, never the rest of the ~16-file closure, and nothing detects a corrupt/truncated
  stage (interrupted copy, disk-full, bit-rot, partial relocation). A torn stage → `import daemon`
  raises → OS service crash-loops with NO re-stage until a live session re-runs
  `_setup_os_keepalive()` — which an all-sessions-down host (the exact keepalive scenario) cannot
  provide. Fix: a cheap pre-launch integrity gate — the launched entry (or a thin pre-step) verifies
  the staged closure is complete + uncorrupted before `import daemon` (e.g. sha256 each staged file
  vs the cache `.integrity/manifest`, reusing the existing manifest machinery, FAIL-OPEN exactly
  like the stub), and on mismatch/missing `restage` from `latest_cache_scripts_dir()` before
  importing. Acceptance: corrupt one staged closure file → next keepalive launch re-stages from
  cache and starts clean; if the cache is ALSO gone, fail LOUDLY to the keepalive log rather than
  silent-crash-loop. Files: `scripts/daemon_keepalive_entry.py`, `scripts/lib/keepalive_stage.py`,
  `scripts/lib/launchd_keepalive.py` (+ tests).

- **Load-bearing constraints / gotchas:**
  - This is the DEEPEST immortality layer (the OS keepalive). FAIL-OPEN/FAIL-LOUD, never silent.
  - Keep CPV-persistence-clean: resolve interpreter, NEVER dynamically load a non-fixed script.
  - The interpreter-resolution + restage must be idempotent + re-runnable.

## Scope guards / non-goals
- Do NOT build a generic "config self-heal subsystem" — D1 is N/A, D2/D3 are already covered.
- Do NOT touch `rules_installer` (it already IS the D1-adjacent reinstall loop).
- D-α resolves the INTERPRETER only; the script path stays the fixed verbatim entry (CPV-clean).

## Why this exists
Closes the only two real config-resilience gaps the GROUP D evaluation found, WITHOUT
re-implementing the self-heal that GROUP A/B + rules_installer already provide. The honest,
token-saving conclusion of the eval: ship D-α + D-β, then GROUP D is done.
