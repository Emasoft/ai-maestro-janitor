---
trdd-id: G4BCRUP7
title: Armed once means autonomous forever — the 16-capability contract, audited and closed
column: dev
created: 2026-08-11T20:35:18+0200
updated: 2026-08-12T12:50:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

### 2026-08-12 session — released v3.1.4 + v3.1.5, and drained the WORK columns to ZERO

**Shipped and CLI-verified installed** (tag-vs-cache diff, 0 missing, markers confirmed IN
THE CACHE): v3.1.4 (librarian `globs:` inversion janitor#252; orphaned-resume ledger flood)
and v3.1.5 (a live-identity change is a rotation, whoever performed it).

**`dev` went 7 → 0 and `testing` 7 → 5 — almost none of it by finishing work.** Six cards
were asserting activity that could not happen. The recurring cause, now carded and FIXED:
`af499ee3` (the cadence deletion) orphaned the premises of three cards at once, and **nothing
re-checks a STATE block against the tree**. That is now **check 5** of
`trdd-state-reconciliation` (TRDD-FDV1RQEB, `9a9bf0fa`) — a backticked identifier absent at
HEAD but present in `git log -S` history, severity by placement.

| card | was | now | why |
|---|---|---|---|
| AR9IUGIJ | dev | backburner | option C tuned a knob `af499ee3` deleted |
| 50V256RH | dev | backburner | root cause FALSIFIED — `/reload-plugins --force` DOES re-point live skills |
| VXFNDHXT | dev | archived/superseded | its TTL probe no longer exists; part 2 closed by `DEFAULT_TTL_MINUTES = 5` |
| I6ZZWVDN | testing | backburner | blocked on a real 429 — none in 26 days, which is the rotator working |
| UA4FAX67 | testing | todo | its trigger is BLACKED OUT on a server-owned host (fixed in v3.1.5) |
| QE390SJA | testing | backburner | every implementable box closed; only a field observation left |

**THE FINDING WORTH CARRYING FORWARD** (now in PROJECT memory, `ATOM-4GQU-0C9J`): when a live
ai-maestro server CLAIMS a chore, the janitor stops PERFORMING the act but keeps owning
everything downstream — so any breadcrumb our code writes goes unwritten, and the feature dies
exactly where the act still happens. Nothing notices, because a missing breadcrumb is
identical to "the event never occurred". Fix pattern: key off state BOTH runtimes produce
(a changed live IDENTITY), never off our own event-stamp. **Ask this of every chore the server
can claim.**

**FOUR CARDS ARE IN THE OWNER'S QUEUE and I had not been reporting them:** YBOZW3ES and
DO6X4ZF8 (both shipped, gates green, "awaiting the owner's call only"), KQ9WM4TZ (bless the
breadcrumb design), 6CRC9SQQ (a cross-project negotiation only the owner can initiate).

**NEXT ACTION:** keep draining `todo` (20 cards); the WORK columns are honest now. Do NOT
re-audit the six cards above — each carries its own dated correction.

---

### The 2026-08-11 head (kept)

**AUDIT DONE (5 reports in `reports/janitor-autonomy-audit/`). The prior HELD, and sharpened:
the recurring defect is not missing code — it is code that exists, is tested, is documented,
and NEVER RUNS.** Three instances in one session: the model fallback shipped dark (default
False), `fleet_plugin_updates.sweep()` had ZERO callers, and this card's own R9 fix nearly
shipped dead behind an ImportError swallowed by its `except`. Audit for REACHABILITY, never for
absence — `grep` finds all three and reports them present.

**SHIPPED so far:** R3 (sweep wired as a 6h daemon task under the marketplace lock,
`daemon.py:1869`) · R7 (model fallback default-ON) · R9 (429 fires a detached `rotator auto`
from the StopFailure hook — the ONLY recovery point a rate limit cannot reach, because a
heartbeat fire is itself a turn) · R11 · R14 (7 passes at 1/day) · R16 (CI failures into the
findings ledger, so they outlive a dead cron).

**R8 needs no work HERE: verified live on this host** — 3 accounts, rotation fired 2026-08-11
10:00:13 (`7d=100% +LOCALLY-EXPIRING -> rotate`). The audit's "default OFF" is a FRESH-INSTALL
gap only. Do not "fix" what is already running.

**RELEASED as v3.1.0 and CLI-VERIFIED** (2026-08-11): 1531/1531 tracked files present in the
installed cache, and all six behaviour markers confirmed IN THE CACHE (not merely in the tag) —
`ACTIVE 429 RECOVERY`, `task_fleet_plugins_update`, `FLEET_AWAITING_ESC_IDLE_S`, the 1/day
wikimem defaults, the model-fallback knob, and the `--porcelain` worktree parse with the broken
`| head | awk` form gone. R6 (presence-gated ESC) landed in that release.

**NEXT ACTION:** ONE owner decision, plus one QUESTION I ASKED WRONGLY — correct it before
re-asking (2026-08-12):
  1. hard-restart rungs — still OFF. They kill a wedged pid, losing that session's in-memory
     conversation. Enabling is the only way a dead pid self-heals unattended. Genuinely open.
  2. **"PROJECT-domain ticket approval gate" WAS TOO COARSE — do not re-ask it as posed.** The
     owner has ALREADY given a standing class-level direction, verified in USER memory
     `feedback_security_act_dont_ask#act-dont-ask-security`: for branch-protection rulesets,
     GitHub workflow YAML, publish pipelines and push hooks — do NOT use AskUserQuestion, fix
     everything detected, commit, report after; no push. It explicitly overrides RULE 1.4 for
     that work-class. Asking again re-litigates a settled question.

**The genuinely open slice** (per TRDD-631fa3de's own STATE, which is a DELIBERATE park, not
neglect — do not "revive" it as drift): autonomous EDITING of workflow YAML / repo files BEYOND
the ratified `baseline-*` rulesets. Applying the ratified pair as-is is already exempt+shipped;
the open pick is whether the janitor may REWRITE a vulnerable workflow on detection.

**VERIFIED 2026-08-12 — it IS the shipped-dark pattern, and it contradicts a standing owner
directive. Fourth instance this week.** `apply_baseline_rulesets` has exactly TWO callers:
  - `scripts/github_config_fix.py` — the ON-DEMAND `/janitor-github-config-fix` command (a human
    must run it), and
  - `scripts/guard/branch_protection_apply.py` — the only AUTOMATIC path, whose gate 1 is
    `guard_mode_enabled()`, default False, returning `0  # silent — the user has not opted in`.
It applies the RATIFIED baselines (its own docstring), not beyond-baseline deviations — so the
Tier-2 approval reasoning does NOT justify the default. Applying the ratified pair as-is is
EXEMPT per manager-approval-defaults §F, and `act-dont-ask-security` explicitly names
branch-protection rulesets as fix-on-detection.

So on a default install the janitor **never** auto-applies branch protection; it only flags
(`detectors/branch-protection.py`). TRDD-631fa3de's STATE claims "the janitor now auto-applies
the ratified pair" — that claim is FALSE on a default install and should be corrected there too.

**NEXT ACTION for this slice:** flip `guard_mode_enabled()` to default-ON. It is already
belt-and-braces guarded — `/janitor-autofix-off` vetoes it, the repo slug must resolve, `gh`
must be present, the viewer must be admin, and an unfetchable ruleset list means don't act. The
DEFAULT is the only thing standing between a detected unprotected branch and the owner's "every
minute is a window for supply-chain compromise". Do NOT widen it beyond the ratified pair —
beyond-baseline rewriting stays the genuinely open pick.
After those: R6 residual (permission-prompt detection via pane text) and the R3 server-host
blackout below.

**R3 CAVEAT, caught by the roster tripwire and NOT closable here:** on a host running a live
ai-maestro server the daemon is suppressed and nothing claims `fleet-plugins-update`, so
fleet-wide plugin updates are BLACKED OUT there. Standalone hosts are fine. Closing it needs
ai-maestro to claim the chore (cross-repo, same shape as ai-maestro#111 / TRDD-6CRC9SQQ); the
`global-chore-blackout` detector is what makes it visible meanwhile.

**TWO CONSTRAINTS THAT ARE NOT BUGS — do not burn a session trying to code around them:**
1. ~~A permission prompt needs pane-text detection.~~ **CORRECTED 2026-08-11 by measurement.**
   The premise holds — a Claude Code PERMISSION prompt is UI state, not a transcript record, so
   `awaiting_user_decision` genuinely cannot see it — but the conclusion drawn from it was
   WRONG. Such a session's transcript goes STALE, so it is diagnosed `frozen`, and
   `fleet_recovery.action_for("frozen", …)` already returns `esc_nudge, esc_nudge, esc_nudge,
   force_restart`. It is already ESC'd today. Coverage comes from STALL detection, not from
   recognising the dialog, and building a pane-text recogniser would have duplicated a working
   path while adding a false-positive surface that could ESC a healthy session.
   The genuine residual is much narrower: DIAGNOSIS PRECEDENCE. If such a session's cron also
   looks dead it is classified `cron_dead`, whose action is `rearm` — which TYPES A COMMAND
   into whatever is on screen, i.e. the 2026-07-17 failure re-run for a case
   `awaiting_user_decision` cannot flag. That is a precedence question (prefer `frozen` when the
   transcript is stale AND a dialog may be up), not a detection project.
2. Rotation requires >= 2 accounts, and registering the second needs a HUMAN one-time browser
   login. Below that, "rotate before the limit" degrades to "wait for the window" by physics.

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
