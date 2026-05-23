# Advisory sources — GHSA + OSV.dev contracts

Two independent data sources are queried per fire. Findings are unioned; either source by itself catches most published-then-malicious cases, both together catch the long tail of registry-specific advisories that GitHub has not mirrored yet.

## Table of contents

- [Why two sources](#why-two-sources)
- [Per-source contracts](#per-source-contracts)
- [Cross-source post-processing](#cross-source-post-processing)

## Why two sources

- GHSA is GitHub's curated advisory database. Strong on npm + PyPI + crates because GitHub owns the largest mirror of those registries and adds advisories within minutes of disclosure. Weak on registry-specific advisories that the upstream maintainers file directly with the registry (e.g. PyPI's own "package yanked for malware" notices) that take days or weeks to land in GHSA.
- OSV.dev is the Open Source Vulnerabilities database maintained by Google. It aggregates GHSA, PyPI advisories, RustSec, and many more sources. Its advantage over GHSA is the registry-direct feed: an npm package yanked for malware appears in OSV.dev within ~1 hour of the npm registry marking it, often before the GHSA mirror catches up.

Using both sources costs ~2 API calls per fire (one batched GHSA GraphQL, one batched OSV `/v1/querybatch`) and closes the gap between disclosure and detection from "days" to "hours" for the Shai-Hulud-class threat.

## Per-source contracts

### GitHub Security Advisories (GHSA) via gh api graphql

Single batched GraphQL query, one per ecosystem present in the installed set. Use `gh api graphql` (already authenticated).

```bash
gh api graphql -F cursor="$LAST_PUBLISHED" -F eco="NPM" -f query='
  query($eco: SecurityAdvisoryEcosystem!, $cursor: DateTime!) {
    securityAdvisories(first: 100, ecosystem: $eco, publishedSince: $cursor,
                       orderBy: {field: PUBLISHED_AT, direction: ASC}) {
      nodes {
        ghsaId
        severity
        publishedAt
        permalink
        vulnerabilities(first: 50) {
          nodes {
            package { name ecosystem }
            vulnerableVersionRange
            firstPatchedVersion { identifier }
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }'
```

- `$eco`: `NPM`, `PIP`, or `RUST` — see ecosystem mapping in [lock-file-formats.md](lock-file-formats.md).
- `$cursor`: ISO 8601 datetime from the last successful run; on cold start use `1970-01-01T00:00:00Z` and accept the larger first response (still capped at 100 per page).
- Paginate via `pageInfo.endCursor` until `hasNextPage` is false. Most steady-state runs return zero new advisories and one page is enough.
- `vulnerableVersionRange` is a string like `>= 2.0.0, < 2.1.5` — parse per the ecosystem range parser below.

### OSV.dev via curl

The `/v1/querybatch` endpoint takes up to 1000 `(package, version, ecosystem)` queries in one HTTP POST and returns a list of advisory-ID sets, one per query.

```bash
curl -sS -X POST https://api.osv.dev/v1/querybatch \
  -H "Content-Type: application/json" \
  -d '{"queries": [
        {"package": {"name": "left-pad", "ecosystem": "npm"}, "version": "1.3.0"},
        {"package": {"name": "requests", "ecosystem": "PyPI"}, "version": "2.28.0"}
       ]}'
```

Response shape:

```json
{"results": [
  {"vulns": [{"id": "GHSA-xxxx"}, {"id": "PYSEC-yyyy"}]},
  {"vulns": []}
]}
```

OSV.dev does NOT accept a `publishedSince` filter on the batch endpoint, so it returns the full set of known advisories per `(package, version)` on every call. The cursor optimization (see [cursor-cache-protocol.md](cursor-cache-protocol.md)) bounds this by short-circuiting OSV.dev entirely when zero new advisories arrived from GHSA since the last run AND the installed set is unchanged.

For each query, follow up with `/v1/vulns/<id>` ONLY for IDs that the cursor cache marks as new — that's the per-advisory API call that fetches severity, affected ranges, and references.

## Cross-source post-processing

### Merging advisories across sources

Each advisory ID is unique (GHSA-, PYSEC-, RUSTSEC-, etc.). Build a set keyed by ID; the value is the union of the affected `(package, version-range)` triples from both sources. If GHSA says `severity: HIGH` and OSV.dev's per-advisory record says `severity: MODERATE`, take the higher of the two — false positives on severity are recoverable, missed CRITICAL flags are not.

### Severity mapping

| GHSA `severity` | OSV.dev `database_specific.severity` | Watcher severity |
|---|---|---|
| `CRITICAL` | `CRITICAL` | CRITICAL (fail loud, exit 1) |
| `HIGH` | `HIGH` | HIGH (fail loud, exit 1) |
| `MODERATE` | `MEDIUM` | MEDIUM (informational, no exit code change) |
| `LOW` | `LOW` | LOW (informational) |

If a source returns no severity field (rare; usually OSV.dev for very fresh advisories), default to HIGH so the user is notified and can downgrade after manual triage.

### Range matching per ecosystem

| Ecosystem | Parser | Example range |
|---|---|---|
| `npm` | semver (node-semver compatible) | `>= 2.0.0 < 2.1.5` |
| `PyPI` | PEP 440 | `>=2.28.0,<2.29.0` |
| `crates.io` | semver (cargo flavor) | `>=0.4.0, <0.4.7` |

Use `uv run` shims to call a tiny Python helper that parses each range — relying on installed `node` or `cargo` for parsing introduces an extra runtime dependency and a slower hot path.

### Network error handling

- GHSA transient 5xx → retry once with 5s backoff. Persistent failure → exit 3 with `[FAILED] GHSA query failed`. The cursor MUST NOT be advanced on failure — the next run will retry the same window.
- OSV.dev 5xx → log `[partial] OSV.dev unreachable, GHSA only` and continue. The findings report flags any package as "GHSA-confirmed only" so the user knows the OSV cross-check was skipped. Cursor is advanced ONLY based on advisories actually seen — so the next run will pick up anything OSV.dev had that GHSA did not yet mirror.
- Rate-limit headers (`X-RateLimit-Remaining: 0` on either API) → exit 0 with `[skip] rate-limited until <reset>`. The cursor is not advanced.
