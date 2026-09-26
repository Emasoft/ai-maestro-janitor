---
trdd-id: SWSNQAZF
title: jev-verify harness silently no-ops when invoked from nested or backgrounded shells
column: todo
status: tasked
created: 2026-09-27T00:44:14+0200
updated: 2026-09-27T00:51:17+0200
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
- 2026-09-27T00:44:52+0200 — column → todo. verified evidence on the card, ready for lean-worker dispatch
2026-09-27T00:55+0200 — review-fork remediation recorded: the 'ruled out cwd relativity' line in the body is WITHDRAWN (it rested on hd6/hd7 runs with stale sidecar timestamps — consume happens BEFORE the age check, so those runs only proved consume-then-stale-ignore). Re-tested with fresh sidecars: nested-bash + REPO-relative scratch -> v3_pass false (0.05s no-op); nested-bash + /tmp scratch -> v3_pass true (3.96s) — scratch-inside-repo vs outside-repo IS a real variable (review's lead confirmed). BUT not the whole story: direct-shell + repo-scratch PASSED at 00:36 (4.33s) and fails deterministically now (0.05s, twice) — a third time/state-dependent variable is unidentified; the scratch-cmp-A..D deletion at ~00:47 is one candidate event but recreating them did not restore the pass. One config surfaced a real masked error: from repo cwd with /tmp scratch the hook ran but 'jev_compact failed (exit 1): (self, mode, buffering, encoding, errors, newline)' — an open() TypeError signature in the compact subprocess; investigate that FIRST, it may share the root cause. Env correction: 'env vars identical' — SHLVL differed 2 vs 3, all others identical. Shell-nesting per se DISPROVEN as the variable. The harness loud-failure requirement stands: fresh unconsumed sidecar + empty stdout must exit non-zero; jev_compact failures must not be swallowed by the never-raises wrapper.
