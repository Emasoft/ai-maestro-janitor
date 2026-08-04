---
name: wikimem-retrieval-engine
description: "recall returned the wrong page / why is a memory search so expensive / what does memgrep rank on / lint fails on everything and I cannot find the real errors / how do I hop from a search result to the"
ocd: 2026-07-26
lmd: 2026-07-26
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: janitor
---

# wikimem-retrieval-engine


^ATOM-FQHJ-ZCCK [desc:"recall is TWO HOPS — a lean triage row, then one exact fetch by locator", keywords: why_is_a_memory_search_so_expensive how_do_I_get_the_full_atom_after_a_search what_does_recall_actually_print memory_listing_costs_too_many_tokens, type: project, ocd: 2026-07-26, lmd: 2026-07-26]

Retrieval is deliberately two hops: `recall <symptom>` prints ONE lean row per hit
(`<lmd>⇥<locator>⇥<description>`, tab-separated), then `recall <locator>` fetches that one element
in full. Cost is measured END-TO-END — `tokens(search) + tokens(the hop it forces)` — because a
per-call metric flatters a thin list that hides its hop and punishes a fat one-shot that needs
none. `--output medium|full` exist; `full` is a DEBUGGING layer, not a richer default, and it is
the only one that prints lessons, keywords and the score.


^ATOM-HI7N-NLPS [desc:"a locator is an IDENTITY and an exact key — never a filesystem path", keywords: recall_printed_a_huge_absolute_path what_is_the_locator_column can_I_look_up_a_page_by_name page_row_costs_more_than_the_atom, type: project, ocd: 2026-07-26, lmd: 2026-07-26]

A lean row's locator is an atom id, or a page's frontmatter `name:` — never a path. Measured:
page rows are 35-39% of all result rows and an absolute path costs ~90 tokens each, ~80-110 per
query. It is `name:` and not the file stem because wikilinks resolve through `name:` and the two
differ on ~3% of pages; printing the stem would give those pages a second address the wiki never
uses. Every printed locator is an EXACT lookup (`recall <atom-id>` or `recall <page-name>`), which
is the point: a locator that only usually resolves teaches trust in a key that fails one day.


^ATOM-BY9Z-PBZZ [desc:"the scorer is TIERED, which is why rank-1 ties effectively do not happen", keywords: recall_returned_the_wrong_page_first does_the_keyword_order_matter should_I_add_a_tie-break_to_ranking why_did_my_keyword_migration_change_nothing, type: project, ocd: 2026-07-26, lmd: 2026-07-26]

Scoring is tiered, not a flat hit count: exact keyphrase (1000) >> contiguous phrase inside a
keyword (100) >> all query words present (10) >> each word (1), with token-aware matching so `cat`
does not match `concatenate`. Consequence worth knowing before touching ranking: an exact-keyword
hit is claimed by ONE atom, so rank 1 is decided outright — measured 0 ties in 203 exact-phrase
queries and 1 in 201 half-remembered ones. Tie-breaks after `score` therefore almost never fire;
`lmd` is the only one implemented, and adding more was rejected on that measurement.


^ATOM-SOZ7-C672 [desc:"lint prints every finding but gates only on ERROR", keywords: memgrep_lint_fails_on_everything I_cannot_find_the_real_errors why_is_an_uncited_footnote_reported min-severity_flag, type: project, ocd: 2026-07-26, lmd: 2026-07-26]

`memgrep lint` classifies every finding ERROR/WARN/INFO and prints ALL of them; `--min-severity`
(default `error`) moves only the EXIT CODE. INFO is a shape the model BLESSES — an uncited `[^N]:`
page-level lesson, which was 57% of all findings when it was rated an error, so the gate failed on
every corpus. WARN is real but not fixable from the page being edited (one-sided link) or needs a
semantic judgement (oversized atom). ERROR is corruption or invisibility. On the live USER scope:
161 findings, 8 ERRORs. [^1]

## See also

- `[[memory-system]]` — the surrounding system this engine serves: the three scopes, where
  memories live, and the recall-before-acting protocol.


^ATOM-B9G7-XSR8 [desc:"memgrep default-excludes status:superseded atoms from search (recall+find); --include-superseded restores; addressed second-hop always returns them", keywords: recall_does_not_return_an_atom_that_exists superseded_atom_missing_from_search_results where_did_the_old_atom_go include_superseded_flag search_shows_obsolete_facts, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

Since TRDD-57WJL5L2 (commit cceb229), memgrep DEFAULT-EXCLUDES `status:superseded` atoms from every SEARCH path — recall + find, walk + index-backed, all four filtered at the consumer side. `--include-superseded` (on recall and find) restores them, rendered with a `[SUPERSEDED → <lesson-id>]` tag. Two deliberate exceptions: ADDRESSED lookups (`recall <ATOM-ID>` / `recall <page-name>`) always return superseded content with no flag — an explicit address is an explicit request — and superseded LESSONS stay searchable (pre-existing render_lesson_line design intent; the exclude is keyed on ATOM status only, from the atom's own `status:` prop, never body position). Lint enforces the readability layer: WARN `superseded-atom-above-delimiter` (superseded atom above a `## Superseded` heading) and WARN `superseded-atom-no-delimiter-heading` (superseded atoms but no heading; the fence-aware SSOT is `superseded_heading_line`). The reorder pass that clears those WARNs is TRDD-QKWU26ZG.


^ATOM-UFZJ-DKHV [desc:"a delimiter inside an unescaped value is memgrep's recurring parser defect, and it hides itself because recall still appears to work", keywords: keywords_went_missing_from_a_lesson lint_says_no_keywords_but_they_are_right_there_on_disk the_write_verb_produced_what_its_own_lint_rejects a_bracket_in_a_desc_broke_parsing recall_still_finds_it_so_the_lint_must_be_wrong, ocd: 2026-08-04, lmd: 2026-08-04]

memgrep's recurring parser defect is ONE class: a DELIMITER appearing inside a VALUE it was never escaped out of. Three instances, all different sites — janitor#138 (a truncated `keywords:` makes an atom unretrievable), janitor#152 (a `[^N]` inside a code span is invisible to lint), janitor#184 (a `[` inside a quoted `desc:` desyncs the `[`…`]` metadata scan, so `keywords:"…"` is parsed as the lesson BODY). #184 is the worst because it is reachable from the WRITE side: `add-lesson --desc` takes free prose, so the SANCTIONED verb produced what its own lint rejected. THE TRAP, and why this is worth remembering: **the failure hides itself.** A symptom query still finds the affected lesson — by full-texting the leaked metadata now sitting in the body — so a maintainer who reacts to the WARN by testing recall concludes the lint is wrong and moves on, while the structured field is gone. Retrievable by accident, not by its recall surface. FIX SHAPE: make the READER quote-aware, never escape-on-write. Escaping repairs only pages written after the fix; a quote-aware reader repairs the whole existing corpus at once — proven on #184, where the untouched repro page went from 1 finding to lint-exit=0 under the rebuilt binary. Always leave a fallback to the old scan for malformed input, so the fix cannot add a loss mode that did not already exist. [^2]

## Notes and lessons learned

[^1]: [id:ATOM-I4FM-82K6, status:valid, desc:"the lint was right and the parser was wrong — documenting the grammar declared atoms", keywords:"lint_flags_my_own_documentation_page prose_example_became_a_real_atom duplicate_atom_id_I_never_wrote is_this_lint_finding_a_false_positive documenting_a_syntax_is_not_using_it", ocd:2026-07-28, lmd:2026-07-28] DO NOT dismiss a lint finding that fires on a page DOCUMENTING the syntax as a false positive, BECAUSE the atom parser scanned the whole line, so `^id [k: v]` written inside backticks declared 13 REAL atoms — four sharing one id, a collision no author wrote. DO fix the parser (anchor the marker at line start) instead: the lint was right and the defect was one layer deeper, in the code that feeds the index.
[^2]: [id:ATOM-9MBI-LL4R, status:valid, desc:"a parse WARN that recall seems to contradict is the parser being right and recall succeeding by accident", keywords:"lint_warns_but_recall_still_finds_it the_warning_must_be_a_false_positive keywords_are_right_there_in_the_file memgrep_lint_disagrees_with_memgrep_recall", ocd:2026-08-04, lmd:2026-08-04] DO NOT dismiss a memgrep parse/lint WARN because a symptom query still returns the page, BECAUSE a leaked metadata field lands in the BODY, where full-text search still matches it — so recall succeeding proves nothing about whether the STRUCTURED field survived, and the two tools are not disagreeing. DO open the raw page and confirm the field is where the model says it belongs before calling the finding a false positive.
