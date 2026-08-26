<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active** (`DATA` =
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`): no `DATA` ⇒ orphan — INERT,
> and the user may delete THIS FILE only, never a memory store; `DATA/global-state/kill-switch.flag`
> (or legacy `~/.claude/janitor-global-state/kill-switch.flag`) ⇒ deliberately stopped, INERT this
> session; else ACTIVE.

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

## The ratified 22-column vocabulary (3-pillars 3.0.0)

USER-ratified 2026-08-23 (TRDD-UNTF690M, `PRRD G2.1`; spec
`3-pillars-spec.md` 3.0.0 at ai-maestro `governance-rules` head
`c8b0e9cb` — the canonical text for every clause cited here).

**22 columns**, 1:1 with the TRDD `column:` enum — **19 lifecycle**:

```
backburner → approval → design → design_ai_review
  → design_human_review → todo → verify_assumptions → plan
  → dispatch → dev → testing → ai_review → human_review
  → complete → publish → published → deploy → live → live_auditing
```

plus **3 exception** columns: `blocked`, `failed`, `superseded`.
Identifiers are snake_case; hyphenated spellings are prose-only
(3P-KAN-17). The five 3.0.0 additions' normative meanings
(3P-KAN-18/-19) live in
`rules/references/universal-kanban-3p300-columns.md` — READ IT before
moving any card into one of them (`design` now precedes `todo`).

**The LEGAL SET for `column:` is 27, not 22** (3P-KAN-20): five
BRACKET values sit outside the board — `proposal`, `planned`,
`refused`, `completed`, `cancelled` — defined by the folder lifecycle
in `trdd-design-tasks.md`. `proposal`/`planned` are the intake
antechamber ahead of `backburner`; terminal values leave the board,
each archived AS ITSELF (3P-ZON-05) into `design/archived/`
(`refused` into `design/refused/`).

**Pre-3.0.0 cards are grandfathered** (3P-KAN-21): entered `todo`,
`design` or `backburner` on or before 2026-08-23 ⇒ conformant under
that column's OLD meaning — never flagged, never auto-migrated.

This vocabulary is CANONICAL: every consumer aligns TO it, never the
reverse; a coarser view may GROUP columns for display but must
round-trip mutations back to the full vocabulary.

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
# Needs attention
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

One source of truth (a kanban that IS the TRDD corpus cannot drift),
portability (git + markdown + grep is the whole stack), and an upgrade
path (the ai-maestro overlay turns the same board multi-agent without
migrating any data — the cards were TRDDs all along).
