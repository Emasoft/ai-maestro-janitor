---
name: feedback_memory_system_is_more_than_memgrep
description: "Is memgrep the whole memory system? No — what the AI-Maestro memory system actually is, and where the recall/write skills + the rule + the reference impl live (read before auditing or integrating 'the memory system')."
ocd: 2026-06-08
lmd: 2026-06-13
metadata:
  node_type: memory
  type: feedback
  tier: component
  functionality: janitor
---

The AI-Maestro **memory system is NOT just memgrep.** memgrep is only the SEARCH
tool. The system is **{ tool · rules · skills · (optional) hooks }** (USER reframe,
2026-06-08):

- **tool** — `memgrep` (Rust, `<repo-root>/scripts/memgrep/`): markdown-AST
  recall engine; ranks notes by how a SYMPTOM query hits `description + title + tags`.
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


^ATOM-9AWW-4NCO [desc:"authoring routes through memgrep write verbs not hand-written md", keywords: how_to_write_a_wikimem_memory never_hand-write_wikimem_md use_memgrep_add-atom_new-page_add-lesson_verbs canonical_5-key_lesson_form atom_correct_by_construction_pass_only_body_and_keywords, type: feedback, ocd: 2026-07-21, lmd: 2026-07-21]

Authoring a wikimem memory routes through memgrep WRITE VERBS, never a hand-written `.md` (owner directive 2026-07-21, TRDD-R02HTRUD): `memgrep new-page` scaffolds a valid page; `add-atom --page P --keywords "…"` (body on stdin) appends a canonical `^ATOM-… [keywords:…, ocd, lmd]`; `add-lesson --page P --atom ID --keywords "…"` emits the ONE canonical 5-key lesson `[id:ATOM-…, status:valid, keywords:"…", ocd, lmd]`. The tool synthesizes the id, dates, and bracket formatting so an atom is correct BY CONSTRUCTION — the agent passes only (body, keywords). The 3 skills (janitor-memory-write/-update/-recall) now call these verbs; only JUDGMENT stays as prose (TRDD-6RO0L3M0). The `wikimem-syntax` heartbeat detector self-validates the corpus (TRDD-VPTQ4067). This is why the pre-2026-07-21 corpus had drifted (three conflicting hand-written lesson schemas → 153 lean lessons, since migrated to 5-key, TRDD-5FNZ7ZKO).

## Notes and lessons learned

[^1]: [id:ATOM-MG06-0016, status:valid, keywords:"path_in_memory_note_goes_stale memgrep_moved_tools_to_scripts cite_role_not_literal_path", ocd:2026-06-08, lmd:2026-06-13] The engine path moved: it was `tools/memgrep/`
  when this note was first written, relocated to `scripts/memgrep/` during the v0.7.0
  publish-unblock (CPV flagged `tools/` as a non-standard dir, RC-NONSTD-DIR-001).
  Lesson: a path in a memory note is the thing most likely to go stale — cite the
  symptom/role of a file, and re-verify the literal path against the current tree.
