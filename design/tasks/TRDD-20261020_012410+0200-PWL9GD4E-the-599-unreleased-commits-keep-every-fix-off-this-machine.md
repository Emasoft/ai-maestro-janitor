---
trdd-id: PWL9GD4E
title: The 599 unreleased commits keep every fix off this machine
column: todo
status: tasked
created: 2026-10-20T01:24:10+0200
updated: 2026-10-20T01:24:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T01:24:10+0200
---

# The 599 unreleased commits keep every fix off this machine

THE FINDING, MEASURED: 599 commits sit on main after the v3.8.11 release, and the fixes that answer the owner complaints of 2026-10-20 are among them — so this machine is running code that is older than the code that would fix it. The gap is not a missing fix; it is an unreleased one.

WHAT IS PROVEN BY EXECUTION, not by inspection. Both code paths were run against THIS host's live rotator home (the plugin DATA dir's oauth-rotator home (~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator)):

- The REPO tree's scripts/lib/rotator_alert.py drift_parts(root, now) returns urgent=[] and advisory={} — the owner-only conditions are NOT agent-visible.
- The INSTALLED 3.8.11 tree's rotator_alert.drift_line(root, now) returns both owner-only texts: "every account is at its usage limit - waiting for a window to reset" and "no spare account to rotate to - run /janitor-capture-all-logins".

That is the whole repetition complaint. The repo already excludes those conditions from agent context (commit f795816c, TRDD-JWIGGMH0, 2026-10-19); the INSTALLED plugin still prints them on every single fire. The fix is 4 days old and unshipped.

WHY THE REPEAT IS STRUCTURAL, not a tuning problem. The heartbeat cron fires every 5 minutes on this project (4-59/5 * * * *). A standing owner-only condition — one that only /janitor-capture-all-logins can clear, and which has been true for days because every account is at its usage limit — therefore produced 288 identical drift lines per day, each one re-read by a model turn. The condition is not urgent: it is a standing chore awaiting the owner. The repo's separation of URGENT from ADVISORY exists precisely to stop this, and the installed build predates it.

THE SAME GAP EXPLAINS THE SECOND SYMPTOM, in part. The [token-anomaly] line of 2026-10-20 01:00 fired on 7,029,998 weighted tokens, "87.1x the session median". Measured against this project's own token-meter.jsonl: 3,610 heartbeat turns, p50 69,928, p90 346,995, p99 1,015,544, and 20 turns above 2M — four buckets above 7M in the last 12 days. The 01:00 bucket is ONE turn with 18 assistant messages, 6,447,908 input tokens, 5,731,532 cache-read, 8,937 output. So the detector's verdict is a TRUE POSITIVE by its own definition (it cleared both the robust-z bar and the absolute floor), and the spike is BOUNDED work in the main context, not a runaway process: there were no background subagents, so the line's advice — "stop background subagents with TaskStop and /compact" — names a lever the reader does not have. That ADVICE gap is real, is a separate and small change, and is NOT this card's subject. This card is about why no fix reaches the machine.

THE PUBLISH PATH IS MEASURED AND IT IS BLOCKED AT STEP 4 OF 11. uv run python scripts/publish.py --dry-run on this tree: step 0 bypass check clean, step 1 clean tree, step 2 lint+typecheck green (ruff clean, mypy 537 files clean, pyright 0 errors), step 3 tests green, step 4 "Validating plugin (remote CPV)" FAILS with "[CPV integrity] CRITICAL: integrity manifest mismatch" plus 3446 "deleted locally" entries, exit 2. This is the KNOWN upstream defect recorded on TRDD-CWKM5218 (cause found 2026-10-10 12:37): the validator under uvx takes site-packages as its plugin root, so no version is read, the hard-coded REPO_RAW_MAIN_URL names branch main while the repository's branch is master, every fetch 404s, and a stale ~/.cache/cpv/github-manifest-vmain.json then makes every manifest entry read as deleted. publish.py exempts exactly PLUGIN_SKIP_GITHUB_INTEGRITY and CPV_SKIP_GH_AUTH_CHECK (publish.py:1643), and CWKM5218 records that every release from 3.7.1 through 3.8.11 shipped under that exemption. So the publish is not blocked in principle — it is blocked by the PROJECT RULE on the board-drain card TRDD-S6GX1DHN, which says verbatim: "No publish until the board is drained".

THE RULE AND THE NEED ARE IN TENSION, AND THE TENSION IS THE ACTUAL BUG. The board is 343 open cards (66 testing, 39 blocked, 14 human_review, 6 todo, 2 dev, 101 complete-but-unarchived, 109 backburner). Draining 343 cards is a long job. But the owner's complaint is that alerts the janitor cannot act on repeat on every fire, and the fix for that is sitting in the tree, unreleased, since 2026-10-19. A rule that makes the machine's own fixes unreachable until an arbitrarily large board is drained will keep producing this class of incident indefinitely, and no detector will ever escalate it: repo-state reports it as a LOW ADVISORY, which is the correct severity for a repo that is merely dirty and the wrong severity for a repo whose shipped artifact is 599 commits behind its own working tree.

THE MECHANISM THAT MAKES IT SELF-PERPETUATING, measured. The dispatcher stub (plugins/data/.../dispatcher-stub.py) re-resolves the NEWEST CACHED VERSION on every fire and os.execv()s into it (stub main(): versions sorted, reversed, first verified one wins). The cron prompt points at the STUB, not at a version, so the installed plugin rolls forward only when a NEW VERSION IS PUBLISHED. A fix in the repo is invisible to every heartbeat until it is released. So the loop is: alert repeats -> agent diagnoses it correctly -> agent writes the fix -> agent commits it -> the fix sits in the tree -> the heartbeat keeps running the old build -> the alert keeps repeating. Each cycle produces a better commit and the same alert, and the alert is the only thing the owner actually sees.

WHAT THIS CARD MUST SETTLE, and what it deliberately does NOT decide: (1) the release of the already-written fix, and (2) whether the board-drain rule should have a carve-out for a fix that answers a LIVE owner complaint. (1) is a publish, and a publish is outward-facing — the owner's standing mandate permits it ONLY through scripts/publish.py, and the board-drain rule gates it. (2) is a change to a rule recorded in a TRDD, and that rule's own text leaves the decision to the owner.

NEXT ACTION: read TRDD-S6GX1DHN's "## Rules added by the review of 4de85716" section (it binds every wave and wins over the wave text) and determine whether a live-complaint fix is releasable ahead of the drain. If it is not, this card's deliverable is the unblock; if it is, this card closes as the release of f795816c plus the 599 commits.

## Approval log

- 2026-10-20T01:24:10+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
