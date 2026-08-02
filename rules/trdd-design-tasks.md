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
**PROJECT-scoped** (in the repo, git-tracked, shared) or **LOCAL-scoped** (outside the repo,
machine-private) — see step 1.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/trdd-design-tasks-full.md`
> Holds the id/timestamp recipe, the full frontmatter schema, the column-transition matrix,
> the folder lifecycle, the grep cheat-sheet, the v1→v2 migration, and the rationale. Read it
> when you need a field or a transition you don't know. Everything below is normative on its
> own; the reference only expands it.

## The normative core

1. **Location — a TRDD is PROJECT- or LOCAL-scoped, and its SCOPE IS ITS PATH.** Both roots
   hold the SAME four lifecycle folders (`proposals/ tasks/ archived/ refused/`), so every
   rule and tool here works by swapping ONE path:

   | scope | root | git |
   |---|---|---|
   | `project` (default) | `<project-root>/design/` | **tracked + pushed** — every contributor sees it |
   | `local` | `~/.claude/projects/<slug>/design/` | **outside the repo — cannot be committed** |

   `<slug>` = the project's absolute path with every non-alphanumeric char replaced by `-` —
   the SAME slug LOCAL *memory* uses, so both local corpora sit under one local-scope root.
   PROJECT `design/` MUST NOT be in `.gitignore`. LOCAL needs no gitignore entry at all —
   nothing is written inside the repo, so a repo the tooling merely visits is not mutated.

   **Scope routing — decide BEFORE authoring.** Ask: *"would this task be TRUE and USEFUL for
   a contributor who clones this repo on a DIFFERENT machine?"* **No → LOCAL** (an absolute
   `$HOME` path, a hostname, a username, a credential, "on THIS machine", an install state
   each force it). **Yes → PROJECT. UNSURE → LOCAL** — a leaked machine-private TRDD is
   already pushed, whereas promoting local→project later is deliberate. A task may SPLIT,
   cross-linked. A `scope:` field may appear (absent = `project`) but the **path is
   authoritative** — it decides git-tracking — so the path wins and the field is a lint target.

2. **Filename.** `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`. `<id8>` is an **8-char
   UPPERCASE base36** id (`A-Z0-9`) — this IS the canonical id (no UUID), unique across
   **BOTH roots** (the collision check scans both). Test for a taken id with
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
    Three clauses, without which the rule forbids the very edit that closes a card:
    the closing edit is the LAST permitted write, not the first forbidden one; `## Approval
    log` is an append-only ledger and is EXEMPT (an audit trail that cannot be appended to
    cannot record the act of closing); and `published`/`live` archive AS THEMSELVES —
    rewriting `published → completed` destroys the fact that it shipped, so the
    archive-eligible set is `completed|cancelled|superseded|published|live`, and an absent
    `release-via:` defaults to `none` (terminal `complete`). Rationale: the reference.
13. **One atomic task per TRDD.** If you catch yourself writing "and also do X", X is an
    NPT, an EHT, or its own TRDD.
14. **One kanban board, `scope` as a badge — not a second board.** Columns and transitions
    are identical; tools scan BOTH roots by default.
15. **A LOCAL TRDD needs no approval** — it is a chore on the user's own machine and there is
    no MANAGER for it. Sole exception: if it is **destructive or irreversible on the user's
    machine** (rotating a credential, deleting a store, purging history) it needs **USER**
    approval and waits in the local `proposals/`.

## Authoring, in short

Route the scope (1) → mint id + timestamps (2) → minimal frontmatter → `column: backburner`
(`live_auditing` for an audit TRDD) → the same ISO datetime in BOTH `created:` and `updated:`
→ the prose → a TaskCreate entry naming the id. A **PROJECT** TRDD is then `git add`-ed **by
name** and committed (`docs: add TRDD-<id8> — <summary>`); report the id + commit. A **LOCAL**
one is in no repo — report the id + path.

Resuming later: look the id up in BOTH roots with `find` (never an `ls` glob — step 2):
`find design ~/.claude/projects/<slug>/design -iname 'TRDD-*-<id8>-*.md'` → read the **STATE
block first**. (**`-iname`, NOT `-name`** — legacy LOWERCASE ids are permanently valid: cited
in immutable commit subjects, so they cannot be renamed without destroying that provenance.
Load-bearing indefinitely, not a migration aid; measured, 76% of one live board.) On
disagreement the STATE block wins (hand-edits beat stale fields) — then fix the frontmatter.

## Does NOT apply to

Session handoffs (`docs_dev/`), scenario tests, proposal reports, inline `TODO:` comments, or
trivial tasks you finish this session (use TaskCreate). TRDDs are for **non-trivial design tasks
that must survive as tracked project artifacts**.
