---
name: memory-system
description: "how does the wiki-memory system work / where do memories live / how to recall before acting / what is memgrep / how do I install the memory system in a new project / why did my PROJECT memory page get flagged for a leak / LOCAL vs PROJECT vs USER scope precedence / memgrep binary is stale on this host / another host reports lint errors I cannot reproduce / cargo install does not roll forward with the plugin update"
ocd: 2026-06-13
lmd: 2026-08-02
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
ranking). [^2] Put **symptom vocabulary** in `description`, put the **answer** in the
body (two-hop recall: symptom query → note → body answer). The
`## Notes and lessons learned` section is MANDATORY on every page even when empty
— the standing landing zone for `[^N]` correction lessons; the page-shape pass
flags a note that omits it, or that omits `ocd`/`lmd`.

**The index is memgrep's, and ONLY memgrep's** (v0.13.0, TRDD-a5780c23): recall runs on
the agent-invisible, unlimited SQLite index `.memgrep/index.db` (or a live note-scan) and
NEVER reads a human index.[^5] `MEMORY.md` is now a **deprecation stub** — never
maintained, loaded-as-index, or hand-trimmed. The daily **harvest chore**
(`/janitor-memory-harvest`) re-files any stray memory an agent mis-adds to `MEMORY.md`
(or a loose `.md`) back into proper wiki pages, NON-destructively, then stubs `MEMORY.md`.
Each PROJECT corpus carries one `<project>-overview.md` entry page — `memgrep overview
<dir>` prints it (the Wikipedia-style overview that links to the deeper pages).

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
| `overview <memdir…>` | print the project's `*-overview.md` entry page (the navigation entry point; the MEMORY.md stub advertises this command) |
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

## The heartbeat detectors + nudges (janitor enforcement)

The SURFACING detectors run on the janitor heartbeat, surface candidates to a
proposal file or a one-line nudge, and **never mutate a fact** (RULE 0):
the **janitor** reorganizes structure and surfaces contradictions; an **agent**
creates and corrects content. (The one MUTATING path is the autonomous wikimem
editor — split / repair / consolidate / conflict — which `memory-maintenance`
SCHEDULES and which edits ONLY through the `memory_txn` transaction core, never a
raw write.) All scope resolution for every detector + the scheduler is the shared
`scripts/lib/memory_scopes.py` SSOT.[^4] The surfacing detectors skip the
janitor's own repo (`state.is_self_scan_target`) unless
`CLAUDE_PLUGIN_ALLOW_SELF_SCAN` is set.

- **`memory-scope-leak`** (`scripts/detectors/memory-scope-leak.py`) — keeps the
  PUSHED PROJECT scope free of machine/user-private data, because PROJECT is the
  ONLY scope that leaves the machine. [^3] It scans every `<repo-root>/memory/**/*.md`
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

- **`memorize-nudge`** (`scripts/detectors/memorize-nudge.py`, TRDD-87935f21 #6) —
  keeps the wiki POPULATED. When SUBSTANTIVE (non-bookkeeping) commits have landed
  since the last LOCAL/PROJECT memory note, it nudges the agent to
  `/janitor-memory-write` what changed + WHY (recall-first). Universal but
  adoption-gated (silent unless the wiki is already in use; `…REQUIRE_ADOPTION=false`
  for the fleet's aggressive mode), ≥3 substantive commits, one nudge per interval,
  auto-silences the instant a note is written. Read-only (git + note mtimes); never
  reads USER scope (a cross-project write would falsely suppress this project's nudge).

- **`why-in-commits`** (`scripts/detectors/why-in-commits.py`, TRDD-87935f21 #6) —
  enforces the commit-discipline rule (the WHY belongs in the message body; only the
  author can write it and it is lost once committed). Surfaces recent subject-only
  feat/fix/refactor/perf commits (no body → no WHY). ai-maestro-gated (the fleet that
  mandates it + uses conventional commits), ≥3 deficient over a 3-day window, set-based
  dedupe (one reminder per distinct deficient set — never re-nags immutable history).
  Read-only git log.

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
law, so the graph navigates from ANY entry point in ANY direction. [^1]

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

`/janitor-memory-user-add`, `/janitor-memory-user-search`,
`/janitor-memory-user-share` manage the USER's OWN agent-invisible memories at
`$HOME/.claude/projects/<project-slug>/memory/user-mem/` (a sibling of the agent
corpus inside LOCAL). The legacy `/to-user-mem` / `/search-user-mem` /
`/share-user-mem` names still work (deprecated aliases, kept recognised-and-blocked
so they never leak). This is a DISTINCT corpus from the agent wikimem pages — its
search routes through `memgrep find` but it is private: the agent cannot read it
except via the one `/janitor-memory-user-share <N>` gate. Don't conflate it with
the agent memory wiki recalled by `/janitor-memory-recall`.

## See also

- [[claude-md-canonical-form]] — CLAUDE.md is the index over this corpus; what may live in it, and the migration contract.
- [[feedback_memory_system_is_more_than_memgrep]] — the system is {tool · rules ·
  skills · hooks}, not just the memgrep binary.
- `[[reference_memgrep_links_to_from_semantics]]` — the `links --to`/`--from`
  directional-flag gotcha (intuition inverts them).
- [[janitor-is-not-a-role-agent]] — why PROJECT scope is the ONLY memory that
  survives a maintainer-agent takeover (it clones the repo; everything uncommitted
  is lost), and why the janitor carries no role plugin.
- `[[wikimem-retrieval-engine]]` — how recall actually RANKS and PRINTS: the
  two-hop contract, the tiered scorer, why a locator is an identity rather than a
  path, and the lint severity model.
- [[reference_cpv_dotclaude_gitignore_fp]] — why memory lives under `.claude/` in
  the first place, and the CPV `--strict` false-positive that decision trips.


^ATOM-EG1F-FJJM [desc:"memgrep is a per-host cargo install, NOT a shipped artifact — its logic version-skews across machines and a plugin update never fixes it.", keywords: memgrep_binary_is_stale_on_this_host lint_reports_errors_another_host_does_not_see cargo_install_does_not_roll_with_the_plugin_update memgrep_version_skew_across_machines permanent_findings_that_no_edit_clears, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**`memgrep` is built and installed PER HOST (`cargo install --path
scripts/memgrep`), so it does NOT roll forward when the plugin updates.** The
plugin ships the Rust *source*; every machine compiles its own binary into
`$HOME/.cargo/bin`. Two hosts on the same plugin version can therefore run
different recall/lint/index LOGIC indefinitely, and no plugin update will ever
reconcile them.

The tell is a finding that **one host reports and another cannot reproduce**,
especially one that never changes. Measured on janitor#165: a downstream host
reported 5 permanent lint ERRORs on every heartbeat, while this host reported
`none at or above ERROR` from the same detector on the same code — the filter
that excluded those files (`collect_md`'s `is_index_file` guard, added
2026-07-07) was simply not in the reporter's binary.

Before treating a cross-host discrepancy as a code defect, reconcile the
binaries: `cd <checkout>/scripts/memgrep && cargo install --path .` on the host
that sees it. That is also the recovery after ANY edit to the crate — a source
change is invisible until reinstalled. [^6]


^ATOM-K04O-1VMN [desc:"The USER-MEMORY subsystem section verbatim from CLAUDE.md: the commands, the immutable counter, the legacy-alias blocking, and the decision:block / additionalContext privacy mechanics", keywords: user_memory_subsystem_commands_add_search_share private_agent_invisible_store decision_block_user_prompt_submit_hook legacy_to-user-mem_search-user-mem_share-user-mem_aliases_blocked, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**USER-MEMORY subsystem (`commands/janitor-memory-user-{add,search,share}.md` +
`scripts/hooks/on-prompt-submit-user-mem.py` + `scripts/lib/user_mem_lib.py`,
TRDD-4334aad0; renamed TRDD #196)** — a PRIVATE, agent-invisible user-authored
memory store at `~/.claude/projects/<slug>/memory/user-mem/` (sibling of the
agent corpus), with an immutable monotonic counter (`.counter` + flock; numbers
retired-never-reused). `/janitor-memory-user-add [<text>]` saves (bare → previous
user message via transcript); `/janitor-memory-user-search <q>` searches ONLY
that store via `memgrep find <q> <dir> --use-index` (the `+`/`-`/wildcard/phrase
DSL lives in the Rust crate); `/janitor-memory-user-share <N>` is the ONE gate
that injects a memory into context. The legacy `/to-user-mem` / `/search-user-mem`
/ `/share-user-mem` names still work (deprecated aliases) and — critically — stay
recognised-and-blocked so a user who types one never leaks (an UNRECOGNISED form
is not intercepted → the private text reaches the model). PRIVACY (verified vs
the Claude Code hook docs): the UserPromptSubmit hook returns `decision:block`
(erases the prompt → save text + search query never reach the model) and surfaces
confirmations/results via `systemMessage` (user-only); `/janitor-memory-user-share`
is the sole path using `additionalContext` (which DOES reach the model). Fast
no-op for any non-user-mem prompt; never crashes the session.


^ATOM-9YTP-I1SZ [desc:"RETRO-LESSON is the 7th chore: backfills lesson form onto pointer-less superseded atoms; WHY only from provenance; skill must stamp superseded-by itself", keywords: superseded_atom_has_no_lesson retro_lesson_chore seventh_memory_chore retire-atom_did_not_stamp_superseded-by how_many_editorial_passes, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

The wikimem editor runs SEVEN chores since TRDD-J3ZH3RSI (commit 009af29): split, repair, atomize, harvest, RETRO-LESSON, consolidate, conflict — retro-lesson backfills the lesson form (DO NOT X, BECAUSE why, DO Y instead) onto atoms that were superseded BEFORE the update-invariant existed. Its precheck signature is an atom marker with `status:superseded` but NO `superseded-by:` pointer (the exact pair `add-lesson --supersedes --retire-atom` stamps together); cadence key `retro_lesson_per_day`, default 1/day (ON, conservative cap — owner directive 2026-08-11 superseded the earlier 0=OFF default) like every pass. Two load-bearing rules: the WHY comes ONLY from the commit/TRDD provenance chain — unsourceable ⇒ FLAG for a human, never invented — and the skill must complete the `superseded-by:` pointer itself via the repair-op txn, because memgrep's `--retire-atom` is idempotent-SKIPPED when a `status:` prop already exists (precisely the retro case); without that step the precheck re-fires on the same atom forever. [^7]

## Notes and lessons learned

[^1]: [id:ATOM-MG07-0001, status:valid, keywords:"memgrep_links_to_from_inverted verify_directional_flags_asymmetric_fixture one_sided_link_defect", ocd:2026-06-13, lmd:2026-06-13] `memgrep links --to NOTE` returns NOTE's
  OUT-links and `--from NOTE` returns its BACKLINKS — the intuition inverts them
  (you'd expect `--from` to mean "links FROM this note"). Under THE LINK LAW the
  two sets agree, so a disagreement between `--to` and `--from` is a one-sided
  link defect to flag for the librarian. Lesson: verify directional CLI flags
  with an asymmetric fixture, not by name-intuition.
[^2]: [id:ATOM-MG07-0002, status:valid, keywords:"recall_ranks_description_title_tags_only index_by_question_not_answer symptom_vocabulary_in_description", ocd:2026-06-13, lmd:2026-06-13] `memgrep recall` ranks on
  `description + title + tags` ONLY — `metadata.type` does NOT affect ranking.
  So a note found only by its answer's jargon is mis-authored: the symptom
  vocabulary (the user's words / the error text) MUST be in `description`, with
  the answer in the body. Index by the QUESTION, not the answer.
[^3]: [id:ATOM-MG07-0003, status:valid, keywords:"project_scope_only_pushed_can_leak unsure_local_safe_default memory_scope_leak_polices_project", ocd:2026-06-13, lmd:2026-06-13] PROJECT scope (`<repo-root>/memory/`) is the
  ONLY scope that leaves the machine (git-tracked + pushed), which is exactly why
  it is the one that can leak and the only one `memory-scope-leak` polices. LOCAL
  and USER live under `$HOME/.claude/` and are never pushed, so they are not
  scanned. Machine-private detail belongs in LOCAL; "UNSURE → LOCAL" is the safe
  default precisely because PROJECT is the pushed scope.
[^4]: [id:ATOM-MG07-0004, status:valid, keywords:"extract_shared_resolver_before_third_copy test_heartbeat_detectors_as_subprocess lru_cache_leaks_first_test_root", ocd:2026-06-19, lmd:2026-06-19] The LOCAL/PROJECT/USER scope-dir resolvers
  were copy-pasted byte-identical into `memory-maintenance` + `memory-librarian`
  with an "IDENTICAL to ..." comment; adding a 3rd consumer (`memorize-nudge`)
  would have calcified a 3-way duplication that silently routes recall/write to the
  WRONG dir the moment one copy drifts (esp. the USER-path `${CLAUDE_PLUGIN_DATA}`
  gotcha — the running plugin's data dir is NOT the janitor's at heartbeat time).
  Extracted to `scripts/lib/memory_scopes.py` (the SSOT, with tests). Lesson:
  extract the shared resolver BEFORE the 2nd copy gets a 3rd sibling. And test
  heartbeat detectors AS A SUBPROCESS (how the heartbeat runs them) — `state`'s
  `project_root`/`janitor_root` are process-lifetime `@lru_cache`d, so in-process
  repeated `main()` calls leak the first test's resolved root (the cache is correct
  in production, where every heartbeat is a fresh process).
[^5]: [id:ATOM-MG07-0005, status:valid, keywords:"memory_md_growing_index_was_the_bug never_put_growing_index_in_context search_engine_owns_unlimited_index", ocd:2026-06-20, lmd:2026-06-20] Pre-v0.13.0 this page said "`MEMORY.md` is the human
  index loaded each session and the canonical index." That model WAS the bug: the
  context-loaded MEMORY.md grew unbounded with the corpus, so agents hand-trimmed it to
  save context and LOST pointers / corrupted memories. v0.13.0 (TRDD-a5780c23) moved the
  index ENTIRELY into memgrep's agent-invisible, unlimited SQLite — there is no
  human-maintained index any more. Lesson: never put a growing index in the agent's
  context window; let the search engine own it (unlimited, invisible). The daily harvest
  chore and the deprecation stub keep it that way against agents who re-add to MEMORY.md.
[^6]: [id:ATOM-Y1XB-UMXQ, status:valid, desc:"janitor#165 — the reported symptom was unreproducible here because the reporter's memgrep predated the fix.", keywords:"another_host_reports_a_finding_i_cannot_reproduce filed_a_bug_for_a_stale_binary cross_host_discrepancy_is_not_always_a_code_defect", ocd:2026-08-02, lmd:2026-08-02] DO NOT treat "another host reports a finding this host cannot reproduce" as proof of a code defect, BECAUSE any per-host-compiled tool (memgrep) can run older logic indefinitely while both hosts sit on the same plugin version, so the discrepancy is evidence about the BINARIES before it is evidence about the code. DO reconcile the binaries first (`cargo install --path scripts/memgrep`), and say which half you actually verified when you answer.
[^7]: [id:ATOM-ZJE4-9AOD, status:valid, desc:"lesson-uncited is EXPECTED on an aspect/methodology page — cite only what passes the travel test", keywords:"lesson-uncited_findings should_I_cite_every_uncited_lesson is_a_page-level_lesson_a_defect bulk-citing_to_clear_the_linter does_this_lesson_travel_with_the_atom 27_lesson-uncited_on_one_corpus", ocd:2026-08-05, lmd:2026-08-05] DO NOT clear `lesson-uncited` findings by citing them from whatever atom is nearest, BECAUSE a citation is a CLAIM that the lesson TRAVELS with that atom — a fabricated one would carry the lesson away from its page in a later split — and on an aspect/methodology page most lessons are page-level BY DESIGN: they are the shared method, owned by the page, not by one atom. DO apply the travel test per lesson ("if this atom moved to another page, would this lesson have to follow?"), cite only where the answer is yes, and RECORD the verdict so the next session does not re-derive it. Measured 2026-08-05 on debugging-methodology.md: of 7 uncited lessons only 2 passed — `[^7]` (idle-calibrated timeout) to the SLOW-vs-STUCK atom, and `[^8]` (a linter green over zero files) to the "a summarizer cannot prove absence" atom, which already cited `[^8]`'s own declared sibling `[^4]`. The other 5 were correct as-is. Two supports: `memgrep add-lesson` REQUIRES `--atom`, so an uncited lesson is legacy or hand-authored rather than a fresh defect; and the code is ORPHANED (no chore gate detects it — janitor#200), so nothing will ever dispatch to "fix" it for you.
ONE SUBCLASS DOES HAVE AN OWNER: on a page with ZERO atoms, "cite it from an atom" is
IMPOSSIBLE advice — the page is free prose and the real fix is to ATOMIZE it, which
`atomize_has_work` (pages with no atom markers at all) genuinely covers. Verified 2026-08-05:
5 of 13 flagged pages were zero-atom, carrying 6 of the 20 residual findings.
