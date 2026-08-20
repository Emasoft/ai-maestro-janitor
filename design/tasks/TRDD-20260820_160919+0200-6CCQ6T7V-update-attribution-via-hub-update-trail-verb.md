---
trdd-id: 6CCQ6T7V
title: Plugin-update attribution — consume the hub's aimaestro-plugins update-trail verb in cache-integrity diagnostics
column: backburner
created: 2026-08-20T16:09:19+0200
updated: 2026-08-20T16:09:19+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-4OFMHOZ7]
npt: []
eht: []
---

# Consume `aimaestro-plugins.sh update-trail` for 4OFMHOZ7-class attribution

## Why

The 4OFMHOZ7 investigation (truncated plugin cache dir) burned hours attributing WHO
wrote the cache dir when: the daemon was exonerated only by log forensics, and the
initial truncator stayed unattributable because no per-target update stamps existed.
The hub accepted that finding and shipped `aimaestro-plugins.sh update-trail
[--limit N] [--target id] [--json]` — a queryable per-target update history.

## What

1. When a cache-integrity finding fires (plugin-cache-install-integrity class: missing
   agents/commands/hooks, partial dir), the detector/report enriches the finding with
   the last few `update-trail --target <id> --json` rows when the hub backend is
   present — actor, timestamp, outcome — so attribution is one read instead of a
   forensic session.
2. Fail-open: backend absent or verb errors ⇒ finding is emitted exactly as today,
   with a one-line "no update trail available" note.
3. Test: fake `aimaestro-plugins.sh` on PATH echoing canned JSON ⇒ enrichment present;
   absent ⇒ enrichment skipped, finding unchanged.

## Acceptance

- [ ] Cache-integrity finding carries the trail rows when the hub verb answers
- [ ] Backend absent ⇒ byte-identical finding + explicit no-trail note
- [ ] pytest, ruff, mypy, pyright clean

## Approval log
