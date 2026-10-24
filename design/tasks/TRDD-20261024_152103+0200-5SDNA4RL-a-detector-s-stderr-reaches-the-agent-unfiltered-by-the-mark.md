---
trdd-id: 5SDNA4RL
title: A detector's stderr reaches the agent unfiltered by the marker defang
column: dev
status: tasked
created: 2026-10-24T15:21:03+0200
updated: 2026-10-24T15:44:24+0200
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

2026-10-24: isolated probe (scratch copy of scripts/, throwaway detector zz-stderr-probe, empty scratch CLAUDE_PROJECT_DIR and state dirs). CONTROL PASS: the stdout line came back defanged as ⟦janitor-reload⟧ positive-control. LEAK YES: the bare [janitor-resume] the detector wrote to stderr appeared raw as the first line of the Bash tool result; a second run with stdout and stderr split to files proved the raw line came from stderr. The ls -l --full-time listing of this repo's .janitor/state was identical before and after (names, sizes and mtimes; contents were not compared). The cron path is the same channel: dispatcher-stub.py hands over with os.execv in its version resolver, which keeps the file descriptors (verified by reading the code), and the cron fire runs the stub inside a Bash tool call, as the probe did. That uv run --script leaves the stub's stderr inherited is inferred, not probed. Root cause: the subprocess.run calls in _run_detector (observed by the probe) and in _phase_guard_branch_protection (read in code, not probed) pipe stdout only, so a detector's stderr is inherited unfiltered. Evidence: reports/stderr-probe/20261024_153904+0200-stderr-probe.md (gitignored).
Fix review (2026-10-24): approved with conditions. (1) Pipe stderr with encoding utf-8 and errors replace, so a non-UTF-8 byte cannot crash a fire. (2) A detached grandchild that inherited stderr would hold the new pipe open and stall every fire until the detector timeout; an audit of scripts/detectors, scripts/lib and scripts/guard found eight detached spawns (local-plugins-update, project-plugins-update, cold_cache_clear_task, jev_compaction_lane, fleet_inject, global_state, and two in terminal_trigger), and every one sends stderr to a log file, DEVNULL or its own pipe, and no shell=True spawn exists. (3) Re-emit stderr defanged rather than dropping it: state.py run_subprocess and branch_protection_lib.py:597 print real diagnostics there, the latter including text from gh stderr that GitHub can influence. Limit: this narrows but does not close the gap in the heartbeat protocol, which acts on markers in the fire's stdout while the model sees stdout and stderr merged; dispatch.py's own stderr writes and the stub's are not filtered.
