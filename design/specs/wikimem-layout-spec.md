---
spec: wikimem-layout
spec-version: 0.1.0
status: draft
created: 2026-10-23T17:20:00+0200
updated: 2026-10-23T17:20:00+0200
maintainer: ai-maestro-janitor
project-id: ai-maestro-janitor
requested-by: Emasoft (owner rulings PRRD G13-G26, 2026-10-23)
extends: wikimem-memgrep 2.5.0 (design/specs/wikimem-memgrep-spec.md) — where the two disagree, this draft wins once it is normative
relevant-rules: [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 25, 26]
---

# Wikimem layout, page identity, copies and cross-project import — DRAFT

Status DRAFT: decisions below are the agent's under PRRD G26.1 ("i leave the decisions to you … bade your decisions on verified facts. never assume anything"). Every decision cites the measured fact it rests on (file:line, or a command run on 2026-10-23 and its result). Anything not yet measured is a VERIFY item (WL-VER) that must close before the code that depends on it is written. The owner may overturn any decision; owner text in the PRRD always wins over this file.

## WL-FACT — measured facts this draft rests on (2026-10-23)

- F1. Claude Code names a project folder after the launch path with every non-alphanumeric character replaced by `-`, without resolving symlinks. Doc quote (cc projects-directory reference): "`<project>` is your working directory path with every character other than letters and digits replaced by `-`". Data: 190 slug folders; sessions with a symlinked recorded cwd and slug == transform(cwd): cli 705, sdk-py 2727, sdk-cli 139, claude-desktop 8. Exceptions: 3 worktree slugs, 1 truncated long path with a hash suffix.
- F2. 18 projects already own two slug folders (`-Users-<user>-Code-X` and `-Volumes-EmaUITEK4TBSSD-Code-X`, `~/Code` being a symlink). No two different real paths share a slug in the 119 folders with a recorded cwd. 71 slug folders have no session file; 38 of 119 recorded cwds no longer exist.
- F3. Session lines carry a top-level `cwd` and `entrypoint`; the first 1-4 metadata lines may lack `cwd`; a session's cwd can change mid-session.
- F4. Claude Code's cleanup deletes only listed session files (`<session>.jsonl`, orphaned/superseded variants, `<session>/subagents/`, `<session>/tool-results/`). Doc: "the sweep doesn't delete the memory files in a project's auto memory directory, `projects/<project>/memory/`" (since v2.1.228); it removes that folder only if empty for the whole period. Other subfolders (design/) are not listed.
- F5. memgrep: index per scope root at `<root>/.memgrep/index.db` (index.rs:33-35), gitignored by `.memgrep/.gitignore` = `*`. Scope is decided by path only (memory.rs:6787 `scope_layer`); 0 pages carry `scope:`. Slug = `$CLAUDE_PROJECT_DIR` or cwd as given (memory.rs:6747-6752), one slug only.
- F6. memgrep env overrides `WIKIMEM_{LOCAL,PROJECT,USER}_SCOPE_PATH` exist (memory.rs:6719-6728); validation is only "set and non-empty".
- F7. The write gate's atom-id check counts pages in the current write batch only (pre_write.rs ~215-275). Measured: editing page A whose copy B shares an atom id succeeds; B is left stale. `memgrep lint` reports `atom-dup-id` (WMATOM-001) as an ERROR on every copy; `reindex` accepts it. Duplicate `name:` is not checked by any rule.
- F8. There is no page id besides `name:`/the file stem (index.rs:1074-1085); pages are addressed by path. No `project-id` or owner field exists on pages. The USER folder holds an `architecture.md` symlinked from another project, so names collide across projects.
- F9. memgrep keeps no edit history (atomic_write_page, memory.rs:2839). The USER mirror `~/.claude/ai-maestro-janitor-memory/` is an overwrite copy (memory_scopes.py:582-640), no `.git`; only whole dropped pages survive in `.superseded/`.
- F10. publish-globally = a file symlink in the USER root pointing at the PROJECT page (memory.rs ~7158). Nothing checks project ownership; the write-path hook blocks hand edits only.
- F11. Janitor slug builders follow the literal path (memory_scopes.py:282-296) except three: fleet_scan.py:969 (realpath), fleet_status.py:322 (realpath, only `/` dashed), identify_environment.py:348 (abspath inline).
- F12. trddgrep's resolver uses `process.cwd()`, a realpath (ai-maestro lib/pillar/design-root.ts:22, environment.ts:66); the janitor's `local_design_root` uses `$CLAUDE_PROJECT_DIR` then git's first worktree line (trdd_common.py:203-217).
- F13. `.git/info/exclude` keeps one named file out of git while its sibling stays visible (temp repo test: `check-ignore` hit `.git/info/exclude:7:mem/a.md`; `status` listed only `mem/b.md`). Nothing in the repo or global gitignore ignores `*.local.md`.
- F14. The harvest chore copies Claude Code's raw notes (top-level notes without wikimem frontmatter) into wikimem pages and leaves the source untouched (skills/janitor-memory-harvest/SKILL.md; TRDD-ab232dbd, owner decision: duplication accepted). SKILL.md calls it dormant today.
- F15. 3-pillars cards carry `project-id: <repo name>` (100 cards here: `ai-maestro-janitor`).

## WL-REQ — requirements

Each line: id, the requirement, its source (G = owner rule, D = agent decision under G26.1), its evidence.

### Locations and slugs
- WL-1. LOCAL memory lives directly in `~/.claude/projects/<slug>/memory/`, with no `wikimem/` subfolder. Source G15, G16.
- WL-2. LOCAL design lives in `~/.claude/projects/<slug>/design/` (TRDD-M5BRPISQ). Source G15. Risk: F4 does not list design/ as protected or as deleted; VERIFY-3.
- WL-3. The slug of the CURRENT session is Claude Code's: the launch path as given, non-alphanumeric to `-`. Source G24 (supersedes G23). Evidence F1. New LOCAL pages and LOCAL cards are written under this slug.
- WL-4. A project's slug SET is every slug folder whose recorded cwd (F3: the first line that has one) resolves by realpath to the same project root, or to the same git toplevel, plus slug(p) for each known alias path p of the root (realpath, launch path, `$PWD`, and every top-level symlink in the home directory that points at an ancestor of the root). A folder is never added on its name alone, because slugging is lossy (`/a-b` and `/a/b` give the same slug). Folders with no session file (F2: 71) join only through the alias rule. Source G25 (D for the method). Evidence F1-F3. The map slug to realpath is cached and refreshed when a folder's newest session file changes.
- WL-5. Search (recall, find, lint, index reads) covers every folder in the slug set (WL-4); writes go to the current slug (WL-3). The same slug set applies to LOCAL design for trddgrep and the janitor (D, extending G25 to design, since the same two-slug split F2 hits design). Evidence F2, F12.
- WL-6. Every slug builder routes through ONE shared rule per language (Python memory_scopes.project_slug, Rust memory.rs scope_project_slug, TypeScript in ai-maestro). The three deviating builders (F11) are fixed. Source D. Evidence F11.

### Pages, scope and indexes
- WL-7. Every wikimem page carries `scope: local|project|user` in its frontmatter. memgrep finds pages by content (a markdown file with wikimem frontmatter) anywhere under a scope root, recursing into subfolders. Source G17, G19. Evidence F5 (today the path decides). VERIFY-5.
- WL-8. A page with no `scope:` gets it from its path (today's rule, F5) and lint autofixes the field. Source D.
- WL-9. When a page's `scope:` and its location disagree, the field wins for indexing and editing rules, with one hard exception: a page whose scope is `local` or `user` and that git would track (not ignored) is refused for indexing and reported, never silently indexed. Source G19 (the field decides) + D (privacy guard). Evidence F13.
- WL-10. One index file per scope, named as the owner named them: `wm_local_index.db`, `wm_project_index.db`, `wm_user_index.db`, each inside its scope root's `.memgrep/` folder, which already ignores itself (F5). G17 says "the project scope index in each project design folder"; G18 says the memories and their index "should share the same folder"; this draft follows G18 and records the conflict as WL-CONF-1. A folder that mixes scopes (G18) holds one index per scope present.
- WL-11. The env overrides (F6) are validated at parse time: PROJECT must resolve inside the project root and must not be gitignored there; LOCAL must resolve inside the project root or inside one of the project's slug folders (WL-4); USER is unrestricted. On violation memgrep warns and uses the default path. Source G18.

### Local pages inside a tracked tree
- WL-12. A `local` page inside a git work tree is kept out of git by a memgrep-managed block in that repository's `.git/info/exclude` (never committed, so no filename leaks, F13). Before every write and in lint, memgrep runs `git check-ignore` on each local page in a work tree and refuses the write if git would track it. Source G18 (mixing allowed) + D. Evidence F13.

### Page identity and copies
- WL-13. Every page gets a unique id in frontmatter, `page-id: PAGE-XXXX-XXXX`, minted like atom ids. `name:` stays the human slug. Two files are copies of one page if and only if they share `page-id`. Source G19 ("they have all an unique id") + D (names collide across projects, F8).
- WL-14. Copies are allowed and recommended (G21). memgrep keeps every copy identical: a write to one copy is applied to every copy found in the indexes it can see (the project's slug set, the PROJECT root, USER, and imported copies), inside one journalled transaction that holds every affected scope's lock. Moving an atom between two pages updates every copy of both pages (G20). Source G19, G20, G21. Evidence F7 (today copies drift).
- WL-15. The atom-id uniqueness rule changes: one atom id may appear in several files only when those files share one `page-id`; anywhere else it stays an error. Source D. Evidence F7.
- WL-16. Copies found with different content (edited outside memgrep) are reported (`page-copies-diverged`) and writes to that page are refused until `memgrep reconcile <page-id>` resolves them by an explicit choice; memgrep never picks a winner by itself. Source D (never assume which copy is right).

### Ownership and editing across projects
- WL-17. PROJECT and LOCAL pages carry `project-id:`, using the 3-pillars value (F15). A memgrep write to a PROJECT or LOCAL page is refused when the current project's id differs from the page's. USER pages are editable from any project. publish-globally pages are read-only outside their project. Source G19. Evidence F10 (no check today). VERIFY-4.
- WL-18. An imported copy (WL-21) keeps the owner's `page-id` and `project-id` and is read-only in the importing project; the owner's edits reach it through WL-14. To change it locally an agent forks it into a new page with a new `page-id`. This reconciles G19 (read-only elsewhere) with G20/G21 (copies stay in sync). Source D; WL-CONF-2.

### USER versioning
- WL-19. The USER root becomes a local git repository (never pushed). memgrep commits after every write batch that touched USER pages, inside the write lock; reverting is `git revert`. The mirror sync (F9) stays as a second copy. Source G19 ("strong versioning to ensure errors can be reverted"). Evidence F9 (no history today). VERIFY-6.

### Harvest
- WL-20. Harvest keeps copying Claude Code's raw notes and never edits them (TRDD-ab232dbd stands); harvested pages now land in the same flat folder (WL-1). The indexer ignores raw notes because they have no wikimem frontmatter (WL-7). Source G16 + D. Evidence F14.

### Cross-project import (TRDD-TBBEB8JD)
- WL-21. `memgrep import` lists PROJECT pages of other projects that concern the current project's components and copies the chosen ones in, keeping their ids (WL-18). Other projects are found from the realpaths of recorded cwds that still exist (F2, F3). Components are matched by the dependency names in the current project's manifests (package.json, Cargo.toml, pyproject.toml, go.mod) against the other pages' title, tags, keywords and globs; candidates are shown, never imported silently. Source G21 + D.
- WL-22. Only PROJECT pages are importable (LOCAL pages are machine-private; USER pages are already shared). An imported page passes the same private-data screen as any PROJECT write before it lands in a tracked folder. Source D.
- WL-23. The memgrep help EXAMPLES block and the recall/write skills recommend sharing component pages across projects, with a caveat that copies stay in sync only once WL-14 ships; the `import` example ships with WL-21. Source G21.

## WL-CONF — conflicts between owner rules and how this draft resolves them

- WL-CONF-1. G17 puts the project index in "each project design folder"; G18 says memories and their index share a folder. Resolution WL-10 (G18), because an index in design/ would sit beside TRDD cards, not beside the pages it indexes.
- WL-CONF-2. G19 makes other projects' pages read-only; G20/G21 keep copies in sync and recommend copying. Resolution WL-18: sync flows from the owner project outward; importing projects read but do not edit.
- WL-CONF-3. G15 puts LOCAL memory in "the same folder of claude code memories"; G24 follows Claude Code's slug, which splits a project across launch paths (F2). Resolution WL-4/WL-5: search the whole slug set, write to the current slug.

## WL-VER — facts to measure before the dependent code is written

- VERIFY-1. Is `$CLAUDE_PROJECT_DIR` the logical (launch) or physical path in a session launched through `~/Code`? Not measured anywhere. Blocks WL-3 for hooks.
- VERIFY-2. Does Claude Code follow a symlinked slug folder or memory folder? No case exists (0 symlinked slug or memory folders). Blocks any design that links slug folders together.
- VERIFY-3. Does Claude Code's cleanup ever touch `<slug>/design/`? Docs list only session files (F4). Blocks WL-2's migration (TRDD-M5BRPISQ).
- VERIFY-4. Where a project's `project-id` comes from when it has no 3-pillars cards, and whether two projects can share one (it is a repo name, F15).
- VERIFY-5. Does memgrep's indexer recurse into subfolders today? Not located (no WalkDir or read_dir hit in index.rs).
- VERIFY-6. Cost and behaviour of committing the USER root on every write (time per commit; git storing the publish-globally symlinks; concurrency with the write gate).

## WL-TRDD — implementation cards (minted from this spec once it is reviewed)

Existing: TRDD-KLT5F93P (flatten LOCAL memory, WL-1), TRDD-M5BRPISQ (LOCAL design to the slug folder, WL-2), TRDD-TBBEB8JD (import, WL-21 to WL-23).
Planned, one card each: VERIFY-1 to VERIFY-6; slug-set resolver and single slug rule (WL-3 to WL-6); scope field and content-based discovery (WL-7 to WL-9); per-scope index files (WL-10); env override validation (WL-11); local pages in tracked trees (WL-12); page-id and copy sync with the journal (WL-13 to WL-16); project ownership (WL-17, WL-18); USER git versioning (WL-19); harvest into the flat folder (WL-20).
