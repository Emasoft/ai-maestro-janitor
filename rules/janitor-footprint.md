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

# ai-maestro-janitor — what it creates on this machine

**Read this before deleting anything under `.janitor/`, `.claude/`, `memory/`,
`reports/`, or `.trashcan/`** — a Claude that finds these without context has
mistaken real memory stores for junk and tried to delete them.

The **ai-maestro-janitor** plugin is installed at **USER scope**, so it runs in
**every** project on this machine. A ~5-minute heartbeat runs drift/security
detectors; a single global daemon owns machine-wide plugin updates + OAuth
keepalive; and it provides the markdown **memory system**. Its capabilities are
on-demand **`/janitor-*` commands** — memory (`/janitor-memory-recall|write|update`),
hygiene (`/janitor-audit`, `/janitor-doctor`, `/janitor-identify-environment`),
control (`/janitor-arm`, `/janitor-pause`, `/janitor-disarm`), plus supply-chain,
GitHub-workflow, branch-protection, and `/janitor-safe-delete` helpers (type
`/janitor-` to list them).

It **creates and maintains** the paths below. **Never delete a memory STORE or
the plugin DATA dir** (real knowledge / persistent state); regeneratable caches
are safe to remove.

## Per project (under each repo / `$CLAUDE_PROJECT_DIR`)

| Path | What it is | Safe to delete? |
|---|---|---|
| `.janitor/state/`, `.janitor/logs/` | per-session detector state (last-run stamps, seen-files, flags) + logs | **yes** — regenerated; gitignore it |
| `.claude/project/memory/` | **PROJECT**-scope wiki memory — git-**tracked + PUSHED**, shared by every contributor | **NO** — real shared knowledge |
| `reports/`, `reports_dev/` | agent reports (may hold private data) — **gitignored** | yes — ephemeral |
| `.trashcan/` | `/janitor-safe-delete` staging — gitignored, auto-purged after ~90d | recover from here; otherwise auto-purged |

## Global (under `~/.claude/`)

| Path | What it is | Safe to delete? |
|---|---|---|
| `~/.claude/rules/*.md` | the janitor's shipped GLOBAL rules — hygiene (this one, `markdown-memory-recall`, `use-safe-delete`, `commit-discipline`, `janitor-heartbeat-protocol`) + the 3 ai-maestro-INDEPENDENT governance rules (`trdd-design-tasks`, `prrd-design-rules`, `universal-kanban` — the janitor half of ai-maestro TRDD-DE9757LJ, issue #73) | no — canonical. A **project-local copy** of any of these is a redundant mirror: gitignore or delete it, **never commit** it (it would impose a personal global rule on every contributor) |
| `~/.claude/projects/<slug>/memory/` | **LOCAL**-scope wiki memory — machine-private notes (paths, hostnames, hints) | **NO** — real knowledge |
| `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` | the janitor's **DATA** dir — dispatcher stub, **USER**-scope memory (canonical), OAuth-rotator + daemon state | **NO** — persistent state |
| `~/.claude/ai-maestro-janitor-memory/` | the **USER-scope memory MIRROR** — a synced backup of the canonical USER corpus, kept OUTSIDE the data dir so it survives a plain `plugin uninstall` (TRDD-GFT33HT9). SessionStart syncs it and restores from it after a data-dir loss | **NO** — real knowledge (a memory store) |
| `~/.claude/plugins/data/…/global-state/` | the machine-wide daemon singleton (pid / flock / locks / timestamps) — CANONICAL since TRDD-2U8AH82F | no — the daemon recreates what it needs |
| `~/.claude/janitor-global-state/` | the LEGACY daemon-state dir — auto-migrated into the DATA dir by the daemon; kept only as a read-fallback for not-yet-updated sessions (see its README-MOVED.txt) | after every session runs a post-migration janitor, yes |

**Rule of thumb:** any `…/memory/…` directory and the plugin **DATA** dir hold
real state — never delete them. `.janitor/state`, `.janitor/logs`, `reports*`,
and `.trashcan` are regeneratable. The memory system's three scopes + a per-file
inventory live in `markdown-memory-recall.md`.
