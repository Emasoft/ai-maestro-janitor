<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active** (`DATA` =
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`): no `DATA` ⇒ orphan — INERT,
> and the user may delete THIS FILE only, never a memory store; `DATA/global-state/kill-switch.flag`
> (or legacy `~/.claude/janitor-global-state/kill-switch.flag`) ⇒ deliberately stopped, INERT this
> session; else ACTIVE.

# TRDD: Task Requirement Design Documents (v2)

> **Layering note.** This is the UNIVERSAL BASE (IND) of the 3-pillars design system — it
> assumes nothing beyond a git repo and one Claude, who performs every duty named here with
> the USER as sole approver. In a registered ai-maestro agent workdir the server-installed
> overlay `aimaestro-trdd-approval.md` EXPANDS this base with multi-agent transition
> authority, approval tiers and title-based routing; it never restates this base.

**Rule:** every non-trivial feature spec, backlog item, or deferred-work design note is
saved as a **TRDD** — one `.md` file in a `design/tasks/` folder, with a grep-first YAML
frontmatter carrying the structured state and a body carrying the prose. A TRDD is
**PROJECT-**, **LOCAL-**, or **USER-scoped** — see step 1 for the roots and their git status.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/trdd-design-tasks-full.md`
> Holds the id/timestamp recipe, the full frontmatter schema, the column-transition matrix,
> the folder lifecycle, the grep cheat-sheet, the v1→v2 migration, and the rationale. Read it
> when you need a field or a transition you don't know. Everything below is normative on its
> own; the reference only expands it.

## The normative core

1. **Location — a TRDD is PROJECT-, LOCAL-, or USER-scoped, and its SCOPE IS ITS PATH.**

   | scope | root | git |
   |---|---|---|
   | `project` (default) | `<project-root>/design/` | tracked + pushed |
   | `local` | `~/.claude/projects/<slug>/design/` | outside the repo, never committed |
   | `user` | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/design/` | host-only, never pushed |

   All three share the SAME four lifecycle folders (`proposals/ tasks/ archived/ refused/`).
   `<slug>` = the project's absolute path, non-alphanumeric → `-`. PROJECT `design/` MUST NOT
   be gitignored; LOCAL/USER need no entry.

   **Scope routing.** Ask: *true and useful for a contributor on a DIFFERENT machine?* No →
   LOCAL (a `$HOME` path, hostname, username, credential, "on THIS machine", install state).
   One project → PROJECT. Fleet-wide or owned by none → USER. UNSURE → LOCAL. May SPLIT,
   cross-linked. `scope:` may appear (absent = `project`) but the **path is authoritative**.

2. **Filename.** `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`. `<id8>` is an **8-char
   UPPERCASE base36** id (`A-Z0-9`) — this IS the canonical id (no UUID), unique across
   **every scope root that exists** (the collision check scans all of them). Test for a taken
   id with `find … -iname … | grep -q .` — **never** `ls <glob>`, and **`-iname`, never
   `-name`** (both load-bearing; why: the reference).
3. **Reference a TRDD as `TRDD-<id8>`** (or `#<id8>` casually). Lookups are
   case-insensitive; the id is always WRITTEN uppercase. Put it in the commit subject of
   every commit that implements it, and in whatever the session uses to track work in flight.
   **A LOCAL TRDD may cite a PROJECT TRDD** (`parent-trdd`, `blocked-by`, `npt`, `eht`).
   **A PROJECT TRDD MUST NOT cite a LOCAL one** — a dangling reference for every other
   contributor. The one hard invariant the scope split introduces; greppable.
4. **Frontmatter is grep-first.** One field per line. Lists are flow-style `[a, b, c]`.
   Enums are bare kebab-case. Titles contain no colons. Dates are ISO 8601 with the local
   offset (`%Y-%m-%dT%H:%M:%S%z`). No trailing whitespace or comments on data lines.
5. **Minimal frontmatter** (a trivial TRDD needs only these; the schema is OPEN — add any
   field from the full reference when it applies):

   ```yaml
   ---
   trdd-id: M7BZ4X1Q
   title: <one line, no colons>
   column: backburner
   created: 2026-06-02T11:53:00+0200
   updated: 2026-06-02T11:53:00+0200
   current-owner: <session>
   task-type: feature        # feature|bugfix|refactor|docs|infra|security|artifact|spike|audit
   ---
   ```

6. **`column:` is the state machine.** v2 moved pipeline state here from v1's `status:` (not
   retired — specs carry `status: normative`): the residue is a **VALUE, never the field
   NAME** — never key on the name, `column:` wins, a missing field gets no synthesized value,
   one pipeline claim per card. The 17-column vocabulary lives in `universal-kanban.md`; the
   terminal branch follows `release-via: publish|deploy|none`; `blocked` applies whenever
   `blocked-by:` is non-empty (record `pre-block-column:`, restore when cleared).
7. **BUMP `updated:` on every edit that CHANGES WHAT THE TRDD ASSERTS** — not just column
   changes. The board sorts on it, so a MECHANICAL repair (a format/syntax pass that changes
   no fact) must NOT bump it, or the repair silently reorders the whole board.
8. **`implementation-commits:`** accumulates the SHAs that landed this TRDD's code — the
   backtracking field: how a bug found later is traced to the TRDD that introduced it.
9. **NPT vs EHT.** `npt:` = Necessary Prerequisite Tasks (must finish BEFORE `dev`). `eht:`
   = Effects Handling Tasks (post-conditions — parent **cannot reach `complete`** until every
   EHT is terminal). **Derived TRDDs are MANDATORY, depth-1**: empty `npt:`/`eht:`, never a
   `parent-trdd:`; siblings order via `blocked-by:`; `created-by:` set once; refusals archive
   `approved: false`. Full: the reference.
10. **STATE head block — MANDATORY once a TRDD spans more than one session.** Right after the
    title (append-only growth otherwise surfaces stale facts as current) add:
    `## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — <date>`.
    Single source of truth, kept current on every edit; carries each component's state, the
    **NEXT ACTION** (one step, runnable as written), load-bearing gotchas, an explicit
    **SUPERSEDED — do NOT carry forward** list, and artifacts to read first.
11. **Reports are evidence; decisions become TRDDs.** A report (audit, benchmark) presents DATA
    and lives in gitignored `reports/`. The moment it leads to a DECISION, that decision goes
    into a TRDD — a new one, or an existing TRDD's STATE block.
12. **Terminal columns are frozen — AFTER the transition that made them terminal.** No body
    edits on `complete`/`failed`/`superseded`/`published`/`live`; new work = new TRDD. Only
    `updated:` (and, when superseding, `superseded-by:`) may change. Narrow exceptions: the
    closing edit itself; `## Approval log` (append-only, EXEMPT); EVERY terminal column
    archives AS ITSELF — no rename on the way in (archive-eligible =
    `complete|completed|cancelled|superseded|published|live`; absent `release-via:` defaults
    to `none`; 3-pillars spec 2.0.0 amended 3P-ZON-05 on 2026-08-18 to admit `complete`
    because the complete→completed rename was a dual-write measured drifting 232 times
    fleet-wide — the rule moved, not the cards); and a body line FALSELY, MACHINE-VERIFIABLY
    contradicting the terminal `column:` MAY be removed. Worked example + why so narrow: the
    reference.
13. **One atomic task per TRDD.** If you catch yourself writing "and also do X", X is an
    NPT, an EHT, or its own TRDD.
14. **One kanban board, `scope` as a badge — not a second board.** Columns and transitions
    are identical; tools scan every scope root by default.
15. **A LOCAL TRDD needs no approval** — a chore on the user's own machine, no MANAGER for it.
    Sole exception: **destructive or irreversible** work (credential rotation, store deletion,
    history purge) needs **USER** approval, waiting in local `proposals/`.

## `review-after:` — the expiring, self-releasing park

`review-after: YYYY-MM-DD` parks a TRDD from `trdd-drift` until that date — opt-in only
(`backburner` stays drift-eligible by default). MUST be a snooze, not a mute, and MUST fail
OPEN on a malformed date. Full grammar + rationale: the reference.
Implementation: `scripts/detectors/trdd-drift.py::review_after_epoch`.

## Cross-project scope discriminators

Additive, lint-enforced incrementally: `project-id:` — PROJECT discriminator (`scope:
project` SHOULD carry it; `scope: user`/`local` MUST NOT). `host-id:` — the `scope: user`
discriminator. `repo:` — per-card annotation, not a discriminator. Full grammar: the
reference.

## Authoring, in short

Route the scope (1) → mint id + timestamps (2) → minimal frontmatter → `column: backburner`
(`live_auditing` for an audit TRDD) → the same ISO datetime in BOTH `created:` and `updated:`
→ the prose → note the id in the session's own in-flight task tracking, if it has any. A
**PROJECT** TRDD is then `git add`-ed **by
name** and committed (`docs: add TRDD-<id8> — <summary>`); report the id + commit. A **LOCAL**
one is in no repo — report the id + path.

Resuming later: `find` the id across every scope root with `-iname` (never `-name`, never an
`ls` glob — step 2) → read the **STATE block first**; on disagreement it wins over the
frontmatter (hand-edits beat stale fields) — then fix the frontmatter. Exact command + why
`-iname`: the reference.

## Does NOT apply to

Session handoffs (`docs_dev/`), scenario tests, proposal reports, inline `TODO:` comments, or
trivial same-session tasks (track those in-session; they need no TRDD). For **non-trivial design
tasks that must survive
as tracked project artifacts**.
