---
name: memory-system-editor-gotchas
description: "add-atom inserts a new atom in the wrong place / atom-after-footer lint defect never converges / can I raise the atom budget knob / memgrep refused my write because the atom is too big / no memory chore runs on PROJECT scope by default / edit_project_scope / why did the repair chore skip my project page / does memgrep ever refuse a write outright / publish-globally-missing never drains / should I add publish-globally to repair_defect / scope=None suppresses a finding in a fail-open module / an argument whose failure mode has zero live instances / code implements a variant nothing exercises / memgrep binary is stale on this host / cargo install does not roll forward with a plugin update / what is the private user-memory subsystem / how does janitor-memory-user-share work / what is the retro-lesson chore and why does it exist / a superseded atom has no lesson attached"
ocd: 2026-06-13
lmd: 2026-09-03
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: janitor
  globs: [".claude/project/memory/**"]
  originSessionId: memory-audit-draft
publish-globally: false
split-lineage: c89f02722a424b5385204031e5db35ce
---

# Memory-system editor gotchas and the private user-memory store

Part of the [[memory-system]] functionality: the private user-memory store (a
separate, agent-invisible corpus), and the wikimem editor's own accumulated
operational gotchas -- the atom-insertion footer anchor, the atom-size
budget, the PROJECT-scope edit gate, the publish-globally field, the
retro-lesson chore, and per-host memgrep version skew. Split out of
[[memory-system]] 2026-09-03 to keep that page a navigable overview instead
of a dump -- see it for the scope model, the note format, the memgrep
engine, and the three authoring skills.

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


^ATOM-HO67-QC61 [desc: "no memory chore runs on PROJECT scope by default (edit_project_scope=False) — 81% of lint findings are therefore unreachable", keywords: the_lint_finding_count_never_goes_down a_memory_chore_never_fixes_project_pages why_did_the_repair_chore_skip_my_project_page edit_project_scope does_the_janitor_edit_.claude/project/memory memgrep_lint_findings_persist_forever a_completed_chore_pass_did_not_move_the_number edit_project_scope_defaults_false project_pages_are_out_of_every_chore_reach lint_findings_that_no_chore_can_drain, ocd: 2026-08-26, lmd: 2026-08-26]

NO memory chore ever runs on PROJECT scope by default, and this is the mechanism behind "the lint number never moves". `memory-maintenance._scopes_in_play` (`:135`) drops PROJECT from the eligible roots unless `memory_settings.get("edit_project_scope")` is on — and it defaults `False` (`memory_settings.py:61`). The rationale is sound and is NOT a bug: PROJECT memory is in-repo and unpushable outside `publish.py`, so an agent editing it would create commits nothing can push. MEASURED 2026-08-26: of 67 `memgrep lint` findings across all three roots, **54 (81%) were PROJECT-scope** — 29 `publish-globally-missing` and 25 `atom-after-footer` on 10 pages — i.e. structurally unreachable by every chore, no matter how correct the per-chore candidacy predicate is. This is the missing half of janitor#276's note that *"a completed pass could not move the number, so the same line repeated forever"*: #276 correctly fixed the PROMOTION (a severity regex matching ERROR inside the clause negating it) and left the immovability as background. The immovability is the scope gate. Consequence for anyone diagnosing a chore: the scope gate runs BEFORE the candidacy predicate, so confirm the target root is in the eligible set before reading the predicate that judges it — see [[git-index-lock-orphan-recovery]] for the same "correct mechanism that never reaches its case" shape in a different subsystem, and TRDD-AO8MPK5D for a card that named the predicate as the cause and had to be corrected. [^8]




^ATOM-OHWM-HR13 [desc: "Never gate a memory-precheck defect check on an optional scope/path discriminator — it would be the first None-path in that module that SUPPRESSES a finding (fail-CLOSED in a fail-OPEN module)", keywords: scope=None_suppresses_a_finding gate_a_precheck_check_on_scope_label fail-closed_None_default_in_memory_precheck repair_has_work_scope_optional add_a_scope-gated_defect_check never_gate_a_check_on_an_optional_discriminator fail_open_house_posture make_the_discriminator_required scope_gated_check_skips_silently first_none_path_that_suppresses, ocd: 2026-08-27, lmd: 2026-08-27]

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


^ATOM-GLCB-AN5U [desc: "publish-globally is NOT a repair-gate defect and must never be added to repair_defect — memgrep decides it from FILESYSTEM state, so page text cannot split the two missing-cases", keywords: publish-globally-missing_never_drains lint_count_stuck_at_29 add_publish-globally_to_repair_defect widen_repair_defect_signature gate_and_arbiter_parity_publish-globally repair_chore_does_not_fix_publish-globally publish-globally_missing_29_pages symlink_evidence_of_publish_intent normalize_on_write_self_heals gate_silent_never_dispatches, ocd: 2026-08-27, lmd: 2026-08-27]

`memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the
single-source repair-candidacy predicate) deliberately has NO check for it. The gap is CORRECT —
rejected 2026-08-27 (TRDD-AO8MPK5D, `efad7a99`), recorded in `memory_content_precheck.py` beside
the janitor#260 rejection. Three independent reasons:

1. **The symlink split is real in CODE but had ZERO instances here.** `publish_globally_state`
   (`memory.rs:4878`) reads FILESYSTEM state — whether a USER-root symlink resolves to this page —
   splitting "field missing" into `MissingDefaultFalse` (no symlink → `false`) vs
   `MissingSymlinkImpliesTrue` (symlink present → `true`, evidence of intent). MEASURED 2026-08-27:
   of 29 PROJECT pages missing the field, **0** had a symlink, so `false` would have been 29/29
   correct. Treat this as the WEAKEST reason, not the strongest — see the lesson below.
2. **It runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD/arbiter-CLEAR;
   this is gate-SILENT/lint-loud, so it never dispatches and never loops.
3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the sole write choke point and
   normalizes before AND after every write, unconditionally.

Before adding ANY scope-gated check here, read `ATOM-OHWM-HR13` — the tidiest-looking variant is
fail-CLOSED. STALENESS SIGNAL: the count GROWING across releases means pages are being written
OUTSIDE the choke point; re-open only on that. [^9]

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



## Governed by

- [[memory-system]] -- the functionality hub this page is one part of.

## See also

- [[memory-system]] -- the overview and parts map.
- [[memory-system-tooling-and-protocol]] -- the memgrep engine and heartbeat
  detectors these gotchas are gotchas ABOUT.
- [[memory-system-superseded-history]] -- the retired predecessor atoms of the
  publish-globally chain this page's live atom (ATOM-GLCB-AN5U) now states.
- [[git-index-lock-orphan-recovery]] -- the same "correct mechanism that never
  reaches its case" shape in a different subsystem.

## Notes and lessons learned

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

[^6]: [id:ATOM-Y1XB-UMXQ, status:valid, desc:"janitor#165 — the reported symptom was unreproducible here because the reporter's memgrep predated the fix.", keywords:"another_host_reports_a_finding_i_cannot_reproduce filed_a_bug_for_a_stale_binary cross_host_discrepancy_is_not_always_a_code_defect", ocd:2026-08-02, lmd:2026-08-02] DO NOT treat "another host reports a finding this host cannot reproduce" as proof of a code defect, BECAUSE any per-host-compiled tool (memgrep) can run older logic indefinitely while both hosts sit on the same plugin version, so the discrepancy is evidence about the BINARIES before it is evidence about the code. DO reconcile the binaries first (`cargo install --path scripts/memgrep`), and say which half you actually verified when you answer.

[^7]: [id:ATOM-ZJE4-9AOD, status:valid, desc:"lesson-uncited is EXPECTED on an aspect/methodology page — cite only what passes the travel test", keywords:"lesson-uncited_findings should_I_cite_every_uncited_lesson is_a_page-level_lesson_a_defect bulk-citing_to_clear_the_linter does_this_lesson_travel_with_the_atom 27_lesson-uncited_on_one_corpus", ocd:2026-08-05, lmd:2026-08-05] DO NOT clear `lesson-uncited` findings by citing them from whatever atom is nearest, BECAUSE a citation is a CLAIM that the lesson TRAVELS with that atom — a fabricated one would carry the lesson away from its page in a later split — and on an aspect/methodology page most lessons are page-level BY DESIGN: they are the shared method, owned by the page, not by one atom. DO apply the travel test per lesson ("if this atom moved to another page, would this lesson have to follow?"), cite only where the answer is yes, and RECORD the verdict so the next session does not re-derive it. Measured 2026-08-05 on debugging-methodology.md: of 7 uncited lessons only 2 passed — `[^7]` (idle-calibrated timeout) to the SLOW-vs-STUCK atom, and `[^8]` (a linter green over zero files) to the "a summarizer cannot prove absence" atom, which already cited `[^8]`'s own declared sibling `[^4]`. The other 5 were correct as-is. Two supports: `memgrep add-lesson` REQUIRES `--atom`, so an uncited lesson is legacy or hand-authored rather than a fresh defect; and the code is ORPHANED (no chore gate detects it — janitor#200), so nothing will ever dispatch to "fix" it for you.
ONE SUBCLASS DOES HAVE AN OWNER: on a page with ZERO atoms, "cite it from an atom" is
IMPOSSIBLE advice — the page is free prose and the real fix is to ATOMIZE it, which
`atomize_has_work` (pages with no atom markers at all) genuinely covers. Verified 2026-08-05:
5 of 13 flagged pages were zero-atom, carrying 6 of the 20 residual findings.

[^8]: [id: ATOM-LATA-4NGJ, status: valid, desc: "a TRDD body is not a recall surface — recall indexes memory pages, never design/tasks", keywords: "I_rediscovered_something_a_TRDD_already_recorded is_this_finding_actually_new does_memgrep_recall_search_the_design_tasks_folder a_fact_that_lives_only_in_a_card_body why_did_I_re-derive_a_known_mechanism prior_art_check_before_filing_a_card", ocd: 2026-08-26, lmd: 2026-08-26] DO NOT treat a finding you reached by reading source as NEW without searching the TRDD corpus for it first, BECAUSE a card body is not a recall surface: TRDD-LFSWY0C6 recorded this exact PROJECT-gate finding on 2026-08-13 — same file, same two line numbers, same "silently disabled on every default install" conclusion — and I re-derived it from scratch 13 days later, then wrote it up as though it were new and let a second card (TRDD-AO8MPK5D) inherit that framing. `memgrep recall` searches MEMORY pages only; nothing indexes `design/tasks/*.md`, so a fact that lives solely in a card is invisible to the retrieval path every session actually uses. DO grep `design/tasks/` for the symbol or setting name (here `edit_project_scope`) alongside the memory recall before claiming a mechanism is unrecorded — and when the grep hits, MIGRATE the fact to a memory page and cite the card, which is what this atom now is.

[^9]: [id: ATOM-BLQS-A2XW, status: valid, supersedes: ATOM-GLCB-AN5U, desc: "the publish-globally symlink ambiguity is real in code but had 0 instances on this corpus — measured 2026-08-27 after the owner challenged the claim", keywords: "reason_sounds_strongest_but_has_zero_instances code_implements_a_variant_nothing_exercises 50/50_guess_claim count_the_instances_before_ranking_an_argument enum_variant_with_no_live_cases", ocd: 2026-08-27, lmd: 2026-08-27] DO NOT rank an argument by how bad its failure mode SOUNDS when the failure has zero measured instances — I led this atom with "text cannot split the two missing-cases, so it hands the agent a 50/50 guess that could silently un-publish a page", which reads as the strongest of three reasons and was the weakest. BECAUSE the split is real in memgrep's CODE (four `PublishGloballyIssue` variants) but not in the CORPUS: measured 2026-08-27, of 29 PROJECT pages missing the field, **0** had a symlink — every one is unambiguously `MissingDefaultFalse`, so writing `false` would have been 29/29 correct, not a coin flip. The owner caught this by asking the obvious question I had not: a published page carries `publish-globally: true`, so when would the field be missing AND a symlink exist? DO count the live instances of a code path before citing it as a reason, and say the count out loud in the claim ("real in code, 0 instances here") — the verdict here still stands, but on reasons 2 (gate-silent ⇒ never dispatches ⇒ never loops) and 3 (self-heals on write), plus the fail-CLOSED `scope=None` trap in ATOM-OHWM-HR13. An enum variant is evidence that someone anticipated a case, never evidence that the case occurs. SUPERSEDED BODY: `memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the single-source repair-candidacy predicate) deliberately has NO check for it. The gap is CORRECT — rejected 2026-08-27 (TRDD-AO8MPK5D, `efad7a99`), recorded in `memory_content_precheck.py` beside the janitor#260 rejection. Three independent reasons: 1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads FILESYSTEM state — whether a USER-root symlink resolves to this page — splitting "field missing" into `MissingDefaultFalse` (no symlink → `false`) vs `MissingSymlinkImpliesTrue` (symlink present → `true`, evidence of intent). A text+path predicate cannot tell them apart, so it hands the agent a 50/50 guess whose wrong branch SILENTLY UN-PUBLISHES a page somebody deliberately published. 2. **It runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD/arbiter-CLEAR; this is gate-SILENT/lint-loud, so it never dispatches and never loops. 3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the sole write choke point and normalizes before AND after every write, unconditionally. Before adding ANY scope-gated check here, read `ATOM-OHWM-HR13` — the tidiest-looking variant is fail-CLOSED. STALENESS SIGNAL: the count GROWING across releases means pages are being written OUTSIDE the choke point; re-open only on that.
