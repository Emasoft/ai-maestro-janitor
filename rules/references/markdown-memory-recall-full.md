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

# Markdown memory — recall protocol (the search half)

The harness `# Memory` directive (injected each session) tells you how to
**WRITE** memories. This rule is the missing half: how to **RECALL** them, the
**discipline** that makes recall work, and the **tool** (`memgrep`) that powers
it. Together they are "the memory system": authoring (directive) + recall (this
rule) + the search tool (memgrep) + the note corpus.

## THE PROACTIVE-USE CONTRACT (do this UNPROMPTED — the whole point of memory)

The memory system is **worthless if it is only used when the user asks**. Every
agent — orchestrator and sub-agent, in every plugin — uses it **proactively**, by
default, without being told. Four standing commitments:

1. **RECALL BEFORE ACTING.** Before you debug a recurring problem, make a design
   decision, or act on a recurring alert — RECALL FIRST ("have we hit this
   before?"). One symptom-indexed query across all 3 scopes (the snippet below),
   indexed by the **SYMPTOM / the user's words**, never the answer's jargon. It
   is cheap and it is the entire reason a memory exists. Skipping it means
   re-deriving (often badly) something a past session already solved.

2. **WRITE / UPDATE AFTER SOLVING.** After you solve a non-trivial problem, fix a
   bug, or make a decision that isn't derivable from the code — capture it into
   the wiki page that OWNS the subject (RECALL first so you update, not
   duplicate). Use the correction protocol when it supersedes a prior fact: clean
   the body to the current truth AND demote the old statement to a dated `[^N]`
   lesson carrying the WHY. The fact moves forward clean; the error becomes a
   guardrail. `/janitor-memory-write` (MEMORIZE) and `/janitor-memory-update`.

3. **MAINTAIN THE PROJECT WIKIMEM.** Each project's agent proactively keeps its
   **PROJECT-scope** pages current — an **architecture hub**, the **key-solution
   component** pages, the **publish/deploy pipeline** page — so this knowledge is
   git-tracked and shared with every dev (not stranded in one session's head). If
   the project has no wikimem yet, bootstrap it once with
   `/janitor-memory-bootstrap`.

4. **SCOPE ROUTING (decide BEFORE writing).** machine-private (local paths,
   usernames, hostnames, secrets, machine-specific detail) → **LOCAL**;
   project-shared knowledge with NO private data → **PROJECT**; true across all
   projects → **USER**. **UNSURE → LOCAL** (the safe scope; the `memory-scope-leak`
   detector polices PROJECT/USER for anything sensitive).

This contract is not optional and not gated on a user request. The three skills
(`/janitor-memory-recall`, `/janitor-memory-write`, `/janitor-memory-update`) are
the executable form of commitments 1-2; `/janitor-memory-bootstrap` stands up
commitment 3 in a fresh project.

## The one law that makes memory work: index by the QUESTION, not the answer

A memory is found from the SYMPTOM, not the solution. When you write a note,
its `description:` (and `title`/`tags`) MUST carry the words a future session
will have when the problem RECURS — the user's words, the error text, the
symptom — NOT the jargon of the fix.

- WRONG `description`: "OAuth creds live in the macOS keychain services".
  (Findable only if you already know the answer is "keychain".)
- RIGHT `description`: "rotator failed, had to log in manually — where are the
  creds / why did the swap fail" + the keychain fact in the BODY.

Two-hop recall: a symptom query lands you on the note; the note's BODY gives the
answer. The `description` is the load-bearing surface — `memgrep recall` ranks
on `description + title + tags` ONLY (the `metadata.type` taxonomy does NOT
affect ranking — it is ORGANIZATIONAL-only metadata, so don't over-invest effort
choosing it; a note is found purely by its `description`/`title`/`tags`). Put
symptom vocabulary in `description`; put the answer in the body.

## Recall BEFORE acting (the protocol)

This is commitment 1 of THE PROACTIVE-USE CONTRACT above — recall FIRST, every
time, unprompted. The mechanics:

```bash
# Compose the THREE scope roots (see "Memory scopes" below); search them in ONE call:
LOCAL_MEM="$HOME/.claude/projects/<project-slug>/memory"          # slug = project path, dashed
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null)/.claude/project/memory" # git-tracked, shared (in-repo, namespaced under .claude/ via gitignore exception)
USER_MEM="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory"  # global; the JANITOR's FIXED plugin-DATA dir — hard-coded, NOT ${CLAUDE_PLUGIN_DATA} (that resolves to the RUNNING plugin's dir, which in an arbitrary agent's shell is some other plugin, not the janitor)
ROOTS=(); for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS+=("$d"); done  # ARRAY, not a space-joined string — zsh (macOS default) does NOT word-split an unquoted "$ROOTS", so the string form passes all roots as ONE bogus path → silent 0 results. The "${ROOTS[@]}" array form works in BOTH bash and zsh.
SYMPTOM="the user's words / the error / the symptom"              # NOT the answer's jargon

if command -v memgrep >/dev/null 2>&1; then
  memgrep recall "$SYMPTOM" "${ROOTS[@]}"  # notes ranked best-first as: path — description
else
  grep -rliE "$SYMPTOM" "${ROOTS[@]}"      # fallback: plain grep, degrade-not-break
fi
```

Privacy: the LOCAL root's `user-mem/` subdir is the user's PRIVATE store —
agent-invisible by design. memgrep's memory subcommands exclude it at the ENGINE
level; the plain-`grep` FALLBACK does not, so pipe fallback results through
`grep -v '/user-mem/'` and never open a path that names it.

Read the top 1-3 notes the recall returns; the answer is in their bodies. The
note's SCOPE is its path (under `~/.claude/projects/…` = LOCAL, under the repo
= PROJECT, under the janitor PLUGIN_DATA dir `…/plugins/data/<janitor>/memory` = USER); when two scopes state conflicting
facts, the MORE SPECIFIC scope wins: LOCAL over PROJECT over USER. If recall
returns nothing, the memory doesn't exist yet — consider writing one after you
solve the problem (per the `# Memory` directive).

## Memory scopes (LOCAL / PROJECT / USER)

The wiki is layered like Claude Code's own memory (user CLAUDE.md / project
CLAUDE.md / CLAUDE.local.md). Three roots, one recall surface:

| Scope | Root | Git | Contains |
|---|---|---|---|
| **LOCAL** | `~/.claude/projects/<slug>/memory/` | outside any repo — never pushed | machine-private notes: local paths, hostnames, credentials hints, per-instance info. The harness `# Memory` directive writes here; `user-mem/` (the user's private store) lives inside it |
| **PROJECT** | `<git-root>/.claude/project/memory/` | **tracked + PUSHED** — shared by every dev (in-repo, namespaced under `.claude/`; if `.claude/` is gitignored, add a `!.claude/project/memory/**` exception so the scope is actually pushed) | project knowledge any contributor needs: architecture facts, codebase gotchas, project lessons. Sensitive/local data FORBIDDEN — the janitor's `memory-scope-leak` detector polices this scope |
| **USER** | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` (the janitor's FIXED data dir — resolved by this EXPLICIT hard-coded path, **never** via `${CLAUDE_PLUGIN_DATA}`, because that env var is the *running* plugin's data dir — in an arbitrary agent's shell or the heartbeat it points at some other plugin, not the janitor) | the janitor's plugin DATA dir — **never** a `~/.claude/<custom>/` folder (those can be cleaned up as stray); untouchable by design, survives plugin updates + `--keep-data` uninstall | cross-project knowledge: user preferences, machine-independent lessons |

**Write routing (decide the scope BEFORE authoring):** contains a local path /
username / hostname / secret / machine-specific detail → **LOCAL**. Project
knowledge any dev needs → **PROJECT**. About the user across projects →
**USER**. **UNSURE → LOCAL** (the safe scope; promotion to PROJECT is a
deliberate later act, and the scope-leak detector flags anything sensitive that
lands in PROJECT).

## File & folder inventory — "I found this on disk; what is it, is it safe to touch?"

When a session encounters one of these artifacts in a tree, this table says what
it is, its scope, its git expectation, and whether it is safe to delete. **Do NOT
delete a memory STORE** (the note corpus) — that is real knowledge. Redundant
RULE MIRRORS, by contrast, are safe to gitignore or delete.

| Path / artifact | What it is | Scope | Git status | Safe to delete? |
|---|---|---|---|---|
| `~/.claude/rules/markdown-memory-recall.md` | THIS recall-protocol rule | USER (global) | global config (not a repo) | no — canonical |
| `<project>/.claude/rules/markdown-memory-recall.md` | **redundant byte-identical mirror** of the global rule | project | **untracked** (gitignore it, or delete) | **YES** — the global copy already applies to every project; never commit it (it would impose a personal global rule on every contributor). The janitor no longer creates this (issue #36, user-scope-wins); pre-existing orphans are safe to remove |
| `<project>/.claude/rules/use-safe-delete.md` | same situation for the safe-delete rule | project | should be gitignored | **YES** — same as above |
| `~/.claude/projects/<slug>/memory/*.md` | LOCAL note corpus (machine-private) | LOCAL | outside any repo | **NO** — real knowledge |
| `…/<slug>/memory/MEMORY.md` | Anthropic's native memory BUFFER — the harness writes + auto-loads it; coexists with the wiki; the janitor HARVESTS from it into the wiki, never stubs/trims it | LOCAL | — | no — real memory (the buffer) |
| `…/<slug>/memory/.memgrep/index.db` | the SQLite recall sidecar (`memgrep reindex`) | LOCAL | gitignore if ever inside a repo | yes — regenerated on demand |
| `…/<slug>/memory/memory-reorg-proposed.md` | the `memory-librarian` detector's proposed aggregations | LOCAL | — | yes — regenerated by the detector |
| `…/<slug>/memory/user-mem/` | the user's PRIVATE agent-invisible store | LOCAL | — | **NO** — user data |
| `<git-root>/.claude/project/memory/*.md` | PROJECT note corpus (git-tracked, shared) | PROJECT | **tracked + PUSHED** (`!.claude/project/memory/**` gitignore exception) | **NO** — shared knowledge |
| `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` | USER (cross-project) note store — CANONICAL | USER | never in a repo | **NO** — real knowledge |
| `~/.claude/ai-maestro-janitor-memory/` | the USER-store BACKUP MIRROR (survives a plain `plugin uninstall`; SessionStart syncs + restores it — TRDD-GFT33HT9) | USER | never in a repo | **NO** — real knowledge (a memory store) |
| `/janitor-memory-{write,update,recall,bootstrap}` | the executable protocol (skills) | plugin | — | n/a |
| `memgrep` (`~/.cargo/bin/memgrep`) | the Rust recall engine | tool | — | n/a (protocol degrades to `grep` if absent) |

**The one inconsistency this resolves:** a project-local copy of a *universal global
rule* (`~/.claude/rules/*`) is ALWAYS redundant — Claude Code loads the global
copy for every project. The janitor installs its shipped rules at **USER scope
only** when it is user-installed; it does not drop project-local mirrors. If you
find an orphan one (from an older version), gitignore or delete it — do not commit
it.

## memgrep — the recall engine

`memgrep` is `rg` for markdown (gitignore-aware tree walk, per-line regex,
markdown-structural filters, boolean `--where`, link semijoin, and the memory
subcommands `recall`/`index`/`links`/`fact`). Its own teaching doc is
`scripts/memgrep/SKILL.md` in `ai-maestro-janitor`.

- **Availability:** memgrep is a Rust binary. If `command -v memgrep` is empty,
  install it once: `cargo install --path <…>/ai-maestro-janitor/scripts/memgrep`
  (puts it on `~/.cargo/bin`). Until then, the plain-`grep` fallback above
  works on note frontmatter + bodies — recall degrades, never breaks.
- **recall** `memgrep recall "SYMPTOM" <memdir>` — symptom-ranked notes,
  precision-first (surface matches suppress body-only matches unless nothing
  matched the surface), printed `path — description`, best first.
- **atoms** — a page body is a sequence of first-class **atoms**, each OPENED
  by a leading Obsidian block-property marker `^<id> [keywords: a b c, …]` (the
  marker line sits above the fact; the content below it is the atom's body). An atom
  **owns its own notes/lessons/see-also**, tied to it by INLINE `[^N]` footnote
  references it cites; their DEFINITIONS are pooled at the page bottom under section
  headings, and `recall` GROUPS them by that section — `# Notes` → a `notes:` group,
  `# Lessons Learned` → a `lessons learned:` group, `# See also` → a `see also:` group
  (whose def links out to a related memory). `recall` ALSO
  returns matching atoms — ranked by the `keywords:` surface, interleaved with pages
  by score — and AGGREGATES each atom into its full self-contained record:
  `path#atom-id — <keywords>`, then the atom's content, then its resolved `[^N]`
  footnotes in those section-named groups. So a single FACT is recalled in full, with its
  history + relations, not just as part of its page. Author a durable fact as an atom
  by giving it a `^id [keywords: …]` marker and attaching its history/relations as the
  atom's own `[^N]` references (a see-also is a footnote defined under `# See also`). An
  atom may also carry an optional `desc:` — a ≤64-char snake_case slug, a one-line summary
  memgrep + the handoff display `_`→space beside the atom id (DISPLAY-only, never a recall
  surface; distinct from the PAGE-level `description:` frontmatter — a different key at a
  different level). The harvest stamps
  `claude_mem_ref:`/`claude_mem_hash:` provenance props that **find-claude-mem-ref**
  `memgrep find-claude-mem-ref <buffer.md> <memdir>` queries (full grammar +
  recall-output shape in `scripts/memgrep/SKILL.md` and the wikimem-model atom section).

## Read-the-notes rule — a memory's lessons are part of the memory

When you read ANY memory, you MUST also read **all the notes/lessons attached to
it** — every `[^N]` footnote reference and the `## Notes and lessons learned`
entries they point to. Reading a memory's facts without its lessons is
incomplete: the lessons are *why* the facts are the way they are and *what
errors not to repeat*. Recall the page, read it WHOLE (facts + its linked
lessons), then act.

This is FREE — you never issue a second search for the references. `memgrep`
auto-resolves footnotes on the memory subcommands: `recall` (default-on) and
`find` (default-on) APPEND each returned note's resolved lessons; `fact` does
too with `--with-notes`. One `memgrep recall` yields body **and** every linked
WHY in a single result.

- Render is token-economical by default: an inline reference shows as a **bare
  number `[9]`**, and after the body memgrep appends the list
  `[9] - <lesson WHY text>.` — only the number + the content (no on-disk
  footnote machinery, no per-note metadata).
- `--full-notes` restores each lesson's leading `[…]` metadata prefix; `--no-notes`
  suppresses the lessons (body only). URLs / image links / cross-references in a
  lesson are ALWAYS kept, even in the minimal form — only metadata is strippable.
- A footnote-free note appends nothing, so the read-the-notes rule is a no-op on
  notes that have no lessons yet.

## memgrep recall / find / index — the command surface that shipped

These are the actual flags on the shipped binary (verify with `memgrep recall
--help` / `find --help`). Every one below exists today.

- **recall** — symptom-ranked pages, lessons appended by default:

  ```bash
  memgrep recall "SYMPTOM" <memdir>                 # ranked path — description (+ lessons)
  memgrep recall "SYMPTOM" <memdir> --no-notes      # body only, no lessons
  memgrep recall "SYMPTOM" <memdir> --sort lmd      # order by last-modified date (newest first)
  memgrep recall "SYMPTOM" <memdir> --sort ocd --order asc   # oldest-created first
  memgrep recall "SYMPTOM" <memdir> --since 2026-06-01 --until 2026-06-09   # date window (on lmd)
  memgrep recall "SYMPTOM" <memdir> --since 2026-06-01 --date-field ocd     # window on creation date
  ```

  `--sort score|ocd|lmd` (default `score` = relevance), `--order asc|desc`
  (default `desc`), `--since`/`--until` filter on `--date-field ocd|lmd`
  (default `lmd`), `--top N` (default 10), `--use-index` (force the SQLite
  sidecar; auto-used when fresh, else the live walk — results always correct).

- **find** — note-level `+`/`-`/wildcard/phrase keyword search (NOT line grep).
  The query is ONE whitespace-quoted string: `+TERM` mandatory, `-TERM` exclude,
  bare `TERM` optional (ranks). `*` = wildcard (any run); `"quoted phrase"`
  matches verbatim WITH spaces and may be `+`/`-` prefixed; a `+`/`-` INSIDE a
  token is literal (`pro*-debug*` is ONE term). `--only-notes` searches the
  resolved `[^N]` lessons instead of pages. Composes with every recall flag
  above. A literal `-` query reads the query from STDIN (privacy: keeps a
  private query off the process table — the user-mem search uses this).

  ```bash
  memgrep find "+rotator +keychain -widget" <memdir>          # must have rotator AND keychain, not widget
  memgrep find '+"old approach" retry' <memdir>               # mandatory phrase + optional ranker
  memgrep find "+max_retries" <memdir> --only-notes           # search ONLY the lessons-learned
  ```

- **overview** — the navigation entry point: print the corpus's
  `<project>-overview.md` wiki page (the reader's way INTO the wiki — the command
  the MEMORY.md deprecation stub advertises).

  ```bash
  memgrep overview <memdir>            # print the overview page that links into the deeper pages
  ```

- **lint** — the structural integrity gate: page-shape / frontmatter / footnote /
  link violations, exit≠0 on any violation (what the librarian's shape pass and
  the repair chore check against).

  ```bash
  memgrep lint <memdir>                # structural integrity gate (exit != 0 on any violation)
  ```

- **find-claude-mem-ref** — the harvest provenance query: list every wiki ATOM
  whose `claude_mem_ref:` block-prop references a Claude-memory buffer file,
  printed `path#atom-id\t<source-hash>`. The harvest diffs the buffer file's
  current hash against the stored ones to skip already-harvested, unchanged
  memories.

  ```bash
  memgrep find-claude-mem-ref feedback_oauth.md <memdir>      # atoms harvested from that buffer note
  ```

- **index / reindex** (aliases) — build the persistent `.memgrep/index.db`
  SQLite sidecar (gitignored, git-incremental — re-parses only changed files).
  `memgrep index --markdown` is the legacy `memory-index.md` doc-generator (the
  per-note title/summary/tags/TOC/backlinks index); `--full` rebuilds the
  SQLite index from scratch.

  ```bash
  memgrep reindex <memdir>             # build/refresh the SQLite query index
  memgrep index --markdown <memdir>    # the human-readable memory-index.md doc-generator
  ```

## The note format (recall-relevant fields)

The `# Memory` directive is the authoring source-of-truth. On disk, notes are:

```yaml
---
name: <kebab-slug>                 # == filename stem
description: "<symptom surface — the load-bearing recall field>"
ocd: <YYYY-MM-DD>                  # Original Creation Date — set once on create
lmd: <YYYY-MM-DD>                  # Last Modified Date — bump on every edit
metadata:
  node_type: memory
  type: user | feedback | project | reference
  originSessionId: <uuid>
publish-globally: true | false   # PROJECT pages only — see below
---
<body: the one fact; for feedback/project add **Why:** and **How to apply:**>

## Notes and lessons learned
```

**`publish-globally:` is mandatory on every PROJECT-scope page** (absent it is a lint finding
memgrep normalizes it in, always, around every write). `true` symlinks the page into the USER memory root so every other
project's agent can find it — no copy, so no drift; the symlink is the only mechanism. Default
`false`: PROJECT memory is git-tracked and pushed while USER scope is machine-private, so
publishing a page beyond its own project must be opt-in, never assumed. Set it `true` only for
pages describing this project's public surface (features, APIs) that other projects need to
know about — not its internals.

That normalization timing (before AND after every write, never a separate cleanup pass) is a
correctness requirement: a page missing the field is malformed, and a write onto a malformed
structure corrupts it. It is idempotent — an already-normal page is not rewritten (the chore
schedulers stat these files, so a no-op must not touch the mtime).

Two invariants, both reconciled by that same always-on normalization (`memgrep lint` still
REPORTS them so a human can see the state, but lint is not what performs the repair):

| state | meaning | fix |
|---|---|---|
| `true`, no symlink | published in name only | CREATE the symlink |
| symlink exists, no field | the symlink is the intent | ADD `publish-globally: true` |
| `false` + a symlink | a contradiction | **reported, never auto-resolved** — dropping the symlink and flipping the flag are both defensible, so it is a human's call |

**Maintain the page at its PROJECT home, never through the symlink alias.** The symlink escapes
the USER scope root, so that scope's transaction guard refuses to write it (correctly), and the
chore candidate lister skips it for the same reason (janitor#249). One element, one page, one
place it is edited.

The `## Notes and lessons learned` section is MANDATORY on every page, even
when empty — it is the standing landing zone for a `[^N]` correction lesson and
keeps the corpus shape uniform (the janitor's `memory-librarian` page-shape pass
flags a note that omits it, or that omits `ocd`/`lmd`).

**The WIKI index is memgrep's, and ONLY memgrep's.** Recall over the curated WIKI runs
entirely on the Rust SQLite index `.memgrep/index.db` (auto-built, git-incremental,
**agent-invisible**, **no size limit**), or a live note-scan when no index exists — either
way the wiki's recall never reads a human-maintained index. The janitor **never hand-maintains
a wiki index** (agents who hand-trimmed an ever-growing index lost pointers and corrupted the
corpus — that is why the wiki index lives wholly in memgrep). `memgrep index --markdown`'s
`memory-index.md` is an optional throwaway doc, never a load-bearing index.

**MEMORY.md is the BUFFER, not the wiki index — the two COEXIST, and the harvest bridges them.**
`MEMORY.md` belongs to Anthropic's **native** memory system: the harness `# Memory` directive
writes it and auto-loads it into every session, and current Claude Code keeps growing it. So it
is an **unorganized memory BUFFER that grows on its own** — a first-class, coexisting system,
NOT a stub to retire:

- The janitor **never stubs it, never trims it, never maintains it as an index.** The harness
  owns its content; the janitor only READS it as a harvest source. (CC 2.1.186's native
  reminder to "compact `MEMORY.md` when nearing the size limit" targets this harness-owned
  buffer — expected harness behavior, ORTHOGONAL to the janitor's memgrep-indexed wiki; the
  janitor neither triggers nor suppresses it.)
- A **harvest cron** (`/janitor-memory-harvest`; the `[janitor-memory-harvest]` heartbeat
  marker) continuously finds **newly-created** buffer memories and **MIRRORS** them into the
  curated WIKI in metadata-rich form (the editorial model below) — additively, **incrementally**
  (a per-scope watermark, so the same memory is never re-mirrored), and **non-destructively**
  (the buffer is left 100% intact).

The two systems cooperate by division of labor: the **buffer** captures fast + raw (Anthropic
loads it natively each session); the **wiki** is the curated, linked, `ocd`/`lmd`-dated,
git-versioned long-term memory (memgrep-recalled); **harvest** keeps the wiki in sync with new
buffer memories. At recall time BOTH are covered — the harness auto-loads `MEMORY.md` (the
buffer) and `memgrep recall` searches the wiki. So the harness `# Memory` directive's "maintain
a `MEMORY.md` pointer list" is **honored** (it IS the buffer); the wiki is the separate,
memgrep-recalled curated layer the harvest keeps current.

**The navigation entry point — `<project>-overview.md`.** Each PROJECT-scope corpus
carries ONE `<project>-overview.md` wiki page: a concise **Wikipedia-style overview**
of the whole project — a container of the overall-project memories with links OUT to
the deeper, more specific wikimem pages. It is **not an index** (no exhaustive pointer
list) and stays small; it is the reader's way INTO the wiki. `memgrep overview <memdir>`
prints it. Bootstrap seeds it; agents grow
it as the project's top-level story and link from it down to the hubs + key component
pages — never paste those pages' detail into it.

## The wiki layer — pages are wiki nodes, not loose notes (wikimem)

The corpus is a navigable WIKI, not a pile (TRDD-bc16d602). On top of the note
format above, every page declares its place in the pyramid and its context:

- **`metadata.tier: hub | aspect | component`** — a `hub` is one functionality's
  overview (frontend, backend, db, …) carrying `metadata.globs:` (the file
  patterns it owns — so "I'm editing this FILE" maps to its hub); an `aspect` is
  a GENERAL rule shared by many elements (EXPAND — it RADIATES an `## Applies to`
  ray-list down to every element it governs); a `component` is ONE element's page
  (REDUCE — it RECEIVES, carrying `## Governed by` up-links only, and never
  re-copies a governing rule). One element = one page, always.
- **THE LINK LAW: every link is bidirectional.** If A links to B, B links to A —
  `Applies to` ↔ `Governed by` across tiers, `See also` ↔ `See also` laterally.
  Wire both ends in the same edit; the janitor librarian flags one-sided links.
- **Updates never delete:** a superseded memory is demoted to a dated `[^N]`
  lesson with its WHY (see the lessons conventions below), never erased.
- **Navigate progressively:** recall surfaces the TIP (the hub / the best page);
  follow only the links the task needs; read a shared general page ONCE and
  reuse it across every component that points at it.

The executable protocol is the three janitor skills — `/janitor-memory-write`
(MEMORIZE), `/janitor-memory-update` (UPDATE), `/janitor-memory-recall` (RECALL)
— and the full data model lives in the write skill's
`references/wikimem-model.md`. Existing flat notes stay valid (no `tier` ⇒
`component`); the wiki emerges incrementally as pages are touched.

## THE LESSON FORM — the full field grammar (moved off the rule floor, 2026-07-26)

The shipped rule carries only the one-line shape and the recall law. The complete grammar is
here, because it is reference material and the rule floor is re-written into cache by every
cold subagent on the machine.

```text
[^N]: [id:ATOM-xxxx-xxxx, status:valid|superseded, superseded-by:ATOM-xxxx-xxxx, keywords:"<key_phrase> …", ocd:<date>, lmd:<date>] DO NOT <X>, BECAUSE <why>. DO <Y> instead.
```

The bracketed metadata block is the lesson's **ADDRESS**. `id`, `status`, `keywords`, `ocd`,
`lmd` are REQUIRED; `superseded-by` is required once superseded.

- **`keywords:` is the RECALL SURFACE** — the phrases a future session SEARCHES with (the
  symptom), usually NOT the words the lesson's prose uses. **No keywords ⇒ no recall ⇒ the
  memory does not exist.** A **comma** splits FIELDS, **quotes** delimit the keywords VALUE, a
  **space** splits the KEY-PHRASES inside it — so each is `underscore_joined`, never shredded.
  A phrase written `a phrase, another phrase` loses everything after the first comma, silently:
  the parser drops the segment and the page still looks correct. **Two distinct syntaxes exist:**
  the write VERB's `--keywords` flag is COMMA-separated (spaces inside a phrase are fine — it
  underscore-joins each phrase); the STORED props block on disk is SPACE-separated instead — a
  hand-written comma there silently drops everything after it, one more reason never to
  hand-author a props block directly.
- **`status:`** `valid` (holds) | `superseded` (history — NEVER apply it; follow
  `superseded-by`). **`id:`** is stable and unique corpus-wide; `[^N]` is page-local and
  renumbers, so only `id` is a durable reference — and corpus-uniqueness is what makes a bare
  id a sufficient retrieval key for the second hop.
- **Prose:** ONE lesson = ONE mistake · ≤3 lines / ~40 words · all three parts. `DO NOT` names
  the act about to be repeated; `BECAUSE` carries the WHY, without which the lesson cannot stop
  the repeat; `DO … instead` is the exit. Chronology and evidence belong in the page BODY or a
  TRDD, never in the lesson.

## Lessons-learned conventions (footnotes + per-element dates)

Memory pages grow a bottom `## Notes and lessons learned` section. The format is
**standard markdown footnotes** — nothing new to memorize, and memgrep's
markdown parser already understands it:

- In the body, reference a lesson as `[^N]`; under `## Notes and lessons learned`
  define it as `[^N]: <the WHY>`. memgrep resolves ref ↔ def WITHIN the same note
  by default and inlines the lesson when it returns the note.
- A lesson is a **first-class memory element**, not a second-class footnote — it
  carries the same metadata schema a fact does, including two intrinsic dates:
  - **OCD — Original Creation Date** (when the lesson/fact was first written),
  - **LMD — Last Modified Date** (when its content last changed).
  These survive when the background librarian moves a memory between pages, so a
  page's filesystem mtime is NOT a reliable age for any element it holds — the
  per-element OCD/LMD is. memgrep reads OCD from frontmatter `ocd` (alias
  `created`) and LMD from `lmd` (alias `updated`, falling back to the file
  mtime). On a lesson, the dates live in its leading `[ocd:… lmd:…]` metadata
  prefix — stripped from the default render, restored by `--full-notes`.

```markdown
<clean, current FACTS about this topic>. The widget retries 3× then fails.[^3]
... tangential topics LINK, never duplicate: see [[other-topic]] ...

## Notes and lessons learned
[^3]: [ocd:2026-06-09 lmd:2026-06-09] earlier this said "retries 5×"; wrong, the
  cap is 3 — the config key was misread as `max_attempts` when it is
  `max_retries`. Lesson: verify the constant against the source, not the
  variable name.
```

Authoring the lessons (clean-the-fact-in-place + demote-the-error correction
protocol) is the WRITE side — see the `janitor-memory-write` skill. Searching
across lessons (`find --only-notes`, `--since`/`--until` over OCD/LMD) is the
recall side above.

## Evaluating / improving the system: the dual-test method

When designing or testing memory recall, run BOTH tests and judge BOTH
dimensions in each:

- **Test A — cold-recall:** simulate a session with NO prior recollection;
  build the query ONLY from the symptom/user's words, never the answer's
  jargon. Tests "is the right note findable from the symptom?".
- **Test B — write-then-recall:** author a note, then retrieve it. Tests the
  round-trip.

In each, evaluate (1) YOUR search strategy AND (2) the system's retrieval, and
improve both. **Contamination warning:** after you WRITE a note you are biased
toward its wording — your own cold-recall is no longer cold. Do cold-recall
from a clean framing, or have the symptom come from the user verbatim.

## The memory system's parts (how they connect)

| Part | Surface | Role |
|---|---|---|
| Authoring | `# Memory` harness directive + `janitor-memory-write` skill | write one fact per note; symptom-indexed `description`; the correction protocol (clean fact in place, demote error to a `[^N]` lesson) |
| Recall | THIS rule + `janitor-memory-recall` skill + `memgrep recall`/`find` | symptom-ranked recall, lessons auto-appended |
| Bootstrap | `janitor-memory-bootstrap` skill | stands up a project's wikimem once: creates the PROJECT-scope dir (+ gitignore exception), seeds an architecture-hub page, points the agent at the proactive contract; MEMORY.md stays the harness-owned buffer (bootstrap never stubs it) |
| Organization (SURFACE) | `memory-librarian` detector (janitor heartbeat) | SURFACES aggregation/conflict candidates to `memory-reorg-proposed.md`; never edits content |
| Organization (EXECUTE) | the janitor's **`janitor-memory-subconscious-agent`** (async, opus, its own context) | runs the COMPLEX editorial passes — consolidate/merge, split (incl. fail-safe seam synthesis for seamless pages), conflict/harmonize, repair, harvest — through the crash-safe transaction core; dispatched in the BACKGROUND by the heartbeat's `[janitor-memory-*]` markers |
| Tool | `memgrep` (`scripts/memgrep/SKILL.md`) | the engine all three lean on |
| Private user store | `/janitor-memory-user-{add,search,share}` (legacy `/to-user-mem`, `/search-user-mem`, `/share-user-mem` still work, deprecated) | the USER's own agent-invisible memories — a SEPARATE corpus, not the agent notes; search routes through `memgrep find` |

### Division of labor — leave editorial work to the janitor's subconscious agent

There are exactly **two** roles, and a main agent stays in the first:

- **A MAIN agent (you, in any session) does ONLY SIMPLE ops, INLINE:** recall
  (`/janitor-memory-recall`), create a page / add ONE atom (`/janitor-memory-write`),
  update ONE fact via the correction protocol (`/janitor-memory-update`). That is the
  whole surface. You **never** run a complex editorial pass yourself — not split, not
  merge/consolidate, not conflict/harmonize, not dedupe, not repair, not harvest, not
  any multi-page reorganization. They are transaction-gated, easy to get wrong, and
  would burn your context on work that is not yours.
- **The janitor's `janitor-memory-subconscious-agent` does ALL complex editorial work,
  ASYNC, in its own context.** The heartbeat dispatches it in the background when a pass
  is due (the `[janitor-memory-*]` markers). If you NOTICE editorial work is needed (a
  page is too big, two pages overlap, a contradiction, a malformed page), just **note it
  and move on** — the librarian surfaces it and the subconscious agent executes it. Do
  NOT do it yourself, and do NOT block on it.

So: **janitor** = surfaces (librarian) + executes the reorg (subconscious agent, async);
**main agent** = creates/corrects atomic content only. This is why a seamless page that
"can't be split" is not your problem to solve inline — the subconscious agent splits it
fail-safe on its own schedule.

## Why this rule exists

The memory system had a fully-built recall engine (memgrep, 42 tests), a live
note corpus, and the harness authoring directive — but no durable rule tying
them together. A fresh session was blind to the recall half. This rule is that
missing piece: it makes "recall before acting" and "index by symptom" a
standing discipline, with a tool command that degrades to grep when the binary
isn't present.

## STAY ON TOPIC — the full routing rule (moved out of the rule, 2026-07-13)

The rule states the law; this is the rationale and the routing table it compresses.

**One page = one subject.** Someone who recalls `claude-client-authentication` is looking for
facts about *claude client authentication* — not for your lessons about how to debug. A
general, transferable lesson ("verify before you 'fix'", "falsify each layer separately",
"absence of evidence is not evidence") is **OFF-TOPIC POLLUTION** inside a case page, and it
is doubly wrong because it *scatters* the methodology across every page that happened to teach
it, so the one page that should own it owns nothing.

**The routing question, asked of every lesson BEFORE you write it:**

> *Is this true only of THIS subject, or would it still be true of a completely different bug
> in a completely different system?*

| The lesson is… | It belongs in… |
|---|---|
| specific to the subject (this API's quirk, this daemon's flag, this keychain's ACL behavior) | **the subject's own page** |
| a transferable way of WORKING (how to diagnose, verify, falsify, decide, avoid a reasoning trap) | **the methodology page that owns it** — e.g. `debugging-methodology` |

**Before creating a new methodology page, SURVEY what already exists** (`memgrep recall
"methodology"` / `"debugging"` across the scopes) and add to the owner rather than minting a
fifth near-synonym. Methodology is nearly always **USER** scope: a way of working is true
across all projects, whereas the case facts that taught it usually are not.

**When you MOVE a lesson out of a case page, leave the case page a link, not a hole** — the
link law still applies (`[[debugging-methodology]]` ↔ `See also`), and no knowledge is
deleted, only relocated to its rightful owner.

## AUTHORING — route every write through a memgrep verb, then validate (full)

A HAND-WRITTEN atom is where malformed memories come from — an unquoted `desc:` that breaks
grep, a `[^N]` lesson with metadata but no body that `find --only-notes` can't see, an atom too
long to be one fact. So **do not hand-author wikimem markdown**: the memgrep write verbs
synthesise valid syntax by construction.

- new page → `memgrep new-mem-topic --tier hub|aspect|component --name N --description "…" --type … [--scope local|private-project|public-project|user]` (was: `new-page`; there is NO `--path` — the file lands at `<scope root>/<name>.md`)
- new fact → `memgrep new-mem-atom --page P --keywords "symptom phrases" --desc "quoted ≤200-char prose"` (body on stdin; was: `add-atom`)
- new lesson → `memgrep update-mem-atom --page P --lesson --atom ID --keywords "…"` (DO-NOT/BECAUSE/DO on stdin; was: `add-lesson`)
- move an atom → `memgrep migrate-mem-atom <atom> --from A --to B` (NEVER hand-move — it drops lessons and collides footnote numbers; was: `migrate`)
- delete a page/atom → `memgrep delete-mem-topic --page P` / `memgrep delete-mem-atom --page P --atom ID` (moves to `.trashcan/`, never unlinks — RULE 0)
- merge duplicates → `memgrep merge-mem-topic --from A --into B` / `memgrep merge-mem-atom --page P --atom ID --into ID2`
- split an over-long page/atom → `memgrep split-mem-topic --page P --atoms … --into NEW --name … --description …` / `memgrep split-mem-atom --page P --atom ID --at … --desc …`
- link two pages/atoms → `memgrep reference-mem-topic --page P --to Q` / `memgrep reference-mem-atom --page P --atom ID --to Q` (wires the bidirectional `[[wikilink]]`)

### The wiki is COLLABORATIVE — authorship confers NO ownership

**Every wikimem page is a Wikipedia page, not a personal notebook.** USER- and PROJECT-scope
pages are the shared work of every agent on this machine, and **you are expected to write and
update them even when another agent wrote them.** If a page is wrong, incomplete, or
contradicted by something you just measured — UPDATE IT. Never mint a near-synonym page, never
park a hedged "in my case…" beside the wrong fact, never settle for mentioning it in chat.
There is no "their page" and no permission to seek; `contributors:` records who has helped, it
does not gate who may.

**Correcting is SAFE BY CONSTRUCTION; hesitating is the risky move.** The write verbs version
rather than replace (see the supersession protocol immediately below), so **no memory is ever
lost — only superseded**: sometimes with a lesson explaining the error, sometimes as a plain
previous revision. Overwriting another agent's work is therefore not a failure this rule has to
guard against — it cannot happen. The failure it DOES guard against is **a known-false fact left
standing because whoever measured the truth assumed the page belonged to someone else.** What
protects a page is `memgrep validate` + `lint`, never authorship.

**Correcting a wrong fact is a SUPERSESSION, never a delete or an overwrite.** Run
`memgrep update-mem-atom --lesson --supersedes --atom <id>` FIRST (was: `add-lesson --supersedes`) —
it embeds the atom's current body verbatim as `SUPERSEDED BODY: <old>` (the never-delete rule,
enforced) and records the WHY as a dated lesson — THEN clean the atom's body to the new truth,
keeping the SAME id (a `-v2` duplicate is the anti-pattern). An atom's dated superseded-lessons
ARE its changelog and TRAVEL with it on a `migrate-mem-atom`. Only a pure typo / formatting slip
is edited in place.

**After EVERY edit, prove it:** `memgrep validate <page> && memgrep lint <page>`. `lint` is
deterministic + FP-free — it catches an unquoted desc, a body-less lesson, an oversized atom, a
supersession missing its `SUPERSEDED BODY:`, a dangling footnote, and a one-sided `[[link]]`. A
non-zero exit is a defect to fix NOW, before moving on.

### Concurrent editing (TRDD-7YHT3FNK)

The write verbs are scope-LOCKED and use `--base-sha256` compare-and-swap: a verb refuses to
land if the page changed since you last read it, rather than silently clobbering a concurrent
agent's edit. `memgrep update-mem-topic` (was: `edit`) itself is an exact-unique-match replace —
it fails loudly on a stale or ambiguous match instead of guessing. Edit wikimem pages ONLY
through the memgrep verbs or the Edit tool — never raw shell (`sed`/`echo >>`/etc.), which
bypasses both the lock and the syntax guarantees the verbs exist to provide. On a "changed since
enqueued" refusal: re-read the page, recompute your edit against the new content, and retry —
never force past the refusal.

## THE RECALL LAW — illustration + the two corollaries (moved out of the rule, 2026-07-26)

The rule states the law and both corollaries normatively. The worked example and the incidents
that produced the corollaries live here, because the rule ships in every session's context floor
and that floor is capped.

### Indexing by the question — the worked example

- WRONG: "OAuth creds live in the macOS keychain services." (Findable only if you already know
  the answer is "keychain".)
- RIGHT: "rotator failed, had to log in manually — where are the creds / why did the swap fail"
  — with the keychain fact in the BODY.

### Corollary 1 — appending to a page must extend its `description:`

`memgrep recall` ranks on `description + title + tags` and NEVER the body. So a fact or `[^N]`
lesson appended under a description that does not mention its symptom is **unfindable** — you
wrote it, and recall still misses it.

**Incident, 2026-07-26.** Correct lessons about an OAuth *rotation failure* were appended to the
page `claude-subscription-usage-endpoint`, whose description covered only "how do I read my 5h/7d
usage %". A symptom query for the rotation failure ranked a DIFFERENT page first; the new lessons
did not surface at all. Adding the rotation symptoms ("account rotation stopped finding a safe
target", "every account looks maxed at the same time") to `description:` fixed it immediately.

The description must describe the page **as it is now**, not as it was when created. A page that
grows new subjects and keeps its birth description silently loses them.

### Corollary 2 — a lesson that constrains CODE ships with an executable check

A note explains a guard; it is not the guard.

**Incident, same day, same corpus.** That same page already carried the lesson "DO NOT call this
endpoint with a default or generic `User-Agent` — it requires `claude-code/*` and drops anything
else into an aggressive rate-limit bucket." Meanwhile `ai-maestro-janitor`'s own rotator had been
sending `User-Agent: claude-account-rotator` to that exact endpoint on a 60 s beat for weeks. The
lesson was correct, well-indexed, and recalled correctly — and changed nothing, because no code
path consulted it. The bug was found by auditing the code, not by reading the memory.

So when a lesson says "never do X in code", land the thing that FAILS when X happens — a test, a
lint rule, a publish gate — in the SAME change that records the lesson. The lesson then explains
*why* the check exists, which is the job prose is actually good at.
