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
loaded each session. `memgrep index` can generate a richer `memory-index.md`
(per-note title/summary/tags/TOC/backlinks) — that is an OPTIONAL generated
artifact; `MEMORY.md` remains the canonical loaded index. Recall does not need
either index — it scans the notes directly.

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

## Why this rule exists

The memory system had a fully-built recall engine (memgrep, 42 tests), a live
note corpus, and the harness authoring directive — but no durable rule tying
them together. A fresh session was blind to the recall half. This rule is that
missing piece: it makes "recall before acting" and "index by symptom" a
standing discipline, with a tool command that degrades to grep when the binary
isn't present.
