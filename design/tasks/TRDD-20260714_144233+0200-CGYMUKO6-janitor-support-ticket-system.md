---
trdd-id: CGYMUKO6
title: Janitor support-ticket system — incident management with heartbeat-scheduled repair agents
column: dev
created: 2026-07-14T14:42:33+0200
updated: 2026-07-14T14:42:33+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: high
labels: [incident-management, tickets, heartbeat, agents, governance]
relevant-rules: [1]
---

# Janitor support-ticket system

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-14

**The gap.** The janitor DETECTS incidents well and REPAIRS almost none. A finding becomes a drift
line — a nag the main Claude may or may not act on — and if it doesn't, the finding recurs forever.
`security_helpers.security_agent_hint()` is the current state of the art: a *suggestion* to run an
agent, with no scheduling, no memory, no retry, no budget, and no record of whether anyone ever did
it. **Incident management is a janitor responsibility, and the janitor has no queue.**

**Motivating incident (2026-07-14):** memgrep's schema migration manufactured a corrupt FTS index. It
sat undetected until an agent tripped over it. `open()` now self-heals, but if a FRESHLY BUILT index
still fails validation, that is a CODE bug — and the janitor can only shout about it.

**The substrate already exists.** `detectors/memory-maintenance.py` is a working scheduler: it picks a
due chore, records it, and emits a BARE MARKER; the model (the only thing that CAN spawn agents) reads
the marker and launches ONE background agent. This TRDD **generalizes that substrate into a general
incident queue** — it does not invent a second one.

---

## THE OWNERSHIP BOUNDARY (the load-bearing decision — USER, 2026-07-14)

**Who owns the broken thing decides whether the janitor may act alone.**

| domain | what it covers | ticket opened by | dispatch | TRDD |
|---|---|---|---|---|
| **HARNESS** | the janitor's OWN machinery: the memgrep index + its migrations, the daemon, its own state files, its own self-integrity | **the janitor, automatically** | **automatic** — next free heartbeat slot | none (operational self-repair) |
| **PROJECT** | the USER's code, GitHub repo, workflows, branch rulesets, dependencies | **nobody, until approved** | only after approval | **a proposal TRDD, authored up-front** |

**HARNESS** — the janitor is fixing *itself*. Nobody else owns that machinery, a broken index or a
crash-looping daemon is unambiguously a defect, and the blast radius is regeneratable state. It opens
its own ticket and dispatches without asking. This is the memgrep case, and it is the whole point.

**PROJECT** — the janitor is a GUEST in the user's repo. It may **propose**, never execute:
1. the detector authors a **proposal TRDD** under `design/proposals/` (`column: proposal`) describing
   the finding and the proposed fix;
2. the drift line carries the **exact command, already bearing that TRDD's id**:
   `/janitor-ticket-open --trdd <ID8>`;
3. the main Claude **proactively recommends** it (and keeps reminding — a finding must not be
   forgotten);
4. **running the command IS the approval**: it creates the ticket AND promotes the TRDD
   `proposal → planned` (git mv into `design/tasks/`), after which the scheduler may dispatch it.

This is not a new governance concept — it is exactly the ratified approval-tier rule.
`manager-approval-defaults.md` category **B makes TRDD intake/authoring EXEMPT** (the janitor may
write a proposal unasked) while `design/proposals/` is by definition **NOT authorized to execute**.
The ticket system simply gives that gate a *button*. The kind→domain mapping lives in **our code**
(`KIND_REGISTRY`), never in the ticket's text, so a ticket cannot talk its way from PROJECT to HARNESS.

**Budget (USER):** **2 dispatches per heartbeat, 20 per rolling 24h**, severity-ordered, oldest-first.

---

## THE CONSTRAINT THAT SHAPES THE IMPLEMENTATION

A HARNESS ticket dispatches an agent **with no human in the loop**. Therefore:

1. **Ticket text is UNTRUSTED DATA, never instructions.** Ticket fields carry text derived from
   attacker-influenceable sources — filenames, dependency names, workflow lines, GitHub issue titles.
   Pasting that into an agent prompt is a prompt-injection vector **that the janitor itself would be
   delivering**. So: the agent's **instructions are CONSTANT and come from our code** (the `kind →
   skill` registry); the ticket supplies only **data** (ids, paths, counts), sanitized on ingest via
   `state.sanitize_for_drift_line`, fenced in the prompt, and explicitly labelled untrusted. The
   dispatch marker stays **bare and constant**; the ticket id is `T-<8 base36>`, regex-validated
   before it can reach a prompt.
2. **Safety lives in the EXECUTOR.** The dispatched agent inherits a hard, non-overridable preamble
   from the `janitor-ticket-work` skill (never from the ticket): never delete uncommitted work
   (RULE 0); never rotate credentials, force-push, or push to `main`; **never edit another project's
   source** (file an issue / open a PR — the cross-project rule); fix what is safe and **FLAG** what
   needs a human; if the fix needs a *design decision*, open a TRDD instead of guessing.
3. **A forged marker must trigger NOTHING.** Inherited from the memory scheduler's contract: the
   agent re-reads the ticket from the store and refuses unless it is genuinely `dispatched` with a
   fresh stamp. A hallucinated `[janitor-ticket]` achieves nothing.

**Not a second kanban.** Tickets are the janitor's OPERATIONAL queue (incidents + their automated
repair) — gitignored, ephemeral. TRDDs remain the DESIGN board. A ticket that turns out to need a
design decision opens a TRDD ("reports are evidence, decisions become TRDDs").

---

## Architecture

```
DETECT (any detector)
   ├─ HARNESS kind → tickets.open()            → status: open        (dispatchable)
   └─ PROJECT kind → tickets.propose()         → proposal TRDD + a drift line carrying
                                                  `/janitor-ticket-open --trdd <ID8>`
                                                 (no ticket exists until that command runs)
                             ↓
SCHEDULE  detectors/ticket-dispatch.py
   gates: full mode · not paused/stopped/rate-limited · budget left · in-flight slot free
   picks ≤2 by (severity, oldest-first) under a MACHINE-WIDE flock, marks them `dispatched`
                             ↓
   [janitor-ticket]                      ← BARE marker: the only thing that authorizes a spawn
   T-7QK2M4XZ · janitor-repair-agent
                             ↓
EXECUTE   the cron turn spawns ONE background agent per line, with a CONSTANT prompt:
   "Work janitor ticket T-…. Load the janitor-ticket-work skill and follow it exactly."
                             ↓
VERIFY    the agent reads the ticket as DATA, works it, closes it with a status + report path
```

**State machine:** `open → dispatched → in_progress → resolved | failed`. `failed` with attempts left
→ back to `open` with a 30-min backoff. Attempts exhausted → `needs_human`, surfaced every fire with
the exact command — **never silently dropped**. A `dispatched`/`in_progress` ticket gone stale (>1h —
its agent died) returns to `open`, attempts++, so a killed agent (the weekly-cap case that killed the
memory agent this very session) cannot strand a ticket.

## THE ISSUE-CODE CATALOG (USER, 2026-07-14) — how a finding BECOMES a ticket

**Every issue every janitor scanner can detect gets a stable numeric id and a description**, and each
code carries a **template** that converts it into a ticket (HARNESS) or a proposal TRDD (PROJECT).
Without this, each detector hand-rolls its own prose and the propose step is ad-hoc; with it, raising
an incident is one call and the wording, severity, domain, and agent are all decided by the code.

`scripts/lib/issue_catalog.py` — ONE registry, the single source of truth:

```python
ISSUE_CATALOG = {
  "MEMGREP-001": Issue(scanner="memgrep-validate", kind="index-corruption", severity="high",
                       title="the FTS index does not match its content table",
                       what="…", why_it_matters="…", fix="rebuild from the content tables"),
  "MEMGREP-004": Issue(..., kind="migration-failure", severity="critical",
                       title="a migration left `{table}` without column `{column}`", …),
  "WFSEC-001":   Issue(scanner="workflow-security", kind="security-workflow", severity="high",
                       title="attacker-controlled expression interpolated into `run:`", …),
  "BRPROT-001":  Issue(scanner="branch-protection", kind="branch-protection", …),
  "DEP-001":     Issue(scanner="supply-chain",      kind="dependency-advisory", …),
  "CRED-001":    Issue(scanner="remote-credentials",kind="leaked-credential", severity="critical", …),
  …
}
raise_issue("WFSEC-001", where="ci.yml:42", evidence=[".github/workflows/ci.yml"])
```

`raise_issue(code, **data)` is the ONLY entry point a detector needs. It looks the code up, resolves
the `kind` → (domain, agent) via `KIND_REGISTRY`, renders the template with the **sanitized** data,
and then routes by domain — `tickets.open_ticket()` for HARNESS, `ticket_proposal.propose()` for
PROJECT. **The code decides the domain**, so a detector cannot accidentally grant itself unattended
dispatch, and the injection boundary is preserved (the template is ours; only the `{data}` is theirs).

**Code format:** `<SCANNER>-<NNN>` — stable, greppable, never renumbered (a shipped code is immutable,
like a schema version). The `description` is what the user reads in the TRDD; the `fix` is what the
agent is told to attempt.

**Validators emit codes too.** memgrep's `validate_db` gains a code per failure class
(`MEMGREP-001` FTS desync · `-002` file integrity · `-003` stale FTS column set · `-004` missing
column · `-005` orphaned rows · `-006` version stamp), printed machine-readably so the
`memgrep-index-health` detector maps stderr → code → ticket with no prose parsing.

**Coverage is the acceptance criterion:** every finding every scanner can emit must have a code. The
sweep covers the security detectors, the repo/ruleset scanners, the dependency scanners, the workflow
auditor (zizmor + Sentinel rule ids map 1:1 onto codes), the memory/wikimem validators, and the
janitor's own self-integrity checks.

**The published catalog — `docs/ISSUE-CODES.md` (USER, 2026-07-14).** The janitor's documentation
carries the full list of every detectable issue code, from every scanner and validator: code, scanner,
severity, domain (HARNESS/PROJECT), what it means, and how it is fixed.

It is **GENERATED from `issue_catalog.py`, never hand-written** (`scripts/issue_catalog_doc.py
--write`), and a test asserts the doc matches the catalog — a hand-maintained list drifts the moment
someone adds a code, and a *stale* catalog of issue codes is worse than none (it is a document that
lies about what the janitor can see). Same discipline as the fenced CLAUDE.md project map: one source
of truth, a derived artifact, and a check that fails when they diverge.

## Files

**Phase 1 — core:** `scripts/lib/tickets.py` (model + store + PURE selection/backoff + `KIND_REGISTRY`
carrying kind→domain→agent→skill) · `scripts/ticket_cli.py` (the single mutation surface) ·
`scripts/detectors/ticket-dispatch.py` (the scheduler, modelled on `memory-maintenance.py`) ·
`agents/janitor-repair-agent.md` · `skills/janitor-ticket-work` (the agent procedure + the safety
preamble) · `skills/janitor-tickets` (console) · `skills/janitor-ticket-open` (the approval button) ·
`rules/janitor-heartbeat-protocol.md` (+`[janitor-ticket]`) · `.claude-plugin/plugin.json` (knobs) ·
`scripts/dispatch.py` (roster).

**Phase 2 — the motivating producer:** `scripts/detectors/memgrep-index-health.py` (HARNESS: validates
each scope's index; N consecutive failures → auto-ticket) + `security_helpers.ticket_hint()` (PROJECT:
propose + recommend).

**Phase 3:** the remaining producers (`workflow-security`, `branch-protection`, `fleet-github-config`,
daemon crash-loop, `janitor-self-integrity`).

## ⏵ PROGRESS (2026-07-14) — where to resume

**DONE and committed:**
- **Phase 1a — the core** (`9b66a98`): `scripts/lib/tickets.py` (queue + `KIND_REGISTRY` + the PURE
  select/backoff/budget logic) and `scripts/lib/ticket_proposal.py` (propose → approve → promote).
  **18 tests**, and BOTH security boundaries falsified.
- **Phase 1b — scheduler + CLI** (`cf18e8d`): `scripts/detectors/ticket-dispatch.py`,
  `scripts/ticket_cli.py`, and `global_state.ticket_dispatch_lock` (its OWN flock — reusing the
  marketplace lock would serialize ticket dispatch against plugin updates and starve it).

**VERIFIED END-TO-END on a scratch project, both domains:**
- HARNESS: opens itself → the scheduler emits the bare marker → a second fire does NOT re-dispatch →
  budget decremented.
- PROJECT: a direct open is **REFUSED** → `propose()` writes a proposal TRDD whose HOSTILE title
  (`[janitor-self-disarm] …`) comes out **DEFANGED** as `⟦janitor-self-disarm⟧` → **no ticket exists**
  until `/janitor-support-open-ticket TRDD-<id>` → ticket queued + TRDD promoted `proposal → planned`.

**NEXT ACTION (in order):**
1. **`scripts/lib/issue_catalog.py`** — the issue-code catalog above (the user's latest requirement).
   This is now the keystone: every producer routes through `raise_issue(code, **data)`.
2. **Codes in memgrep's `validate_db`** (`MEMGREP-001…006`) + the `memgrep-index-health` detector — the
   motivating producer (a failed migration → a ticket → the repair agent).
3. **The EXECUTE half**: `agents/janitor-repair-agent.md`, `skills/janitor-support-work-ticket`
   (carrying the hard safety preamble), `skills/janitor-support-tickets` (console),
   `skills/janitor-support-open-ticket` (the approval button).
4. **Wire it in**: the `[janitor-ticket]` marker in `rules/janitor-heartbeat-protocol.md`, the
   `ticket-dispatch` detector in `dispatch.py`'s roster, the 6 knobs in `.claude-plugin/plugin.json`.
5. Map every existing scanner's findings onto codes (the coverage criterion).

**Nothing is live yet** — the scheduler is not in the detector roster and the marker is not in the
protocol rule, so no ticket can be dispatched until step 4. That is deliberate: the EXECUTE half must
exist before the SCHEDULE half is armed.

Reuses: `state.atomic_write` / `sanitize_for_drift_line` / `state_dir`, the `global_state` flock,
`dedupe.emit_once`, `trdd_common.scope_folder`/`ensure_local_design` (for the proposal TRDD).

## Verification

1. **Pure core** — dedupe (same key ⇒ ONE ticket, not 50), severity ordering, backoff, attempt
   exhaustion → `needs_human`, stale-reclaim, rolling-24h budget.
2. **The ownership boundary** — a PROJECT kind must NEVER produce a dispatchable ticket without an
   approved TRDD; a HARNESS kind must dispatch with no approval. **Falsify both directions.**
3. **Injection** — a ticket whose title contains `[janitor-ticket]`, `[janitor-self-disarm]`, and
   "Ignore previous instructions" must be defanged on ingest and must never reach the agent prompt as
   anything but fenced data. *This is the test that earns unattended dispatch.*
4. **Forged marker** — an agent asked to work a ticket that is not `dispatched` refuses.
5. **Gate falsification** — remove the budget cap / the per-fire cap / the in-flight check and the
   corresponding test must fail.
6. **End-to-end** — corrupt a scratch memgrep index → health detector opens a ticket → next heartbeat
   emits `[janitor-ticket]` → repair agent runs → ticket closes `resolved` with a report path.
7. Full `pytest` + `ruff check` + `cargo test` green before any publish.

## Notes and lessons learned

[^1]: [ocd:2026-07-14 lmd:2026-07-14] The janitor could already SEE every one of these incidents; what
  it lacked was a way to *schedule* the repair. A detector that can only print is a monitoring system,
  not a maintenance system — and a nag that recurs forever trains its reader to ignore it, which makes
  the detector worse than useless (it consumes attention and buys none). Lesson: a finding without an
  owner, a schedule, and a terminal state is not a finding, it is noise. The queue — dedupe, backoff,
  attempt limits, an explicit `needs_human` terminal — is what turns detection into maintenance.

[^2]: [ocd:2026-07-14 lmd:2026-07-14] The ownership boundary (HARNESS auto / PROJECT propose-only) was
  the USER's correction to an earlier "everything auto-dispatches" design, and it is *better* than what
  it replaced — not a restriction on it. Autonomy is legitimate exactly where the janitor owns the
  broken thing and the blast radius is its own regeneratable state; it is illegitimate the moment the
  janitor reaches into someone else's repo, no matter how confident the fix. The elegant part is that
  the project half needed no new governance: `design/proposals/` ALREADY means "authored, not
  authorized", and TRDD authoring is ALREADY approval-exempt. The ticket system just gave that
  existing gate a button. Lesson: when a new subsystem needs an approval model, look for the one the
  project already ratified before inventing one — a second gate is a second thing to drift.
