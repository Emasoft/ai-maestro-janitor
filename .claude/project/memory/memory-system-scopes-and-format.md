---
name: memory-system-scopes-and-format
description: "how does the wiki-memory 3-scope model work / LOCAL vs PROJECT vs USER scope precedence / where do memories live / what fields does a wikimem note frontmatter carry / why did my PROJECT memory page get flagged for a leak / what is the load-bearing recall field / does memgrep recall rank on the body or the description / why is MEMORY.md a deprecation stub / where does the harvest chore file stray memories / what is the note format for a memory page / index by the question not the answer"
ocd: 2026-06-13
lmd: 2026-09-03
metadata:
  node_type: memory
  type: project
  tier: aspect
  functionality: janitor
  originSessionId: memory-audit-draft
publish-globally: false
split-lineage: c89f02722a424b5385204031e5db35ce
---

# Memory-system scopes and note format

Part of the [[memory-system]] functionality (the wiki-memory system's LOCAL /
PROJECT / USER scope model and its note frontmatter/format). Split out of
[[memory-system]] 2026-09-03 to keep that page a navigable overview instead of
a dump -- see it for the memgrep engine, the three skills, the heartbeat
detectors, the wikimem layer, and the editor's operational gotchas.

## The 3-scope model (LOCAL / PROJECT / USER)

The corpus is layered exactly like Claude Code's own memory (the user CLAUDE.md,
the project CLAUDE.md, and the git-ignored project-local CLAUDE override file).
Three roots, ONE recall surface — recall
searches all three that exist in a single call. Paths are generic on purpose; the
machine-specific expansion (the actual `<project-slug>`, `<repo-root>`, the
account/host details a LOCAL note may hold) **lives in LOCAL scope** and is never
written here.

| Scope | Root | Git status | Holds |
|---|---|---|---|
| **LOCAL** | `$HOME/.claude/projects/<project-slug>/memory/` (`<project-slug>` = the project's absolute path with every separator dashed) | OUTSIDE any repo — **never pushed** | machine-private notes: local paths, usernames, hostnames, credential hints, per-instance facts. The harness `# Memory` directive writes here; the user's PRIVATE store `user-mem/` is a sibling inside it |
| **PROJECT** | `<repo-root>/memory/` (`<repo-root>` = `git rev-parse --show-toplevel`) | **git-tracked + PUSHED** — shared by every contributor | project knowledge any dev needs: architecture facts, codebase gotchas, project lessons. **Sensitive/local data FORBIDDEN** — the `memory-scope-leak` detector polices this scope |
| **USER** | `$HOME/.claude/memory/` | never in any repo | cross-project knowledge: user preferences, machine-independent lessons |

**Precedence — LOCAL > PROJECT > USER.** When two scopes state conflicting facts,
the MORE SPECIFIC scope wins (LOCAL beats PROJECT beats USER). A note's scope IS
its path: under `$HOME/.claude/projects/…` = LOCAL, under the repo = PROJECT,
under `$HOME/.claude/memory` = USER.

**Write routing (decide the scope BEFORE authoring):** contains a local path /
username / hostname / secret / machine-specific detail → **LOCAL**. Project
knowledge any dev needs → **PROJECT**. About the user across projects → **USER**.
**UNSURE → LOCAL** — the safe scope; promotion to PROJECT is a deliberate later
act, and the scope-leak detector flags anything sensitive that lands in PROJECT.

Compose the roots once (the same block all three skills use):

```bash
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"          # machine-private
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"  # git-tracked
USER_MEM="$HOME/.claude/memory"                                            # global
ROOTS=""; for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS="$ROOTS $d"; done
```

## The note format (recall-relevant fields)

On disk every note is a markdown file whose stem == frontmatter `name:`:

```yaml
---
name: <kebab-slug>                 # == filename stem
description: "<symptom surface — the load-bearing recall field, indexed by the QUESTION>"
ocd: <YYYY-MM-DD>                  # Original Creation Date — set once on create
lmd: <YYYY-MM-DD>                  # Last Modified Date — bump on every edit
metadata:
  node_type: memory
  type: user | feedback | project | reference
  tier: hub | aspect | component   # wikimem tier (absent ⇒ component)
  functionality: <hub-slug>        # which functionality this lives under
  globs: ["<owned file patterns>"] # REQUIRED on hubs; omit on most leaves
---
<body: the one fact; for feedback/project add **Why:** and **How to apply:**>

## Notes and lessons learned
```

The `description:` is the load-bearing recall surface — `memgrep recall` ranks on
`description + title + tags` ONLY (the `metadata.type` taxonomy does NOT affect
ranking). [^2] Put **symptom vocabulary** in `description`, put the **answer** in the
body (two-hop recall: symptom query → note → body answer). The
`## Notes and lessons learned` section is MANDATORY on every page even when empty
— the standing landing zone for `[^N]` correction lessons; the page-shape pass
flags a note that omits it, or that omits `ocd`/`lmd`.

**The index is memgrep's, and ONLY memgrep's** (v0.13.0, TRDD-a5780c23): recall runs on
the agent-invisible, unlimited SQLite index `.memgrep/index.db` (or a live note-scan) and
NEVER reads a human index.[^5] `MEMORY.md` is now a **deprecation stub** — never
maintained, loaded-as-index, or hand-trimmed. The daily **harvest chore**
(`/janitor-memory-harvest`) re-files any stray memory an agent mis-adds to `MEMORY.md`
(or a loose `.md`) back into proper wiki pages, NON-destructively, then stubs `MEMORY.md`.
Each PROJECT corpus carries one `<project>-overview.md` entry page — `memgrep overview
<dir>` prints it (the Wikipedia-style overview that links to the deeper pages).


## Governed by

- [[memory-system]] -- the functionality hub this page is one part of.

## See also

- [[memory-system]] -- the overview and parts map.
- [[memory-system-tooling-and-protocol]] -- the memgrep engine, the three
  authoring skills, and the heartbeat detectors that police this scope model.

## Notes and lessons learned

[^2]: [id:ATOM-MG07-0002, status:valid, keywords:"recall_ranks_description_title_tags_only index_by_question_not_answer symptom_vocabulary_in_description", ocd:2026-06-13, lmd:2026-06-13] `memgrep recall` ranks on
  `description + title + tags` ONLY — `metadata.type` does NOT affect ranking.
  So a note found only by its answer's jargon is mis-authored: the symptom
  vocabulary (the user's words / the error text) MUST be in `description`, with
  the answer in the body. Index by the QUESTION, not the answer.

[^5]: [id:ATOM-MG07-0005, status:valid, keywords:"memory_md_growing_index_was_the_bug never_put_growing_index_in_context search_engine_owns_unlimited_index", ocd:2026-06-20, lmd:2026-06-20] Pre-v0.13.0 this page said "`MEMORY.md` is the human
  index loaded each session and the canonical index." That model WAS the bug: the
  context-loaded MEMORY.md grew unbounded with the corpus, so agents hand-trimmed it to
  save context and LOST pointers / corrupted memories. v0.13.0 (TRDD-a5780c23) moved the
  index ENTIRELY into memgrep's agent-invisible, unlimited SQLite — there is no
  human-maintained index any more. Lesson: never put a growing index in the agent's
  context window; let the search engine own it (unlimited, invisible). The daily harvest
  chore and the deprecation stub keep it that way against agents who re-add to MEMORY.md.
