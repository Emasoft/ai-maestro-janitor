# Changelog

All notable changes to this project will be documented in this file.

## [0.13.0] - 2026-06-20

### Bug Fixes

- Split candidate-scan excludes private/generated files + portable (TRDD-87935f21)
- Resolve [[name]] wikilinks by frontmatter name:, not just file-stem (#49)
- Clear CPV --strict on the new harvest skill + index-rule content (TRDD-a5780c23)

### Documentation

- Scope-migration helper design — ai-maestro corpus option b (TRDD-47df698b)
- Memgrep-managed index + editor anti-corruption (TRDD-a5780c23)
- Part A done (MEMORY.md retired in rule+skills); remaining 3 itemized (TRDD-a5780c23)
- Harvest chore — incorporate stray memory artifacts (MEMORY.md + loose .md) into the wiki daily, non-destructive (TRDD-a5780c23)

### Features

- Retire the context-loaded MEMORY.md — recall is memgrep-only (TRDD-a5780c23)
- Add `overview`command — print the <project>-overview.md entry page (TRDD-a5780c23)
- <project>-overview.md entry page + wire `memgrep overview`into the stub (TRDD-a5780c23)
- Verify body-fact fidelity — passes can no longer paraphrase/drop a fact (TRDD-a5780c23, #48)
- Harvest chore — daily non-destructive incorporation of stray memory into the wiki (TRDD-a5780c23 Part C)

