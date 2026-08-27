---
name: memory-system
description: "how does the wiki-memory system work / where do memories live / how to recall before acting / what is memgrep / how do I install the memory system in a new project / why did my PROJECT memory page get flagged for a leak / LOCAL vs PROJECT vs USER scope precedence / memgrep binary is stale on this host / another host reports lint errors I cannot reproduce / cargo install does not roll forward with the plugin update / memgrep refused my write because the atom is too big / can I raise the atom budget knob / add-atom inserts a new atom in the wrong place / atom-after-footer lint defect never converges / what is the private user-memory subsystem / how does janitor-memory-user-share work / what is the retro-lesson chore and why does it exist / a superseded atom has no lesson attached / does memgrep ever refuse a write outright"
ocd: 2026-06-13
lmd: 2026-08-27
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: janitor
  originSessionId: memory-audit-draft
publish-globally: false
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


^ATOM-Q2PU-PYE0 [desc:"the atom-insertion footer anchor is implemented TWICE (Rust add-atom + Python repair precheck) and the copies must change together", keywords: add-atom_inserts_atom_in_wrong_place atom_inside_link_section footer_anchor atom-after-footer memgrep_and_precheck_disagree repair_chore_never_converges the_footer_anchor_is_implemented_twice_rust_and_python encode_the_rule_not_the_list_of_headings janitor#250_shipped_twice_for_the_same_reason a_page_whose_only_footer_is_see_also_stayed_broken change_both_copies_in_the_same_commit any_trailing_footer_section_above_notes_counts, ocd: 2026-08-11, lmd: 2026-08-11]

The atom-insertion footer anchor exists TWICE and the copies must never drift: the crate's `footer_section_line` (scripts/memgrep/src/memory.rs) decides where `add-atom` splices a new atom, and `_footer_heading_line` (scripts/lib/memory_content_precheck.py) decides where `repair_defect` says an atom is MIS-placed (`atom-after-footer`). If they disagree, one relocates atoms the other then flags as defects, forever — a repair chore that can never converge. Change them in the same commit, by construction.

The family is `## Applies to` / `## Governed by` / `## See also` / `## Notes and lessons learned`, but the RULE is "any trailing footer section that sits above Notes" — encode the rule, not the list. janitor#250 shipped twice for exactly this reason: the first fix (7edbb755) covered the three headings the issue body happened to exemplify, and a page whose only footer was `## See also` stayed broken until 36a416e4. The reporter had stated the general rule in a comment before the first fix was written.


^ATOM-MZSU-TEZS [desc: "the atom budget WARNS and queues the page to the split chore — it never refuses a write; raising the knob is the wrong lever", keywords: memgrep_refused_my_write_because_the_atom_is_too_big add-atom_failed_on_the_atom_budget MEMGREP_ATOM_MAX_CHARS_blocked_a_memory_write can_I_raise_the_atom_budget_knob an_oversized_atom_warning_appeared_but_the_write_succeeded the_atom_budget_is_a_notification_not_a_gate refusing_would_push_the_author_back_to_hand-editing janitor-memory-split_chore_owns_decomposition finds_candidates_via_memgrep_lint_atom-oversized never_re-implement_the_rust_parser_in_python owner_decision_2026-08-22_WM-LINT-03a the_count_of_oversized_atoms_only_ever_refilled, ocd: 2026-08-22, lmd: 2026-08-22]

The atom budget (`MEMGREP_ATOM_MAX_CHARS`, default 1500) is a NOTIFICATION, not a gate: `check_new_body_budget` prints a warning to stderr and writes the atom anyway (owner decision 2026-08-22, WM-LINT-03a). Refusing was worse than useless — a write verb that rejects an over-budget body pushes the author back to hand-editing markdown, which is exactly the bypass the memgrep-only write path exists to close, and the count of oversized atoms only ever refilled (TRDD-WN7M829Y). The OWNER of decomposition is the `janitor-memory-split` chore, which handles BOTH scales — oversized PAGES (`split_max_bytes`) and over-budget ATOMS — and finds its atom candidates by shelling out to `memgrep lint` and parsing `[atom-oversized]`, never by re-implementing the Rust parser in Python. Consequence for an author: an over-budget warning means "the librarian will split this later, and splitting it yourself now is better" — it never means retry, and it never means raise the knob.


^ATOM-HO67-QC61 [desc: "no memory chore runs on PROJECT scope by default (edit_project_scope=False) — 81% of lint findings are therefore unreachable", keywords: the_lint_finding_count_never_goes_down a_memory_chore_never_fixes_project_pages why_did_the_repair_chore_skip_my_project_page edit_project_scope does_the_janitor_edit_.claude/project/memory memgrep_lint_findings_persist_forever a_completed_chore_pass_did_not_move_the_number, ocd: 2026-08-26, lmd: 2026-08-26]

NO memory chore ever runs on PROJECT scope by default, and this is the mechanism behind "the lint number never moves". `memory-maintenance._scopes_in_play` (`:135`) drops PROJECT from the eligible roots unless `memory_settings.get("edit_project_scope")` is on — and it defaults `False` (`memory_settings.py:61`). The rationale is sound and is NOT a bug: PROJECT memory is in-repo and unpushable outside `publish.py`, so an agent editing it would create commits nothing can push. MEASURED 2026-08-26: of 67 `memgrep lint` findings across all three roots, **54 (81%) were PROJECT-scope** — 29 `publish-globally-missing` and 25 `atom-after-footer` on 10 pages — i.e. structurally unreachable by every chore, no matter how correct the per-chore candidacy predicate is. This is the missing half of janitor#276's note that *"a completed pass could not move the number, so the same line repeated forever"*: #276 correctly fixed the PROMOTION (a severity regex matching ERROR inside the clause negating it) and left the immovability as background. The immovability is the scope gate. Consequence for anyone diagnosing a chore: the scope gate runs BEFORE the candidacy predicate, so confirm the target root is in the eligible set before reading the predicate that judges it — see [[git-index-lock-orphan-recovery]] for the same "correct mechanism that never reaches its case" shape in a different subsystem, and TRDD-AO8MPK5D for a card that named the predicate as the cause and had to be corrected. [^8]




^ATOM-OHWM-HR13 [desc: "Never gate a memory-precheck defect check on an optional scope/path discriminator — it would be the first None-path in that module that SUPPRESSES a finding (fail-CLOSED in a fail-OPEN module)", keywords: scope=None_suppresses_a_finding gate_a_precheck_check_on_scope_label fail-closed_None_default_in_memory_precheck repair_has_work_scope_optional add_a_scope-gated_defect_check, ocd: 2026-08-27, lmd: 2026-08-27]

Passing the SCOPE LABEL into `memory_content_precheck` predicates looks like the clean way to add
a scope-specific check — both real callers already hold the label, so no path→scope re-derivation
is needed. It is a trap.

`scope` is OPTIONAL (`repair_has_work(root, *, scope: str | None = None, ...)`), and that function
goes out of its way to fail OPEN on it: `if scope is None: return True  # cannot read the ledger ⇒
never suppress` (~`:840`). Every uncertain path in the module is deliberately fail-OPEN, including
an unreadable page (`return True  # FAIL-OPEN (libs audit L-11)`).

DO NOT add a check whose condition is `scope == "PROJECT"`, BECAUSE when `scope is None` it
silently skips — making it the FIRST None-path in the module that SUPPRESSES a real finding, and
at runtime that is indistinguishable from a clean corpus. DO make the discriminator REQUIRED if a
scope-specific check is genuinely warranted (which also removes the optional-parameter smell), or
put the rule in `memgrep lint` where the arbiter already owns path- and filesystem-dependent
questions.


^ATOM-GLCB-AN5U [desc: "publish-globally is NOT a repair-gate defect and must never be added to repair_defect — memgrep decides it from FILESYSTEM state, so page text cannot split the two missing-cases", keywords: publish-globally-missing_never_drains lint_count_stuck_at_29 add_publish-globally_to_repair_defect widen_repair_defect_signature gate_and_arbiter_parity_publish-globally repair_chore_does_not_fix_publish-globally, ocd: 2026-08-27, lmd: 2026-08-27]

`memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the
single-source repair-candidacy predicate) deliberately has NO check for it. The gap is CORRECT —
rejected 2026-08-27 (TRDD-AO8MPK5D, `efad7a99`), recorded in `memory_content_precheck.py` beside
the janitor#260 rejection. Three independent reasons:

1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads
   FILESYSTEM state — whether a USER-root symlink resolves to this page — splitting "field
   missing" into `MissingDefaultFalse` (no symlink → `false`) vs `MissingSymlinkImpliesTrue`
   (symlink present → `true`, evidence of intent). A text+path predicate cannot tell them apart,
   so it hands the agent a 50/50 guess whose wrong branch SILENTLY UN-PUBLISHES a page somebody
   deliberately published.
2. **It runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD/arbiter-CLEAR;
   this is gate-SILENT/lint-loud, so it never dispatches and never loops.
3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the sole write choke point and
   normalizes before AND after every write, unconditionally.

Before adding ANY scope-gated check here, read `ATOM-OHWM-HR13` — the tidiest-looking variant is
fail-CLOSED. STALENESS SIGNAL: the count GROWING across releases means pages are being written
OUTSIDE the choke point; re-open only on that.

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


^ATOM-EG1F-FJJM [desc:"memgrep is a per-host cargo install, NOT a shipped artifact — its logic version-skews across machines and a plugin update never fixes it.", keywords: memgrep_binary_is_stale_on_this_host lint_reports_errors_another_host_does_not_see cargo_install_does_not_roll_with_the_plugin_update memgrep_version_skew_across_machines permanent_findings_that_no_edit_clears memgrep_is_a_per-host_cargo_install_not_a_shipped_artifact two_hosts_on_the_same_plugin_version_run_different_logic reconcile_the_binaries_with_cargo_install_--path a_source_change_is_invisible_until_reinstalled janitor#165_downstream_host_reported_5_permanent_lint_errors the_plugin_ships_source_every_machine_compiles_its_own_binary the_recovery_after_any_crate_edit_is_reinstalling, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-K04O-1VMN [desc:"The USER-MEMORY subsystem section verbatim from CLAUDE.md: the commands, the immutable counter, the legacy-alias blocking, and the decision:block / additionalContext privacy mechanics", keywords: user_memory_subsystem_commands_add_search_share private_agent_invisible_store decision_block_user_prompt_submit_hook legacy_to-user-mem_search-user-mem_share-user-mem_aliases_blocked what_is_the_private_user-memory_subsystem how_does_janitor-memory-user-share_work an_immutable_monotonic_counter_numbers_never_reused an_unrecognised_legacy_alias_would_leak_private_text additionalContext_is_the_only_path_that_reaches_the_model a_private_agent-invisible_user-authored_memory_store fast_no-op_for_any_non-user-mem_prompt_never_crashes systemMessage_surfaces_confirmations_user-only, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-9YTP-I1SZ [desc:"RETRO-LESSON is the 7th chore: backfills lesson form onto pointer-less superseded atoms; WHY only from provenance; skill must stamp superseded-by itself", keywords: superseded_atom_has_no_lesson retro_lesson_chore seventh_memory_chore retire-atom_did_not_stamp_superseded-by how_many_editorial_passes retro-lesson_backfills_lesson_form_onto_old_superseded_atoms the_why_comes_only_from_commit_trdd_provenance unsourceable_why_must_be_flagged_for_a_human_never_invented the_skill_must_stamp_superseded-by_itself_via_the_repair_txn without_the_stamp_the_precheck_re-fires_forever seven_wikimem_editorial_chores_since_TRDD-J3ZH3RSI cadence_key_retro_lesson_per_day_default_1_conservative_cap, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

The wikimem editor runs SEVEN chores since TRDD-J3ZH3RSI (commit 009af29): split, repair, atomize, harvest, RETRO-LESSON, consolidate, conflict — retro-lesson backfills the lesson form (DO NOT X, BECAUSE why, DO Y instead) onto atoms that were superseded BEFORE the update-invariant existed. Its precheck signature is an atom marker with `status:superseded` but NO `superseded-by:` pointer (the exact pair `add-lesson --supersedes --retire-atom` stamps together); cadence key `retro_lesson_per_day`, default 1/day (ON, conservative cap — owner directive 2026-08-11 superseded the earlier 0=OFF default) like every pass. Two load-bearing rules: the WHY comes ONLY from the commit/TRDD provenance chain — unsourceable ⇒ FLAG for a human, never invented — and the skill must complete the `superseded-by:` pointer itself via the repair-op txn, because memgrep's `--retire-atom` is idempotent-SKIPPED when a `status:` prop already exists (precisely the retro case); without that step the precheck re-fires on the same atom forever. [^7]


## Superseded


^ATOM-31W8-NR3A [desc: "publish-globally is NOT a repair-gate defect and must never be added to repair_defect — memgrep decides it from FILESYSTEM state, so page text cannot split the two missing-cases", keywords: publish-globally-missing_never_drains lint_count_stuck_at_29 add_publish-globally_to_repair_defect widen_repair_defect_signature gate_and_arbiter_parity_publish-globally repair_chore_does_not_fix_publish-globally, ocd: 2026-08-27, lmd: 2026-08-27, status: superseded, superseded-by: ATOM-GLCB-AN5U]

`memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the
single-source repair-candidacy predicate) deliberately has NO check for it. That gap is CORRECT —
re-litigated and rejected 2026-08-27 (TRDD-AO8MPK5D, `efad7a99`); rejection recorded in
`memory_content_precheck.py` beside the janitor#260 one. Three independent reasons:

1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads
   FILESYSTEM state — whether a USER-root symlink resolves to this page — and splits "field
   missing" into `MissingDefaultFalse` (no symlink → `false`) vs `MissingSymlinkImpliesTrue`
   (symlink present → `true`, evidence of intent). A text+path predicate cannot tell them apart,
   so it hands the agent a 50/50 guess whose wrong branch SILENTLY UN-PUBLISHES a page somebody
   deliberately published.
2. **The disagreement runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD and
   arbiter-CLEAR; this is gate-SILENT and lint-loud, so it can never dispatch and never loops.
   Coverage shortfall, not the #227 class.
3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the SOLE write choke point and runs
   `normalize_page_until_clean` before AND after every write, unconditionally.

STALENESS SIGNAL: the count GROWING across releases means pages are being written OUTSIDE the
choke point (raw Edit-tool writes to PROJECT memory) — a bigger bug than the field. Re-open only
on that evidence. See [[ATOM on the scope=None fail-CLOSED trap]] before adding ANY scope-gated
check here.

^ATOM-MWID-C4CR [desc: "publish-globally is NOT a repair-gate defect and must never be added to repair_defect — memgrep decides it from FILESYSTEM state, so text cannot split the two missing-cases", keywords: publish-globally-missing_never_drains lint_count_stuck_at_29 add_publish-globally_to_repair_defect widen_repair_defect_signature gate_and_arbiter_parity_publish-globally repair_chore_does_not_fix_publish-globally pass_scope_label_to_a_precheck_predicate memory_chore_predicate_takes_no_path, ocd: 2026-08-27, lmd: 2026-08-27, status: superseded, superseded-by: ATOM-31W8-NR3A]

`memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the
single-source repair-candidacy predicate) deliberately has NO check for it. That gap is CORRECT
and was re-litigated and rejected on 2026-08-27 (TRDD-AO8MPK5D, commit `efad7a99`); the rejection
is recorded in `memory_content_precheck.py` beside the janitor#260 one.

Three independent reasons, and the first is the one people miss:

1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads
   FILESYSTEM state — whether a USER-root symlink resolves to this page — and splits "field
   missing" into `MissingDefaultFalse` (no symlink → write `false`) vs `MissingSymlinkImpliesTrue`
   (symlink present → write `true`, the symlink being evidence of intent). A text+path predicate
   cannot tell them apart, so it hands the agent a 50/50 guess whose wrong branch SILENTLY
   UN-PUBLISHES a page somebody deliberately published.
2. **The disagreement runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD and
   arbiter-CLEAR. This is gate-SILENT and lint-loud: it can never cause a dispatch, so it can
   never loop or burn a token. Coverage shortfall, not the #227 class — do not reason about the
   two as the same bug.
3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the SOLE write choke point and runs
   `normalize_page_until_clean` before AND after every write, unconditionally. The flagged pages
   are simply pages nothing has written since the field was introduced.

The variant that looks cleanest is the worst: gating the check on a `scope=None` default would make
it the FIRST None-path in that module that SUPPRESSES a finding, where `repair_has_work` (~`:840`)
explicitly does the opposite (`if scope is None: return True`). Fail-OPEN is the house posture; a
scope-gated skip is fail-CLOSED and looks identical to a clean corpus.

STALENESS SIGNAL: the `publish-globally-missing` count GROWING across releases rather than
shrinking means pages are being written OUTSIDE the choke point (raw Edit-tool writes to PROJECT
memory) — a much bigger bug than the field. Re-open this only on that evidence.
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
[^8]: [id: ATOM-LATA-4NGJ, status: valid, desc: "a TRDD body is not a recall surface — recall indexes memory pages, never design/tasks", keywords: "I_rediscovered_something_a_TRDD_already_recorded is_this_finding_actually_new does_memgrep_recall_search_the_design_tasks_folder a_fact_that_lives_only_in_a_card_body why_did_I_re-derive_a_known_mechanism prior_art_check_before_filing_a_card", ocd: 2026-08-26, lmd: 2026-08-26] DO NOT treat a finding you reached by reading source as NEW without searching the TRDD corpus for it first, BECAUSE a card body is not a recall surface: TRDD-LFSWY0C6 recorded this exact PROJECT-gate finding on 2026-08-13 — same file, same two line numbers, same "silently disabled on every default install" conclusion — and I re-derived it from scratch 13 days later, then wrote it up as though it were new and let a second card (TRDD-AO8MPK5D) inherit that framing. `memgrep recall` searches MEMORY pages only; nothing indexes `design/tasks/*.md`, so a fact that lives solely in a card is invisible to the retrieval path every session actually uses. DO grep `design/tasks/` for the symbol or setting name (here `edit_project_scope`) alongside the memory recall before claiming a mechanism is unrecorded — and when the grep hits, MIGRATE the fact to a memory page and cite the card, which is what this atom now is.
