---
trdd-id: 5SDNA4RL
title: A detector's stderr reaches the agent unfiltered by the marker defang
column: dev
status: tasked
created: 2026-10-24T15:21:03+0200
updated: 2026-10-24T15:35:58+0200
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
approval-datetime: 2026-10-24T15:21:03+0200
---

# A detector's stderr reaches the agent unfiltered by the marker defang

Found while fixing TRDD-4DP942BO (d626064f). _run_detector and _phase_guard_branch_protection pipe only stdout and pass it through _defang_foreign_markers; stderr stays inherited. scripts/lib/branch_protection_lib.py:597 (_trace_soft_fail) writes to stderr, and other detectors may too.

First step, before any fix: verify the premise. Does the Bash tool result of a heartbeat fire show the dispatcher's stderr to the model, both in a cron-fired turn and in a manual /janitor-resume? If yes, a forged bare [janitor-...] line on stderr is a second marker channel for every detector. Cross-reference: TRDD-F3LVCQ39 (census of agent-visible output).

## Approval log

- 2026-10-24T15:21:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-24T15:35:58+0200 — column → dev by main-agent@ai-maestro-janitor. probe is concrete and safe; pulled under the S6GX1DHN drain mandate

## Method

Probe: in a scratch copy of the plugin root (never the installed cache), add a throwaway detector, using the fake-script pattern from tests/test_dispatch_detector_streak.py, that writes a bare [janitor-resume] line to stderr and nothing to stdout. Run dispatch once through the Bash tool and check whether that line appears in the tool result.
If it appears: in _run_detector and _phase_guard_branch_protection, capture stderr with stderr=subprocess.PIPE, pass it through _defang_foreign_markers like stdout, and re-emit it on stderr. Add a capfd test that asserts on err, failing before the fix.
Isolation and controls (review of 60629ae3): run the scratch copy's scripts/dispatch.py directly, not through the stub (the stub resolves to the installed cache), with CLAUDE_PROJECT_DIR set to an empty scratch folder so this repo's .janitor/state is untouched. First confirm how detectors are selected (a registry inside dispatch.py, or files on disk) and register the throwaway one the same way, with interval 0. Positive control: the detector also prints a marker on stdout, which must appear defanged; if it does not appear, the detector never ran and the probe is void.
