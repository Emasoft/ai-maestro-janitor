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
| `…/<slug>/memory/MEMORY.md` | DEPRECATED stub — index retired to memgrep; loaded but tiny; never maintained or hand-trimmed | LOCAL | — | no |
| `…/<slug>/memory/.memgrep/index.db` | the SQLite recall sidecar (`memgrep reindex`) | LOCAL | gitignore if ever inside a repo | yes — regenerated on demand |
| `…/<slug>/memory/memory-reorg-proposed.md` | the `memory-librarian` detector's proposed aggregations | LOCAL | — | yes — regenerated by the detector |
| `…/<slug>/memory/user-mem/` | the user's PRIVATE agent-invisible store | LOCAL | — | **NO** — user data |
| `<git-root>/.claude/project/memory/*.md` | PROJECT note corpus (git-tracked, shared) | PROJECT | **tracked + PUSHED** (`!.claude/project/memory/**` gitignore exception) | **NO** — shared knowledge |
| `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` | USER (cross-project) note store | USER | never in a repo | **NO** — real knowledge |
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
  above.

  ```bash
  memgrep find "+rotator +keychain -widget" <memdir>          # must have rotator AND keychain, not widget
  memgrep find '+"old approach" retry' <memdir>               # mandatory phrase + optional ranker
  memgrep find "+max_retries" <memdir> --only-notes           # search ONLY the lessons-learned
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
---
<body: the one fact; for feedback/project add **Why:** and **How to apply:**>

## Notes and lessons learned
```

The `## Notes and lessons learned` section is MANDATORY on every page, even
when empty — it is the standing landing zone for a `[^N]` correction lesson and
keeps the corpus shape uniform (the janitor's `memory-librarian` page-shape pass
flags a note that omits it, or that omits `ocd`/`lmd`).

**The index is memgrep's, and ONLY memgrep's.** Recall runs entirely on the Rust
SQLite index `.memgrep/index.db` (auto-built, git-incremental, **agent-invisible**,
**no size limit**), or a live note-scan when no index exists — either way recall
never reads a human index. So there is **no human-maintained index** any more.
`MEMORY.md` is now a tiny **DEPRECATION STUB**; `memgrep index --markdown`'s
`memory-index.md` is an optional throwaway doc. Do **NOT** append note pointers to
`MEMORY.md`, do **NOT** load it as an index, and **NEVER hand-trim it** — agents who
trimmed the old ever-growing index lost pointers and corrupted the corpus, which is
exactly why the index moved entirely into memgrep. The canonical stub content
(seeded by bootstrap, kept current by the harvest chore):

```text
# MEMORY — index retired (managed by memgrep)
⚠ DEPRECATED stub — do NOT add pointers here, load this as an index, or trim it.
The memory index is 100% managed by memgrep (agent-invisible, unlimited SQLite
index at .memgrep/index.db). To use project memory:
- ENTRY POINT — navigate the project:  memgrep overview <memdir>
  (prints <project>-overview.md: the overview that links out to the deeper pages)
- RECALL by symptom:  memgrep recall "<symptom>" <memdir>   (or: memgrep find …)
Protocol: ~/.claude/rules/markdown-memory-recall.md
```

The harness `# Memory` directive still says to maintain a `MEMORY.md` pointer
list; that is **superseded for this memory system** — the stub is the whole file,
the harness loads only that tiny notice, and recall is memgrep-only.

**The navigation entry point — `<project>-overview.md`.** Each PROJECT-scope corpus
carries ONE `<project>-overview.md` wiki page: a concise **Wikipedia-style overview**
of the whole project — a container of the overall-project memories with links OUT to
the deeper, more specific wikimem pages. It is **not an index** (no exhaustive pointer
list) and stays small; it is the reader's way INTO the wiki. `memgrep overview <memdir>`
prints it (the command the MEMORY.md stub advertises). Bootstrap seeds it; agents grow
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
| Bootstrap | `janitor-memory-bootstrap` skill | stands up a project's wikimem once: creates the PROJECT-scope dir (+ gitignore exception), seeds an architecture-hub page + the MEMORY.md deprecation stub, points the agent at the proactive contract |
| Organization | `memory-librarian` detector (janitor heartbeat) | SURFACES aggregation/conflict candidates to `memory-reorg-proposed.md`; never edits content (a session does the conscious reorg) |
| Tool | `memgrep` (`scripts/memgrep/SKILL.md`) | the engine all three lean on |
| Private user store | `/janitor-memory-user-{add,search,share}` (legacy `/to-user-mem`, `/search-user-mem`, `/share-user-mem` still work, deprecated) | the USER's own agent-invisible memories — a SEPARATE corpus, not the agent notes; search routes through `memgrep find` |

Separation of powers: the **janitor** reorganizes structure and *surfaces*
contradictions but never edits a fact; an **agent** creates and corrects content
but never reorganizes. (The background auto-merge — the librarian consolidating
clusters into one wiki page — is DESIGNED but not yet shipped; today the detector
only proposes, an agent applies.)

## Why this rule exists

The memory system had a fully-built recall engine (memgrep, 42 tests), a live
note corpus, and the harness authoring directive — but no durable rule tying
them together. A fresh session was blind to the recall half. This rule is that
missing piece: it makes "recall before acting" and "index by symptom" a
standing discipline, with a tool command that degrades to grep when the binary
isn't present.
