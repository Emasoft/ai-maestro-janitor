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

# Universal kanban — the permanent task system of every project

> **Layering note.** This is the UNIVERSAL BASE (IND) of the kanban
> pillar — a MONO-agent task manager that assumes nothing beyond a git
> repo and one Claude. When the project is a registered ai-maestro
> agent workdir, the server-installed overlay
> (`aimaestro-kanban-multiagent.md`) EXPANDS this base into a
> multi-agent shared board with dashboard and GitHub-Project sync — it
> never restates this base.

**Rule:** Every project runs ONE kanban board, and that board is not a
separate tool — it is a **VIEW over the TRDD corpus**. The cards are
the TRDD files under `design/`; a card's column is its frontmatter
`column:` field; moving a card = editing `column:` (plus the `git mv`
between design/ folders when the move crosses a lifecycle zone, per
the TRDD folder-lifecycle rules). There is no second task database to
drift out of sync — the TRDDs ARE the board.

## The ratified 17-column vocabulary

The board has exactly **17 columns**, 1:1 with the TRDD `column:`
enum — **14 lifecycle**:

```
backburner → todo → design → dispatch → dev → testing → ai_review
  → human_review → complete → publish → published → deploy → live
  → live_auditing
```

plus **3 exception** columns: `blocked`, `failed`, `superseded`.

The folder-lifecycle overlay values (`proposal`, `planned`, `refused`,
`cancelled`, `completed`, `superseded` — defined in
`trdd-design-tasks.md`) BRACKET this pipeline; they are states of the
same `column:` field, not additional work columns. `proposal`/`planned`
cards sit in an intake antechamber ahead of `backburner`, and the
terminal values leave the board — `completed`/`cancelled`/`superseded`
into `design/archived/`, `refused` into `design/refused/`. A board view
may render them as an intake lane and a done lane.

This vocabulary is CANONICAL. Any tool, script, UI, or mirror that
displays or mutates tasks aligns TO these 17 columns — never the
reverse. A consumer must not invent a divergent column set, rename
columns, or collapse them; a coarser view (e.g. a 4-column summary
board) may GROUP columns for display but must round-trip mutations
back to the full vocabulary.

## Mono-agent operation (the standalone mode)

In a standalone project there is exactly ONE schedule and ONE worker:

- **Single assignee.** Every task's `assignee:` is the project's own
  Claude. There is no dispatch decision to make — `dispatch → dev` is
  a self-assignment.
- **Self-managed.** The same Claude authors the cards (TRDDs), moves
  them through the columns as it works, and reports the board state to
  the USER. The USER steers by approving proposals and reviewing
  `human_review` cards; the Claude does everything else.
- **WIP discipline.** Keep few cards in the WORK columns
  (`dev`/`testing`/`ai_review`) at once; a mono-agent board with ten
  parallel `dev` cards is a sign of context-thrash, not throughput.
- **Exception columns are signals to the USER.** `blocked` cards list
  their `blocked-by:`; `failed` cards stay on the board (retryable —
  never archived as failed); `superseded` cards leave the board on the
  next archival pass.

## Rendering the board

The board is greppable — no server required:

```bash
# The whole board in one shot (column per card)
grep -H "^column:" design/tasks/*.md design/proposals/*.md 2>/dev/null

# One column
grep -l "^column: dev$" design/tasks/*.md

# The exception columns (needs attention)
grep -lE "^column: (blocked|failed)$" design/tasks/*.md
```

Render it for the USER as a compact table (column → cards with
`TRDD-<id8>` + title) whenever asked "what's on the board" / "status".

## Card discipline

- **One card = one TRDD.** No cards without a TRDD file behind them;
  no TRDD that should be worked on without appearing on the board.
- **Todo-list entries reference their card** (`TRDD-<id8>` in the
  subject) so the ephemeral session todo list and the durable board
  stay linked.
- **Column moves follow the TRDD rules** — the transition table, the
  folder lifecycle, and the `updated:` bump live in
  `trdd-design-tasks.md`; this rule adds no second state machine.

## Why this exists

- **One source of truth.** A kanban that mirrors a task database
  drifts; a kanban that IS the TRDD corpus cannot.
- **Portability.** Any project — with or without ai-maestro — gets a
  full task system from nothing but git + markdown + grep.
- **Upgrade path.** When the project joins ai-maestro, the overlay
  turns the same board multi-agent (shared assignees, dashboard UI,
  GitHub-Project mirror) without migrating any data: the cards were
  TRDDs all along.
