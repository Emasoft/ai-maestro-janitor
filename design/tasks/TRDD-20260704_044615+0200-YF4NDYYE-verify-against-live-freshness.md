---
trdd-id: YF4NDYYE
title: Plugin-freshness helper — verify cached plugin matches live before any cache-based audit (issue 69)
column: todo
created: 2026-07-04T04:46:15+0200
updated: 2026-07-04T04:46:15+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: MEDIUM
effort: S
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [audit-accuracy, cache]
external-refs: ["https://github.com/Emasoft/ai-maestro-janitor/issues/69"]
---

# TRDD-YF4NDYYE — Verify-against-live plugin freshness helper (issue #69)

## The task

Issue #69: audits/detectors that read the plugin CACHE (`~/.claude/plugins/cache/...`) can
report against a stale version — findings look authoritative but describe code that is no
longer what's installed/published, wasting an agent's whole investigation. Add a freshness
helper + make cache-based audits declare what they audited.

## Plan

1. `scripts/lib/plugin_freshness.py`: `freshness(plugin_root)` returns
   `{cached_version, installed_pin, latest_published, is_stale}` — reuse
   `version_update_lib.resolve_latest_published` + `pinned_version_for`; offline ⇒
   `latest_published=None`, never blocks (fail-open, cached-vs-pin check still works).
2. Wire it into the audit surfaces that read the cache: `/janitor-audit`,
   `janitor-self-integrity`, `provenance-audit` — each report header states
   `audited <plugin>@<version> (pin <pin>; latest <latest|unknown>)` and a one-line STALE
   warning when versions diverge.
3. Skills that instruct agents to read cached plugin code get one sentence: check
   freshness first; if stale, update/reload before auditing.

## Derived tasks

- Keep it CHEAP: the GitHub latest-release probe must be cadence-limited (reuse the
  existing daemon version-check stamp rather than a fresh network call per audit).
- Tests: stale detection (cache≠pin), offline fallback, header formatting.

## Verification

- An audit run against a deliberately old cache dir prints the STALE banner; issue #69
  closed with the report link as evidence.
