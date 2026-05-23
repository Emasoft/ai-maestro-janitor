# Cursor cache protocol — keeping the watcher under 12 API calls/hour

The watcher is designed to run hourly via the existing janitor heartbeat. To avoid burning the GitHub API budget on every fire, an advisory cursor is persisted between runs so each call to GHSA only asks for advisories published AFTER the last successful run.

## Table of contents

- [File location and lifecycle](#file-location-and-lifecycle)
- [Per-fire API budget math](#per-fire-api-budget-math)
- [Failure recovery and invalidation](#failure-recovery-and-invalidation)

## File location and lifecycle

### File location and shape

Path: `$MAIN_ROOT/.janitor/state/sca-cursor.json` (sibling of every other janitor state file).

Schema:

```json
{
  "version": 1,
  "last_advisory_published": "2026-05-19T14:23:07Z",
  "lock_file_hashes": {
    "package-lock.json": "sha256:abcd...",
    "uv.lock": "sha256:ef01..."
  },
  "last_successful_run": "2026-05-20T08:00:00Z"
}
```

Fields:

- `version`: integer, currently `1`. Bumped on any breaking schema change. A run that reads an unrecognized `version` treats the file as corrupt (cold start).
- `last_advisory_published`: ISO 8601 datetime (UTC, `Z` suffix). The `publishedSince` filter for the next GHSA query. Equal to `max(advisory.publishedAt)` over every advisory seen in the last successful run.
- `lock_file_hashes`: per-lock-file SHA-256 of the on-disk content. Used to decide whether the installed set has changed since last run; if every hash matches, OSV.dev cross-check can be skipped entirely (the GHSA delta is the only thing that can affect findings).
- `last_successful_run`: ISO 8601 datetime of when the watcher last completed without `[FAILED]`. Diagnostic only — not used for filtering.

### Cold start vs warm start

| Condition | Behaviour |
|---|---|
| File missing | Cold start. Set `last_advisory_published` to `1970-01-01T00:00:00Z`. Issue ONE GHSA query per ecosystem (paginated up to all-history; typically 1-3 pages for any active project's installed set since GHSA only returns advisories actually matching `(package, version)` later in the pipeline). OSV.dev queried for every installed `(package, version)`. |
| File present, valid JSON, `version: 1` | Warm start. Use `last_advisory_published` as the `publishedSince` cursor. |
| File present, invalid JSON | Treat as corrupt. Warn (`[warn] sca-cursor corrupt, cold-starting`) but do NOT delete the file. The successful end-of-run write overwrites it atomically. |
| File present, unknown `version` | Same as corrupt. Forward-compat is the next run's problem. |

## Per-fire API budget math

GitHub `gh`-authenticated API limits: 5000 GraphQL requests/hour per token. The watcher's steady-state per-fire cost:

- 1 GHSA query per ecosystem present (typically 1-3: npm, PyPI, crates.io). Each query is paginated; in steady state, the response is < 100 advisories per ecosystem per hour, so 1 page each.
- 1 batched OSV.dev `/v1/querybatch` call (free API, no auth) ONLY when the GHSA delta is non-empty OR `lock_file_hashes` differ.
- N follow-up `/v1/vulns/<id>` calls to OSV.dev — only for advisory IDs NEW since the last run (in steady state, zero).

Steady-state ceiling (no new advisories, lock files unchanged): 3 API calls per fire (one per ecosystem). At a 5-minute heartbeat that's 36/hour; at hourly cadence (recommended) that's 3/hour, well below the 12/hour target.

Burst ceiling (new disclosure of a Shai-Hulud-scale event, ~50 new advisories across all ecosystems): 3 GHSA queries + 1 OSV.dev batch + ~50 OSV.dev follow-ups = ~54 calls in the affected fire. Subsequent fires return to the steady-state ceiling once the cursor catches up.

### Atomic update protocol

The cursor must be updated atomically so a crash mid-run cannot leave a partially-written file. The protocol:

1. Build the new state dict in memory.
2. Serialize to JSON.
3. Write to `$CURSOR_FILE.tmp.<pid>`.
4. `mv -f "$CURSOR_FILE.tmp.<pid>" "$CURSOR_FILE"` — `mv` on the same filesystem is atomic on POSIX.
5. Update happens ONLY after the report has been written and stdout status line emitted. Any failure before that point leaves the previous cursor in place; the next run will redo the same window safely (idempotent — GHSA returns the same advisories for the same `publishedSince`).

## Failure recovery and invalidation

### Recovery from corruption

A corrupt cursor file does NOT block the watcher: the next run cold-starts, takes the bigger one-time cost, and writes a fresh valid cursor on success. The bad file is overwritten atomically — no manual cleanup ever needed.

If a corrupt cursor persists across runs (e.g. the filesystem is read-only or the JSON serializer keeps producing bad output), the watcher will keep cold-starting every run. That's wasteful but never wrong; the user notices because every run takes longer than expected, and the fix is to inspect `$STATE_DIR` write permissions.

### Cursor invalidation

The cursor MUST be invalidated (cold start forced) when:

- The schema version bumps (`version: 2` is added in a future release; runs on the old code see an unknown version and cold-start).
- The lock-file set on disk has changed dramatically (more than 30% of `lock_file_hashes` entries don't match). This is a heuristic — a `npm install` that updates dozens of transitive deps could have introduced new vulnerable versions that the GHSA cursor would not flag because those advisories were published BEFORE the cursor (the user just hadn't installed the affected package yet).

The 30% threshold is tunable via `sca_lockfile_drift_pct` userConfig (default `30`). Implementation-wise: count entries in `lock_file_hashes` whose stored hash differs from the on-disk SHA-256, divide by total tracked entries, compare against the threshold. Above threshold → cold start AND log `[info] lock files drifted >30%, cold-starting cursor`.
