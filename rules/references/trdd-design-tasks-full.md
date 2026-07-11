<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — CONDITIONAL on the janitor being active.** Check the janitor's
> state first (cheap `$HOME` existence checks), then act:
> - **UNINSTALLED** — if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` is
>   ABSENT, the plugin was uninstalled and this file is an ORPHAN it could not remove (Claude
>   Code does not clean a plugin's `~/.claude/rules/` or a project's `.claude/rules/` on
>   uninstall). Treat this rule as INERT, and tell the user it is an orphaned janitor rule they
>   may delete. NEVER delete any MEMORY store — only this rule file, and only with the user's ok.
> - **DISARMED** — else if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/kill-switch.flag`
>   OR the legacy `~/.claude/janitor-global-state/kill-switch.flag` EXISTS (set by
>   `/janitor-global-disarm`), the janitor is intentionally stopped → treat this rule as INERT
>   this session.
> - **ACTIVE** — otherwise the janitor is running; apply the rule as written below.

# TRDD: Task Requirement Design Documents (v2)

> **Layering note.** This is the UNIVERSAL BASE (IND) of the 3-pillars
> design system — it assumes nothing beyond a git repo and one Claude.
> In a standalone project the project's own Claude performs every duty
> named here and the USER is the sole approver. When the project is a
> registered ai-maestro agent workdir, the server installs an overlay
> (`aimaestro-trdd-approval.md` and siblings, in the workdir's
> `.claude/rules/`) that EXPANDS this base with multi-agent transition
> authority, approval tiers, and title-based routing — the overlay never
> restates this base.

> **SCOPE (amended 2026-07-11).** A TRDD is **PROJECT-scoped** (`<project-root>/design/`,
> git-tracked and pushed) or **LOCAL-scoped** (`~/.claude/projects/<slug>/design/`, outside
> the repo and machine-private). Its **scope IS its path**. The local root mirrors the
> project root exactly — the same four lifecycle folders — so everything in this reference
> applies to both by swapping ONE path. The normative scope-routing rule, the both-roots
> collision check, and the hard "a PROJECT TRDD MUST NOT cite a LOCAL one" invariant live in
> the loaded rule (`trdd-design-tasks.md`, step 1); they are not restated here. Where this
> document says "git-tracked" below, read it as **PROJECT-scoped**.

**Rule:** Every non-trivial feature spec, backlog item, or deferred-work
design note MUST be saved as a **Task Requirement Design Document (TRDD)**
in a `design/tasks/` folder — `<project-root>/design/tasks/` for a PROJECT TRDD,
`~/.claude/projects/<slug>/design/tasks/` for a LOCAL one. A PROJECT TRDD is a
git-tracked artifact of the project; a LOCAL TRDD lives outside every repo and is
never committed. Every TRDD is a single `.md` file with a YAML frontmatter that
captures all the structured state (column, ownership, dependencies, test
requirements, deploy/publish target, commit hashes, …) and a body that
captures the prose. The frontmatter is **grep-first**; tools never need
to parse anything else to answer ordinary questions about a TRDD.

This is **v2** of the TRDD rule. It supersedes v1
(`status:`-based enum + minimal frontmatter). v1 TRDDs continue to work
through the migration path in [Migration from v1](#migration-from-v1);
new TRDDs use v2.

## What's new in v2

- **`column:` replaces `status:`**. The 14-stage kanban pipeline +
  `blocked` is the canonical state machine.
- **NPT and EHT relationships** — every TRDD can spawn Necessary
  Prerequisite Task children (`npt:`) and Effects Handling Task children
  (`eht:`), in addition to traditional `blocked-by:`.
- **8-char id reference syntax** — `TRDD-K3QX9P2W` or `#K3QX9P2W` is
  the canonical short form (UPPERCASE base36, no UUID).
- **Full delivery / verification / impact metadata** — `release-via:`,
  `test-requirements:`, `audit-requirements:`, `review-requirements:`,
  `runtime-targets:`, `impacts:`, etc.
- **Design-column 1→N split / N→1 group semantics** — the design pass
  can decompose a proto-TRDD into many full TRDDs (or merge several).
- **Per-rule PRRD citations** — `relevant-rules:` in frontmatter pins
  the PRRD rule numbers a TRDD must comply with.
- **Backtracking — `implementation-commits:`** — the SHAs that landed
  this TRDD's code, so a bug discovered later can be traced to the TRDD
  that introduced it.

## Location

**Canonical path:** `<project-root>/design/tasks/TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`

- `design/tasks/` lives at the project root and is committed to the repo.
- It MUST NOT be in the project's `.gitignore` — fix the gitignore if it is.
- TRDDs are NEVER saved in `docs_dev/` (gitignored) or `~/.claude/`
  (not project-scoped).

If `design/` or `design/tasks/` does not exist, create with `mkdir -p`.

## Filename format

```
design/tasks/TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md
```

Three components separated by `-`:

- `<YYYYMMDD_HHMMSS±HHMM>` — **creation timestamp**, compact form (no
  `:` in the offset → Windows-safe filesystem), local time + GMT delta.
  Generate via `date +%Y%m%d_%H%M%S%z`.
- `<id8>` — **8-char UPPERCASE base36 id** (`A-Z` + `0-9`, 36 symbols), e.g.
  `K3QX9P2W`. This IS the canonical id — there is **no separate UUID**. It is
  the **canonical short reference** in messages, commits, and citations
  (`TRDD-K3QX9P2W` or `#K3QX9P2W`). Lookups are **case-insensitive** (so
  `#k3qx9p2w` still resolves), but the id is always WRITTEN uppercase —
  filenames are case-insensitive on macOS/Windows, so an uppercase-only
  alphabet makes a same-file collision impossible. 36⁸ ≈ 2.8 trillion ⇒
  collision-free in practice (~2M TRDDs for a 50% chance); the create-time
  check below makes it exact.
- `<slug>` — kebab-case summary (2-4 words).

Generate the id (regenerate on the rare collision):

```bash
gen() { python3 -c "import random,string; print(''.join(random.choices(string.ascii_uppercase+string.digits,k=8)))"; }
ID8=$(gen); while ls design/tasks/TRDD-*-"$ID8"-*.md >/dev/null 2>&1; do ID8=$(gen); done
```

Example filename:

```
design/tasks/TRDD-20260602_115300+0200-K3QX9P2W-maintainer-title.md
```

## Frontmatter — the v2 spec

Every TRDD frontmatter is **grep-first**. The invariants:

1. **One field per line.** No multi-line strings, no folded scalars
   (`>`, `|`), no nested mappings.
2. **Lists are flow-style.** `[a, b, c]` — not block style.
3. **Enum values are bare kebab-case.** `not-started`, `in-progress`,
   `blocked`, `deploy`, `live`, etc. — never quoted, never capitalised.
4. **Titles never contain colons.** Use em-dash `—` or hyphen.
5. **Dates are ISO 8601 + local TZ offset.** Format
   `%Y-%m-%dT%H:%M:%S%z` (e.g. `2026-06-02T11:53:00+0200`). Generate via
   `date +%Y-%m-%dT%H:%M:%S%z`.
6. **No trailing whitespace, no trailing comments** on data lines.

### Full schema (organised by purpose)

```yaml
---
# ─────────── 1. IDENTITY (mandatory)
trdd-id: K3QX9P2W                        # canonical id — 8-char UPPERCASE base36 (no separate UUID)
title: <single line, ≤80 chars, no colons>
column: backburner                       # kanban state (see "Column enum" below)
created: 2026-06-02T11:53:00+0200        # ISO 8601 + local TZ
updated: 2026-06-02T11:53:00+0200        # bump on EVERY edit

# ─────────── 2. OWNERSHIP
current-owner: main-session              # session name with write-lock on body
assignee: main-session                   # who executes (standalone: always this project's Claude)
priority: 3                              # 0 = highest, 9 = lowest
severity: LOW                            # CRITICAL | HIGH | MEDIUM | LOW | NIT
effort: M                                # S | M | L | XL — rough size estimate
labels: [auth, refactor]                 # free-form tags

# ─────────── 3. CLASSIFICATION
task-type: bugfix                        # feature | bugfix | refactor | docs | infra | security | artifact | spike | audit
artifact-kinds: []                       # only when task-type=artifact; e.g. [icon, sound, html]

# ─────────── 4. RELATIONSHIPS (flow-style — grep `^npt:` returns one line per TRDD with full list)
parent-trdd: null                        # the TRDD that spawned this one
npt: [TRDD-K3QX9P2W, TRDD-M7BZ4X1Q]      # Necessary Prerequisite Tasks
eht: [TRDD-71a2239a]                     # Effects Handling Tasks
blocked-by: [TRDD-K3QX9P2W]              # runtime blockers (subset of npt while in-flight)
supersedes: []                           # TRDDs this one replaces
superseded-by: []                        # populated when column=superseded
pre-block-column: null                   # column to restore to when blockers clear
relevant-rules: [3, 27, 64.134]          # PRRD rule numbers; bare = latest version, n.v = pinned

# ─────────── 5. DELIVERY
release-via: publish                     # publish | deploy | none
delivery: pull-request                   # pull-request | direct-push
target-branch: main
feature-branch: null                     # null until created
merge-strategy: squash                   # squash | merge | rebase
must-pass-tests-before-merge: true
publish-target: null                     # marketplace / registry name — when release-via=publish
publish-channel: null                    # stable | beta | nightly — when release-via=publish
deploy-target: null                      # staging | production | dev-server | <custom> — when release-via=deploy
soak-duration: null                      # e.g. "24h" — time TRDD lives in live_auditing after deploy

# ─────────── 6. VERIFICATION REQUIREMENTS
test-requirements: [unit, integration]   # subset of: unit | integration | e2e | dev-browser-headless | performance | lint | typecheck
audit-requirements: []                   # subset of: security-scan | adversarial-scan | dependency-audit | license-check | accessibility
review-requirements: [human-review]      # subset of: human-review | human-evaluation | code-review | design-review
fixtures: [sample-pdf]                   # named fixtures the test suite needs
required-credentials: [github-pat]       # required user-supplied secrets
runtime-targets: [macos, linux]          # platforms/envs this must pass on; "docker" if container required
docker-image: null                       # only when "docker" is in runtime-targets

# ─────────── 7. IMPACT
impacts: [install-script, dependencies]  # subset of: install-script | dependencies | config-schema | migration | public-api | ci-pipeline
migration-direction: null                # forward | backward | both — when migration in impacts

# ─────────── 8. RUNTIME EVIDENCE (mutated as work proceeds)
attempts: 0                              # implementation attempts
test-failures: 0                         # cumulative failure count
last-test-result: not-run                # not-run | pass | fail | partial
last-test-at: null
implementation-commits: []               # SHAs where this TRDD's code landed — primary backtracking field
pr-url: null
ci-runs: []                              # CI run URLs/IDs
published-version: null                  # populated when column reaches published; e.g. "2.10.1"
published-at: null                       # ISO timestamp when published
live-since: null                         # ISO timestamp when deployed live

# ─────────── 9. AUDIT-FLOW (only when task-type=audit)
audit-trigger: null                      # alert | sentry | log | scheduled | manual | user-report
audit-target: null                       # which deployed component is under audit
audit-evidence: []                       # links/paths to logs, sentry events, screenshots
audit-conclusion: null                   # null while investigating | benign | issue-confirmed

# ─────────── 10. EXTERNAL (optional, free-form)
external-refs: []                        # e.g. ["github.com/.../issues/42", "jira:PROJ-123"]
---
```

### Minimal TRDD (most fields use defaults)

```yaml
---
trdd-id: M7BZ4X1Q
title: Add e2e test for password reset flow
column: backburner
created: 2026-06-02T11:53:00+0200
updated: 2026-06-02T11:53:00+0200
current-owner: main-session
task-type: feature
parent-trdd: TRDD-K3QX9P2W
test-requirements: [e2e, dev-browser-headless]
relevant-rules: [3]
---
```

A trivial TRDD uses 6-10 fields. A complex one uses 25+. Absent fields
take documented defaults. **Schema is open** — new fields can be added
without breaking old TRDDs.

## Column enum (the 14-stage kanban + blocked)

`column:` replaces v1's `status:`. Values (in lifecycle order):

| Group | Column | TRDD lives here when… |
|---|---|---|
| **ENTRY** | `backburner` | proto-TRDD parking lot |
| | `todo` | promoted from the backburner, awaiting design |
| | `live_auditing` (entry mode) | investigation task (audit-trigger set) |
| **DESIGN** | `design` | the design pass shapes proto → full TRDD; may 1→N split or N→1 group |
| | `dispatch` | full TRDD designed; awaiting `assignee:` assignment |
| **WORK** | `dev` | assignee implementing (new code OR fixes — same column) |
| | `testing` | tests + audits running; failures bounce back to `dev` |
| | `ai_review` | code review by AI agents |
| | `human_review` | human eyes required (`review-requirements:` includes `human-review`) |
| **READY** | `complete` | requirements met + tested; not yet shipped |
| **SHIP (tools)** | `publish` | actively publishing tool / package |
| | `published` | terminal: users can install the version with this TRDD's work |
| **SHIP (services)** | `deploy` | actively deploying service |
| | `live` | terminal: real traffic reaches this TRDD's code |
| **OPERATE** | `live_auditing` (soak mode) | post-deploy monitoring window |
| **EXCEPTIONS** | `blocked` 🔴 | RED — `blocked-by:` is non-empty |
| | `failed` | terminal: abandoned with post-mortem |
| | `superseded` | terminal: replaced by split/group children |

**Pipeline flows by `release-via:`:**

```
release-via: publish (tool TRDDs):
  backburner → todo → design → dispatch → dev → testing → ai_review
    → (human_review) → complete → publish → published

release-via: deploy (service TRDDs):
  backburner → todo → design → dispatch → dev → testing → ai_review
    → (human_review) → complete → deploy → live → (live_auditing soak) → live

release-via: none (internal TRDDs):
  backburner → todo → design → dispatch → dev → testing → ai_review
    → (human_review) → complete

audit TRDD (task-type: audit):
  live_auditing (entry) → done|complete (if benign)
  OR
  live_auditing → dev → testing → ai_review → ... → deploy → live (if issue-confirmed)
```

`blocked` is **orthogonal** — any working column can divert to `blocked`
when `blocked-by:` becomes non-empty, and the TRDD restores to its
`pre-block-column:` when blockers clear.

## Design-column 1→N split / N→1 group semantics

The `design` column is unique: the design pass can take ONE input and
produce MANY outputs (split), or take MANY inputs and produce ONE output
(group).

**Split (1 → N)** — a complex proto-TRDD becomes N parallel tasks:

- `T_parent.column` → `superseded`
- `T_parent.superseded-by` ← `[T_child1, T_child2, T_child3]`
- Each `T_childN`:
  - `parent-trdd: T_parent`
  - `supersedes: [T_parent]`
  - `column: dispatch` (or `design` if further design is needed)
  - All other frontmatter authored fresh

**Group (N → 1)** — several proto-TRDDs are merged into one larger task:

- Each input `T_in_n.column` → `superseded`
- Each `T_in_n.superseded-by` ← `[T_combined]`
- `T_combined`:
  - `supersedes: [T_in_1, T_in_2, T_in_3]`
  - `parent-trdd: null` (or first input's parent)
  - `column: dispatch`
  - Frontmatter merged thoughtfully (test-requirements, impacts, etc. → union)

## NPT vs EHT semantics

Both are children spawned BY a TRDD; they differ in WHY:

- **`npt:` — Necessary Prerequisite Tasks** — these must complete
  BEFORE the parent can proceed past `dev`. They're typically `blocked-by:`
  references while in-flight.
  Example: "Refactor auth module" depends on "Update auth schema first".
- **`eht:` — Effects Handling Tasks** — these handle the CONSEQUENCES
  of the parent's work. They are **post-conditions**, not preconditions —
  the parent can land its code, but it can't reach `complete` until its
  EHTs are also closed.
  Example: "Refactor auth module" needs EHTs "Update all callers of
  authenticate()", "Update auth-related docs", "Re-test downstream
  consumers".

A parent's transition to `complete` is gated on:

```
(column == ai_review or human_review)  ─ tests + reviews passed
  AND  all eht children are in terminal column (complete | published | live | superseded)
```

## The 8-char id reference syntax

Every TRDD's `trdd-id` IS its canonical short form — an 8-char UPPERCASE
base36 id (`A-Z` + `0-9`); there is no separate UUID:

| Form | Meaning |
|---|---|
| `TRDD-K3QX9P2W` | Full short reference — canonical in commits, PR comments, messages |
| `#K3QX9P2W` | Casual short form — appropriate in chat / Slack-like contexts |
| `K3QX9P2W` | Bare id — accepted by `findtrdd.py` as input (matched case-insensitively) |

Tools resolving the short form scan filenames for the
`TRDD-<TS>-<id8>-<slug>.md` pattern (case-insensitively); 36⁸ ≈ 2.8
trillion values ⇒ collision-free in practice. Collisions are prevented at
creation time (regenerate-on-hit), never repaired after the fact.

## STATE head section (mandatory once a TRDD spans >1 session)

Carried over from v1. A TRDD that grows across sessions becomes an
append-only chronological log. Reading it top-down hits the OLDEST
(often SUPERSEDED) facts first — and a compaction summary can carry
those stale facts forward as if current. To stay summary-proof, every
TRDD that spans more than one session MUST carry a **STATE head block**
immediately after the title, before the first body section:

```markdown
## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — <date>
```

It is the SINGLE SOURCE OF TRUTH, kept current on every edit, and
contains:

- **Current state** of each component (done / broken / pending).
- **NEXT ACTION** — the one concrete next step, runnable as written.
- **Load-bearing facts / gotchas** the work depends on.
- **SUPERSEDED — do NOT carry forward** — an explicit list of stale facts.
- **Durable artifacts to read before acting** — paths to reports/specs
  holding the evidence behind the plan.

The STATE block is body content, not frontmatter — its purpose is to
catch a model who reads the body before the frontmatter (which still
happens with current Read-tool behavior).

## Reports are evidence; decisions become TRDDs

Carried over from v1. A **report** (audit, research synthesis, option
benchmark) presents DATA. It lives under `reports/` — gitignored and
ephemeral. The moment a report leads to a DECISION, that decision MUST
be written into a TRDD — a NEW TRDD, or by EXTENDING an existing TRDD's
STATE block / plan steps.

## Todo list cross-reference

Every TaskCreate entry that references a TRDD MUST include its
`TRDD-<id8>` id in its subject or description:

```
"Implement the password-reset flow (TRDD-A58A02C4)"
```

From a todo list entry, you can grep `design/tasks/` for the prefix and
land directly on the spec file.

## Workflow

### Authoring a TRDD (from any column)

1. Generate the 8-char id (regenerate on the rare collision):

   ```bash
   # 8-char UPPERCASE base36 id. There is no UUID. Uppercase-only because macOS/
   # Windows filenames are case-insensitive — a lowercase letter could fold onto an
   # existing id and overwrite its file. The while-loop is the create-time collision
   # check: re-roll until no TRDD already owns this id (36⁸ ≈ 2.8e12, so ~never).
   gen() { python3 -c "import random,string; print(''.join(random.choices(string.ascii_uppercase+string.digits,k=8)))"; }
   TID=$(gen); while ls design/tasks/TRDD-*-"$TID"-*.md >/dev/null 2>&1; do TID=$(gen); done
   SHORT=$TID   # the 8-char id IS the canonical id; SHORT kept as an alias for the steps below
   ```

2. Capture timestamps:

   ```bash
   TS=$(date +%Y%m%d_%H%M%S%z)
   ISO=$(date +%Y-%m-%dT%H:%M:%S%z)
   ```

3. Ensure `design/tasks/` exists; verify `design/` is NOT in `.gitignore`.
4. Create the TRDD at `design/tasks/TRDD-$TS-$SHORT-<slug>.md` with the
   mandatory frontmatter; initialise `column: backburner` (or
   `live_auditing` for audit TRDDs), `trdd-id: $TID`, same ISO datetime
   in BOTH `created:` and `updated:`. Write the prose.
5. Create a TaskCreate entry referencing the TRDD.
6. Stage and commit:

   ```bash
   git add "design/tasks/TRDD-$TS-$SHORT-<slug>.md"
   git commit -m "docs: add TRDD-$SHORT — <short description>"
   ```

7. Tell the user the TRDD ID + commit hash.

### Transitioning a TRDD between columns

Quick reference — each transition and the side effects it carries. In a
standalone project the project's own Claude performs every transition
(the approval-gated ones with USER sign-off — see the folder lifecycle
below). WHO may trigger each transition in a multi-agent setup is
defined by the ai-maestro overlay (`aimaestro-trdd-approval.md`) when
installed.

| Transition | Side effects |
|---|---|
| `backburner → todo` | none |
| `todo → design` | design pass begins |
| `design → dispatch` | full frontmatter authored; may 1→N split |
| `dispatch → dev` | sets `assignee:` |
| `dev → testing` | signal "code ready for tests" |
| `testing → ai_review` | `last-test-result: pass`; `last-test-at:` set |
| `testing → dev` (failure) | `test-failures:` += 1; post-mortem added |
| `ai_review → human_review` | only when `review-requirements:` includes human-review |
| `ai_review\|human_review → complete` | all reviews passed |
| `complete → publish\|deploy` | release pipeline begins |
| `publish → published` | `published-version:`, `published-at:` set |
| `deploy → live` | `live-since:` set |
| `live → live_auditing` (soak) | optional; only when `soak-duration:` set |
| `<any working> → blocked` | `blocked-by:` becomes non-empty; `pre-block-column:` set |
| `blocked → <pre-block-column>` | `blocked-by:` empties; restore previous column |
| `<any> → failed` | after `attempts >= threshold` or USER decision |
| `<any> → superseded` | `superseded-by:` populated (during a design split) |

### Mutating a TRDD

- **Body** — only the TRDD's `current-owner:` mutates the body.
- **`column:`, `assignee:`** — coordination fields; whoever coordinates
  the board may mutate them regardless of `current-owner:` (standalone:
  the project's Claude; the overlay defines per-title authority).
- **`updated:`** — bump on EVERY mutation, not just status changes.
- **Frontmatter format** — every edit re-runs the greppability invariants
  check (one field per line, flow-style lists, bare kebab-case enums).

### Resuming work on a TRDD in a later session

1. Grep `design/tasks/` for the `TRDD-<id8>` id from the todo list:

   ```bash
   ls design/tasks/TRDD-*-K3QX9P2W-*
   ```

2. Read the TRDD top-to-bottom — STATE block FIRST.
3. Verify the STATE block agrees with the frontmatter `column:`. If they
   disagree, the STATE block wins (newer hand-edits beat structured fields).
4. Update the TRDD's frontmatter `column:` field as work progresses. On
   EVERY edit, bump `updated:` to current ISO datetime.
5. When complete (or terminal), keep the TRDD as historical reference.
   Do NOT delete — it's the audit trail mapping a backlog id back to
   the commits that shipped it.

## Folder lifecycle — proposals, tasks, archived, refused

A TRDD lives in exactly one of four folders, by lifecycle state:

| Folder | Lifecycle state (`column:`) | Meaning |
|---|---|---|
| `design/proposals/` | `proposal` | Authored, awaiting approval. **NOT** authorized to execute. |
| `design/tasks/` | `planned` (then every downstream `column:` — `todo`, `dispatch`, `dev`, `testing`, …) | Approved/authorized. In the execution pipeline. |
| `design/refused/` | `refused` | A **proposal that was NEVER approved** — declined at the proposal gate. Kept as an audit record; never deleted. |
| `design/archived/` | `completed` · `cancelled` · `superseded` | **Once-approved** TRDDs that reached a terminal-DONE state — finished, withdrawn, or replaced. Kept; never deleted. **`failed` is NOT here** — it stays in `design/tasks/` (retryable). |

`proposal`, `planned`, `refused`, `cancelled`, `completed`, and
`superseded` are **overlay values of the v2 `column:` field**. `proposal`
precedes `planned`; `planned` is the approved-entry column from which the
owner advances the TRDD through the normal v2 flow (`todo` → `dispatch`
→ `dev` → …).

**Lineage rule (which terminal folder?):** the dividing line is *was it
ever approved?* A proposal that is **declined** never entered the
pipeline → `design/refused/`. A TRDD that **was approved** (reached
`design/tasks/`) and later finishes, is cancelled, or is superseded →
`design/archived/`.

**`failed` is NOT terminal and is NOT archived.** A failed TRDD stays in
`design/tasks/` with `column: failed`; failure is a *retryable* state —
fix the cause (often via other TRDDs) and retry. Only an explicit
decision to give up converts `failed` → `cancelled` (→
`design/archived/`). There is no "archive as failed".

**An OPEN TRDD is exactly one that lives in `design/tasks/`** —
including `blocked` and `failed`. Keeping the zones accurate is why
every decision (approve / refuse / complete / cancel / supersede)
**`git mv`s** the file into the right zone.

### Who approves (standalone)

In a standalone project there are exactly two levels:

- **Routine, in-scope work** — a DERIVED task (an NPT/EHT of an
  already-approved task), or an independent task fully inside the
  current mandate, reversible and local → the project's Claude authors
  it **directly in `design/tasks/` with `column: planned`** and
  proceeds. No approval wait.
- **Everything else** — new scope, destructive or hard-to-reverse
  changes, releases, budget/credential-touching work, or anything the
  USER should see first → author in `design/proposals/` with
  `column: proposal` and wait for the **USER** to approve or refuse.
  When unsure, propose — conservative beats sorry.

(The ai-maestro overlay generalizes these two levels into a 4-tier
authority ladder with COS/MANAGER routing; it never loosens them.)

### Creation procedure (authoring a proposal)

A proposal is a normal v2 TRDD that starts at `column: proposal` in
`design/proposals/`: generate identity + timestamps exactly as in
"Authoring a TRDD" above, write a fully **self-contained** body (the
WHY, the exact changes, acceptance criteria, verification steps), end
with an empty `## Approval log` section, and commit it.

### Promotion protocol (approve: `proposal` → `planned`)

1. Edit frontmatter: `column: proposal` → `column: planned`; bump `updated:`.
2. Append to `## Approval log`:
   `- <ISO> — APPROVED by <approver>. <one-line rationale>.`
3. `git mv design/proposals/TRDD-….md design/tasks/TRDD-….md`.
4. Commit (`docs: approve TRDD-<short> → planned`).

### Refusal protocol

Never delete a refused proposal — it is the audit trail.

1. Edit frontmatter: `column: proposal` → `column: refused`; bump `updated:`.
2. Append to `## Approval log`:
   `- <ISO> — REFUSED by <approver>. <one-line reason>.`
3. `git mv` the file into `design/refused/` (create the folder if absent).
4. Commit (`docs: refuse TRDD-<short> → refused`).

A refused proposal is terminal — re-attempting the idea means a **new**
proposal (which may cite the refused one).

### Archival protocol (complete / cancel / supersede)

| State | `column:` | When |
|---|---|---|
| **completed** | `completed` | the work is finished / shipped (its release-via terminal reached) |
| **cancelled** | `cancelled` | the work is **withdrawn** — no longer wanted |
| **superseded** | `superseded` | replaced by other TRDD(s) (record them in `superseded-by:`) |

1. Edit frontmatter: `column:` → the terminal state; bump `updated:`
   (set `superseded-by:` when superseding).
2. Append to `## Approval log`:
   `- <ISO> — <COMPLETED|CANCELLED|SUPERSEDED> by <approver>. <one-line reason>.`
3. `git mv` the file into `design/archived/` (create the folder if absent).
4. Commit (`docs: archive TRDD-<short> → <state>`).

### Batch approval syntax (the fast review path)

Reviewing proposals one-by-one does not scale. The canonical fast path:

1. **List** — print every pending proposal in `design/proposals/` as a
   numbered one-line table (number, id, title) sorted by `created:`,
   keeping a manifest mapping each number → stable `trdd-id`.
2. **Decide** — the approver replies with:
   - `approved: 4,6,22` — approve **exactly** those numbers; every
     unlisted proposal stays PENDING (`approved:` never refuses by
     omission).
   - `refused: 48,7` — refuse **exactly** those numbers **and APPROVE
     every other proposal in the listing** (the bulk path for when
     approvals outnumber refusals).
   - Both lines together — both are **explicit** lists; everything else
     stays PENDING.
3. Numbers resolve against the most recent listing's manifest (by
   stable `trdd-id`, not array position).

## Migration from v1

v1 TRDDs use `status:` (6 values) and a sparser frontmatter. They keep
working through automatic mapping:

| v1 `status:` | v2 `column:` (mapping) |
|---|---|
| `not-started` | `backburner` (default) — or `todo`/`dispatch` if context indicates |
| `in-progress` | `dev` (default) — or `design`/`testing`/etc. if context indicates |
| `completed` | `complete` (NOT `published`/`live` — those are runtime states beyond v1) |
| `failed` | `failed` |
| `blocked` | `blocked` |
| `superseded` | `superseded` |

Tools (`findtrdd.py`, kanban renderer) accept both. A TRDD with
`status:` but no `column:` is treated as v1 and the mapping is applied
read-only.

**On next edit** of a v1 TRDD, the agent should:

1. Replace `status:` with `column:` using the table above.
2. Add absent v2 fields where their values are known:
   - `current-owner:`, `assignee:`, `priority:` from context
   - `task-type:` based on what the TRDD does
   - `release-via:` (default `none` — promote to `publish`/`deploy` if it ships)
   - `test-requirements:`, `audit-requirements:`, etc. (default `[]`)
3. Commit as a normal TRDD edit with `chore(trdd): migrate <short> to
   v2 frontmatter` message.

Do NOT auto-migrate v1 TRDDs en masse — incremental migration on next
touch is the right cadence.

## Grep cheat-sheet (extended)

```bash
# Every TRDD's column in one go (UID-prefixed)
grep -H "^column:" design/tasks/*.md

# All currently in-blocked TRDDs (the RED column)
grep -l "^column: blocked$" design/tasks/*.md

# All TRDDs in WORK group (dev/testing/ai_review/human_review)
grep -lE "^column: (dev|testing|ai_review|human_review)$" design/tasks/*.md

# All TRDDs with a specific assignee
grep -l "^assignee: some-agent$" design/tasks/*.md

# All TRDDs that cite PRRD rule 64
grep -lE "^relevant-rules:.*\\b64\\b" design/tasks/*.md

# All TRDDs that cite PRRD rule 64 in body (any version)
grep -rlE "PRRD [GS]64(\\.|\\b)" design/tasks/

# All TRDDs blocked by a specific TRDD prefix
grep -l "^blocked-by:.*TRDD-K3QX9P2W" design/tasks/*.md

# All TRDDs that landed commit abc1234
grep -l "^implementation-commits:.*abc1234" design/tasks/*.md

# All audit TRDDs whose conclusion is "issue-confirmed"
grep -l "^audit-conclusion: issue-confirmed$" design/tasks/*.md

# All TRDDs whose tests have failed ≥3 times
awk '/^test-failures: [3-9]|^test-failures: [0-9][0-9]/' design/tasks/*.md

# Last 5 TRDDs touched, chronologically (most-recent last)
grep -H "^updated:" design/tasks/*.md | sort -t: -k2 | tail -5

# Every TRDD's title in one shot
grep -H "^title:" design/tasks/*.md

# Find a TRDD by its id (filename glob — case-insensitive on macOS/Windows)
ls design/tasks/TRDD-*-K3QX9P2W-*.md

# Find a TRDD by its id in the frontmatter (-i: lookups are case-insensitive)
grep -li "^trdd-id: K3QX9P2W$" design/tasks/*.md

# Find a TRDD by content keyword
grep -rl "<keyword>" design/tasks/

# All tool TRDDs not yet published
grep -lE "^release-via: publish$" design/tasks/*.md | xargs grep -L "^column: published$"

# All service TRDDs not yet live
grep -lE "^release-via: deploy$" design/tasks/*.md | xargs grep -L "^column: live$"
```

For richer queries (e.g. "which TRDDs are blocked by a TRDD that is
itself blocked?") prefer `findtrdd.py --where ...` over chained `grep`.

## Why this exists

- **Searchability.** The id in the filename + todo list lets you jump
  from backlog entry to full spec in one grep.
- **Persistence.** `design/tasks/` is git-tracked; survives branch
  switches, clean clones, and `rm -rf docs_dev/`.
- **Reviewability.** PRs that touch a TRDD get reviewed alongside the
  code, catching stale specs before they cause drift.
- **Discoverability.** New contributors (or future you) can see the
  full feature backlog without access to private session notes.
- **Uniqueness.** Date-based filenames collide when multiple specs are
  created the same day; the 8-char id never collides (create-time check).
- **Backtracking** — `implementation-commits:` lets a bug from any time
  trace back to the TRDD that introduced the code.
- **Compliance is greppable.** "Which TRDDs comply with rule 64?" →
  `grep -lE '^relevant-rules:.*\\b64\\b'`. One command, no API.

## Anti-patterns

- **Putting multiple decisions in one TRDD.** Each TRDD is one atomic
  task. If you're tempted to "and also do X" in a TRDD, that's an NPT
  or EHT child, or a separate TRDD entirely.
- **Editing a `completed` / `failed` / `superseded` / `published` /
  `live` TRDD's body.** Those are terminal columns. New work = new TRDD.
  Only `updated:` and (for `superseded`) the `superseded-by:` field may
  be touched.
- **Skipping the STATE block on multi-session TRDDs.** The grep-cheat
  finds your TRDD but the model reading it without the STATE block can
  surface stale facts as if current.
- **Citing rules without their numbers.** "Should follow the
  installation conventions" is unverifiable; "should follow `PRRD G3.1`"
  is checkable.
- **Mutating `column:` without bumping `updated:`.** The kanban view
  relies on `updated:` for "last touched" sorting; stale `updated:` makes
  the board misleading.
- **Marking a TRDD `complete` while its EHTs are open.** EHTs are
  post-conditions; the parent's transition to `complete` must wait.

## Does NOT apply to

- **Session handoff files** — `docs_dev/YYYY-MM-DD-handoff-*.md` is
  still fine for session state not committed.
- **Scenario test files** — use `tests/scenarios/SCEN-NNN_*.scen.md`
  with sequential numbers, tracked in the scenarios folder.
- **Proposal reports** — `tests/scenarios/reports/*_<timestamp>.md`.
- **Trivial TODOs** that will be done in the current session — just use
  TaskCreate, no TRDD needed.
- **Inline code comments / TODOs** — those are fine where they are.

TRDDs are specifically for **non-trivial design tasks** that will be
picked up later and need to survive as tracked artifacts of the project.
