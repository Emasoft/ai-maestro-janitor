<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active** (`DATA` =
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`): no `DATA` ⇒ orphan — INERT,
> and the user may delete THIS FILE only, never a memory store; `~/.claude/janitor-control/kill-switch.flag`
> (or the older `DATA/global-state/kill-switch.flag`) ⇒ deliberately stopped, INERT this
> session; else ACTIVE.

# ai-maestro-janitor — what it creates on this machine

**Read this before deleting anything under `.janitor/`, `.claude/`, `memory/`,
`reports/`, or `.trashcan/`** — a Claude that finds these without context has
mistaken real memory stores for junk and tried to delete them.

The **ai-maestro-janitor** plugin is installed at **USER scope**, so it runs in
**every** project on this machine. A ~5-min heartbeat runs drift/security
detectors; a single global daemon owns machine-wide plugin updates + OAuth
keepalive; and it provides the markdown **memory system**. Its capabilities are
on-demand **`/janitor-*` commands** — memory (`/janitor-memory-recall|write|update`),
hygiene (`/janitor-audit`, `/janitor-doctor`, `/janitor-identify-environment`),
control (`/janitor-arm`, `/janitor-pause`, `/janitor-disarm`), plus supply-chain,
GitHub-workflow, branch-protection, and `/janitor-safe-delete` helpers (type
`/janitor-` to list them).

It **creates and maintains** the paths below. **Never delete a memory STORE or
the plugin DATA dir**; regeneratable caches are safe to remove.

## Per project (under each repo / `$CLAUDE_PROJECT_DIR`)

| Path | What it is | Safe to delete? |
|---|---|---|
| `.janitor/state/`, `.janitor/logs/` | per-session detector state (stamps, seen-files, flags) + logs | **yes** — regenerated; gitignore it |
| `.claude/project/memory/` | **PROJECT**-scope wiki memory — git-**tracked + PUSHED**, shared | **NO** — real shared knowledge |
| `reports/`, `reports_dev/` | agent reports (may hold private data) — **gitignored** | yes — ephemeral |
| `.trashcan/` | `/janitor-safe-delete` staging — gitignored, purged after ~90d | recover here; else auto-purged |

## Global (under `~/.claude/`)

| Path | What it is | Safe to delete? |
|---|---|---|
| `~/.claude/rules/*.md` | shipped GLOBAL rules — hygiene (this one, `markdown-memory-recall`, `use-safe-delete`, `commit-discipline`, `janitor-heartbeat-protocol`) + 3 ai-maestro-INDEPENDENT governance rules (`trdd-design-tasks`, `prrd-design-rules`, `universal-kanban` — janitor half of TRDD-DE9757LJ, issue #73) | no — canonical. A project-local copy is a redundant mirror: gitignore/delete it, **never commit** (imposes a personal rule on every contributor) |
| `~/.claude/projects/<slug>/memory/` | **LOCAL**-scope wiki memory — machine-private notes (paths, hostnames, hints) | **NO** — real knowledge |
| ~~`~/.claude/projects/<slug>/design/`~~ → `<project-root>/.claude/local/design/` | **LOCAL** TRDD cards moved IN-TREE, gitignored (TRDD-WY198OIP, ai-maestro#163) — memory stays at the slug dir above | n/a — migrated, not deleted |
| `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` | the janitor's **DATA** dir — dispatcher stub, **USER**-scope memory (canonical), OAuth-rotator + daemon state | **NO** — persistent state |
| `~/.claude/ai-maestro-janitor-memory/` | **USER-scope memory MIRROR** — a synced backup of the canonical USER corpus, kept OUTSIDE the data dir so it survives a plain `plugin uninstall` (TRDD-GFT33HT9); SessionStart syncs it and restores after a data-dir loss | **NO** — real knowledge |
| `~/.claude/plugins/data/…/global-state/` | machine-wide daemon singleton (pid/flock/locks/timestamps) — CANONICAL since TRDD-2U8AH82F | no — daemon recreates what it needs |
| `~/.claude/janitor-global-state/` | LEGACY daemon-state dir — **RETIRED (TRDD-ULEGRT01)**: no resolver rung, no reads; the daemon copies leftovers to DATA on first run (README-MOVED.txt) | yes, once `DATA/global-state/migrated-from-legacy.ts` exists |

**Rule of thumb:** any `…/memory/…` dir and the plugin **DATA** dir hold real
state — never delete them. `.janitor/state`, `.janitor/logs`, `reports*`, and
`.trashcan` are regeneratable. Memory scopes + per-file inventory:
`markdown-memory-recall.md`.
