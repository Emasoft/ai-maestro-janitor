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

**Rule:** every non-trivial feature spec, backlog item, or deferred-work design note is
saved as a **TRDD** — one git-tracked `.md` file in `<project-root>/design/tasks/`, with a
grep-first YAML frontmatter carrying the structured state and a body carrying the prose.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/trdd-design-tasks-full.md`
> It holds the complete 10-group frontmatter schema, the column-transition matrix, the
> folder lifecycle (proposals/tasks/archived/refused), the approval tiers, the grep
> cheat-sheet, the v1→v2 migration, the anti-patterns, and the rationale. Read it when you
> need a field you don't know or a transition you haven't made before. Everything below is
> normative on its own; the reference only expands it.

## The normative core

1. **Location.** `<project-root>/design/tasks/` — git-tracked, never in `.gitignore`, never
   in `docs_dev/` or `~/.claude/`. Create with `mkdir -p` if absent.
2. **Filename.** `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`.
   `<id8>` is an **8-char UPPERCASE base36** id (`A-Z0-9`) — this IS the canonical id;
   there is **no UUID**. Regenerate on the (vanishingly rare) collision:
   ```bash
   gen() { python3 -c "import random,string; print(''.join(random.choices(string.ascii_uppercase+string.digits,k=8)))"; }
   ID8=$(gen); while ls design/tasks/TRDD-*-"$ID8"-*.md >/dev/null 2>&1; do ID8=$(gen); done
   TS=$(date +%Y%m%d_%H%M%S%z); ISO=$(date +%Y-%m-%dT%H:%M:%S%z)
   ```
3. **Reference a TRDD as `TRDD-<id8>`** (or `#<id8>` casually). Lookups are
   case-insensitive; the id is always WRITTEN uppercase. Put it in the commit subject of
   every commit that implements it, and in any TaskCreate entry that tracks it.
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

## Authoring, in short

Generate the id + timestamps (step 2) → write the file with the minimal frontmatter →
`column: backburner` (or `live_auditing` for an audit TRDD) → same ISO datetime in BOTH
`created:` and `updated:` → write the prose → create a TaskCreate entry naming the id →
`git add` the file **by name** and commit (`docs: add TRDD-<id8> — <summary>`) → tell the
user the id and the commit.

Resuming later: `ls design/tasks/TRDD-*-<id8>-*` → read the **STATE block first**. If the
STATE block and the frontmatter disagree, the STATE block wins (hand-edits beat stale
fields) — then fix the frontmatter.

## Does NOT apply to

Session handoffs (`docs_dev/`), scenario tests, proposal reports, inline `TODO:` comments,
or trivial tasks you will finish this session (use TaskCreate). TRDDs are for **non-trivial
design tasks that must survive as tracked artifacts of the project**.
