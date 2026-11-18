---
trdd-id: 6E2I17HN
title: The redaction bridge and the secrets-shield-scan skill start bun in the caller folder so a project bunfig preload runs
column: complete
status: archived
created: 2026-11-18T17:06:43+0100
updated: 2026-11-18T17:21:51+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T17:06:43+0100
implementation-commits: [54e7d7c8]
---

# The redaction bridge and the secrets-shield-scan skill start bun in the caller folder so a project bunfig preload runs

## Approval log

- 2026-11-18T17:06:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-18T17:21:51+0100 — COMPLETE by main-agent@ai-maestro-janitor. archived as complete (from column backburner).

## Symptom

scripts/lib/transcript_redact.py _bridge_results runs subprocess.Popen([bun, bridge]) with no cwd, so the redaction bridge runs in the caller folder (a project). skills/janitor-secrets-shield-scan/SKILL.md (originally lines 40 and 224, now 40 and 226) told the agent to run bun run scan.ts from the caller folder, and scan.ts defaults its root to process.cwd() (scan.ts:124). A project bunfig.toml preload then runs as code, and could disable redaction before transcripts go to an outside model.

## Measured fact

bun 1.3.14, measured by the main agent: 'bun --cwd T script.ts' and 'bun script.ts' run from folder T both execute T/bunfig.toml preload and load T/.env. bun loads bunfig.toml and .env from its WORKING folder, not the script folder. --config on the command line does not reach Worker threads (measured by another worker), so it is not a fix.

## Fix

1. transcript_redact.py: Popen gets cwd=_BRIDGE.parent (the plugin hooks folder), never the caller folder. 2. SKILL.md: run 'bun --cwd ${CLAUDE_PLUGIN_ROOT} ${CLAUDE_PLUGIN_ROOT}/scripts/shield_scan/scan.ts [options] <absolute root>'; root and --out must be absolute because with --cwd a relative path resolves against the plugin folder. 3. Red test first in tests/test_transcript_redact.py: a tmp_path bunfig.toml preload must not run.
Landed (uncommitted when written): transcript_redact.py Popen cwd=_BRIDGE.parent; SKILL.md lines 40, 43 and 226 (checklist) use bun --cwd. Test: tests/test_transcript_redact.py::test_bridge_does_not_run_the_bunfig_preload_of_the_caller_folder (failed before the fix with assert not True, passes after). Measured 2026-11-18: bun --cwd <plugin> scan.ts run from a folder with a preload bunfig wrote no marker; bare bun scan.ts from the same folder wrote it. Open follow-ups: scan.ts:201 worker spawn has no cwd; scan.ts:2 header is stale; references/redact-and-restore.md:116 says bun run restore.ts from the caller folder; vault.ts:3 and :302 show bare bun vault.ts.

## Acceptance checklist

- [x] the redaction bridge starts bun with cwd=_BRIDGE.parent, never the caller folder (54e7d7c8, scripts/lib/transcript_redact.py)
- [x] a bunfig.toml preload in the caller folder does not run inside the bridge (by main-agent run: the new test fails on an archive of the pre-fix HEAD with assert not True and passes after the fix; tests/test_transcript_redact.py 30 passed; ruff, ruff format, mypy, pyright clean)
- [x] the secrets-shield-scan skill runs bun --cwd "${CLAUDE_PLUGIN_ROOT}" with an absolute root and --out (54e7d7c8, SKILL.md; by worker measurement: bun --cwd <plugin> scan.ts from a preload folder wrote no marker, a bare bun scan.ts wrote it)
- [x] the remaining exposure is carded: TRDD-51IDZ4DB
