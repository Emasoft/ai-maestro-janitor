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
saved as a **TRDD** — one `.md` file in a `design/tasks/` folder, with a grep-first YAML
frontmatter carrying the structured state and a body carrying the prose. A TRDD is
**PROJECT-scoped** (in the repo, git-tracked, shared) or **LOCAL-scoped** (outside the repo,
machine-private) — see the scope table in step 1.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/trdd-design-tasks-full.md`
> It holds the complete 10-group frontmatter schema, the column-transition matrix, the
> folder lifecycle (proposals/tasks/archived/refused), the approval tiers, the grep
> cheat-sheet, the v1→v2 migration, the anti-patterns, and the rationale. Read it when you
> need a field you don't know or a transition you haven't made before. Everything below is
> normative on its own; the reference only expands it.

## The normative core

1. **Location — a TRDD is PROJECT- or LOCAL-scoped, and its SCOPE IS ITS PATH.** Same
   lifecycle, different root:

   | scope | root | git |
   |---|---|---|
   | `project` (the default) | `<project-root>/design/` | **tracked + pushed** — every contributor sees it |
   | `local` | `~/.claude/projects/<slug>/design/` | **outside the repo — cannot be committed** |

   `<slug>` is the project's absolute path with every non-alphanumeric character replaced by
   `-` — the SAME slug the LOCAL *memory* scope uses, so the two local corpora sit side by
   side under one local-scope root. The local root **mirrors the project root exactly** (the
   same four lifecycle folders `proposals/ tasks/ archived/ refused/`), so every rule,
   protocol and tool here works by swapping ONE path and nothing else:

   ```
   ~/.claude/projects/<slug>/
   ├── memory/          <- LOCAL memory  (already exists)
   └── design/          <- LOCAL design  (mirrors <repo>/design/ exactly)
       ├── proposals/   <- a local task still awaiting a decision
       ├── tasks/       <- OPEN local work (incl. blocked and failed — failed is retryable)
       ├── archived/    <- completed · cancelled · superseded
       └── refused/     <- proposals never approved
   ```

   PROJECT `design/` is git-tracked and MUST NOT be in `.gitignore`. LOCAL needs **no
   gitignore entry at all** — nothing is written inside the repo, so a repo the tooling
   merely visits is not mutated. Never put a TRDD in `docs_dev/`. Create with `mkdir -p`.

   **Scope routing — decide BEFORE authoring** (mirrors the memory-scope rule). Ask: *"would
   this task be TRUE and USEFUL for a contributor who clones this repo on a DIFFERENT
   machine?"*
   - **No → LOCAL.** Each of these forces local: an absolute `$HOME` path, a hostname, a
     username, a credential or token, "on THIS machine", a specific install/cache state,
     anything about a plugin's own runtime data dir.
   - **Yes → PROJECT.**
   - **UNSURE → LOCAL.** Local is the safe scope: promoting local→project later is a
     deliberate act, whereas a leaked machine-private TRDD is already pushed.

   A task may SPLIT — the machine-agnostic work as a PROJECT TRDD, the per-machine state as a
   LOCAL one, cross-linked.

   A `scope: project | local` frontmatter field may appear (absent = `project`), but the
   **path is authoritative**: it is what actually decides whether the file is git-tracked, so
   on any disagreement the path wins and the field is a lint target, exactly as a memory
   note's scope is its path.

2. **Filename.** `TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md`.
   `<id8>` is an **8-char UPPERCASE base36** id (`A-Z0-9`) — this IS the canonical id;
   there is **no UUID**. It must be unique across **BOTH roots of a project**, so the
   collision check scans both — a citation that could mean two TRDDs destroys the one
   property the whole citation grammar rests on. Regenerate on the (vanishingly rare) hit:
   ```bash
   gen()   { LC_ALL=C tr -dc 'A-Z0-9' < /dev/urandom | head -c 8; }
   # `find | grep -q .` — NOT `ls <glob>`. An unmatched glob is dropped by some shells, so
   # `ls` then runs with NO arguments, lists the cwd, and exits 0 — which the loop below
   # reads as "collision", regenerating forever. That is an infinite loop, not a nit.
   taken() { find "$1" "$2" -name "TRDD-*-$3-*.md" 2>/dev/null | grep -q .; }
   SLUG=$(pwd | tr -c '[:alnum:]' '-'); LOCAL_DESIGN="$HOME/.claude/projects/$SLUG/design"
   ID8=$(gen); while taken design "$LOCAL_DESIGN" "$ID8"; do ID8=$(gen); done
   TS=$(date +%Y%m%d_%H%M%S%z); ISO=$(date +%Y-%m-%dT%H:%M:%S%z)
   ```
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
14. **One kanban board, `scope` as a badge — not a second board.** A local card renders like
    any other; columns and transitions are identical. Tools take the root(s) to scan and
    default to BOTH.
15. **Approval of a LOCAL TRDD is `none` by default** — it is a chore on the user's own
    machine and there is no MANAGER for that. The exception is the one that always applies:
    if the task is **destructive or irreversible on the user's machine** (rotating a
    credential, deleting a store, purging history), it needs **USER** approval and waits in
    the local root's `proposals/`. That is why the local root keeps `proposals/` and
    `refused/` instead of being a flat folder.

## Authoring, in short

Route the scope (step 1) → generate the id + timestamps (step 2) → write the file with the
minimal frontmatter → `column: backburner` (or `live_auditing` for an audit TRDD) → same ISO
datetime in BOTH `created:` and `updated:` → write the prose → create a TaskCreate entry
naming the id.

A **PROJECT** TRDD is then `git add`-ed **by name** and committed (`docs: add TRDD-<id8> —
<summary>`); tell the user the id and the commit. A **LOCAL** TRDD is in no repo — there is
nothing to commit, so just tell the user the id and the path.

Resuming later: look the id up in BOTH roots (`find`, not an `ls` glob — see step 2) —
`find design ~/.claude/projects/<slug>/design -name 'TRDD-*-<id8>-*.md'` → read the **STATE
block first**. If the STATE block and the frontmatter disagree, the STATE block wins
(hand-edits beat stale fields) — then fix the frontmatter.

## Does NOT apply to

Session handoffs (`docs_dev/`), scenario tests, proposal reports, inline `TODO:` comments,
or trivial tasks you will finish this session (use TaskCreate). TRDDs are for **non-trivial
design tasks that must survive as tracked artifacts of the project**.
