---
trdd-id: ZIKYQQY0
title: The runaway guard still needs a second abandonment signal and a correct ledger destination
column: todo
status: tasked
created: 2026-10-20T19:07:56+0200
updated: 2026-10-20T19:07:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T19:07:56+0200
---

# The runaway guard still needs a second abandonment signal and a correct ledger destination

Two adversarial reviews of the runaway-kill chore (TRDD-5G66S0HK, commit e67f9b0c) found five defects, which are fixed in 871d3649. This card owns the findings that REMAIN.

A-0 THE AGE GATE HAS ALREADY PRODUCED A MEASURED NEAR-MISS. On 2026-10-20 a test that drove the real chore against the real process table caused the guard to select pid 29880 as its victim: a LIVE pytest run in this very repo, 3716 s old, belonging to another session and running at that moment. The project's own sandbox guard BLOCKED the signal ('that process was NOT spawned by this test'), so nothing was killed — but the attempt is the measurement, and the guard's only protection against another session's running work is the age gate, whose shipped 3600 s value was one minute from expiring on a live process. The offending TEST is fixed (it now stubs the killer), but the RULE is not. This item is no longer a refinement: it is the difference between a guard that is safe and a guard that is one minute away from killing a colleague's test suite.

A-1 THE AGE GATE IS THE ONLY THING PROTECTING ANOTHER SESSION'S LIVE WORK, and the shape allowlist does not help. MEASURED on the live host with the gate relaxed to 0: THIRTY-TWO processes became killable, and the two largest were a LIVE plugin-validation run (221 MB) and a LIVE pytest run (184 MB) belonging to other sessions. 'pytest' is on the allowlist because an agent's abandoned test run is a real runaway shape, and a live pytest run matches that pattern EXACTLY — the shape alone cannot tell them apart. A review measured a 2202-second-old agent-started pytest run on this host and confirmed it would be a victim at a 3700-second gate. THE FIX NEEDED: a second, INDEPENDENT discriminator for 'abandoned', not a restatement of the age. The candidate is measurable and already in hand — a process that is BOTH older than the gate AND reparented to launchd (ppid=1, its session gone) is an orphan, while an old process with a live parent chain is somebody's work. MEASURED on the six peak-space/watch.mjs orphans killed by hand on 2026-10-20: all six had ppid=1 and all six still carried the Claude environment markers. A second option is a per-shape age gate: the pytest shapes need a far larger gate than a statusline process does, because a legitimate test suite runs for hours. Until one of these ships, THE AGE GATE IS LOAD-BEARING AND THE KNOB HAS NO FLOOR, so an owner who sets it to 0 to 'make it more responsive' starts killing other sessions' running work.

A-2 THE KILL RECORD DOES NOT GO TO THE AFFECTED PROJECT'S LEDGER. The card's acceptance clause 8 requires it, and the daemon cannot do it today: findings_ledger.record is called with no project_dir, so it resolves to the CALLER's own project — for the daemon, the janitor's own ledger, never the killed process's project. The daemon does not know the project set, which is the same constraint the broadcast channel already respects. The fix must find the killed process's project from its command line or its environment (CLAUDE_PROJECT_DIR is carried by agent children and is exactly the right source) and pass it as project_dir, with the per-project channeling invariant still respected: the LEDGER entry is per-project (legal), while the BROADCAST stays host-level (also legal, and the two are different surfaces with different rules).

A-3 actor='human' IS SEMANTICALLY WRONG ON THE KILL RECORD. The HUMAN_ONLY_DIRECTIVE renders as 'HUMAN-ONLY — surface this to your human and move on; do not re-evaluate or attempt this yourself: '. The kill is ALREADY DONE — there is nothing to re-evaluate and nothing to attempt, so the directive is a lie about a finding whose content is 'I did it'. The repo-state card's own review established the rule that actor='human' means the remedy needs the owner; that is true there and false here. The fix is either to drop the field, or to give the ledger a distinction between 'needs the owner's action' and 'is a report the owner should see'.

A-4 THE BROADCAST RE-SURFACES EVERY HISTORICAL KILL INTO EVERY NEW SESSION. record_kill keeps the last 50 kills and NOTHING EVER CLEARS THE FILE. The dispatch phase's stamp is per-project, so a session that starts later has an empty stamp and re-prints ALL retained kills as a burst of drift lines into a fresh session's context. The stamp file is also written as the union of everything ever seen and is never pruned, so it grows without bound and every heartbeat re-reads it. The fix: a lifecycle for the file — an ack, or an age bound on the retained kills — plus a bounded stamp.

A-5 DEAD CODE AND A FALSE DOCSTRING IN runaway_alert.py. drift_parts is never called (the dispatch phase calls pending_kills directly) and its docstring describes a mechanism that does not exist; it claims 'the daemon's file is cleared by ack' and THERE IS NO ack FUNCTION. REPEAT_S and MAX_MSG_CHARS are declared and never used, and the 1-hour backoff the docstring claims does not exist. select_refused_alert takes min_etime_s and never uses it, so a caller passing it believes the alert is age-filtered when it is not.

A-6 THE JANITOR'S OWN LAUNCHD AGENT IS SAFE BY SHAPE, NOT BY PROTECTION. The protected set is {daemon pid, daemon's parent}, and the janitor's launchd agent (com.ai-maestro-janitor.daemon) is safe only because its command line matches no runaway shape. Since the allowlist includes pytest and 'uv run pytest', a future allowlist entry could match the janitor itself. A structural exclusion (by the janitor's own script paths) makes this an invariant rather than an accident.

A-7 THE SWAPFILE COUNT CAN NEVER BE READ ON THIS macOS, so the SWAPFILES threshold arm is unreachable. vm.swapusage carries no file count and vm.swapinfo does not exist on this host ('sysctl: unknown oid vm.swapinfo'), so the count is always None and the threshold can never fire. The panic log's '69 swapfiles' is exactly the signal the card wanted, and it is not being read. Either find the real source of the count on macOS, or drop the claim that it is read. The card's acceptance must not name a reading the code cannot take.

A-8 THE COMPRESSOR MEASUREMENT IS A PROXY, AND THE DOCSTRING PRESENTS IT AS THE THING. The code measures 'Pages occupied by compressor' as a PERCENTAGE OF PHYSICAL RAM (measured here: ~44% of 64 GB). The panic condition was '100% of segments limit' — the compressor's own SEGMENT POOL exhausted, which is a different quantity from a RAM ratio. The two correlate, but the docstring says the occupied pages 'are the one measured' as though the proxy question were settled, and the commit message's 'THE PROBE SEES WHAT FREE MEMORY CANNOT' leans on it. The docstring must say plainly that this is a PROXY for the segment-limit condition, not the condition itself.

ACCEPTANCE: (1) a second independent abandonment signal ships, and a live-host measurement shows that another session's RUNNING work is not a victim with the age gate RELAXED; (2) the kill record reaches the killed process's own project ledger, and a test asserts the project_dir is the killed process's, not the caller's; (3) the actor field is either correct or gone, with the reason stated; (4) the broadcast file has a lifecycle and the stamp is bounded, and a test asserts a NEW session does not re-print historical kills; (5) the dead code and the false 'ack' docstring are removed; (6) the janitor's own launchd agent is excluded structurally; (7) the swapfile-count claim matches what the code can actually read, or the threshold is removed; (8) the compressor docstring says PROXY, not the thing.

MUTATION-VERIFY every new assertion, and remember the three vacuous tests this card already found: a test must make the clause under test the ONLY thing that can refuse its subject.

## Approval log

- 2026-10-20T19:07:56+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
