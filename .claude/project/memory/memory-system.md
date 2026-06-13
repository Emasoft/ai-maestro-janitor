---
name: memory-system
description: "how does the wiki-memory system work / where do memories live / how to recall before acting / what is memgrep / how do I install the memory system in a new project / why did my PROJECT memory page get flagged for a leak / LOCAL vs PROJECT vs USER scope precedence"
ocd: 2026-06-13
lmd: 2026-06-13
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: janitor
  originSessionId: memory-audit-draft
---

# The wiki-memory system (janitor functionality)

The janitor **owns the reference implementation** of the markdown wiki-memory
system — the engine (`memgrep`), the three authoring/recall/update skills, the
two heartbeat detectors that police it, and the recall-discipline rule. Other
plugins/projects adopt it; this page is the component page for that functionality
as the janitor ships it.

**Why:** sessions are stateless across context windows; a durable, symptom-indexed
markdown corpus + a recall engine lets a future session find "have we hit this
before?" instead of re-deriving (badly) what was already learned. The whole
discipline is "index by the QUESTION, not the answer" — a memory is found from
the SYMPTOM (the user's words / the error text), and the note's body holds the
fix.

**How to apply:** run RECALL before debugging a recurring problem, before a design
decision, before editing a file in an unloaded area, and before MEMORIZE (so you
update the right page instead of duplicating). Then MEMORIZE only what is
NON-OBVIOUS and reusable; UPDATE non-destructively when a fact changes.

## The 3-scope model (LOCAL / PROJECT / USER)

The corpus is layered exactly like Claude Code's own memory (the user CLAUDE.md,
the project CLAUDE.md, and the git-ignored project-local CLAUDE override file).
Three roots, ONE recall surface — recall
searches all three that exist in a single call. Paths are generic on purpose; the
machine-specific expansion (the actual `<project-slug>`, `<repo-root>`, the
account/host details a LOCAL note may hold) **lives in LOCAL scope** and is never
written here.

| Scope | Root | Git status | Holds |
|---|---|---|---|
| **LOCAL** | `$HOME/.claude/projects/<project-slug>/memory/` (`<project-slug>` = the project's absolute path with every separator dashed) | OUTSIDE any repo — **never pushed** | machine-private notes: local paths, usernames, hostnames, credential hints, per-instance facts. The harness `# Memory` directive writes here; the user's PRIVATE store `user-mem/` is a sibling inside it |
| **PROJECT** | `<repo-root>/memory/` (`<repo-root>` = `git rev-parse --show-toplevel`) | **git-tracked + PUSHED** — shared by every contributor | project knowledge any dev needs: architecture facts, codebase gotchas, project lessons. **Sensitive/local data FORBIDDEN** — the `memory-scope-leak` detector polices this scope |
| **USER** | `$HOME/.claude/memory/` | never in any repo | cross-project knowledge: user preferences, machine-independent lessons |

**Precedence — LOCAL > PROJECT > USER.** When two scopes state conflicting facts,
the MORE SPECIFIC scope wins (LOCAL beats PROJECT beats USER). A note's scope IS
its path: under `$HOME/.claude/projects/…` = LOCAL, under the repo = PROJECT,
under `$HOME/.claude/memory` = USER.

**Write routing (decide the scope BEFORE authoring):** contains a local path /
username / hostname / secret / machine-specific detail → **LOCAL**. Project
knowledge any dev needs → **PROJECT**. About the user across projects → **USER**.
**UNSURE → LOCAL** — the safe scope; promotion to PROJECT is a deliberate later
act, and the scope-leak detector flags anything sensitive that lands in PROJECT.

Compose the roots once (the same block all three skills use):

```bash
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"          # machine-private
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"  # git-tracked
USER_MEM="$HOME/.claude/memory"                                            # global
ROOTS=""; for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS="$ROOTS $d"; done
```

## The note format (recall-relevant fields)

On disk every note is a markdown file whose stem == frontmatter `name:`:

```yaml
---
name: <kebab-slug>                 # == filename stem
description: "<symptom surface — the load-bearing recall field, indexed by the QUESTION>"
ocd: <YYYY-MM-DD>                  # Original Creation Date — set once on create
lmd: <YYYY-MM-DD>                  # Last Modified Date — bump on every edit
metadata:
  node_type: memory
  type: user | feedback | project | reference
  tier: hub | aspect | component   # wikimem tier (absent ⇒ component)
  functionality: <hub-slug>        # which functionality this lives under
  globs: ["<owned file patterns>"] # REQUIRED on hubs; omit on most leaves
---
<body: the one fact; for feedback/project add **Why:** and **How to apply:**>

## Notes and lessons learned
```

The `description:` is the load-bearing recall surface — `memgrep recall` ranks on
`description + title + tags` ONLY (the `metadata.type` taxonomy does NOT affect
ranking). Put **symptom vocabulary** in `description`, put the **answer** in the
body (two-hop recall: symptom query → note → body answer). The
`## Notes and lessons learned` section is MANDATORY on every page even when empty
— the standing landing zone for `[^N]` correction lessons; the page-shape pass
flags a note that omits it, or that omits `ocd`/`lmd`.

`MEMORY.md` is the human index (`- [Title](file.md) — hook`, one line per note),
loaded each session and the canonical index. `memgrep index --markdown` can
generate a richer `memory-index.md` (per-note title/summary/tags/TOC/backlinks)
— an OPTIONAL generated artifact. Recall needs neither — it scans notes directly,
transparently using the SQLite `.memgrep/index.db` when fresh.

## The memgrep engine

`memgrep` is `grep`/`rg` for markdown: gitignore-aware tree walk, per-line regex,
markdown-structural filters (`--heading`, `--level`, `--code-lang`,
`--node table,…`, inline `--bold`/`--code-span`/…), boolean `--where 'EXPR'`
(`fm.KEY "v"`, `path/name "glob"`, `links-to`/`linked-from` link-semijoin), plus
the memory subcommands. **All grep muscle memory transfers** (`-i -w -n -l -c -e
PATTERN [PATH…]`, `--json`, `--hidden`); numeric/version ranges use pip syntax
(`>=1.2,<3.5`), wildcards are `*`. Its own teaching doc is
`<repo-root>/scripts/memgrep/SKILL.md`.

Multi-root is first-class: every subcommand accepts several `<memdir>` roots, so
one call searches LOCAL + PROJECT + USER together (`$ROOTS`).

| Subcommand | What it does |
|---|---|
| `recall "SYMPTOM" <memdir…>` | rank notes by symptom match → `path — description`, best first; each note's `[^N]` lessons appended (default-on). Query the QUESTION's words |
| `find "<query>" <memdir…>` | note-level `+`/`-`/wildcard/phrase keyword search; `--only-notes` searches the lessons instead of pages |
| `index` / `reindex <memdir>` | build/refresh the persistent SQLite query index `.memgrep/index.db` (gitignored, git-incremental); `--full` rebuilds from scratch |
| `index --markdown <memdir>` | legacy doc-generator → `memory-index.md` (add `--write` to write the file) |
| `links --broken\|--orphans\|--to N\|--from N` | link graph / semijoin over the corpus |
| `fact [--cat/--comp/--session/--kind/--since/--until]` | query one-fact-per-line memory lines; `--with-notes` (OFF by default) appends lessons |

**`recall`** — symptom-ranked, precision-first (surface matches suppress
body-only matches unless nothing matched the surface). Shared flags on
`recall`/`find`: `--with-notes` (default ON — resolve+append `[^N]` lessons) ·
`--no-notes` (body only) · `--full-notes` (keep each lesson's leading
`[ocd:… lmd:…]` prefix; URLs/images always kept) · `--sort score|ocd|lmd`
(default `score`=relevance) · `--order asc|desc` · `--since/--until` over
`--date-field ocd|lmd` (default `lmd`) · `--top N` (default 10) · `--use-index`
(force the SQLite sidecar; auto-used when fresh — results always correct).

**`find` DSL** — ONE whitespace-quoted string: `+TERM` mandatory, `-TERM`
exclude, bare `TERM` optional (ranks); `*` = wildcard; `"quoted phrase"` matches
verbatim WITH spaces and can be `+`/`-` prefixed; a `+`/`-` INSIDE a token is
literal (`pro*-debug*` is ONE term). `--only-notes` runs the same DSL over the
resolved lessons.

```bash
memgrep recall "<symptom in the user's / the error's words>" $ROOTS   # symptom recall + lessons
memgrep recall "<symptom>" $ROOTS --sort lmd                          # newest-touched first
memgrep find "+rotator +keychain -widget" $ROOTS                      # AND two terms, exclude one
memgrep find '+"old approach" retry' $ROOTS                           # mandatory phrase + optional ranker
memgrep find "+max_retries" $ROOTS --only-notes                      # search ONLY the lessons-learned
memgrep links --to <note> $ROOTS                                      # the note's OUT-links
memgrep links --from <note> $ROOTS                                    # the note's BACKLINKS (intuition inverts these)
memgrep reindex $ROOTS                                                # refresh the SQLite query index
```

**Read-the-notes rule (FREE):** `recall`/`find` auto-resolve and APPEND each
returned note's `[^N]` lessons by default, so one call yields the facts AND every
WHY. Render is token-economical: an inline ref shows as a bare `[9]`, and after
the body memgrep appends `[9] - <lesson WHY text>.` — the on-disk `[^9]`/`[^9]:`
footnote machinery does not leak. Reading a memory's facts without its lessons is
incomplete; recall the page, read it WHOLE, then act.

## The three skills (the executable protocol)

| Skill | Leg | Does |
|---|---|---|
| `/janitor-memory-write` | MEMORIZE | CREATE/CAPTURE a durable fact as a navigable wikimem page. Finds the right existing page first (never duplicates); only when none fits, creates a HUB/ASPECT/COMPONENT page via the expand/reduce decision, wires both ends of every See-also link, indexes by symptom, appends the MEMORY.md line |
| `/janitor-memory-recall` | RECALL | FIND/READ — two entry points: FILE-anchored (about to edit a file → surface that functionality's HUB via its `globs`, descend its links to the detail needed) and SYMPTOM ("have we hit this before?" → rank pages by description/title/tags). Read-only; degrades to grep when memgrep is absent |
| `/janitor-memory-update` | UPDATE | MODIFY a page — ADD a decision to the owning page, CORRECT a fact non-destructively (the 2-step protocol), or RESHAPE a page that outgrew its tier (expand/reduce/merge/rename). Keeps See-also, the hub map, and the lessons trail consistent |

**THE UPDATE INVARIANT (governs every update):** a superseded memory is NEVER
deleted — in two moves, (1) the body is cleaned to the current truth, and (2) the
superseded statement is DEMOTED to a dated `[^N]` lesson under
`## Notes and lessons learned` carrying the WHY (what it used to be + the root
cause it changed). The corrected body links to it with `[^N]`. This is RULE 0
(never lose information) + the Bug-Autopsy directive applied to memory.

## The two heartbeat detectors (janitor enforcement)

Both run on the janitor heartbeat, SURFACE candidates to a proposal file, and
**never mutate a fact** (RULE 0). Separation of powers: the **janitor**
reorganizes structure and surfaces contradictions; an **agent** creates and
corrects content. Both skip the janitor's own repo (`state.is_self_scan_target`)
unless `CLAUDE_PLUGIN_ALLOW_SELF_SCAN` is set.

- **`memory-scope-leak`** (`scripts/detectors/memory-scope-leak.py`) — keeps the
  PUSHED PROJECT scope free of machine/user-private data, because PROJECT is the
  ONLY scope that leaves the machine. It scans every `<repo-root>/memory/**/*.md`
  page with the private-path lib, the PII shapes, the cloud + CI/CD credential
  libs, and an unknown-secret entropy pass (Shannon entropy + base64-ish gate),
  and emits `[memory-scope-leak] <file>: <class> — demote to LOCAL scope before
  push` per hit (the material belongs in LOCAL). It also runs gitignore guards:
  PROJECT `memory/` must be TRACKED (a `.gitignore` rule swallowing it would mean
  the shared scope is silently never pushed — `git check-ignore`), and a
  LOCAL-shaped store committed INSIDE the repo (a `projects/<slug>/memory/` tree)
  is itself a leak. It writes `memory-scope-leak-proposed.md` and one heartbeat
  line; the proposal NEVER includes the matched secret text. Graceful no-op when
  not a git repo / no PROJECT `memory/` / empty corpus / unchanged finding set.
  The tool's own `.memgrep/` index sidecar and the index/proposal files
  (`MEMORY.md`, `memory-index.md`, `memory-reorg-proposed.md`) are excluded from
  scanning. **This is the load-bearing privacy guard for the whole 3-scope model.**

- **`memory-librarian`** (`scripts/detectors/memory-librarian.py`) — SURFACES
  (never mutates) memory aggregation/conflict candidates across all three scope
  roots that exist (LOCAL → PROJECT → USER) to `memory-reorg-proposed.md`. It
  parses `memgrep index --markdown` + `memgrep links`, then reports: same-topic
  note CLUSTERS (tag-based primary + token-overlap fallback) that could
  consolidate; same-topic note PAIRS that are NOT cross-linked (conflict
  candidates); the LINK-LAW audit (one-sided links — every wikimem link must be
  bidirectional); per-note page-SHAPE issues (missing `## Notes and lessons
  learned`, missing `ocd`/`lmd`, etc.); broken/orphan links; and MEMORY.md ↔
  on-disk sync mismatches. The background auto-merge (consolidating a cluster into
  one wiki page) is DESIGNED but not yet shipped — today the detector only
  proposes; an agent applies via `/janitor-memory-update`.

## The wikimem layer (pages are wiki nodes, not loose notes)

The corpus is a navigable WIKI, not a pile. On top of the note format, every page
declares its place in the pyramid via `metadata.tier`:

- **`hub`** — one functionality's overview (frontend, backend, db, janitor, …).
  Carries `metadata.globs:` (the file patterns it owns), so "I'm editing this
  FILE" maps to its hub. The tip of the iceberg: overview + the big general
  decisions + the parts map.
- **`aspect`** — a GENERAL rule shared by many elements (a style, protocol,
  config, convention). It **EXPANDS / RADIATES**: it carries an `## Applies to`
  ray-list DOWN to every element it governs. A sun.
- **`component`** — ONE element's page. It **REDUCES / RECEIVES**: it carries
  `## Governed by` up-links to its governors and NEVER re-copies a governing rule.
  A terminal. **One element = one page, always** (one-component-one-page).

**THE LINK LAW — every link is bidirectional.** If A links to B, B links to A:
`## Applies to` ↔ `## Governed by` across tiers, `## See also` ↔ `## See also`
laterally. Wire both ends in the same edit; links are **scope-local** (a
`[[wikilink]]` may only target a page in the SAME scope root — reference another
scope's page in prose). The librarian flags one-sided links as a safety net, but
the author wires both ends now. memgrep's `--to`/`--from` agree under the link
law, so the graph navigates from ANY entry point in ANY direction.

**Navigate progressively:** recall surfaces the TIP (the hub / best page); follow
only the links the task needs; read a shared general page ONCE and reuse it
(cache the suns) across every component that points at it. Reading a whole
functionality's tree "to be safe" defeats the wiki — context spend stays
proportional to the task. The full data model lives in the write skill's
`references/wikimem-model.md`. Existing flat notes stay valid (no `tier` ⇒
`component`); the wiki emerges incrementally as pages are touched.

## Install procedure — adopt the system in a new project/plugin

1. **Install the engine once** (memgrep is a Rust binary that ships in this
   plugin). If `command -v memgrep` is empty:
   `cargo install --path "$CLAUDE_PLUGIN_ROOT/scripts/memgrep"` (or
   `cargo install --path <repo-root>/scripts/memgrep`) — puts it on
   `$HOME/.cargo/bin`. Until installed, recall degrades to plain `grep -rliE`
   over the same roots — it never breaks.
2. **Create the scope dir(s) lazily** — `mkdir -p "$MEMDIR"` for whichever scope
   you first write to (the skills do this on demand). LOCAL and USER live under
   `$HOME/.claude/`; PROJECT lives at `<repo-root>/memory/`.
3. **PROJECT-scope gitignore invariant:** PROJECT `<repo-root>/memory/` MUST be
   git-TRACKED (it is the shared, pushed corpus) — make sure no `.gitignore` rule
   swallows it. Conversely, a LOCAL-shaped `projects/<slug>/memory/` tree must
   NEVER be committed inside a repo. The `memory-scope-leak` detector enforces
   both.
4. **Gitignore the index sidecar:** the SQLite `.memgrep/index.db` inside any
   `memory/` dir is generated cache, not a note — exclude it (memgrep itself
   ships a `.gitignore` for its own dir).
5. **The recall discipline rule** (`markdown-memory-recall.md`) is the standing
   "recall before acting / index by symptom" rule; the janitor installs plugin
   rules into the active scope's `.claude/rules/` on session start. The harness
   `# Memory` directive is the WRITE-side authoring source-of-truth.
6. **Wire the heartbeat detectors** by running the janitor heartbeat in the
   project (`/janitor-arm`); `memory-scope-leak` and `memory-librarian` then run
   on cadence and surface their proposals into the PROJECT `memory/` dir.

## The private user-memory store (a SEPARATE corpus)

`/to-user-mem`, `/search-user-mem`, `/share-user-mem` manage the USER's OWN
agent-invisible memories at `$HOME/.claude/projects/<project-slug>/memory/user-mem/`
(a sibling of the agent corpus inside LOCAL). This is a DISTINCT corpus from the
agent wikimem pages — its search routes through `memgrep find` but it is private:
the agent cannot read it except via the one `/share-user-mem <N>` gate. Don't
conflate it with the agent memory wiki recalled by `/janitor-memory-recall`.

## See also

- `[[feedback_memory_system_is_more_than_memgrep]]` — the system is {tool · rules ·
  skills · hooks}, not just the memgrep binary.
- `[[reference_memgrep_links_to_from_semantics]]` — the `links --to`/`--from`
  directional-flag gotcha (intuition inverts them).

## Notes and lessons learned

[^1]: [ocd:2026-06-13 lmd:2026-06-13] `memgrep links --to NOTE` returns NOTE's
  OUT-links and `--from NOTE` returns its BACKLINKS — the intuition inverts them
  (you'd expect `--from` to mean "links FROM this note"). Under THE LINK LAW the
  two sets agree, so a disagreement between `--to` and `--from` is a one-sided
  link defect to flag for the librarian. Lesson: verify directional CLI flags
  with an asymmetric fixture, not by name-intuition.
[^2]: [ocd:2026-06-13 lmd:2026-06-13] `memgrep recall` ranks on
  `description + title + tags` ONLY — `metadata.type` does NOT affect ranking.
  So a note found only by its answer's jargon is mis-authored: the symptom
  vocabulary (the user's words / the error text) MUST be in `description`, with
  the answer in the body. Index by the QUESTION, not the answer.
[^3]: [ocd:2026-06-13 lmd:2026-06-13] PROJECT scope (`<repo-root>/memory/`) is the
  ONLY scope that leaves the machine (git-tracked + pushed), which is exactly why
  it is the one that can leak and the only one `memory-scope-leak` polices. LOCAL
  and USER live under `$HOME/.claude/` and are never pushed, so they are not
  scanned. Machine-private detail belongs in LOCAL; "UNSURE → LOCAL" is the safe
  default precisely because PROJECT is the pushed scope.
