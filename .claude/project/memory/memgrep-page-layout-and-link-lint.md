---
name: memgrep-page-layout-and-link-lint
description: "a new atom landed inside the Superseded section / new-mem-atom merge split or migrate put an atom under retired atoms / where does memgrep insert a new atom on a page / what is page_layout.rs layout_boundary / lint says foreign-content-in-link-section WMLINK-003 / hidden link in a See also section code span names a page / rewriting a link section lost content silently / WM-LINT-12 report-only no fixer / WMATOM-009 atom after footer remedy / refuse_cross_page_duplicate_ids pre_write.rs duplicate atom id on two pages / link_section_lint.rs note_link_keys / mem_merge.rs mem_split.rs mem_reference.rs superseded_move.rs / lint coverage table rows 47 to 48 / issue 289 memgrep atom placement / issue 358 memgrep link section lint"
ocd: 2026-11-19
lmd: 2026-11-19
publish-globally: false
metadata:
  node_type: memory
  type: reference
  tier: component
---

# memgrep-page-layout-and-link-lint


^ATOM-PXHL-5ADC [desc: "page_layout.rs layout_boundary puts new atoms above ## Superseded so merge, split and migrate no longer file atoms inside retired text", keywords: new_atom_landed_inside_the_Superseded_section new-mem-atom_put_atom_under_retired_atoms page_layout.rs_layout_boundary_footer_section_line memgrep_atom_splice_position mem_merge.rs_mem_split.rs_mem_reference.rs_memory.rs_splice superseded_move.rs_fixer_unchanged WMATOM-008_retired_atoms_after_Superseded_heading See_also_section_joins_first_link_heading issue_289_memgrep page_with_Superseded_above_link_sections, type: reference, trdd: TRDD-8MVESX28, ocd: 2026-11-19, lmd: 2026-11-19]

New atoms land ABOVE ## Superseded (b4509f61, issue 289, TRDD-8MVESX28). Why: footer_section_line ignored ## Superseded, so on a page whose Superseded section sits above the link sections (4 PROJECT pages at the time) or has no link sections (2 PROJECT, 2 USER) a plain new-mem-atom, merge, split or migrate put the new atom INSIDE the retired section. scripts/memgrep/src/page_layout.rs now holds the four boundary scanners (moved byte-identical apart from pub(crate), so no lint verdict changes) and the new layout_boundary: the earliest of the first link heading, ## Superseded and Notes, computed on a frontmatter-free body; all atom splices (mem_merge.rs, mem_split.rs, mem_reference.rs, memory.rs) use it. New See also sections join the first existing link heading so link sections never split around Superseded; merged retired atoms go right after an existing ## Superseded heading, where WMATOM-008 expects them. NOT changed: the superseded-move fixer (scripts/memgrep/src/fixers/superseded_move.rs) and the trailing lint boundary, because retargeting them changes what atom-after-footer can see (a later increment). Watch for it: an atom that appears below a ## Superseded heading on an old binary was put there by the bug, not by the author.


^ATOM-EHTI-1PRG [desc: "WMLINK-003 reports foreign content in a link section as a report-only WARN with no fixer; refuse_cross_page_duplicate_ids duplicate-id cases are pinned", keywords: lint_foreign-content-in-link-section WMLINK-003_WM-LINT-12_warn hidden_link_in_See_also_code_span_names_a_page link_section_rewrite_lost_content_silently issue_358_memgrep_link_section_grammar link_section_lint.rs_note_link_keys WMATOM-009_remedy_message lint_coverage_table_47_to_48_rows rules_gen.rs_main.rs_registration remove_code_span_keep_annotation_then_reference-mem-topic refuse_cross_page_duplicate_ids_pre_write.rs_old=2 same_atom_id_on_two_pages_refused, type: reference, trdd: TRDD-QAF3N673, ocd: 2026-11-19, lmd: 2026-11-19]

Lint rule WMLINK-003 foreign-content-in-link-section (WM-LINT-12, 34f1cd29, TRDD-QAF3N673, issue #358), implemented in scripts/memgrep/src/link_section_lint.rs (emitter; registered through rules_gen.rs and main.rs; page_layout.rs and memory.rs support): issue #358 showed that nothing reported content a link section's grammar makes foreign (hidden code-spanned links, prose, atoms, footnotes, link-less bullets), so a rewrite of such a section could lose it silently, and the installed rule saw only an atom in the trailing footer run, never one in a mid-page See also. It is WARN, fix none, no gate floor, REPORT-ONLY: no fixer, because a safe fixer may not move text that resolve_atoms_from_text would absorb. Classification follows the WM-NOTE-10 order: HIDDEN LINK first (same-target reading), EDGE, PLACEHOLDER, POINTER, SCOPE POINTER, else foreign. Own-scope names resolve through note_link_keys (the key set build_graph registers) from a lazy per-scope-root index; symlinked pages are skipped (linted in their owning scope); an atom marker WMATOM-009 already reports is skipped so one defect gives one finding; one finding per foreign block, and a line holding a raw [[target]] outside a bullet is one finding per line. The message of WMATOM-009 now states the exact remedy; the coverage table (tests/test_memory_lint_gate_coverage.py, docs/ISSUE-CODES.md through issue_codes_gen.py) went from 47 to 48 rows. Dry run with a release build: WMLINK-003 on 22 PROJECT and 205 USER findings, WMATOM-009 0 on all three stores. NOT installed yet (TRDD-QAF3N673 increments 3 and 4 install together, once the write gate refuses a link-heading deletion). Remedy when it fires on a code span naming a page: remove the code span in place keeping the annotation, then add the typed link on both ends with reference-mem-topic. Also fd8e989d (TRDD-XI10BA5D): scripts/memgrep/src/pre_write.rs refuse_cross_page_duplicate_ids has pinned tests for the inherited old=2 duplicate-id cases (the same atom id already on two pages).


## See also

- [[wikimem-retrieval-engine]]
- [[memory-system]]

## Notes and lessons learned
