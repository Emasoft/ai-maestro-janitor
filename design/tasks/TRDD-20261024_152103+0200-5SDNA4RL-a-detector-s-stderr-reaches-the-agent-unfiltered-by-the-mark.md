---
trdd-id: 5SDNA4RL
title: A detector's stderr reaches the agent unfiltered by the marker defang
column: dev
status: tasked
created: 2026-10-24T15:21:03+0200
updated: 2026-10-24T15:40:23+0200
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

## Probe result

2026-10-24: isolated probe (scratch copy of scripts/, throwaway detector zz-stderr-probe, empty scratch CLAUDE_PROJECT_DIR and state dirs). CONTROL PASS: the stdout line came back defanged as ⟦janitor-reload⟧ positive-control. LEAK YES: the bare [janitor-resume] the detector wrote to stderr appeared raw as the first line of the Bash tool result; a second run with stdout and stderr split to files proved the raw line came from stderr. This repo's .janitor/state was byte-identical before and after. The cron path is the same channel: dispatcher-stub.py hands over with os.execv (lines 251 and 262), which keeps the file descriptors, and the cron fire runs the stub inside a Bash tool call, the same thing the probe did. Root cause: _run_detector (scripts/dispatch.py:1551) and _phase_guard_branch_protection pipe stdout only, so a detector's stderr is inherited unfiltered. Evidence: reports/stderr-probe/20261024_153904+0200-stderr-probe.md (gitignored).
