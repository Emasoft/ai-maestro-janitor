<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active.** Check (cheap `$HOME` stats),
> where `DATA` = `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`:
> **UNINSTALLED** (`DATA` absent) → this file is an orphan the plugin could not remove: treat as
> INERT and tell the user they may delete it — but NEVER any MEMORY store, only this rule file, and
> only with their ok. **DISARMED** (`DATA/global-state/kill-switch.flag` or legacy
> `~/.claude/janitor-global-state/kill-switch.flag` exists) → the janitor is intentionally stopped:
> INERT this session. **ACTIVE** (otherwise) → apply the rule below.

# TRDD: Task Requirement Design Documents (v2)

> **Layering note.** This is the UNIVERSAL BASE (IND) of the 3-pillars design system — it
> assumes nothing beyond a git repo and one Claude, who performs every duty named here with
> the USER as sole approver. In a registered ai-maestro agent workdir the server-installed
> overlay `aimaestro-trdd-approval.md` EXPANDS this base with multi-agent transition
> authority, approval tiers and title-based routing; it never restates this base.

**Rule:** every non-trivial feature spec, backlog item, or deferred-work design note is
saved as a **TRDD** — one `.md` file in a `design/tasks/` folder, with a grep-first YAML
frontmatter carrying the structured state and a body carrying the prose. A TRDD is
**PROJECT-scoped** (in the repo, git-tracked, shared), **LOCAL-scoped** (outside the repo,
machine-private), or **USER-scoped** (host-wide, cross-project, machine-private) — see step 1.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/trdd-design-tasks-full.md`
> Holds the id/timestamp recipe, the full frontmatter schema, the column-transition matrix,
> the folder lifecycle, the grep cheat-sheet, the v1→v2 migration, and the rationale. Read it
> when you need a field or a transition you don't know. Everything below is normative on its
> own; the reference only expands it.

## The normative core

1. **Location — a TRDD is PROJECT-, LOCAL-, or USER-scoped, and its SCOPE IS ITS PATH.** All
   three roots hold the SAME four lifecycle folders (`proposals/ tasks/ archived/ refused/`),
   so every rule and tool here works by swapping ONE path:

   | scope | root | git |
   |---|---|---|
   | `project` (default) | `<project-root>/design/` | **tracked + pushed** — every contributor sees it |
   | `local` | `~/.claude/projects/<slug>/design/` | **outside the repo — cannot be committed** |
   | `user` | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/design/` | **host-only — never per-project, never pushed** |

   `<slug>` = the project's absolute path with every non-alphanumeric char replaced by `-` —
   the SAME slug LOCAL *memory* uses, so both local corpora sit under one local-scope root.
   The `user` root sits ALONGSIDE the janitor's USER *memory* root (same fixed plugin-DATA
   dir, a sibling `design/` next to `memory/`) — ONE store per host, mirroring the memory
   system's own LOCAL/PROJECT/USER taxonomy 1:1 (janitor#103). PROJECT `design/` MUST NOT be
   in `.gitignore`. LOCAL and USER need no gitignore entry — nothing is written inside a repo.

   **Scope routing — decide BEFORE authoring.** Ask: *"would this task be TRUE and USEFUL for
   a contributor who clones this repo on a DIFFERENT machine?"* **No → LOCAL** (an absolute
   `$HOME` path, a hostname, a username, a credential, "on THIS machine", an install state
   each force it). **Yes, and scoped to ONE project → PROJECT.** **True across every project
   on this host, or belonging to no single project → USER** (a cross-project mandate, a
   fleet-wide issue, a proposal nobody's project owns). **UNSURE → LOCAL** — a leaked
   machine-private TRDD is already pushed, whereas promoting local→project later is
   deliberate. A task may SPLIT, cross-linked. A `scope:` field may appear (absent =
   `project`) but the **path is authoritative** — it decides git-tracking — so the path wins
   and the field is a lint target.

2. **Filename.** `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`. `<id8>` is an **8-char
   UPPERCASE base36** id (`A-Z0-9`) — this IS the canonical id (no UUID), unique across
   **every scope root that exists** (the collision check scans all of them). Test for a taken id with
   `find … -iname … | grep -q .` — **never** `ls <glob>`, and **`-iname`, never `-name`**
   (both spellings are load-bearing; the failure each prevents is in the reference, with the
   id/timestamp recipe).
3. **Reference a TRDD as `TRDD-<id8>`** (or `#<id8>` casually). Lookups are
   case-insensitive; the id is always WRITTEN uppercase. Put it in the commit subject of
   every commit that implements it, and in any TaskCreate entry that tracks it.
   **A LOCAL TRDD may cite a PROJECT TRDD** (`parent-trdd`, `blocked-by`, `npt`, `eht`).
   **A PROJECT TRDD MUST NOT cite a LOCAL one** — it would be a dangling reference for every
   other contributor, who can never resolve a file that does not exist in their clone. This
   is the one hard invariant the scope split introduces, and it is greppable.
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

6. **`column:` is the state machine.** v2 moved the pipeline state here from v1's `status:`,
   but `status:` is **not retired** (specs carry `status: normative`) — so the residue is a
   **VALUE, never the field NAME**: never key on the name, `column:` wins, a missing field
   gets no synthesized value, one pipeline claim per card. The 17-column vocabulary and its
   order live in `universal-kanban.md`, not restated here; the terminal branch follows
   `release-via: publish|deploy|none`, and `blocked` applies whenever `blocked-by:` is
   non-empty (record `pre-block-column:`, restore to it when it clears).
7. **BUMP `updated:` on every edit that CHANGES WHAT THE TRDD ASSERTS** — not just column
   changes. The board sorts on it, so a MECHANICAL repair (a format/syntax pass that changes
   no fact) must NOT bump it, or the repair silently reorders the whole board.
8. **`implementation-commits:`** accumulates the SHAs that landed this TRDD's code — the
   backtracking field: how a bug found later is traced to the TRDD that introduced it.
9. **NPT vs EHT.** `npt:` = Necessary Prerequisite Tasks — must finish BEFORE the parent
   proceeds past `dev`. `eht:` = Effects Handling Tasks — handle the CONSEQUENCES of the
   parent's work; the parent may land its code but **cannot reach `complete` until every EHT
   is terminal**. **Derived TRDDs are MANDATORY and depth-1**: empty `npt:`/`eht:`, never a
   `parent-trdd:`; siblings order via `blocked-by:`; `created-by:` set once; refusals archive
   `approved: false`. (Full: the reference.)
10. **STATE head block — MANDATORY once a TRDD spans more than one session.** A TRDD grows
    append-only, so a reader (or a compaction summary) hits the OLDEST, often SUPERSEDED facts
    first. Right after the title add:
    `## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — <date>`.
    Single source of truth, kept current on every edit; carries each component's state, the
    **NEXT ACTION** (one step, runnable as written), the load-bearing gotchas, an explicit
    **SUPERSEDED — do NOT carry forward** list, and the artifacts to read first.
11. **Reports are evidence; decisions become TRDDs.** A report (audit, benchmark) presents DATA
    and lives in gitignored `reports/`. The moment it leads to a DECISION, that decision goes
    into a TRDD — a new one, or an existing TRDD's STATE block.
12. **Terminal columns are frozen — AFTER the transition that made them terminal.** Do not
    edit the body of a `complete` / `failed` / `superseded` / `published` / `live` TRDD. New
    work = new TRDD. (Only `updated:` and, when superseding, `superseded-by:` may change.)
    Four clauses, without which the rule forbids the very edit that closes a card, or freezes
    stale noise that CONTRADICTS the record it exists to protect:
    the closing edit is the LAST permitted write, not the first forbidden one; `## Approval
    log` is an append-only ledger and is EXEMPT (an audit trail that cannot be appended to
    cannot record the act of closing); `published`/`live` archive AS THEMSELVES —
    rewriting `published → completed` destroys the fact that it shipped, so the
    archive-eligible set is `completed|cancelled|superseded|published|live`, and an absent
    `release-via:` defaults to `none` (terminal `complete`); and a body line that FALSELY
    duplicates the pipeline state — verifiably contradicting the terminal `column:`, e.g.
    `column: complete` alongside a body `**Status:** Not started` (the v1→v2 residue named in
    step 6) — MAY be removed (janitor#139 ASK 2). It is not part of the record this clause
    protects, only migration noise; deleting it removes a false claim ABOUT history, it does
    not rewrite history. This carve-out is narrow: it authorizes deleting ONLY a
    machine-verifiable contradiction, never a line that merely disagrees in wording, adds
    context, or cannot be mechanically proven false (e.g. a dated "Implemented" note that
    semantically agrees). Rationale: the reference.
13. **One atomic task per TRDD.** If you catch yourself writing "and also do X", X is an
    NPT, an EHT, or its own TRDD.
14. **One kanban board, `scope` as a badge — not a second board.** Columns and transitions
    are identical; tools scan every scope root by default.
15. **A LOCAL TRDD needs no approval** — it is a chore on the user's own machine and there is
    no MANAGER for it. Sole exception: if it is **destructive or irreversible on the user's
    machine** (rotating a credential, deleting a store, purging history) it needs **USER**
    approval and waits in the local `proposals/`.

## `review-after:` — the expiring, self-releasing park

`review-after: YYYY-MM-DD` in frontmatter tells `trdd-drift` to honour a deliberately parked
TRDD until that date, then check it normally again — **opt-in, never inferred**
(`backburner` stays drift-eligible by default). Two properties are deliberate and MUST survive
any reimplementation: it is a **snooze, not a mute** (a bare "shelved" label would silence the
TRDD forever; a date expires on its own, so a park a human forgets re-surfaces), and it **fails
OPEN** (a malformed date is treated as "none set" and the TRDD returns to the normal drift path
— a snooze failing CLOSED would hide work indefinitely, worse than the nag it replaces).
Full grammar + rationale: the reference. Implementation:
`scripts/detectors/trdd-drift.py::review_after_epoch`.

## Cross-project scope discriminators — `project-id:`, `host-id:`, `repo:`

Additive, backward-compatible (janitor#103): absent = today's exact behavior, and the below
are lint targets enforced incrementally on next-touch — never a mass rewrite.

- **`project-id:`** — the PROJECT discriminator: stable and repo-independent, since a project
  may span N GitHub repos but is ONE kanban. `scope: project` TRDDs SHOULD carry it;
  `scope: user`/`local` TRDDs MUST NOT (they bind to no single project).
- **`host-id:`** — the `scope: user` discriminator: which host's global board a TRDD belongs
  to. May be implicit from the host-only store (step 1); the field makes it greppable when a
  `user`-scope TRDD is ever copied or compared across machines.
- **`repo:`** — per-card ANNOTATION naming which of a multi-repo project's repos a card
  touches. It is not a discriminator — `project-id:` alone decides the kanban a card belongs
  to.

This mirrors the memory system's LOCAL/PROJECT/USER taxonomy: a kanban is a QUERY over the
TRDD corpus filtered on these fields (`local`+`created-by`, `project`+`project-id`,
`user`+`host-id`), never a second store.

## Authoring, in short

Route the scope (1) → mint id + timestamps (2) → minimal frontmatter → `column: backburner`
(`live_auditing` for an audit TRDD) → the same ISO datetime in BOTH `created:` and `updated:`
→ the prose → a TaskCreate entry naming the id. A **PROJECT** TRDD is then `git add`-ed **by
name** and committed (`docs: add TRDD-<id8> — <summary>`); report the id + commit. A **LOCAL**
one is in no repo — report the id + path.

Resuming later: look the id up in every scope root with `find` (never an `ls` glob — step 2):
`find design ~/.claude/projects/<slug>/design ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/design -iname 'TRDD-*-<id8>-*.md'` → read the **STATE
block first**. (**`-iname`, NOT `-name`** — legacy LOWERCASE ids are permanently valid: cited
in immutable commit subjects, so they cannot be renamed without destroying that provenance.
Load-bearing indefinitely, not a migration aid; measured, 76% of one live board.) On
disagreement the STATE block wins (hand-edits beat stale fields) — then fix the frontmatter.

## Does NOT apply to

Session handoffs (`docs_dev/`), scenario tests, proposal reports, inline `TODO:` comments, or
trivial tasks you finish this session (use TaskCreate). TRDDs are for **non-trivial design tasks
that must survive as tracked project artifacts**.
