---
trdd-id: G4BCRUP7
title: Armed once means autonomous forever — the 16-capability contract, audited and closed
column: dev
created: 2026-08-11T20:35:18+0200
updated: 2026-08-11T20:35:18+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-TUIBWHT7, TRDD-BRHJHWW0, janitor#246, janitor#248, janitor#249]
---

# Armed once ⇒ autonomous forever

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-11

**This card is an AUDIT-AND-CLOSE, not a build.** The strong prior — to be confirmed or killed
by the audit, never assumed — is that most of the 16 capabilities below are already implemented
and are simply DEFAULT-OFF, unreachable on a fresh install, or dependent on a manual
bootstrap step. The deliverable is therefore mostly: flip defaults, remove manual gates, close
the genuine holes, prove each with a test.

**NEXT ACTION:** collect the five audit reports under `reports/janitor-autonomy-audit/`, turn
every `GAP:` line into a row in the table below with a verdict, then fix in priority order
(R5 blocking-prompt, R6 model switch, R7 rate-limit escape first — those three are what makes a
session STOP, and a stopped session is the failure the owner is describing).

**Do NOT** close a row on the strength of a docstring or a grep hit. Every row needs the
file:line that proves the behaviour, per the claim-verification rule — the janitor has already
shipped two features this year whose default silently disabled them.

## Why (OWNER directive, 2026-08-11, verbatim intent)

> "make the janitor work by itself, update by itself, etc. without the need to re-arm, update,
> etc. manually. once the janitor is armed it must work forever until it is disarmed."

The through-line of every clause is the same requirement: **an agent must never be stopped,
idle, or waiting on a human**, and the main Claude must never be spent on work a script could
do. Everything below is a specialisation of that one sentence.

## The 16-capability contract

| # | Requirement (owner's words, compressed) | Suspected home in the tree |
|---|---|---|
| R1 | Arm once; stays armed until disarmed; no manual re-arm | TUIBWHT7 + BRHJHWW0 (shipped v3.0.0) |
| R2 | Janitor updates ITSELF, automatically | `daemon.task_version_update`, `version_update_lib` |
| R3 | Keeps ALL plugins/extensions used by agents updated — USER, LOCAL **and PROJECT** scope | `fleet_plugin_updates.py`, `*-plugins-update.py` |
| R4 | Tracks the agent's GitHub posts, notices REPLIES, notifies the agent | `gh-reply-watch.py`, `gh_issues_monitor/` |
| R5 | Notices NEW issues on the repo | `github-issues-watch.py` |
| R6 | Any blocking error or ask-user prompt is answered with the DEFAULT option, or escaped | `fleet_inject.build_esc_plan`, `terminal_trigger` |
| R7 | Auto-switch model when the current model's window is spent | `model_fallback.py`, `token_burn.model_fallback_verdict` |
| R8 | Rotate the account token BEFORE the usage limit is met | `oauth_rotator/burn_gate.py` |
| R9 | If a limit lands anyway, escape the error/retry countdown and resume on the rotated token | `on-stop-failure.py`, `rate-limited.flag` |
| R10 | No agent is ever stopped or idle — always working | `session_liveness`, `fleet_recovery`, `peer-freeze-recovery` |
| R11 | A token-waste alert should SUGGEST delegating to lean-workers / cheap subagents | `pre-tool-token-budget.py`, `agentlens_probe` |
| R12 | Remind main Claude to write/update the wikimem after a significant change or lesson | `memorize-nudge.py` |
| R13 | Repos periodically checked for configuration issues | `fleet-github-config.py`, `github_config_audit` |
| R14 | Subconscious agents correct/optimise wikimem in background, silently | `memory-maintenance.py` + curator agent |
| R15 | ALL opened tickets fixed in background | `ticket-dispatch.py`, `janitor-repair-agent` |
| R16 | Every git push verified; CI errors and blockers reported | `ci-status.py` |

Plus the two cross-cutting constraints that govern all sixteen:

- **C1 — Silence discipline.** The main Claude is informed ONLY when the problem is one that
  only it can fix. Everything else goes to the ledger, the daemon, or a background agent.
- **C2 — Zero-token chores.** Anything a script can do must be done by a script, not by
  emitting a drift line that spends main-agent tokens to ask the model to do it.

C2 is the sharper of the two and the easier to violate accidentally: a detector that prints
"you should run X" has NOT automated X — it has moved the cost from a script to the most
expensive model on the machine, while looking like a feature.

## The three that matter most

R6, R7 and R9 are the only ones whose failure **stops** a session; the rest degrade quality or
currency. A stopped session is also the only failure mode that cannot self-heal, because the
thing that would heal it is the thing that stopped. Fix order follows that, not the table order.

R6 deserves particular scrutiny: sending ESC dismisses a prompt, which is NOT the same as
answering it with its default. If the codebase only ever sends ESC, then "answered with the
default option" is unimplemented, and a prompt whose default is the SAFE choice is currently
being cancelled rather than accepted.

## Acceptance

- [ ] Every row R1–R16 carries a verdict backed by a file:line, from the five audit reports
- [ ] R6/R7/R9 (the session-stopping three) are DEFAULT-ON and proven by a test each
- [ ] No capability in the table requires a manual bootstrap, opt-in command, or re-arm on a
      fresh install — or, where one is unavoidable, `/janitor-arm` performs it
- [ ] C2 audit: every drift line that ASKS the model to do something a script could do is
      either converted to a script action or justified in writing on this card
- [ ] R11's suggestion text actually names lean-workers / cheap subagents
- [ ] Released, and CLI-verified installed (tag-vs-cache file diff, 0 missing)
