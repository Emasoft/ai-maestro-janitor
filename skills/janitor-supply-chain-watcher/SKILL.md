---
name: janitor-supply-chain-watcher
description: Audits installed deps for HIGH/CRITICAL advisories (Shai-Hulud-class npm/PyPI/pnpm worm). Walks lock files, queries GHSA + OSV.dev, fails loud on HIGH/CRITICAL overlap. Cursor cache caps cost at <12 API calls/hour. Use when checking a project for known-compromised deps after a lockfile change, before a release, or on hourly cron. Trigger with /janitor-supply-chain-watcher.
---

# Janitor supply-chain-watcher

## Overview

Protects against the published-then-discovered-malicious shape (Shai-Hulud npm/PyPI/pnpm worm). Each fire: discover lock files, extract installed deps, query GHSA + OSV.dev, match advisory ranges, fail loud on HIGH/CRITICAL overlap. Hourly-cron suitable; the cursor cache holds steady-state cost under 12 API calls/hour.

## Prerequisites

- `gh` on PATH, authenticated.
- curl on PATH (for OSV.dev HTTPS queries).
- `uv` for Python parsers.
- Project is a git repo.

## Instructions

1. Resolve paths:

   ```bash
   # Anchor on CLAUDE_PROJECT_DIR, then resolve THAT repo's MAIN checkout (janitor#264).
   # Two real failure modes, and each single-source form hits one: resolving from the CWD
   # picks whichever nested repo the agent happens to be standing in, so two passes of one
   # chore wrote into two different `reports/` trees; using CLAUDE_PROJECT_DIR alone writes
   # into a LINKED WORKTREE, whose reports die with the branch. Anchoring the git call fixes
   # both — the anchor is stable for the whole session, and `git -C` still resolves a
   # worktree to its main checkout.
   ANCHOR="${CLAUDE_PROJECT_DIR:-$PWD}"
   MAIN_ROOT="$(git -C "$ANCHOR" worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p')"
   MAIN_ROOT="${MAIN_ROOT:-$ANCHOR}"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-supply-chain-watcher"; mkdir -p "$REPORT_DIR"
   TIMESTAMP="$(date +%Y%m%d_%H%M%S%z)"
   STATE_DIR="$MAIN_ROOT/.janitor/state"; mkdir -p "$STATE_DIR"
   CURSOR_FILE="$STATE_DIR/sca-cursor.json"
   ```

2. Validate prerequisites. `gh auth status` non-zero → `[FAILED] gh CLI not authenticated`. No curl on PATH → `[FAILED] curl not on PATH`. Fail fast.

3. Discover lock files at project root (skip `node_modules/`, `.venv/`, `vendor/`, `.git/`): `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `requirements.txt`, `uv.lock`, `poetry.lock`, `Cargo.lock`. Zero found → `[skip] no lock files found`, exit 0.

4. Parse each lock into `(ecosystem, package, version)` triples per the per-format parser notes in the reference. Dedupe.

5. Read cursor. Valid JSON → extract `last_advisory_published` (ISO 8601). Missing/corrupt → cold start per the cursor protocol reference.

6. Per ecosystem: query GHSA via `gh api graphql` (`publishedSince: $cursor`, ecosystem), then OSV.dev `/v1/querybatch` for the installed set. Merge advisory IDs. Intersect with installed `(package, version)` using the ecosystem range parser (semver, PEP440, cargo).

7. Filter `severity in {HIGH, CRITICAL}`. Lower severities are informational only — do NOT trigger non-zero exit.

8. Write `$REPORT_DIR/$TIMESTAMP-findings.md`: one section per affected package (package@version, advisory IDs + links, severity, fix-version, upgrade command).

9. Atomically update `$CURSOR_FILE` (`.tmp` then `mv -f`) with `last_advisory_published` = max `published_at` seen this run.

10. Any HIGH/CRITICAL → `[FOUND] N high/critical advisories affect installed deps. Report: <path>`, exit 1. Else `[OK] no high/critical advisories since <cursor>`, exit 0.

## Output

One stdout line (`[FOUND]`, `[OK]`, `[skip]`, `[FAILED]`). Report only when findings exist. Cursor updated atomically.

## Error Handling

- `gh auth status` non-zero → exit 2, `[FAILED] gh CLI not authenticated`.
- GHSA 5xx → retry once (5s); persistent → exit 3, `[FAILED] GHSA query failed`.
- OSV.dev 5xx → `[partial] OSV.dev unreachable, GHSA only`, continue.
- Lock unparseable → exit 4, `[FAILED] cannot parse <path>: <reason>`.
- Cursor corrupt → warn, cold start, do NOT delete (overwrite atomically on success).

## Examples

```text
User: /janitor-supply-chain-watcher
User: audit dependencies for supply-chain attacks
User: scan locks for advisories
```

## Remediation (fix)

The **janitor-security-agent** loads this skill to apply remediations after detection. If `/janitor-autofix-off` is set, this section is skipped — detection and report only.

### Finding class: HIGH/CRITICAL advisory on an installed dependency

**SAFE-TO-AUTO-FIX** — when a `fix_version` is available and the project has a test suite that can be run:

1. Determine the package manager from the lock file (`package-lock.json` → npm, `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `requirements.txt`/`uv.lock`/`poetry.lock` → Python, `Cargo.lock` → cargo).
2. Run the package-manager upgrade to the patched version:
   - npm: `npm install <pkg>@<fix_version> --save-exact`
   - pnpm: `pnpm update <pkg>@<fix_version>`
   - yarn: `yarn upgrade <pkg>@<fix_version>`
   - pip/uv: `uv add "<pkg>>=<fix_version>"` or edit `requirements.txt` and `uv sync`
   - poetry: `poetry add "<pkg>^<fix_version>"`
   - cargo: edit `Cargo.toml` version constraint then `cargo update -p <pkg>`
3. Run the project test suite. On green: commit the updated lock file and manifest. On red: revert the bump and **FLAG-FOR-HUMAN** — the upgrade may be a breaking change requiring code changes.
4. Update the findings report with `[AUTO-FIXED] bumped <pkg> <old> → <fix_version>`.

**FLAG-FOR-HUMAN** — when:
- No `fix_version` is listed in the advisory (advisory has no patch yet).
- The advisory affects a transitive dependency with no direct way to pin the version without forking the parent.
- The test suite exits non-zero after the bump (breaking change).
- The package manager is not in the set above (unsupported ecosystem).

In all FLAG cases, leave a `[FLAGGED] human action required — <reason>` line in the findings report and exit non-zero.

### What is NEVER auto-fixed

- Removing a dependency entirely (may break the application).
- Modifying git history (`git filter-branch`, `git rebase`, BFG).
- Force-pushing branches.
- Suppressing or downgrading an advisory severity to pass a gate.

## Scope

ONLY scans lock files. Does NOT modify manifests or lock files, run package-manager mutations, push, commit, or open PRs. Surfaces fix commands; the user executes them.

## Resources

- [lock-file-formats](references/lock-file-formats.md) — per-format parser notes.
  - [Parsers per ecosystem](references/lock-file-formats.md#parsers-per-ecosystem)
  - [Cross-format concerns](references/lock-file-formats.md#cross-format-concerns)
  - [Parser failure mode](references/lock-file-formats.md#parser-failure-mode)
- [advisory-sources](references/advisory-sources.md) — GHSA + OSV.dev contracts.
  - [Why two sources](references/advisory-sources.md#why-two-sources)
  - [Per-source contracts](references/advisory-sources.md#per-source-contracts)
  - [Cross-source post-processing](references/advisory-sources.md#cross-source-post-processing)
- [cursor-cache-protocol](references/cursor-cache-protocol.md) — keeping the watcher under 12 API calls/hour.
  - [File location and lifecycle](references/cursor-cache-protocol.md#file-location-and-lifecycle)
  - [Per-fire API budget math](references/cursor-cache-protocol.md#per-fire-api-budget-math)
  - [Failure recovery and invalidation](references/cursor-cache-protocol.md#failure-recovery-and-invalidation)
- `$MAIN_ROOT/.janitor/state/sca-cursor.json` — cursor cache.
- `$MAIN_ROOT/reports/janitor-supply-chain-watcher/<TS>-findings.md` — per-run findings.
