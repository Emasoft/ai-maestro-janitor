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
| `~/.claude/rules/*.md` | the janitor's shipped GLOBAL rules (this one, `markdown-memory-recall`, `use-safe-delete`) | no — canonical. A **project-local copy** of any of these is a redundant mirror: gitignore or delete it, **never commit** it (it would impose a personal global rule on every contributor) |
| `~/.claude/projects/<slug>/memory/` | **LOCAL**-scope wiki memory — machine-private notes (paths, hostnames, hints) | **NO** — real knowledge |
| `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` | the janitor's **DATA** dir — dispatcher stub, **USER**-scope memory, OAuth-rotator + daemon state | **NO** — persistent state |
| `~/.claude/janitor-global-state/` | the machine-wide daemon singleton (pid / flock / locks / timestamps) | no — the daemon recreates what it needs |

**Rule of thumb:** any `…/memory/…` directory and the plugin **DATA** dir hold
real state — never delete them. `.janitor/state`, `.janitor/logs`, `reports*`,
and `.trashcan` are regeneratable. The memory system's three scopes + a per-file
inventory live in `markdown-memory-recall.md`.
