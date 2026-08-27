---
name: feedback_memory_system_is_more_than_memgrep
description: "Is memgrep the whole memory system? No — what the AI-Maestro memory system actually is, and where the recall/write skills + the rule + the reference impl live (read before auditing or integrating 'the memory system') / how do I write a new wikimem memory page / never hand-write wikimem markdown / what are the memgrep write verbs / how do concurrent memory edits serialize / two agents edited the same memory page / the content of the wikimem file changed since your command was enqueued / is sed allowed on a memory page / how do I script an edit to a wikimem page without reading the whole page / a merge into an existing page fails verification / survivor slug reported as dangling / why did memory_edit_verify reject a legal merge / what is the flock and CAS protocol for memory writes / lost update on a memory page / does the memory system degrade to plain grep when memgrep is absent / where does the ai-maestro memory ecosystem rollout live"
ocd: 2026-06-08
lmd: 2026-06-13
metadata:
  node_type: memory
  type: feedback
  tier: component
  functionality: janitor
publish-globally: false
---

The AI-Maestro **memory system is NOT just memgrep.** memgrep is only the SEARCH
tool. The system is **{ tool · rules · skills · (optional) hooks }** (USER reframe,
2026-06-08):

- **tool** — `memgrep` (Rust, `<repo-root>/scripts/memgrep/`): markdown-AST
  recall engine; ranks notes by how a SYMPTOM query hits `description + title + tags`. [^1]
- **rule** — `$HOME/.claude/rules/markdown-memory-recall.md` (also shipped as the janitor
  plugin's `rules/markdown-memory-recall.md`, auto-installed by rules_installer):
  recall-before-acting, the note schema, the "index by question/symptom not answer
  jargon" law, the dual-test method.
- **skills** — the reference trio `skills/janitor-memory-recall/`,
  `skills/janitor-memory-write/`, `skills/janitor-memory-update/` in ai-maestro-janitor.
- **hooks (optional)** — an opt-in auto-recall on prompt.

**Why:** treating memgrep AS the whole system is the mistake — the audit found a
strong TOOL but an absent PROTOCOL layer (no rule, no distribution, partial skills).
The system only works when the rule + skills + tool are integrated.

**How to apply:** before auditing/extending/integrating "the memory system", look at
ALL four layers, not just the binary. Reference impl lives in ai-maestro-janitor;
the 13-repo ecosystem rollout is tracked in TRDD-ce195129. Distribution =
`cargo install --path scripts/memgrep` + prebuilt release binaries. Recall must always
degrade to plain `grep` when memgrep is absent. See also `[[memory-system]]` (the full
component page for this functionality) and [[memgrep-index-corrupt-fts-desync]] (the
binary layer's own index-corruption gotcha, a case where "just the binary" was not enough).


^ATOM-9AWW-4NCO [desc:"authoring routes through memgrep write verbs not hand-written md", keywords: how_to_write_a_wikimem_memory never_hand-write_wikimem_md use_memgrep_add-atom_new-page_add-lesson_verbs canonical_5-key_lesson_form atom_correct_by_construction_pass_only_body_and_keywords why_did_the_corpus_have_three_conflicting_lesson_schemas what_does_new-page_scaffold what_does_add-atom_emit does_the_wikimem-syntax_detector_self-validate_the_corpus is_it_ok_to_write_wikimem_markdown_by_hand, type: feedback, ocd: 2026-07-21, lmd: 2026-07-21]

Authoring a wikimem memory routes through memgrep WRITE VERBS, never a hand-written `.md` (owner directive 2026-07-21, TRDD-R02HTRUD): `memgrep new-page` scaffolds a valid page; `add-atom --page P --keywords "…"` (body on stdin) appends a canonical `^ATOM-… [keywords:…, ocd, lmd]`; `add-lesson --page P --atom ID --keywords "…"` emits the ONE canonical 5-key lesson `[id:ATOM-…, status:valid, keywords:"…", ocd, lmd]`. The tool synthesizes the id, dates, and bracket formatting so an atom is correct BY CONSTRUCTION — the agent passes only (body, keywords). The 3 skills (janitor-memory-write/-update/-recall) now call these verbs; only JUDGMENT stays as prose (TRDD-6RO0L3M0). The `wikimem-syntax` heartbeat detector self-validates the corpus (TRDD-VPTQ4067). This is why the pre-2026-07-21 corpus had drifted (three conflicting hand-written lesson schemas → 153 lean lessons, since migrated to 5-key, TRDD-5FNZ7ZKO).


^ATOM-XRNP-HR1J [desc:"every wikimem write path is scope-locked plus compare-and-swap, so a concurrent edit is refused rather than silently lost", keywords: the_content_of_the_wikimem_file_changed_since_your_command_was_enqueued two_agents_edited_the_same_memory_page lost_update_on_a_memory_page memgrep_write_refused wikimem_corruption_with_many_agents how_do_concurrent_memory_edits_serialize replace_X_with_Y_in_a_memory_page memgrep_edit_verb what_is_the_memory-maint_lock_file what_is_base-sha256_used_for how_do_rust_and_python_agree_on_the_same_lock, ocd: 2026-08-04, lmd: 2026-08-04]

Every wikimem WRITE path is scope-LOCKED and compare-and-swap guarded (USER directive 2026-08-03, TRDD-7YHT3FNK) — before this, memgrep's write verbs did a bare read→modify→write with NO lock and NO staleness check, so two agents touching one page silently lost an update. Now: (a) ONE lock protocol shared by two languages — `flock(EX)` on `global_state_dir()/memory-maint-<sha16>.lock`, where sha16 is the first 16 hex of sha256 over the REALPATH-resolved scope-root string (the nearest ancestor dir named `memory`); Rust and Python compute it byte-identically, so memgrep and the Python chore agents mutually exclude, and a symlinked page maps to its canonical scope's lock instead of forking a second one. (b) The write QUEUE is just the kernel's flock wait — memgrep's verbs block with a bounded timeout (`MEMGREP_LOCK_TIMEOUT_S`, default 10s) so concurrent writers serialize deterministically, while the Python txn core keeps skip-if-held (its callers are schedulers that re-fire). (c) Every write verb takes optional `--base-sha256 <hex>`: checked UNDER the lock, mismatch ⇒ nothing written + the canonical refusal "The content of the wikimem file changed since your command was enqueued. Please reread the file first." Verbs WITHOUT the flag are still lost-update-safe, because their read now happens inside the lock. [^2]


^ATOM-NVMU-74WO [desc:"memgrep edit is the sanctioned replace-X-with-Y primitive; raw-shell edits of a live memory page are a documented violation", keywords: replace_X_with_Y_in_a_memory_page memgrep_edit_verb how_do_I_script_an_edit_to_a_wikimem_page is_sed_allowed_on_a_memory_page ambiguous_match_refused_naming_the_count how_do_I_edit_a_page_without_reading_it_all_into_context is_a_heredoc_edit_to_a_memory_page_a_violation what_happens_on_zero_matches what_happens_on_more_than_one_match replace-all_flag_for_memgrep_edit, ocd: 2026-08-04, lmd: 2026-08-04]

`memgrep edit --page P --old-file F1 --new-file F2` is the sanctioned replace-X-with-Y primitive for a live wikimem page (TRDD-7YHT3FNK): plain substring, raw bytes, never a regex — applied only when the old text matches the page exactly and UNIQUELY. 0 matches or a `--base-sha256` mismatch gives the canonical refusal verbatim and writes nothing; more than one match is refused naming the count unless `--replace-all` opts in. It exists so an agent can edit a page WITHOUT reading the whole page into context, which is why it — not raw shell — is the scriptable path. The standing rule: a live page is edited ONLY via a memgrep write verb or the harness Edit tool; sed/heredoc/redirection is a documented violation because it carries neither the scope lock nor the CAS. On the refusal: re-read, recompute, retry — never force.


^ATOM-ODCG-MTZI [desc:"the merge verifier's dangling-reference check must exempt the survivor slug, or a legal merge is refused by its own guard", keywords: merge_refused_no_dangling_refs a_merge_into_an_existing_page_fails_verification memory_edit_verify_rejects_a_legal_merge survivor_slug_reported_as_dangling janitor_183 why_is_the_survivor_page_treated_as_dangling what_is_no_dangling_refs_checking a_set-difference_guard_broke_on_an_element_in_both_sides canonicalize_retired_links_rewrote_the_survivors_own_link why_do_wikilink_redirects_have_the_same_asymmetry, ocd: 2026-08-04, lmd: 2026-08-04]

`memory_edit_verify.no_dangling_refs` guards a merge by proving no surviving page still links a RETIRED slug. The bug (janitor#183): when a merge folds page A into page B, B is BOTH a retired source AND the survivor — so its own slug appeared in `retired_slugs`, every `[[B]]` link on the merged page read as dangling, and the verifier refused a legal merge. Fix: `verify_merge` passes `survivor_slug=survivor or None` and the check subtracts it — `retired = set(retired_slugs) - {survivor_slug}`. THE SHAPE, which is what transfers: a set-difference guard breaks the moment one element belongs to BOTH sides of the relation, and a merge is exactly that — the survivor is a source. Whenever a check says "none of X may appear in Y", ask which element is legitimately in both. `[[wikilink]]` redirects have the same asymmetry: `canonicalize_retired_links` must rewrite links TO the retired slugs but never the survivor's own. See [[wikimem-retrieval-engine]] for the parser-side defect class and [[memory-system]] for the merge protocol.

## Notes and lessons learned

[^1]: [id:ATOM-MG06-0016, status:valid, keywords:"path_in_memory_note_goes_stale memgrep_moved_tools_to_scripts cite_role_not_literal_path", ocd:2026-06-08, lmd:2026-06-13] The engine path moved: it was `tools/memgrep/`
  when this note was first written, relocated to `scripts/memgrep/` during the v0.7.0
  publish-unblock (CPV flagged `tools/` as a non-standard dir, RC-NONSTD-DIR-001).
  Lesson: a path in a memory note is the thing most likely to go stale — cite the
  symptom/role of a file, and re-verify the literal path against the current tree.
[^2]: [id:ATOM-TNIZ-U7TI, status:valid, keywords:"edited_a_memory_page_with_sed_or_a_heredoc raw_shell_edit_of_a_wikimem_page lost_update_on_a_memory_page my_memory_edit_disappeared", ocd:2026-08-04, lmd:2026-08-04] DO NOT edit a live wikimem page with raw shell (sed, a heredoc, `>` redirection) or a script, BECAUSE those paths hold neither the scope flock nor the `--base-sha256` CAS — a concurrent agent's write is then silently overwritten, and the loss is invisible until someone notices a fact is gone. DO route the edit through a memgrep write verb (`edit`/`add-atom`/`add-lesson`/`new-page`/`migrate`) or the harness Edit tool, and on the "changed since your command was enqueued" refusal re-read the page, recompute, and retry instead of forcing.
