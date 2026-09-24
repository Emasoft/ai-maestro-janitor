---
name: reference_memgrep_links_to_from_semantics
description: "memgrep links --to --from look inverted / backlinks vs out-links confusion / which flag shows who points at a page / does --to mean out-links or backlinks / does --from mean out-links or backlinks / memgrep links --to NOTE shows NOTE's out-links / memgrep links --from NOTE shows NOTE's backlinks / how was the inverted intuition first documented wrong / does fm.KEY match nested frontmatter at any depth / does fm.metadata.tier work as a dotted path / where does --where live on the memgrep command / why did a symmetric link fixture fail to catch the inversion / how to verify a CLI's directional flags with an asymmetric fixture / what confirms any hypothesis about link direction / see also memory-system for the wikimem model"
ocd: 2026-06-10
lmd: 2026-09-24
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: janitor
publish-globally: false
---

^I3P7THOS [desc: "memgrep links --to returns out-links; --from returns backlinks; --where lives on the main grep command; fm.KEY matches nested frontmatter at any depth, a dotted path does not", keywords: "memgrep_links_to_from_look_inverted backlinks_vs_out_links_confusion which_flag_shows_who_points_at_a_page does_to_mean_out_links_or_backlinks does_from_mean_out_links_or_backlinks does_fm_key_match_nested_frontmatter_at_any_depth does_fm_metadata_tier_work_as_dotted_path where_does_where_live_on_memgrep_command how_to_verify_cli_directional_flags_with_asymmetric_fixture what_confirms_any_hypothesis_about_link_direction", type: reference, ocd: 2026-06-10, lmd: 2026-09-24]
memgrep `links` flags read relative to the NAMED note, not the link arrow
(verified live, memgrep 0.1.0 `--help` + asymmetric fixture):

- `memgrep links --to NOTE` = NOTE's **OUT-links** (the pages NOTE points at) —
  record lines `note.md:LINE -> target [path]`.
- `memgrep links --from NOTE` = NOTE's **BACKLINKS** (who points at NOTE) —
  bare paths.

Intuition writes them the other way round — the skills docs were initially
authored backwards.[^1] Also verified: `fm.KEY` in `--where` matches the key at
ANY frontmatter depth (`fm.tier` reaches the nested `metadata.tier`; a dotted
`fm.metadata.tier` does NOT work), and `--where` lives on the MAIN grep command
(`memgrep -l . <dir> --where '…' | sort -u`), never on `find`. Canonical
reference: the wikimem-model memgrep table +
`tests/test_wikimem_fixture.py` (which locks these semantics with real-binary
tests). See also `[[memory-system]]`.

## Notes and lessons learned
[^1]: [id:ATOM-MG06-0018, status:valid, keywords:"links_from_to_inverted verify_cli_flags_with_asymmetric_fixture symmetric_fixture_confirms_any_hypothesis", ocd:2026-06-10, lmd:2026-06-10] the first draft of the wikimem skills
  documented `links --from` as out-links and `--to` as inbound — exactly
  inverted. The error: writing tool docs from the preposition's English reading
  instead of probing the binary. A confounded probe (two pages linking each
  other) hid it; only an ASYMMETRIC fixture (A→B, no B→A) exposed the real
  semantics. Lesson: verify a CLI's directional flags with an asymmetric case —
  a symmetric one confirms any hypothesis.
