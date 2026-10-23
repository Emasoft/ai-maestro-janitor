---
trdd-id: JY0OBQZ4
title: Daemon runs at normal priority
column: dev
status: tasked
created: 2026-10-03T03:41:05+0200
updated: 2026-10-23T19:25:45+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:05+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
derived: true
implementation-commits: [30d320eb, b1870adb]
---

# Daemon runs at normal priority

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-18 CURRENT: R1 is done (ProcessType Standard since 2026-10-09, host step N2 done). Open: the tick-time acceptance (under 30 s at high load, high load = load1 at or above the logical core count). 2026-10-23 the field case was observed with mixed results: one 83 s tick at load1 136, all of it in the rotator subprocess, and one 0 s tick a minute later at load1 about 62 (Approval log 15:31). DONE 2026-10-23: the decision between restating the target for extreme load and putting a timeout on a blocking call (neither option yet). NOT DONE: finding which call or step inside the rotator child is slow; that is the NEXT ACTION below. DECIDED 2026-10-23 19:25 (Approval log): neither option yet, the 83 s is not explained; card moved to dev; NEXT ACTION is per-step timing written to rotator.log for every tick of 30 s or more. Numbers and history are in the 2026-10-18 lines under Approval log. SUPERSEDED 2026-10-03 list: full uv run pytest after R4c lands; host step N2 (owner decision): re-stage this Mac's LaunchAgent at ProcessType Standard, then check plutil -extract ProcessType and ps -o pri; after release, tick wall time under 30 s at high load in daemon.log.

### R1 — normal priority (`scripts/keepalive_install.sh:270`, `oauth_rotator/rotator.py claude_running()`)
1. Change `ProcessType` to `Standard`.
2. Add `timeout=10` to the `ps` call in `claude_running()`.
3. No `taskpolicy` demotion of plugin-update chores: at load 400 it would stop `claude plugin update` from finishing, and that is the path that installs this release.
- **Test**: render the plist through `keepalive_install.sh` into a temp dir and assert `plutil -extract ProcessType raw` ≠ `Background`. Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ
2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: Field check FAILED: the installed LaunchAgent plist still says ProcessType Background (the N2 re-stage is not done); since the 3.7.0 daemon start (2026-10-04T12:38) 8 of 1313 rotator ticks took 30 s or more, max 168 s (2026-10-05T06:09); the log is only 34 h and load level is not in it. The card stays in testing; the re-stage of the daemon's launch agent at standard priority is a host step for the owner and has not been done.
2026-10-05 — the 'possibly related: TRDD-HVGU9OBL' line above is WITHDRAWN: that card turned out to describe designed behaviour (the headless daemon skips the primary read on purpose and uses the mirror copy), so it is not a cause of this card's symptom.
2026-10-06 FIELD CHECK NOT MET: the LaunchAgent plist still sets ProcessType Background (the host re-stage step is not done) and the 3.7.5 daemon started 19:47 runs at priority 4; of 66 rotator ticks since then, 4 took 30 s or more (48, 48, 86 and 141 s). Needs the owner's host re-stage. Source: reports/board/20261006_210400+0200-testing-field-check.md.
2026-10-07: owner decision still open; nothing changed today; the LaunchAgent stays at ProcessType Background until the owner says so (re-staging at Standard is reversible).
2026-10-11 01:24. FIELD SIGNAL, NOT MET, from reports/board/20261011_005026+0200-testing-sweep.md (a read-only worker; leads, not re-read by the main session unless said): since the Standard job began (2026-10-09T22:20) 27 of 1514 oauth-rotator-tick runs took 30 s or more (40, 53, 47, 93 s among the first). Host load is in no log, so it is not shown that the slow ticks were under load. Stays in testing.

## Approval log

- 2026-10-03T03:41:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T06:22:33+0200 — column → testing. code committed; only field acceptance after release remains
2026-10-05 — possibly related: TRDD-HVGU9OBL (the primary live credential was unreadable on every logged rotator tick); a hypothesis, not a finding.
- 2026-10-06T21:08:30+0200 — column → human_review by main-agent@ai-maestro-janitor. field evidence in; waits on an owner decision or host step, see STATE
2026-10-09 HOST STEP N2 DONE by the main session under the owner mandate of 2026-10-09 ('just complete all TRDDs and decide yourself'). Before: installed plist ProcessType Background, daemon pid 73460 at pri 4. Ran the installed 3.8.11 keepalive_install.sh install (plist backed up to docs_dev/ first). After: plist ProcessType Standard (plutil), daemon pid 6931 at pri 20 (ps). The log paths in the plist also moved from the retired ~/.claude/janitor-global-state to the plugin DATA global-state dir. The install left the job UNLOADED and the daemon down for about a minute until a manual bootstrap call of launchctl; that defect is carded as TRDD-V13RIZUI. The stale item 'full uv run pytest after R4c' belongs to TRDD-3OS6AXV3, not here. REMAINING, event-gated: daemon.log tick wall times under 30 s across a high-load period on the Standard job (earlier baseline: 4 of 66 ticks at 30 s or more). Assessment report: reports/board/20261009_221754+0200-wave2-JY0OBQZ4.md.
- 2026-10-09T22:19:45+0200 — column → testing by main-agent@ai-maestro-janitor. host step done; waits on the tick-time field check under load
2026-10-18 01:05 FIELD CHECK NOT MET (slow ticks persist; the at-load clause cannot be judged), measured by the main session from daemon.log.1 and daemon.log ('oauth-rotator-tick' done-in lines, ticks of 30 s or more / all ticks, max): 2026-10-16 37/1129 max 188 s; 2026-10-17 73/1288 max 180 s; 2026-10-18 to 01:00 6/45 max 74 s. The daemon has run at ProcessType Standard since 2026-10-09 (host step N2), and slow ticks persist: 3.3 percent and 5.7 percent on the two full days, 13 percent over 45 ticks on 2026-10-18 (every 'done in' line is whole seconds, checked). The card's two Background baselines disagree (4/66 = 6.1 percent on 2026-10-06, 8/1313 = 0.6 percent on 2026-10-05) and none of the three samples has load, so nothing here shows what priority did. So slow ticks still occur on the Standard job; whether the acceptance 'tick wall time under 30 s at high load' fails cannot be told, because host load is in no log. R1 (ProcessType Standard, ps timeout) is done and stays; the open question is which part of the tick is slow. NEXT (buildable): log the host load average and per-phase times on every tick that takes 30 s or more, so the acceptance can be judged; related: TRDD-6CF3L7IJ (backburner). Returned to todo: slow ticks persist and the acceptance cannot be judged until load is logged.
- 2026-10-18T00:57:03+0200 — column → todo by main-agent@ai-maestro-janitor. field check failed: 3-6% of ticks still take 30 s or more on the Standard job
2026-10-18 IN PROGRESS: the daemon now logs 'rotator tick slow: subprocess Ns, esc-pass Ns, rc=..., load L1 L5 L15' for every tick of 30 s or more (commit b1870adb). HIGH LOAD for this card's acceptance = load1 at or above the host's logical CPU core count (sysctl -n hw.ncpu on macOS). The line attributes a slow tick to the rotator subprocess or the ESC pass only; per-step timing inside rotator.py (keychain read, usage call, refresh) is the next step if the subprocess phase dominates. Reaches daemon.log only after a release and a local plugin update.
- 2026-10-18T01:25:14+0200 — column → testing by main-agent@ai-maestro-janitor. slow-tick logging landed in b1870adb; acceptance judged from 'rotator tick slow:' lines after a release
- 2026-10-23T12:48+0200 — FIELD CHECK, NOT MET (read by the main session): b1870adb is in the v3.8.12 and v3.8.13 tags; the daemon restarted 2026-10-23T08:14 after a staged newer version; of 272 oauth-rotator-tick runs since then (about 4.5 h) none took 30 s or more, where the earlier samples on this card (8 of 1313, 27 of 1514, 4 of 66) predict about 2 to 16 and the pooled rate of 39 of 2893 predicts about 4, a mild positive signal, weak against the 0.6% sample; daemon.log holds no 'rotator tick slow:' line, but the running daemon's version was not confirmed, so that absence is evidence only if it carries b1870adb. Load during the window is not logged (the slow line records load only on a slow tick); load1 was 7.32 against 14 logical cores at check time only, so the high-load case the acceptance names is not shown. Stays in testing.
- 2026-10-23T15:31+0200 — FIELD CASE OBSERVED, ACCEPTANCE NOT MET (daemon.log read by the main session): at load1 136.03 on 14 logical cores the line '[2026-10-23T15:29:06+0200] rotator tick slow: subprocess 83s, esc-pass 0s, rc=0, load 136.03 60.22 30.22' was logged, and the tick before it took 8 s; the ticks before and after took 0 s. So the running daemon runs the slow-tick logger b1870adb added (its only emitter is scripts/daemon.py:1064; this resolves the version caveat of the 12:48 line), and one tick at high load took 83 s against the 30 s target, essentially all of it in the subprocess. The 15:30:06 tick took 0 s at load1 about 62, also above 14, so the high-load sample is two ticks, one over and one under the target. The subprocess runs under the same launchd job and so the same Standard class; the open question is whether the target is reachable at about ten times the core count, or one call inside the rotator child blocks under load and needs its own timeout.
- 2026-10-23T19:25+0200 — DECISION (main session, owner mandate of 2026-10-09): neither option yet. Neither a per-call timeout nor restating the target is justified, because the 83 s tick is not yet explained. Read-only traces (reports/board/20261023_192208+0200-JY0OBQZ4-blocking-calls.md and 20261023_192529+0200-JY0OBQZ4-read-count.md): every call in the tick is capped (checked by the main session: subprocess 120 s at daemon.py:1031, ps 10 s at rotator.py:1646; from the worker's code read, not re-checked: security 5-10 s, HTTP 20-30 s); a headless tick makes 5N+1 keychain reads by static count (headless path, current N=3 slots, 16 to 19), only 3 of them before the first rotator.log line, bounded by their caps rather than measured; importing rotator takes 0.07 s at load 10.7, an idle figure that cannot exclude start-up at load 136. So the 55 s before the first rotator.log line is not shown to be explained by keychain reads or imports, and the daemon keeps only about 130 characters of the child stderr, so a timeout line may have been cut. NEXT: log per-step times for every tick of 30 s or more to rotator.log (not stderr), then decide.
- 2026-10-23T19:25:45+0200 — column → dev. decision made: per-step timing before choosing a fix
