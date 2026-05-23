---
name: janitor-supply-chain-watcher
description: Audits installed deps for HIGH/CRITICAL advisories (Shai-Hulud-class npm/PyPI/pnpm worm). Walks lock files, queries GHSA + OSV.dev, fails loud on HIGH/CRITICAL overlap. Cursor cache caps cost at <12 API calls/hour. Use when checking a project for known-compromised deps after a lockfile change, before a release, or on hourly cron. Trigger with /janitor-supply-chain-watcher.
---

# Janitor supply-chain-watcher

## Overview

Protects against the published-then-discovered-malicious shape (Shai-Hulud npm/PyPI/pnpm worm). Each fire: discover lock files, extract installed deps, query GHSA + OSV.dev, match advisory ranges, fail loud on HIGH/CRITICAL overlap. Hourly-cron suitable; the cursor cache holds steady-state cost under 12 API calls/hour.

## Prerequisites

- `gh` on PATH, authenticated.
- `curl` on PATH.
- `uv` for Python parsers.
- Project is a git repo.

## Instructions

1. Resolve paths:

   ```bash
   MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-supply-chain-watcher"; mkdir -p "$REPORT_DIR"
   TIMESTAMP="$(date +%Y%m%d_%H%M%S%z)"
   STATE_DIR="$MAIN_ROOT/.janitor/state"; mkdir -p "$STATE_DIR"
   CURSOR_FILE="$STATE_DIR/sca-cursor.json"
   ```

2. Validate prerequisites. `gh auth status` non-zero → `[FAILED] gh CLI not authenticated`. `curl` missing → `[FAILED] curl not on PATH`. Fail fast.

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
