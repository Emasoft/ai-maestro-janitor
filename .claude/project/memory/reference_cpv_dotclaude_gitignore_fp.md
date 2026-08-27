---
name: reference_cpv_dotclaude_gitignore_fp
description: "CPV --strict blocks the janitor publish on .gitignore missing coverage for .claude/ / why can't the .claude gitignore MINOR be satisfied / is this a filed false positive not something to fix in our gitignore / claude-plugins-validation issue 120 / does git check-ignore .claude exit 0 when we track .claude/project/memory / can git re-include a path under an excluded parent directory / why not add a bare .claude/ gitignore line / would a bare .claude/ line untrack the memory corpus / when does this publish block auto-unblock / should PROJECT memory move out from under .claude to dodge this check / validate_skill.py broken file reference two different fence handling checks / why does a markdown link example inside a fenced template still trip validate_supporting_files / how to clear a Referenced file not found finding in SKILL.md / does a fenced bash block strip literal paths from the check"
ocd: 2026-06-14
lmd: 2026-06-14
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: publish
publish-globally: false
---

CPV `--strict` emits **`[MINOR] .gitignore missing coverage for: Claude Code cache
directory (.claude/)`** and blocks the janitor publish (exit ≥2). This is a **filed
false positive — `claude-plugins-validation#120`** — do NOT try to "fix" it in our
`.gitignore`; it is **mathematically unsatisfiable** alongside our memory design.

**Root cause (verified in CPV source):** `validate_plugin.py:3970`
`_gitignore_covers_category` decides coverage by running `git check-ignore -q -- .claude`
(covered ⇔ exit 0). `git check-ignore .claude` only exits 0 if the **`.claude` directory
entry itself** is ignored. But we DELIBERATELY track `<repo>/.claude/project/memory/**`
(the PROJECT memory scope), which forces the deep gitignore form `.claude/**` +
`!.claude/project/memory/**` — and `git` **cannot re-include a path under an excluded
parent** (`man gitignore`). So `git check-ignore .claude` necessarily exits 1 → CPV
flags it. No gitignore both (a) makes `git check-ignore .claude` exit 0 AND (b) keeps the
memory dir trackable; the two are mutually exclusive.

**How to apply:** when a janitor publish fails CPV `--strict` with ONLY this `.claude/`
MINOR, the plugin is otherwise clean — the publish **auto-unblocks when CPV ships the #120
fix** (the pipeline fetches CPV fresh via `uvx --from git+…`). The alternative (the USER's
call) is to move PROJECT memory out from under `.claude/` to dodge the check entirely. Do
NOT add a bare `.claude/` gitignore line (it prunes the dir and silently un-tracks the
memory corpus). See [[project_janitor_publish_blocked_cpv_fps]] for the broader CPV
publish-gate FP history and [[memory-system]] for why memory lives under `.claude/`.

## Notes and lessons learned
[^1]: [id:ATOM-MG05-0018, status:valid, keywords:"validate_skill_no_fence_exemption two_skill_reference_checks_differ broken_file_reference_markdown_link", ocd:2026-06-14, lmd:2026-06-14] the CPV publish gate has TWO separate skill-reference
  checks with DIFFERENT fence handling: `validate_skill.py:680` (`validate_supporting_files`)
  regex-flags ANY non-resolving `[text](path)` markdown link in SKILL.md with **no fence or
  placeholder exemption** (a `[architecture](architecture.md)` example inside a ```` ```markdown ````
  template fence still trips it); the comprehensive validator's "Broken file reference" check
  is the lenient one that DOES strip fences and honor `<path>`/`{path}`/`example-` placeholders.
  Lesson: to clear a `validate_skill.py` "Referenced file not found", the `[](…)` pattern must
  not appear at all unless it resolves — describe the format in prose, keep literal paths inside
  fenced **bash** (stripped). Don't trust the "fenced content is stripped" hint; it's only one
  of the two checks.
