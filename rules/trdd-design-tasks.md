<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete if the plugin is gone; deleting it never affects any MEMORY store. -->

> [!IMPORTANT]
> **Janitor rule — INERT unless the janitor is active.** Two cheap `$HOME` checks, in order.
> **UNINSTALLED** — `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` ABSENT ⇒
> this file is an orphan the plugin could not remove (Claude Code does not clean a plugin's
> rules dirs on uninstall): treat as INERT and tell the user they may delete it. NEVER delete a
> MEMORY store — only this rule file, and only with the user's ok. **DISARMED** — else if that
> dir's `global-state/kill-switch.flag` (or legacy `~/.claude/janitor-global-state/kill-switch.flag`)
> EXISTS, the janitor is intentionally stopped ⇒ INERT this session. **ACTIVE** — otherwise,
> apply the rule below.

# TRDD: Task Requirement Design Documents (v2)

> **Layering note.** This is the UNIVERSAL BASE (IND) of the 3-pillars design system — it
> assumes nothing beyond a git repo and one Claude, who performs every duty named here with
> the USER as sole approver. In a registered ai-maestro agent workdir the server installs an
> overlay that EXPANDS this base with multi-agent transition authority, approval tiers and
> title-based routing; the overlay never restates this base.

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
   a contributor who clones this repo on a DIFFERENT machine?"*
   - **No → LOCAL.** Each of these forces local: an absolute `$HOME` path, a hostname, a
     username, a credential/token, "on THIS machine", a specific install/cache state.
   - **Yes → PROJECT.** **UNSURE → LOCAL** — the safe scope: promoting local→project later is
     deliberate, whereas a leaked machine-private TRDD is already pushed.
   - A task may SPLIT: machine-agnostic work as a PROJECT TRDD, per-machine state as a LOCAL
     one, cross-linked.

   A `scope: project | local` field may appear (absent = `project`), but the **path is
   authoritative** — it is what decides whether the file is git-tracked — so on any
   disagreement the path wins and the field is a lint target.

2. **Filename.** `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`. `<id8>` is an **8-char
   UPPERCASE base36** id (`A-Z0-9`) — this IS the canonical id; there is **no UUID**. It must
   be unique across **BOTH roots**, so the collision check scans both: a citation that could
   mean two TRDDs destroys the one property the whole citation grammar rests on. Test for a
   taken id with `find … | grep -q .`, **never** `ls <glob>` — an unmatched glob is DROPPED by
   some shells, so `ls` runs with no args, lists the cwd and exits 0, which a
   regenerate-on-collision loop reads as "taken" forever (an infinite loop, not a nit). Copy
   the id/timestamp recipe from the full reference.
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

6. **`column:` is the state machine** (v2 replaced v1's `status:`). Lifecycle order:
   `backburner → todo → design → dispatch → dev → testing → ai_review → (human_review) →
   complete`, then `publish → published` (tools) or `deploy → live → (live_auditing)`
   (services), per `release-via: publish|deploy|none`.
   Orthogonal/terminal: `blocked` (whenever `blocked-by:` is non-empty — record
   `pre-block-column:` and restore to it when it clears), `failed`, `superseded`.
7. **BUMP `updated:` on EVERY edit** — not just column changes. The board sorts on it.
8. **`implementation-commits:`** accumulates the SHAs that landed this TRDD's code. This is
   the backtracking field: it is how a bug found later is traced to the TRDD that
   introduced it. Append as code lands.
9. **NPT vs EHT.** `npt:` = Necessary Prerequisite Tasks — must finish BEFORE the parent
   proceeds past `dev`. `eht:` = Effects Handling Tasks — handle the CONSEQUENCES of the
   parent's work; the parent may land its code but **cannot reach `complete` until every
   EHT is terminal**.
10. **STATE head block — MANDATORY once a TRDD spans more than one session.** A TRDD grows
    append-only, so a reader (or a compaction summary) hits the OLDEST, often SUPERSEDED
    facts first. Immediately after the title, before the first body section:

    ```markdown
    ## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — <date>
    ```

    It is the single source of truth and is kept current on every edit. It carries: the
    current state of each component; the **NEXT ACTION** (one concrete step, runnable as
    written); the load-bearing facts/gotchas; an explicit **SUPERSEDED — do NOT carry
    forward** list; and paths to the durable artifacts to read before acting.
11. **Reports are evidence; decisions become TRDDs.** A report (audit, benchmark) presents
    DATA and lives in gitignored `reports/`. The moment it leads to a DECISION, that
    decision is written into a TRDD — a new one, or by extending an existing TRDD's STATE
    block.
12. **Terminal columns are frozen.** Do not edit the body of a `complete` / `failed` /
    `superseded` / `published` / `live` TRDD. New work = new TRDD. (Only `updated:` and,
    when superseding, `superseded-by:` may change.)
13. **One atomic task per TRDD.** If you catch yourself writing "and also do X", X is an
    NPT, an EHT, or its own TRDD.
14. **One kanban board, `scope` as a badge — not a second board.** Columns and transitions
    are identical; tools scan BOTH roots by default.
15. **A LOCAL TRDD needs no approval** — it is a chore on the user's own machine and there is
    no MANAGER for that. Sole exception, the one that always applies: if it is **destructive
    or irreversible on the user's machine** (rotating a credential, deleting a store, purging
    history) it needs **USER** approval and waits in the local `proposals/`.

## Authoring, in short

Route the scope (step 1) → generate the id + timestamps (step 2) → write the file with the
minimal frontmatter → `column: backburner` (or `live_auditing` for an audit TRDD) → same ISO
datetime in BOTH `created:` and `updated:` → write the prose → create a TaskCreate entry
naming the id. A **PROJECT** TRDD is then `git add`-ed **by name** and committed (`docs: add
TRDD-<id8> — <summary>`); tell the user the id and the commit. A **LOCAL** TRDD is in no repo
— nothing to commit; tell the user the id and the path.

Resuming later: look the id up in BOTH roots with `find` (never an `ls` glob — step 2):
`find design ~/.claude/projects/<slug>/design -name 'TRDD-*-<id8>-*.md'` → read the **STATE
block first**. If it disagrees with the frontmatter, the STATE block wins (hand-edits beat
stale fields) — then fix the frontmatter.

## Does NOT apply to

Session handoffs (`docs_dev/`), scenario tests, proposal reports, inline `TODO:` comments,
or trivial tasks you will finish this session (use TaskCreate). TRDDs are for **non-trivial
design tasks that must survive as tracked artifacts of the project**.
