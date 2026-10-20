---
trdd-id: C8SALZOO
title: Janitor chores must yield to host pressure and never compete for CPU
column: todo
status: tasked
created: 2026-10-20T18:19:36+0200
updated: 2026-10-20T18:19:36+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T18:19:36+0200
---

# Janitor chores must yield to host pressure and never compete for CPU

OWNER DIRECTIVE (2026-10-20), verbatim: 'make this rule for the janitor chores: never execute them when the system is under pressure. wait a moment when the system activity is low to launch them, and pause them as soon as the system becomes too busy again. even if they will slip to the night, it is better than having those chores executed while the other main agents are struggling for cpu time and resources!'

THE INCIDENT THAT PROMPTED IT, MEASURED. On 2026-10-20 the host was unresponsive: load average 856 on a 14-core box, 427 runnable processes, memory 73% free and zero swap. The 166 iOS Simulator daemons were the largest runnable class, but the janitor's OWN background work was competing for the same CPU while seven other Claude sessions were struggling: 43 agentlenspro statusline processes alive at once during a fan-out, four concurrent pytest runs of the janitor's own test suite, six orphaned peak-space/watch.mjs processes reparented to launchd and still burning CPU two hours after their session ended, and tsc --noEmit runs from four different projects. The janitor's chores were not the dominant cause - they were a CONTRIBUTORY cause, and a contributor is still a cause.

THE RULE, in one sentence: a janitor chore must not start while the host is under pressure, and must yield the moment pressure appears.

WHAT 'UNDER PRESSURE' MEANS, and the existing machinery to build on. The janitor already has a load probe: scripts/detectors/host-load.py reads the load average and compares it to a bar of cores x 4 (56 on this host), and scripts/daemon.py's task_memory_guard already reads free memory with a floor. The pressure signal for this rule is the CPU one, because the measured incident was a CPU storm with memory to spare - a free-memory-only probe would have read the host as HEALTHY while it was unusable. The bar must be the LOAD AVERAGE relative to the core count, because an absolute bar does not travel between a 4-core and a 64-core host.

THE THREE BEHAVIOURS, and they are different mechanisms, not one. (1) DEFER: a chore whose due time arrives while the host is under pressure does NOT run; it is rescheduled and runs at the next beat at which the host is calm. A chore that is a few hours late is BETTER than a chore that starves the agent sessions, per the owner's directive. (2) PAUSE: a chore ALREADY RUNNING when pressure appears must be interruptible, so a long-running chore (the daemon's version-update sweep, the oauth rotator's browser capture, a memory chore) yields rather than finishing its work into a saturated host. (3) YIELD THE CPU: the janitor's own daemon and detectors must not themselves be the load. The statusline churn (43 processes) and the abandoned pytest runs are janitor-adjacent work that outlived its session, and a rule that only defers the NEXT beat leaves those running.

THE HARD PART, AND THE CARD MUST SAY IT PLAINLY: A RUNAWAY-KILL DAEMON IS THE ONE CHORE THAT CANNOT WAIT. TRDD-5G66S0HK's whole purpose is to relieve pressure, and a pressure-aware scheduler that defers the pressure-relief chore when the host is under pressure is a deadlock: the one chore that must always run is the one a busy host would suppress. The resolution this card must implement: the pressure gate applies to the MAINTENANCE chores, and the runaway-kill chore is EXEMPT - it runs regardless, because it is the mechanism that ENDS the pressure. A card that does not carve that exemption out ships a janitor that starves exactly when it is needed.

INTERACTION WITH THE EXISTING CHORE ARCHITECTURE, and where this lands. The daemon's chores are registered in scripts/daemon.py's Task registry and mirrored name-for-name in scripts/lib/harness_backend.py's GLOBAL_CHORES (tests/test_harness_backend.py asserts the two match, so a new chore needs an entry in BOTH). The per-project DETECTORS run under scripts/dispatch.py's heartbeat, which is a different path from the daemon's chores and has its own cadence. The gate therefore needs a home in each path, or the rule is only half-enforced.

WHAT MUST BE MEASURED BEFORE THE GATE SHIPS, because a threshold guessed under pressure is how a bad rule gets made. (a) The load-average bar that actually corresponds to 'the other main agents are struggling'. Measured on this host: at load 856 with 427 runnable processes the box was unusable; at load 214 (after the simulator and orphan cleanup) it was usable again. The bar must sit in that band and must not be so low that a single normal fan-out trips it, nor so high that the host is already dead when the gate closes. (b) How a chore learns the pressure signal CHEAPLY: a load average read is one syscall-class call, and the daemon already has a load probe; the gate must not add a per-chore probe that costs a subprocess spawn each. (c) How the load average behaves on THIS host under normal work, because a 14-core box running seven Claude sessions may sit at a load of 100+ without anyone struggling - if so, the bar must be relative to something other than the core count, and the card must MEASURE that rather than assume it.

ACCEPTANCE: (1) a janitor chore's due beat is DEFERRED, not run, when the host is over the pressure bar, and it runs at the next calm beat - with a test that asserts the deferral and one that asserts the eventual run; (2) a chore already running when pressure appears is interrupted or yields, with a test; (3) the runaway-kill chore is EXEMPT from the gate, with a test that asserts it RUNS under simulated pressure - this is the anti-deadlock acceptance and it is the most important one; (4) the pressure bar is derived from the host's core count and is a documented, MEASURED function of it, not a constant; (5) the gate applies in BOTH paths - the daemon's Task registry and the per-project heartbeat detectors - or the card states explicitly which path it covers and why the other is exempt; (6) a status line reports a deferred chore, so a chore that slips to the night is VISIBLE and not silently starved; (7) the janitor's own abandoned work (the statusline churn, the orphaned watchers) is reaped by a mechanism of its own, because deferring the next beat does nothing for work already running.

DO NOT make the bar a load-average constant copied from another host. MEASURE this host's band first and record the numbers with their scope.

## Approval log

- 2026-10-20T18:19:36+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
