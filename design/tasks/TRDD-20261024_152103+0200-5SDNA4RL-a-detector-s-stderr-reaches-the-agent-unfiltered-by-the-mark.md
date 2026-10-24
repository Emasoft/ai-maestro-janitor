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

2026-10-24: isolated probe (scratch copy of scripts/, throwaway detector zz-stderr-probe, empty scratch CLAUDE_PROJECT_DIR and state dirs). CONTROL PASS: the stdout line came back defanged as ⟦janitor-reload⟧ positive-control. LEAK YES: the bare [janitor-resume] the detector wrote to stderr appeared raw as the first line of the Bash tool result; a second run with stdout and stderr split to files proved the raw line came from stderr. The ls -l --full-time listing of this repo's .janitor/state was identical before and after (names, sizes and mtimes; contents were not compared). The cron path is the same channel: dispatcher-stub.py hands over with os.execv (two grep hits in its version resolver), and fd 2 is not close-on-exec, so it is inherited; and the cron fire runs the stub inside a Bash tool call, as the probe did. That uv run --script leaves the stub's stderr inherited is inferred, not probed. Root cause: the subprocess.run calls in _run_detector (observed by the probe) and in _phase_guard_branch_protection (read in code, not probed) pipe stdout only, so a detector's stderr is inherited unfiltered. Evidence: reports/stderr-probe/20261024_153904+0200-stderr-probe.md (gitignored).
Fix review (2026-10-24), verdict approve with three conditions. Review condition 1: pipe stderr with encoding utf-8 and errors replace, so a non-UTF-8 byte cannot crash a fire. Review condition 2: a lingering descendant that inherited stderr would hold the new pipe open and stall each fire on which that detector is due, for up to its timeout (default 120 s). A grep for Popen, start_new_session, nohup, setsid and os.fork/os.spawn in scripts/detectors, scripts/lib and scripts/guard found eight spawns, and every one redirects or pipes stderr; no shell=True spawn exists in those three directories. Self-daemonizing external binaries (git, gh, uv, claude, memgrep), non-Python helpers and other scripts/*.py modules were not audited. REJECTED from condition 2: the lingering-grandchild unit test, because the hazard is a property of individual detectors rather than of dispatch, and such a test would only demonstrate the stall. Replaced by an end-to-end check: a full dispatch fire on a scratch copy before and after the fix, comparing wall time and per-detector outcomes, where any new error:timeout names a detector with a lingering descendant. Review condition 3: correct this card's wording (done), widen the call-site audit (MEASURE found only the two spawn sites in dispatch.py), and add the timeout and owner-marker tests. Per MEASURE (not re-verified here): re-emit stderr defanged rather than dropping it, because state.py run_subprocess and branch_protection_lib.py:597 print real diagnostics there, the latter embedding gh stderr text (lines 619, 647 and 672). Limit: this narrows but does not close the gap in the heartbeat protocol, which acts on markers in the fire's stdout while the model sees stdout and stderr merged; dispatch.py's own stderr writes and the stub's are not filtered.
