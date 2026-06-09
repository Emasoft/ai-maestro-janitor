# Markdown memory — recall protocol (the search half)

The harness `# Memory` directive (injected each session) tells you how to
**WRITE** memories. This rule is the missing half: how to **RECALL** them, the
**discipline** that makes recall work, and the **tool** (`memgrep`) that powers
it. Together they are "the memory system": authoring (directive) + recall (this
rule) + the search tool (memgrep) + the note corpus.

## The one law that makes memory work: index by the QUESTION, not the answer

A memory is found from the SYMPTOM, not the solution. When you write a note,
its `description:` (and `title`/`tags`) MUST carry the words a future session
will have when the problem RECURS — the user's words, the error text, the
symptom — NOT the jargon of the fix.

- WRONG `description`: "OAuth creds live in the macOS keychain services".
  (Findable only if you already know the answer is "keychain".)
- RIGHT `description`: "rotator failed, had to log in manually — where are the
  creds / why did the swap fail" + the keychain fact in the BODY.

Two-hop recall: a symptom query lands you on the note; the note's BODY gives the
answer. The `description` is the load-bearing surface — `memgrep recall` ranks
on `description + title + tags` ONLY (the `metadata.type` taxonomy does NOT
affect ranking). Put symptom vocabulary in `description`; put the answer in the
body.

## Recall BEFORE acting (the protocol)

Before debugging a recurring problem, making a design decision, or acting on a
recurring alert, RECALL first — "have we hit this before?". Cheap, and it's the
whole point of having a memory.

```bash
# memdir is the harness per-project memory dir:
MEMDIR="$HOME/.claude/projects/<project-slug>/memory"   # slug = project path, dashed
SYMPTOM="the user's words / the error / the symptom"     # NOT the answer's jargon

if command -v memgrep >/dev/null 2>&1; then
  memgrep recall "$SYMPTOM" "$MEMDIR"      # notes ranked best-first as: path — description
else
  grep -rliE "$SYMPTOM" "$MEMDIR"          # fallback: plain grep, degrade-not-break
fi
```

Read the top 1-3 notes the recall returns; the answer is in their bodies. If
recall returns nothing, the memory doesn't exist yet — consider writing one
after you solve the problem (per the `# Memory` directive).

## memgrep — the recall engine

`memgrep` is `rg` for markdown (gitignore-aware tree walk, per-line regex,
markdown-structural filters, boolean `--where`, link semijoin, and the memory
subcommands `recall`/`index`/`links`/`fact`). Its own teaching doc is
`tools/memgrep/SKILL.md` in `ai-maestro-janitor`.

- **Availability:** memgrep is a Rust binary. If `command -v memgrep` is empty,
  install it once: `cargo install --path <…>/ai-maestro-janitor/tools/memgrep`
  (puts it on `~/.cargo/bin`). Until then, the plain-`grep` fallback above
  works on note frontmatter + bodies — recall degrades, never breaks.
- **recall** `memgrep recall "SYMPTOM" <memdir>` — symptom-ranked notes,
  precision-first (surface matches suppress body-only matches unless nothing
  matched the surface), printed `path — description`, best first.

## Read-the-notes rule — a memory's lessons are part of the memory

When you read ANY memory, you MUST also read **all the notes/lessons attached to
it** — every `[^N]` footnote reference and the `## Notes and lessons learned`
entries they point to. Reading a memory's facts without its lessons is
incomplete: the lessons are *why* the facts are the way they are and *what
errors not to repeat*. Recall the page, read it WHOLE (facts + its linked
lessons), then act.

This is FREE — you never issue a second search for the references. `memgrep`
auto-resolves footnotes on the memory subcommands: `recall` (default-on) and
`find` (default-on) APPEND each returned note's resolved lessons; `fact` does
too with `--with-notes`. One `memgrep recall` yields body **and** every linked
WHY in a single result.

- Render is token-economical by default: an inline reference shows as a **bare
  number `[9]`**, and after the body memgrep appends the list
  `[9] - <lesson WHY text>.` — only the number + the content (no on-disk
  footnote machinery, no per-note metadata).
- `--full-notes` restores each lesson's leading `[…]` metadata prefix; `--no-notes`
  suppresses the lessons (body only). URLs / image links / cross-references in a
  lesson are ALWAYS kept, even in the minimal form — only metadata is strippable.
- A footnote-free note appends nothing, so the read-the-notes rule is a no-op on
  notes that have no lessons yet.

## memgrep recall / find / index — the command surface that shipped

These are the actual flags on the shipped binary (verify with `memgrep recall
--help` / `find --help`). Every one below exists today.

- **recall** — symptom-ranked pages, lessons appended by default:

  ```bash
  memgrep recall "SYMPTOM" <memdir>                 # ranked path — description (+ lessons)
  memgrep recall "SYMPTOM" <memdir> --no-notes      # body only, no lessons
  memgrep recall "SYMPTOM" <memdir> --sort lmd      # order by last-modified date (newest first)
  memgrep recall "SYMPTOM" <memdir> --sort ocd --order asc   # oldest-created first
  memgrep recall "SYMPTOM" <memdir> --since 2026-06-01 --until 2026-06-09   # date window (on lmd)
  memgrep recall "SYMPTOM" <memdir> --since 2026-06-01 --date-field ocd     # window on creation date
  ```

  `--sort score|ocd|lmd` (default `score` = relevance), `--order asc|desc`
  (default `desc`), `--since`/`--until` filter on `--date-field ocd|lmd`
  (default `lmd`), `--top N` (default 10), `--use-index` (force the SQLite
  sidecar; auto-used when fresh, else the live walk — results always correct).

- **find** — note-level `+`/`-`/wildcard/phrase keyword search (NOT line grep).
  The query is ONE whitespace-quoted string: `+TERM` mandatory, `-TERM` exclude,
  bare `TERM` optional (ranks). `*` = wildcard (any run); `"quoted phrase"`
  matches verbatim WITH spaces and may be `+`/`-` prefixed; a `+`/`-` INSIDE a
  token is literal (`pro*-debug*` is ONE term). `--only-notes` searches the
  resolved `[^N]` lessons instead of pages. Composes with every recall flag
  above.

  ```bash
  memgrep find "+rotator +keychain -widget" <memdir>          # must have rotator AND keychain, not widget
  memgrep find '+"old approach" retry' <memdir>               # mandatory phrase + optional ranker
  memgrep find "+max_retries" <memdir> --only-notes           # search ONLY the lessons-learned
  ```

- **index / reindex** (aliases) — build the persistent `.memgrep/index.db`
  SQLite sidecar (gitignored, git-incremental — re-parses only changed files).
  `memgrep index --markdown` is the legacy `memory-index.md` doc-generator (the
  per-note title/summary/tags/TOC/backlinks index); `--full` rebuilds the
  SQLite index from scratch.

  ```bash
  memgrep reindex <memdir>             # build/refresh the SQLite query index
  memgrep index --markdown <memdir>    # the human-readable memory-index.md doc-generator
  ```

## The note format (recall-relevant fields)

The `# Memory` directive is the authoring source-of-truth. On disk, notes are:

```yaml
---
name: <kebab-slug>                 # == filename stem
description: "<symptom surface — the load-bearing recall field>"
metadata:
  node_type: memory
  type: user | feedback | project | reference
  originSessionId: <uuid>
---
<body: the one fact; for feedback/project add **Why:** and **How to apply:**>
```

`MEMORY.md` is the human index (`- [Title](file.md) — hook`, one line per note)
loaded each session. `memgrep index --markdown` can generate a richer
`memory-index.md` (per-note title/summary/tags/TOC/backlinks) — that is an
OPTIONAL generated artifact; `MEMORY.md` remains the canonical loaded index.
Recall does not need either index — it scans the notes directly (and
transparently uses the SQLite `.memgrep/index.db` when it is fresh).

## Lessons-learned conventions (footnotes + per-element dates)

Memory pages grow a bottom `## Notes and lessons learned` section. The format is
**standard markdown footnotes** — nothing new to memorize, and memgrep's
markdown parser already understands it:

- In the body, reference a lesson as `[^N]`; under `## Notes and lessons learned`
  define it as `[^N]: <the WHY>`. memgrep resolves ref ↔ def WITHIN the same note
  by default and inlines the lesson when it returns the note.
- A lesson is a **first-class memory element**, not a second-class footnote — it
  carries the same metadata schema a fact does, including two intrinsic dates:
  - **OCD — Original Creation Date** (when the lesson/fact was first written),
  - **LMD — Last Modified Date** (when its content last changed).
  These survive when the background librarian moves a memory between pages, so a
  page's filesystem mtime is NOT a reliable age for any element it holds — the
  per-element OCD/LMD is. memgrep reads OCD from frontmatter `ocd` (alias
  `created`) and LMD from `lmd` (alias `updated`, falling back to the file
  mtime). On a lesson, the dates live in its leading `[ocd:… lmd:…]` metadata
  prefix — stripped from the default render, restored by `--full-notes`.

```markdown
<clean, current FACTS about this topic>. The widget retries 3× then fails.[^3]
... tangential topics LINK, never duplicate: see [[other-topic]] ...

## Notes and lessons learned
[^3]: [ocd:2026-06-09 lmd:2026-06-09] earlier this said "retries 5×"; wrong, the
  cap is 3 — the config key was misread as `max_attempts` when it is
  `max_retries`. Lesson: verify the constant against the source, not the
  variable name.
```

Authoring the lessons (clean-the-fact-in-place + demote-the-error correction
protocol) is the WRITE side — see the `janitor-memory-write` skill. Searching
across lessons (`find --only-notes`, `--since`/`--until` over OCD/LMD) is the
recall side above.

## Evaluating / improving the system: the dual-test method

When designing or testing memory recall, run BOTH tests and judge BOTH
dimensions in each:

- **Test A — cold-recall:** simulate a session with NO prior recollection;
  build the query ONLY from the symptom/user's words, never the answer's
  jargon. Tests "is the right note findable from the symptom?".
- **Test B — write-then-recall:** author a note, then retrieve it. Tests the
  round-trip.

In each, evaluate (1) YOUR search strategy AND (2) the system's retrieval, and
improve both. **Contamination warning:** after you WRITE a note you are biased
toward its wording — your own cold-recall is no longer cold. Do cold-recall
from a clean framing, or have the symptom come from the user verbatim.

## The memory system's parts (how they connect)

| Part | Surface | Role |
|---|---|---|
| Authoring | `# Memory` harness directive + `janitor-memory-write` skill | write one fact per note; symptom-indexed `description`; the correction protocol (clean fact in place, demote error to a `[^N]` lesson) |
| Recall | THIS rule + `janitor-memory-recall` skill + `memgrep recall`/`find` | symptom-ranked recall, lessons auto-appended |
| Organization | `memory-librarian` detector (janitor heartbeat) | SURFACES aggregation/conflict candidates to `memory-reorg-proposed.md`; never edits content (a session does the conscious reorg) |
| Tool | `memgrep` (`tools/memgrep/SKILL.md`) | the engine all three lean on |
| Private user store | `/to-user-mem`, `/search-user-mem`, `/share-user-mem` | the USER's own agent-invisible memories — a SEPARATE corpus, not the agent notes; search routes through `memgrep find` |

Separation of powers: the **janitor** reorganizes structure and *surfaces*
contradictions but never edits a fact; an **agent** creates and corrects content
but never reorganizes. (The background auto-merge — the librarian consolidating
clusters into one wiki page — is DESIGNED but not yet shipped; today the detector
only proposes, an agent applies.)

## Why this rule exists

The memory system had a fully-built recall engine (memgrep, 42 tests), a live
note corpus, and the harness authoring directive — but no durable rule tying
them together. A fresh session was blind to the recall half. This rule is that
missing piece: it makes "recall before acting" and "index by symptom" a
standing discipline, with a tool command that degrades to grep when the binary
isn't present.
