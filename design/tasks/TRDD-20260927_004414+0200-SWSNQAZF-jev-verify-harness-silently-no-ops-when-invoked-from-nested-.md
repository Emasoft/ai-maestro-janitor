---
trdd-id: SWSNQAZF
title: jev-verify harness silently no-ops when invoked from nested or backgrounded shells
column: backburner
status: tasked
created: 2026-09-27T00:44:14+0200
updated: 2026-09-27T00:44:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-27T00:44:14+0200
---

# jev-verify harness silently no-ops when invoked from nested or backgrounded shells

Verified 2026-09-27 during the RAEGS1D5 V3/V12 re-stamp: scripts_dev/jev_verify/run_hook.py (V3 harness) fails SILENTLY when run_hook.py itself is invoked from certain shell contexts - a backgrounded compound bash, a heredoc-piped bash, or a bash script file with stdin=/dev/null. Failure signature (reproduced 4+ times): the inner hook subprocess returns in 0.05s with empty stdout, exit 0, stderr empty, sidecar UNCONSUMED - while the byte-identical invocation from the tool's interactive shell passes (wall 4.3-6.7s, v3_pass true). All V3 assertions then report has_compacted_section=false, transcript_path_occurrences=0, jev_really_ran=false. This is a DEV-HARNESS reliability defect (scripts_dev is gitignored, not shipped product code) but it poisons matrix evidence: the 2026-09-27 lean-worker run lost its whole first attempt to this and its driver log held only exit codes. INVESTIGATED, ROOT CAUSE NOT ESTABLISHED: the worker's 'stdin/env plumbing' theory is partially refuted - payload delivery to the hook via subprocess input= was verified correct in a minimal pure-python repro that still fails; ruled out payload mangling, env vars (identical), cwd relativity (absolute also fails when nested), hook-run.sh itself, and terminal_kind ancestry detection (kind=tmux in both contexts). Repro: bash -c 'python3 /tmp/nested-test.py </dev/null' shape, or 'cat <<EOF | bash' wrapping the uv run_hook.py invocation. NEXT: one lean-worker instruments run_hook + the hook (trace which guard returns first: _payload, source check, imports, pane key) under both contexts, diffs the process environment, then fixes or documents the constraint; harness gains a loud failure (non-zero exit or stderr) when the hook no-ops with a fresh unconsumed sidecar, so a future silent batch failure cannot masquerade as a matrix result. Related: TRDD-RAEGS1D5 (evidence stamp), TRDD-DQXMND59 (matrix).

## Approval log

- 2026-09-27T00:44:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
