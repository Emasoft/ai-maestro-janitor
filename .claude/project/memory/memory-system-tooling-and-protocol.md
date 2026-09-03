---
name: memory-system-tooling-and-protocol
description: "how does the memgrep engine work / what are the memgrep subcommands / how do I recall / find / links / reindex / what do the three memory skills do / MEMORIZE RECALL UPDATE / what is the update invariant / how does a superseded memory get demoted to a lesson / what do the memory heartbeat detectors do / memory-scope-leak memory-librarian memorize-nudge why-in-commits / what is the wikimem layer / hub aspect component tiers / the link law every link is bidirectional / how do I install the memory system in a new project / memgrep binary is stale on this host / cargo install does not roll forward with the plugin update"
ocd: 2026-06-13
lmd: 2026-09-03
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: janitor
  globs: ["scripts/memgrep/**", "scripts/lib/memory_*.py"]
  originSessionId: memory-audit-draft
publish-globally: false
split-lineage: c89f02722a424b5385204031e5db35ce
---

# Memory-system tooling and protocol

Part of the [[memory-system]] functionality: the `memgrep` engine, the three
authoring/recall/update skills, the heartbeat detectors that police the wiki,
the wikimem tier layer (hub/aspect/component + the link law), and the install
procedure. Split out of [[memory-system]] 2026-09-03 to keep that page a
navigable overview instead of a dump -- see it for the scope model, the note
format, and the editor's operational gotchas.

## The memgrep engine

^WQBHAC45 [desc:"memgrep is a grep/rg-style markdown search engine with structural filters, boolean --where queries, and dedicated memory subcommands (recall/find/overview/index/links/fact); ordinary grep flags transfer directly.", keywords:"what_is_memgrep how_does_memgrep_engine_work memgrep_subcommand_table grep_muscle_memory_transfers where_expr_boolean_query markdown_structural_filters_heading_level multi_root_searches_local_project_user", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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

^NCA05AI2 [desc:"recall/find share flags (--with-notes, --sort, --since/--until, --top, --use-index); the find DSL uses +term/-term/wildcard/quoted-phrase syntax; worked example commands for recall, find, links, and reindex.", keywords:"memgrep_recall_flags_reference find_dsl_grammar_plus_minus_wildcard how_do_i_search_memory_with_boolean_terms memgrep_command_examples recall_sort_score_ocd_lmd only_notes_searches_lessons", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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

^L65JI3FX [desc:"recall/find auto-resolve and append each returned note's lessons by default (read-the-notes rule); render is token-economical, inline refs show as bare [9] with the WHY appended.", keywords:"read_the_notes_rule_free do_lessons_come_back_automatically_with_recall inline_footnote_render_token_economical recall_returns_facts_and_why_together footnote_machinery_does_not_leak", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
**Read-the-notes rule (FREE):** `recall`/`find` auto-resolve and APPEND each
returned note's `[^N]` lessons by default, so one call yields the facts AND every
WHY. Render is token-economical: an inline ref shows as a bare `[9]`, and after
the body memgrep appends `[9] - <lesson WHY text>.` — the on-disk `[^9]`/`[^9]:`
footnote machinery does not leak. Reading a memory's facts without its lessons is
incomplete; recall the page, read it WHOLE, then act.

## The three skills (the executable protocol)

^H44ZKR94 [desc:"The three memory skills map to MEMORIZE (write, create a page), RECALL (find/read, file- or symptom-anchored), and UPDATE (modify — add, correct, or reshape a page).", keywords:"what_do_the_three_memory_skills_do janitor_memory_write_recall_update memorize_recall_update_leg_mapping which_skill_creates_vs_finds_vs_modifies file_anchored_vs_symptom_anchored_recall", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
| Skill | Leg | Does |
|---|---|---|
| `/janitor-memory-write` | MEMORIZE | CREATE/CAPTURE a durable fact as a navigable wikimem page. Finds the right existing page first (never duplicates); only when none fits, creates a HUB/ASPECT/COMPONENT page via the expand/reduce decision, wires both ends of every See-also link, indexes by symptom, appends the MEMORY.md line |
| `/janitor-memory-recall` | RECALL | FIND/READ — two entry points: FILE-anchored (about to edit a file → surface that functionality's HUB via its `globs`, descend its links to the detail needed) and SYMPTOM ("have we hit this before?" → rank pages by description/title/tags). Read-only; degrades to grep when memgrep is absent |
| `/janitor-memory-update` | UPDATE | MODIFY a page — ADD a decision to the owning page, CORRECT a fact non-destructively (the 2-step protocol), or RESHAPE a page that outgrew its tier (expand/reduce/merge/rename). Keeps See-also, the hub map, and the lessons trail consistent |

^CKDJWQJR [desc:"THE UPDATE INVARIANT: a superseded memory is never deleted — the body is cleaned to the current truth and the superseded statement is demoted to a dated lesson carrying the WHY, per RULE 0 and the Bug-Autopsy directive.", keywords:"what_is_the_update_invariant how_does_a_superseded_memory_get_demoted_to_a_lesson never_delete_a_memory_only_supersede two_step_correction_protocol rule_0_bug_autopsy_applied_to_memory", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
**THE UPDATE INVARIANT (governs every update):** a superseded memory is NEVER
deleted — in two moves, (1) the body is cleaned to the current truth, and (2) the
superseded statement is DEMOTED to a dated `[^N]` lesson under
`## Notes and lessons learned` carrying the WHY (what it used to be + the root
cause it changed). The corrected body links to it with `[^N]`. This is RULE 0
(never lose information) + the Bug-Autopsy directive applied to memory.

## The heartbeat detectors + nudges (janitor enforcement)

^AN7XDVXA [desc:"Heartbeat detectors only SURFACE candidates and never mutate a fact (RULE 0); the janitor reorganizes structure, an agent corrects content, and the sole mutating path is the autonomous wikimem editor through the memory_txn transaction core.", keywords:"what_do_the_memory_heartbeat_detectors_do surfacing_vs_mutating_detectors janitor_never_mutates_a_fact_directly which_path_actually_edits_memory memory_txn_transaction_core scope_resolution_ssot", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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

^OR8Z7JIM [desc:"memory-scope-leak keeps the pushed PROJECT scope free of machine/user-private data — scans every PROJECT page with private-path/PII/credential/entropy checks, enforces PROJECT memory/ stays git-tracked, and never includes the matched secret text in its proposal.", keywords:"what_does_memory_scope_leak_detect load_bearing_privacy_guard_three_scope_model project_memory_must_be_git_tracked local_shaped_store_committed_inside_repo_is_a_leak shannon_entropy_base64_secret_pass gitignore_guard_check_ignore", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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

^0DF9I011 [desc:"memory-librarian surfaces (never mutates) aggregation/conflict candidates across all three scope roots: same-topic clusters, un-cross-linked pairs, one-sided-link audit, page-shape issues, and MEMORY.md sync mismatches; auto-merge is designed but not yet shipped.", keywords:"what_does_memory_librarian_do same_topic_note_clusters_consolidation_candidates conflict_candidate_pairs_not_cross_linked link_law_audit_one_sided_links auto_merge_designed_not_shipped memory_reorg_proposed_file", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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

^DFGB2IF9 [desc:"memorize-nudge keeps the wiki populated by nudging /janitor-memory-write after >=3 substantive commits with no new LOCAL/PROJECT note since; adoption-gated, one nudge per interval, self-silences the instant a note is written, and never reads USER scope.", keywords:"why_does_the_janitor_nudge_me_to_write_a_memory memorize_nudge_detector_trigger_threshold adoption_gated_silent_unless_wiki_in_use substantive_commits_no_new_memory_note self_silences_on_write never_reads_user_scope", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
- **`memorize-nudge`** (`scripts/detectors/memorize-nudge.py`, TRDD-87935f21 #6) —
  keeps the wiki POPULATED. When SUBSTANTIVE (non-bookkeeping) commits have landed
  since the last LOCAL/PROJECT memory note, it nudges the agent to
  `/janitor-memory-write` what changed + WHY (recall-first). Universal but
  adoption-gated (silent unless the wiki is already in use; `…REQUIRE_ADOPTION=false`
  for the fleet's aggressive mode), ≥3 substantive commits, one nudge per interval,
  auto-silences the instant a note is written. Read-only (git + note mtimes); never
  reads USER scope (a cross-project write would falsely suppress this project's nudge).

^89810AOE [desc:"why-in-commits enforces the commit-discipline WHY-in-the-message rule: surfaces recent subject-only feat/fix/refactor/perf commits with no body, ai-maestro-gated, >=3 deficient over a 3-day window, set-based dedupe so it never re-nags immutable history.", keywords:"what_does_why_in_commits_detect commit_message_missing_a_why_body subject_only_conventional_commits ai_maestro_gated_fleet_only three_day_window_deduplication never_re_nags_immutable_history", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
- **`why-in-commits`** (`scripts/detectors/why-in-commits.py`, TRDD-87935f21 #6) —
  enforces the commit-discipline rule (the WHY belongs in the message body; only the
  author can write it and it is lost once committed). Surfaces recent subject-only
  feat/fix/refactor/perf commits (no body → no WHY). ai-maestro-gated (the fleet that
  mandates it + uses conventional commits), ≥3 deficient over a 3-day window, set-based
  dedupe (one reminder per distinct deficient set — never re-nags immutable history).
  Read-only git log.

## The wikimem layer (pages are wiki nodes, not loose notes)

^VGX77X5X [desc:"Every wikimem page declares a tier: hub (functionality overview, carries globs), aspect (a general rule that expands/radiates via Applies to), or component (one element's page that reduces/receives via Governed by, one-component-one-page).", keywords:"what_is_the_wikimem_layer hub_aspect_component_tiers_explained what_is_a_tier_hub_page what_is_an_aspect_page_expand_radiate what_is_a_component_page_reduce_receive one_component_one_page_invariant", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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

^I13TI6G4 [desc:"THE LINK LAW: every wikimem link is bidirectional — Applies to pairs with Governed by across tiers, See also pairs with See also laterally; links are scope-local, and memgrep's --to/--from agree under the law.", keywords:"what_is_the_link_law_in_wikimem every_link_must_be_bidirectional applies_to_governed_by_reciprocal see_also_mirrored_on_both_pages links_are_scope_local_only wire_both_ends_in_the_same_edit", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
**THE LINK LAW — every link is bidirectional.** If A links to B, B links to A:
`## Applies to` ↔ `## Governed by` across tiers, `## See also` ↔ `## See also`
laterally. Wire both ends in the same edit; links are **scope-local** (a
`[[wikilink]]` may only target a page in the SAME scope root — reference another
scope's page in prose). The librarian flags one-sided links as a safety net, but
the author wires both ends now. memgrep's `--to`/`--from` agree under the link
law, so the graph navigates from ANY entry point in ANY direction. [^1]

^JYHON0PY [desc:"Navigate the wiki progressively: recall surfaces the tip (the hub/best page), follow only the links the task needs, and cache the suns — read a shared general page once and reuse it across every component that points at it.", keywords:"how_should_i_navigate_the_wikimem_wiki cache_the_suns_reuse_shared_general_page dont_read_a_whole_functionality_tree context_spend_proportional_to_the_task existing_flat_notes_default_to_component_tier", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
**Navigate progressively:** recall surfaces the TIP (the hub / best page); follow
only the links the task needs; read a shared general page ONCE and reuse it
(cache the suns) across every component that points at it. Reading a whole
functionality's tree "to be safe" defeats the wiki — context spend stays
proportional to the task. The full data model lives in the write skill's
`references/wikimem-model.md`. Existing flat notes stay valid (no `tier` ⇒
`component`); the wiki emerges incrementally as pages are touched.

## Install procedure — adopt the system in a new project/plugin

^JWEHPGUJ [desc:"Adopting the memory system in a new project: cargo-install memgrep once (recall degrades to plain grep until then), create scope dirs lazily, keep PROJECT memory/ git-tracked and gitignore its SQLite index sidecar, and wire the heartbeat detectors via /janitor-arm.", keywords:"how_do_i_install_the_memory_system_in_a_new_project memgrep_binary_missing_cargo_install project_scope_gitignore_invariant gitignore_the_memgrep_index_sidecar wire_heartbeat_detectors_janitor_arm recall_discipline_rule_installed_at_session_start", type: project, ocd: 2026-06-13, lmd: 2026-09-03]
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


## Governed by

- [[memory-system]] -- the functionality hub this page is one part of.

## See also

- [[memory-system]] -- the overview and parts map.
- [[memory-system-scopes-and-format]] -- the LOCAL/PROJECT/USER scope model
  and note frontmatter this tooling operates over.
- [[memory-system-editor-gotchas]] -- the wikimem editor's own operational
  quirks and lint-defect provenance (footer anchor, atom budget,
  edit_project_scope, publish-globally, the retro-lesson chore).

## Notes and lessons learned

[^1]: [id:ATOM-MG07-0001, status:valid, keywords:"memgrep_links_to_from_inverted verify_directional_flags_asymmetric_fixture one_sided_link_defect", ocd:2026-06-13, lmd:2026-06-13] `memgrep links --to NOTE` returns NOTE's
  OUT-links and `--from NOTE` returns its BACKLINKS — the intuition inverts them
  (you'd expect `--from` to mean "links FROM this note"). Under THE LINK LAW the
  two sets agree, so a disagreement between `--to` and `--from` is a one-sided
  link defect to flag for the librarian. Lesson: verify directional CLI flags
  with an asymmetric fixture, not by name-intuition.

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

[^9]: [id: ATOM-BLQS-A2XW, status: valid, supersedes: ATOM-GLCB-AN5U, desc: "the publish-globally symlink ambiguity is real in code but had 0 instances on this corpus — measured 2026-08-27 after the owner challenged the claim", keywords: "reason_sounds_strongest_but_has_zero_instances code_implements_a_variant_nothing_exercises 50/50_guess_claim count_the_instances_before_ranking_an_argument enum_variant_with_no_live_cases", ocd: 2026-08-27, lmd: 2026-08-27] DO NOT rank an argument by how bad its failure mode SOUNDS when the failure has zero measured instances — I led this atom with "text cannot split the two missing-cases, so it hands the agent a 50/50 guess that could silently un-publish a page", which reads as the strongest of three reasons and was the weakest. BECAUSE the split is real in memgrep's CODE (four `PublishGloballyIssue` variants) but not in the CORPUS: measured 2026-08-27, of 29 PROJECT pages missing the field, **0** had a symlink — every one is unambiguously `MissingDefaultFalse`, so writing `false` would have been 29/29 correct, not a coin flip. The owner caught this by asking the obvious question I had not: a published page carries `publish-globally: true`, so when would the field be missing AND a symlink exist? DO count the live instances of a code path before citing it as a reason, and say the count out loud in the claim ("real in code, 0 instances here") — the verdict here still stands, but on reasons 2 (gate-silent ⇒ never dispatches ⇒ never loops) and 3 (self-heals on write), plus the fail-CLOSED `scope=None` trap in ATOM-OHWM-HR13. An enum variant is evidence that someone anticipated a case, never evidence that the case occurs. SUPERSEDED BODY: `memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the single-source repair-candidacy predicate) deliberately has NO check for it. The gap is CORRECT — rejected 2026-08-27 (TRDD-AO8MPK5D, `efad7a99`), recorded in `memory_content_precheck.py` beside the janitor#260 rejection. Three independent reasons: 1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads FILESYSTEM state — whether a USER-root symlink resolves to this page — splitting "field missing" into `MissingDefaultFalse` (no symlink → `false`) vs `MissingSymlinkImpliesTrue` (symlink present → `true`, evidence of intent). A text+path predicate cannot tell them apart, so it hands the agent a 50/50 guess whose wrong branch SILENTLY UN-PUBLISHES a page somebody deliberately published. 2. **It runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD/arbiter-CLEAR; this is gate-SILENT/lint-loud, so it never dispatches and never loops. 3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the sole write choke point and normalizes before AND after every write, unconditionally. Before adding ANY scope-gated check here, read `ATOM-OHWM-HR13` — the tidiest-looking variant is fail-CLOSED. STALENESS SIGNAL: the count GROWING across releases means pages are being written OUTSIDE the choke point; re-open only on that.
