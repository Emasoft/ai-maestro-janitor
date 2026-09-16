---
trdd-id: G4BCRUP7
title: Armed once means autonomous forever — the 16-capability contract, audited and closed
column: complete
created: 2026-08-11T20:35:18+0200
updated: 2026-08-16T06:05:32+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-TUIBWHT7, TRDD-BRHJHWW0, janitor#246, janitor#248, janitor#249, TRDD-KI6OWCZT, TRDD-JPL0JU86]
---

# Armed once ⇒ autonomous forever

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

### 2026-08-14 — R1-R16 re-verified against CURRENT source; R6/R9 default-on now proven by test

Full pass, report: `reports/small-cards/20260814_193048+0200-g4bcrup7.md`. All 16 rows carry a
file:line verdict. Confirms R3/R14/R16 were fixed since the 08-11 audit (`fleet_plugin_updates`
now has a live `Task` registration at `daemon.py:2177`; all 7 memory-editorial rates now default
`1`/day at `memory_settings.py:52-59`; `ci-status.py` now writes through `findings_ledger`).
Added `tests/test_daemon_session_liveness.py::test_session_liveness_beat_is_default_on_with_the_gate_env_var_unset`
— the session-liveness beat that both R6's ESC-escape and R9's rate-limit escape depend on had
no test that explicitly `delenv`'d the gate and proved the beat still fires.

**R6 is honestly PARTIAL, not fully MET, and that is by design, not neglect:** for the two
known human-facing prompts (`ExitPlanMode`/`AskUserQuestion`) the janitor explicitly REFUSES to
inject anything and pages a human instead (`daemon.py:1398-1440`) — "answered with the default
option" never happens for those two, on purpose. Every OTHER stuck diagnosis gets ESC-only
recovery, and that IS default-on and now proven. Do not "fix" this by making the janitor answer
a human-facing dialog — the card's own 2026-08-11 STATE already reasoned through why that would
be worse than paging a human.

**Two acceptance boxes NOT attempted this pass** (left open honestly rather than guessed):
"no manual bootstrap" (R8/R9's rotation opt-in + the 2nd-account browser login are known,
accepted exceptions — not re-litigated) and the C2 drift-line audit (out of scope for the time
budget; one candidate already on record, `project-plugins-update.py:214-235`, not adjudicated).

### 2026-08-13 — R11 closed, and it exposes a SECOND defect class beside "shipped dark"

This card's standing rule is *"do NOT close a row on the strength of a docstring or a grep
hit"* — aimed at code that exists but never RUNS. R11 turned out to be the mirror image, and
the rule as written would have waved it through: the text existed, was **reachable**, and was
**wired** on all three surfaces. Reachability was never the problem. **Nothing held it in
place.** `grep -rn "lean.worker" tests/` returned zero, and the requirement lived as one clause
inside three long advisory strings — the single most reword-prone shape in the tree. A
plausible tidy-up drops R11 and every gate stays green.

**Call it SHIPPED UNGUARDED.** Audit each remaining row for BOTH: *does it run?* **and** *what
fails if someone deletes it?* If the answer to the second is "nothing", the row is not closed —
it is merely true today. Applies with most force to any requirement whose whole implementation
is PROSE (a message, a nudge, a docstring contract), because prose has no compiler.

Method note, worth repeating: my first hypothesis was that the live alarm had OMITTED the
suggestion — the anomaly line I had been shown ended "…robust-z 61.1 over 2578 buckets…
agentlensPro: $201/h". Reading the source disproved it: the clause is unconditional and the
agentlensPro enrichment is appended AFTER it, so a truncated rendering shows the enrichment
while hiding the suggestion. **Absence in a truncated quote is not absence in the code** — the
same "the result looked too clean" tell as the two broken selectors on 2026-08-12, arriving
from the opposite direction.

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

**~~NEXT ACTION for this slice:~~ DONE 2026-08-12 — `guard_mode_enabled()` is now default-ON.**
Unset means ENABLED; only an explicit false spelling (`0/false/no/off`) opts out, so a typo in
the config value can no longer silently disable a security guard. The six remaining gates are
unchanged and all fail-closed, and the applier still reaches ONLY the ratified pair — the
beyond-baseline rewriting question stays the genuinely open pick, untouched.

Verified before flipping, because it was the one thing that could have made this harmful: the
guard resolves its repo slug from `CLAUDE_PLUGIN_ROOT` → `CLAUDE_PROJECT_DIR` → `Path(".")`.
Both env vars are UNSET in the cron-fire context and neither the stub nor `dispatch.py` sets
them, so it falls through to the cwd — i.e. THIS project's own `.claude-plugin/plugin.json`.
A non-plugin project resolves no slug and is skipped outright. Had either var been set to the
janitor's cache dir, a default-ON guard would have re-applied rulesets to the JANITOR's repo
from every project on the machine and never protected the user's own — running, but on the
wrong target.

**VERIFIED END-TO-END on the real path, not only by unit test** (2026-08-12 17:55): running
`scripts/guard/branch_protection_apply.py` with NO env var set now reaches gate 6 and writes
`Emasoft/ai-maestro-janitor  main  already-present` to `.janitor/state/branch-protection-acted.txt`.
Before the flip the same invocation returned at gate 1 and wrote nothing, so the ledger line IS
the behaviour change: gate 1 opens by default, gates 2-5 pass (autofix on, slug resolved, `gh`
present, default branch `main`), and gate 6 correctly short-circuits because the ratified pair is
already in place.
**Still unproven, and say so rather than imply otherwise:** the APPLY branch (POST/PATCH of the
rulesets) did not execute, because this repo is already compliant — nothing needed applying. What
is demonstrated is that the guard is now REACHED; that it applies correctly on a repo lacking
protection is covered only by tests, and would need an unprotected repo to prove for real.

Tests: `test_guard_mode_enabled_default_is_true` replaces the old default-is-false assertion,
plus `test_guard_mode_unset_or_unrecognised_stays_on` (`""`, `"garbage"`, `"of"`, `"flase"` must
all stay ON — under the old opt-in semantics those meant OFF). 47 pass, ruff + mypy clean.
The USER-scope memory that asserted default-OFF as verified reality was superseded, not
overwritten (`^7` on `baseline-branch-rulesets`), and README's two statements of the old default
were corrected.
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

- [x] Every row R1–R16 carries a verdict backed by a file:line, from the five audit reports
      — **VERIFIED 2026-08-14**, table + per-row provenance in
      `reports/small-cards/20260814_193048+0200-g4bcrup7.md`. Several rows rely on the prior
      audit reports' own direct file:line citations (read in full this session) rather than a
      fresh re-open — marked as such in the report, not claimed as freshly verified.
- [x] R6/R7/R9 (the session-stopping three) are DEFAULT-ON and proven by a test each —
      **VERIFIED 2026-08-14.** R7 already had `test_default_is_enabled_with_the_env_var_unset`.
      R6/R9 share `daemon.py:1266`'s default-True session-liveness gate; added
      `test_session_liveness_beat_is_default_on_with_the_gate_env_var_unset`
      (`tests/test_daemon_session_liveness.py`), which `delenv`s the flag and asserts a frozen
      session still gets ESC-only fired. R6's literal "answered with the default option" is
      NOT met for `ExitPlanMode`/`AskUserQuestion` — that is a deliberate refuse-and-page-human
      design (`daemon.py:1398-1440`), reported honestly rather than silently ticked as full.
- [x] No capability in the table requires a manual bootstrap, opt-in command, or re-arm on a
      fresh install — or, where one is unavoidable, `/janitor-arm` performs it
      **SWEPT 2026-08-16, all 16 rows, verdict per row backed by a file:line** —
      `reports/small-cards/20260816_060412+0200-g4bcrup7-bootstrap-sweep.md`.
      **14 AUTONOMOUS · 1 ARM-PERFORMED (R1 — the arm IS the carve-out this box grants) ·
      0 newly-found manual bootstrap · 0 unverified.** The only manual steps that surfaced are
      the ones this card already names and accepts: R8's rotation opt-in, the second-account
      OAuth **browser** login (no CLI can complete an interactive OAuth flow — this one is not
      automatable, not merely un-automated), and R10's `FLEET_HARD_RESTART_ENABLED` default-OFF.

      **R10 stays OFF deliberately and that is NOT a gap in this box.** Enabling it kills a
      wedged session's in-memory conversation, which is an owner policy call, not a mechanical
      default — having `/janitor-arm` flip it would DELETE the decision point rather than
      automate a bootstrap step. It is carded separately (the A5 hard-restart-rungs card, itself
      `blocked` on ai-maestro#102), which is where it belongs.

      **Four claims re-verified first-hand rather than taken from the sweep**, because a sweep is
      evidence and not a decision: `fleet_restart.py:136` (`…FLEET_HARD_RESTART_ENABLED", "0"` —
      OFF) · `daemon.py:1270` (`is_truthy_env(…SESSION_LIVENESS_ENABLED, True)` — ON) ·
      `memory_settings.py:51-58` (all seven passes `1`/day) · and R7, where the sweep's cited
      evidence was **imprecise** — it reported "grep shows a `True` default" while its grep only
      showed the env-var NAME and a docstring. The default is real, at
      `model_fallback.py:61` → `state.is_truthy_env(_ENABLED_ENV, True)`. Right conclusion,
      wrong proof; the proof is what a later reader will re-check, so it is recorded here.
- [x] C2 audit: every drift line that ASKS the model to do something a script could do is
      either converted to a script action or justified in writing on this card
      **DONE 2026-08-16 — 75 sites inventoried (complete coverage), ZERO C2 violations, all
      seven classes justified below. Nothing was converted because nothing needed converting.**

      **(a) The one recorded candidate is CLEARED, on source, not on its line numbers.**
      `project-plugins-update.py` no longer asks the model to commit anything: it commits
      `.claude/settings.json` ITSELF (`_commit_settings`), and prints only when the commit was
      REFUSED by `_commit_blocked_reason` (mid-merge / mid-rebase / mid-cherry-pick / detached
      HEAD) or when it failed. Neither is a C2 violation — a script must not resolve a
      half-finished rebase, and a silent failure would be worse than a line. **The recorded
      range `214-235` had drifted onto an unrelated read-only helper (`_resolve_git_dir`)**, so
      a reader trusting the citation would have adjudicated the wrong code. Cite behaviour, not
      line numbers, in a card that outlives several releases.

      **(b) A full inventory now exists** —
      `reports/c2-drift-audit/20260816_053513+0200-c2-drift-line-sweep.md`: **75 command- or
      action-instructing drift lines across 69 detector files.** **COVERAGE IS COMPLETE —
      113/113, reconciled 2026-08-16.** I first read the gap as 9 sites (113 examined vs a
      `grep -c "print("` count of 122) and recorded it as unexplained; both halves of that were
      wrong. `grep -c` counts matching LINES, and — the real error — the pattern `print(` is a
      SUBSTRING match, so it also caught 8 `*fingerprint(` calls
      (`_server_fingerprint`, `_candidate_fingerprint`, `read_dispatch_fingerprint`, …). A
      word-boundary grep gives **114**, and the one remaining difference is `ci-status.py:296`,
      a COMMENT that mentions `print()` and was rightly excluded. 114 − 1 = 113. Nothing is
      missing from the inventory.

      **(c) Why my own first pass was nearly useless, which is the reusable part.** Two grep
      sweeps over imperative verb phrasings found **6** sites; the exhaustive per-site read
      found 75. The reason is structural: most detectors emit `print(line)` where `line` was
      assembled elsewhere (`r.line`, a `hint`/`fix_hint` variable), so **the imperative text is
      never adjacent to the `print(`** and no grep over emission sites can see it. Any future
      pass must resolve the variable, not scan the call site.

      **(d) ADJUDICATED 2026-08-16 — ZERO C2 violations across all 75 sites.** Method, stated
      so the verdict is auditable rather than asserted: classify all 75 from the inventory,
      then read a representative of EVERY class first-hand in source, plus every site whose
      class was in doubt. Verified this way, not by grep:

      | class | n | why it is not C2 | verified |
      |---|---|---|---|
      | approval gate — `approve the fix with: {command}` | ~10 | The line IS the gate. `issue_catalog.raise_issue` is silent when a ticket is already open and silent FOREVER when a human refused it (suppressed until the evidence changes); it emits the command only to REQUEST approval. Automating it deletes the gate. | `issue_catalog.py:676-705` — one shared source covers all ~10 |
      | `/janitor-*-agent` dispatch | ~9 | Triaging a security finding is judgement. This is the C2-COMPLIANT pattern already — offload to a cheap agent instead of the main model inline. | `binary-magic-scanner`, `repo-trust-score` |
      | `claude plugin *` | ~6 | PRRD S2.1 / issue #7 single-writer FORBIDS the janitor running these itself. | `version-update.py:102` comment states the rule |
      | git ops on the USER's files | ~14 | RULE 0 + `never-git-add-all`: staging/committing/removing a user's files unasked is the harm. | `project-plugins-update` (the cleared candidate) |
      | interactive / credential | ~5 | A browser OAuth login is not scriptable. | `oauth-cookie-reminder.py:152-154` |
      | session-only actions | ~6 | `/compact`, `TaskStop`, `TaskUpdate`, `/mcp` act on the model's OWN session; no external script reaches it. | `token-usage-anomaly.py:146` |
      | human judgement on content | ~25 | Deciding whether an unknown binary is malicious, whether two cards contradict, or what malformed YAML MEANT is not scriptable; a wrong automated repair corrupts silently. | `trdd-drift.py:144`, `branch-protection.py:197` |

      **The one that deserved the hardest look, and passed:** `project-map-drift.py:89,149`
      prints `uv run scripts/claudemd_slim.py index` / `repomap_generate.py` — deterministic
      regenerations a script plainly COULD run. Both drift lines already carry their own
      justification inline: *"the janitor never rewrites CLAUDE.md itself (cache +
      co-ownership safety)"*, and they name WHEN it is cheap ("a fresh session,
      post-compaction, or pre-commit"). Auto-rewriting a prefix-injected file at an arbitrary
      moment forces a full prompt-cache re-write (~150k, TRDD-IJ94O8YD) on a file the user
      co-owns. That is the ideal C2 form: the trade-off is written where the reader meets it.

      **Method caveat, deliberately kept:** this is a class adjudication with a verified
      representative per class (and the largest class verified at its single shared source),
      NOT 75 individual line reads. That is what "justified in writing" needs, but a reader who
      wants per-line certainty should re-derive from the inventory report, which is complete.

      *(The plan recorded an hour earlier — "69 hits second-hand and unadjudicated, justify per
      class after verifying each class's members" — is what (d) above then carried out. Kept as
      the record of the method, not as outstanding work.)*
- [x] R11's suggestion text actually names lean-workers / cheap subagents — **VERIFIED
      REACHABLE AND NOW PINNED.** Three surfaces, all wired: `token-usage-anomaly.py:147`
      (unconditional inside the alarm f-string; roster `dispatch.py:446`),
      `pre-tool-token-budget.py:424` (hard+output) and `:440` (advisory), hook registered at
      `hooks.json:164`. The deny at `:422` deliberately does NOT carry it — it refuses a
      subagent spawn, so advising a subagent there would recommend the thing just blocked.
      **The box could not honestly be ticked on that alone: `grep -rn "lean.worker" tests/`
      returned ZERO.** The requirement lived only as a clause inside three long advisory
      strings — the most reword-prone text in the tree — so any rewrite dropped R11 silently.
      Now guarded by 3 tests (`test_hard_output_nudge_names_the_lean_worker_delegation`,
      `test_advisory_nudge_names_the_lean_worker_delegation`,
      `test_alarm_names_the_lean_worker_delegation`) plus
      `test_the_spawn_deny_never_suggests_delegating_to_a_subagent`, which pins the deny's
      exception so a "make R11 consistent everywhere" edit cannot reintroduce the
      contradiction. Falsified: reworded "lean-worker"→"cheaper" in all three sources and
      exactly those 3 failed; reverted, 50 pass, ruff clean.
- [x] Released, and CLI-verified installed (tag-vs-cache file diff, 0 missing)
      **VERIFIED 2026-08-16 on v3.3.7.** Released: tag + GitHub release, with the Release,
      memgrep-release-binaries and main CI workflows all `completed success`. Installed: the
      cache carries `3.3.7`, and the diff run by the method ATOM-1F78-3R1G prescribes —
      `git ls-tree -r --name-only v3.3.7 | sort` vs `find <cache-dir> -type f` — reports
      **1639 tag files, 0 missing**. The 99 cache-side extras are benign: `.git` internals of
      the shallow clone plus runtime `__pycache__` `.pyc` files, neither of which the tag ships.
      The janitor#232 failure signature was checked BY NAME rather than inferred from the zero,
      because that incident's whole point is that a partial install still LOADS: `agents/` (3),
      `commands/` (3), `hooks/` (1), `skills/` (88), `scripts/` (599), `.claude-plugin/` (1) all
      present, and `.integrity/manifest-sha256.json` present — a missing manifest on an installed
      root is itself a finding since v2.7.2 (ATOM-8WQI-G751).
