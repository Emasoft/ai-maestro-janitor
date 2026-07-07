---
name: janitor-memory-harvest
description: HARVEST executor — the daily NON-DESTRUCTIVE chore that MIRRORS newly-created harness BUFFER memories into the curated wiki. MEMORY.md + the raw notes at the scope root are the harness-owned buffer (auto-loaded each session); the janitor never touches them. For each RAW buffer note not yet mirrored, RECALL its subject across memory/wiki/ then UPDATE-or-CREATE a curated wiki/<name>.md copy and stamp a watermark. The buffer is left 100% intact (separate parallel copies coexist). Use on a [janitor-memory-harvest] marker, or "harvest the memory", "mirror new MEMORY.md memories into the wiki".
---

# Janitor memory — HARVEST (mirror new buffer memories into the curated wiki)

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Sonnet** agent (`janitor-memory-subconscious-agent` — Sonnet, not Opus, per
> the USER cost decision 2026-06-30) — you ARE that agent. Run the whole pass here in your own
> context and return only a one-line result + the report path. A wikimem editorial pass is
> never run inline in a main session (it must not burden CPV or any other session's context).

## What this is (the COEXISTENCE model — TRDD-ab232dbd)

Two memory systems live in PARALLEL in every scope and cooperate:

- **The BUFFER** — `MEMORY.md` + the raw `*.md` notes at the scope ROOT. This is
  Anthropic/harness-owned (the harness `# Memory` directive writes it and auto-loads it
  every session; Claude Code keeps evolving it). It is an unorganized, freely-growing
  buffer. **The janitor NEVER stubs, trims, or modifies it.**
- **The WIKI** — the curated pages under `memory/wiki/`: rich frontmatter (`ocd`/`lmd`/
  `tier`), `[^N]` lessons, bidirectional links, git-versioned, memgrep-indexed.

HARVEST is the BRIDGE: it incrementally finds NEWLY-created buffer memories and **MIRRORS**
each into the wiki as a SEPARATE curated page. The same fact lives in BOTH files
(duplication is accepted, by USER decision — "separate parallel copies"). A per-scope
watermark tracks what has been mirrored so the pass is idempotent.

**THE IRON RULE: never lose a memory, and never touch the buffer.** Harvest is purely
ADDITIVE — it only ever creates/updates wiki pages. When unsure, mirror nothing, leave the
buffer intact, and surface a finding. A missed mirror is recoverable next run.

> **DORMANT today:** every existing top-level `memory/*.md` already carries full wikimem
> frontmatter (it was curated in-place under the old model), and `MEMORY.md` is the legacy
> deprecation stub. So on the CURRENT corpus the discriminator finds ZERO raw buffer notes
> and harvest is a clean no-op. It ACTIVATES the moment the harness next writes a
> minimal-frontmatter note. No bulk move is needed.

## Preconditions (cheap gate, run first)

```bash
JANITOR_ROOT="$(git -C "$CLAUDE_PLUGIN_ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$CLAUDE_PLUGIN_ROOT")"
CLI="$JANITOR_ROOT/scripts/memory_txn_cli.py"
uv run --quiet - <<PY || { echo "wikimem editor disabled — abstain"; exit 0; }
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_txn
sys.exit(0 if memory_txn.editor_enabled() else 1)
PY
```

The `[janitor-memory-harvest]` marker already chose ONE scope for this heartbeat. Do **one
scope per pass**.

## Scope (LOCAL + USER default; PROJECT opt-in)

```bash
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
USER_MEM="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory"  # FIXED data dir, NOT ${CLAUDE_PLUGIN_DATA}
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null)/.claude/project/memory"   # in-repo; opt-in only
```

PROJECT is edited only when `edit_project_scope` is on, and then **staged-not-pushed**
(rides the next `publish.py`). Otherwise restrict to LOCAL + USER. The curated wiki for a
scope is `<scope>/wiki/` (`memory_scopes.resolve_wiki_dir`).

## The procedure

### 1. Find the un-mirrored RAW buffer notes in the ONE scope

A **RAW buffer note** is a top-level `<scope>/*.md` whose frontmatter shape is the harness
minimal form — NO wikimem-only key (`node_type` / `tier`). The discriminator is
`memory_scopes.is_curated_wiki_page(text)` (by CONTENT SHAPE, not path): it returns True for
a CURATED page (SKIP it) and False for a RAW buffer note (a harvest candidate). EXCLUDE the
`wiki/` sub-dir itself, `MEMORY.md`, the generated index files (`memory-index.md`,
`memory-reorg-proposed.md`), and the private `user-mem/`.

Then drop every candidate already mirrored, via the watermark:

```bash
uv run --quiet - <<PY
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_scopes as msc, memory_settings as ms, pathlib
scope, root = "LOCAL", pathlib.Path("$LOCAL_MEM")   # one scope/root per pass
wiki = msc.resolve_wiki_dir(root)
todo = []
for p in sorted(root.glob("*.md")):
    if p.name in {"MEMORY.md", "memory-index.md", "memory-reorg-proposed.md"}:
        continue
    text = p.read_text(encoding="utf-8")
    if msc.is_curated_wiki_page(text):          # already curated → not a buffer note
        continue
    if ms.harvest_note_is_mirrored(scope, str(root), p.name, text):  # unchanged & mirrored
        continue
    todo.append(p.name)
print("\n".join(todo))
PY
```

If the list is empty, nothing is due — STOP cleanly (emit nothing). The harness BUFFER
(MEMORY.md + the raw notes) is **never** read for "pointer lines" any more and is **never**
reduced — it is owned by the harness.

### 2. Mirror each un-mirrored buffer note into the curated wiki (the editorial work)

For each candidate note, **RECALL-before-write** to de-dup against the existing wiki, then
UPDATE-or-CREATE a curated copy in `<scope>/wiki/`:

```bash
memgrep recall "<the note's subject, in the user's words>" "$MEMDIR"
```

> Privacy: `user-mem/` under the LOCAL root is the user's PRIVATE store —
> memgrep excludes it at the engine level; if a result path ever names it,
> treat that as a bug (never open, quote, or mirror it).

- **A wiki page on the same subject already exists** → UPDATE it (the
  `/janitor-memory-update` correction protocol — clean the fact in place, demote a
  superseded statement to a dated `[^N]` lesson). Do NOT create a duplicate.
- **No existing page** → CREATE `wiki/<name>.md` — the `/janitor-memory-write` discipline:
  - **One subject per page; same-theme memories share ONE page.**
  - **Complete frontmatter** — `name`, symptom-indexed `description`, `ocd`, `lmd`,
    `metadata.{node_type: memory, type, tier}`.
  - **Tier expand/reduce** — a general rule → `aspect` (radiates `## Applies to`); one
    element → `component` (receives `## Governed by`); a functionality overview → `hub`.
  - **Bidirectional links** — every `[[link]]` wired on BOTH ends (the link law);
    `## See also` for lateral relations.
  - **Atomic memories, each with its own `## Notes and lessons learned`** section.
  - **Scope routing** — machine-private (local paths / hostnames / secrets) → LOCAL;
    project-shared (no secrets) → PROJECT; cross-project → USER; **UNSURE → LOCAL**.

  How to land the edit (H3, wikimem audit 2026-07-07 — the txn CLI has NO
  harvest/create op, so the two cases route differently):
  - **CREATE a brand-new `wiki/<name>.md`** → a direct `Write` of the new file
    (one atomic file creation; there is no pre-existing content to protect — the
    step-3 `mirror_preservation_ok` gate below is the loss oracle for this case).
  - **UPDATE an existing wiki page** → through the transaction core:
    `memory_txn_cli.py begin <scope> --op repair <rel>` → edit the staged copy →
    `commit --op repair` (one source, the write at the same path — the shape the
    repair gate accepts).
  Then `memgrep reindex "$MEMDIR"`.
  **The buffer note is left exactly as it was** — you mirror its content into `wiki/`, you
  do not move, edit, or delete it.

### 3. Verify the mirror is complete (the gate — NOT a stub reduction)

Prove every un-mirrored buffer note's content now lives in the wiki, with the formal check
`memory_edit_verify.mirror_preservation_ok` — it GATES the watermark stamp:

```bash
uv run --quiet - <<PY
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_edit_verify as v, memory_scopes as msc, pathlib
root = pathlib.Path("$MEMDIR")
wiki = msc.resolve_wiki_dir(root)
# the buffer notes this pass set out to mirror (recompute the same candidate list)
buffer_notes = []
for p in sorted(root.glob("*.md")):
    if p.name in {"MEMORY.md", "memory-index.md", "memory-reorg-proposed.md"}:
        continue
    t = p.read_text(encoding="utf-8")
    if not msc.is_curated_wiki_page(t):
        buffer_notes.append((p.name, t))
wiki_corpus = "\n".join(p.read_text(encoding="utf-8") for p in wiki.glob("*.md")) if wiki.is_dir() else ""
ok, missing = v.mirror_preservation_ok(buffer_notes, wiki_corpus)
print("MIRRORED" if ok else "ABSTAIN: " + "; ".join(missing))
sys.exit(0 if ok else 1)
PY
```

If it prints `ABSTAIN`, a note was not fully mirrored — finish mirroring it (or, if it can't
be mirrored this pass, leave its watermark UNSTAMPED so the next run retries) and surface
`[janitor-memory] harvest abstained: <reasons>`. Only on `MIRRORED` proceed to stamp the
watermark.

### 4. Stamp the watermark (idempotency — only after step 3 passes for a note)

For each note that is now provably mirrored, record it so the next run skips it:

```bash
uv run --quiet - <<PY
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_settings as ms, pathlib
scope, root = "LOCAL", pathlib.Path("$MEMDIR")
for name in """<the mirrored note names, one per line>""".split():
    text = (root / name).read_text(encoding="utf-8")
    ms.harvest_mark_mirrored(scope, str(root), name, text)
PY
```

The watermark keys on the note's CONTENT HASH, so if the harness later EDITS that buffer
note its hash changes and the next harvest re-mirrors the new content (the wiki stays in
sync). The buffer is never modified by this step.

## EXIT / idempotency / bounds

- **SUCCESS** = every un-mirrored buffer note mirrored into a `wiki/` page AND its watermark
  stamped; the buffer (MEMORY.md + raw notes) untouched. Report `[janitor-memory] mirrored
  <N> buffer memory(ies) → wiki (buffer intact)`.
- **Idempotent + daily** — a scope whose buffer notes are all already mirrored (the watermark
  covers them) is a no-op; off by default (opt-in via `harvest_per_day`; `0` disables). The
  chore is PERMANENT — it mirrors whatever new memories the harness adds, forever.
- **Bounded** — one scope per pass; honors the kill-switch + `harvest_per_day=0`.
- **Never destructive, never touches the buffer** — only creates/updates `wiki/` pages and
  stamps the watermark. A crash mid-pass is safe: the buffer remains, the watermark records
  only proven-mirrored notes, and the next daily run mirrors whatever is still un-mirrored.

## Done when (terminating conditions)

This pass is complete when ONE of these holds (one scope per pass; it never deletes a memory
and NEVER modifies the harness buffer):

- [ ] **NOTHING DUE** — no un-mirrored RAW buffer note in the scope (all curated or already
  watermarked): STOP cleanly, emit nothing.
- [ ] **MIRRORED** — every un-mirrored buffer note copied into a `wiki/` page AND
  `mirror_preservation_ok` returned `MIRRORED` AND its watermark stamped; the buffer left
  intact: emit `mirrored <N> buffer memory(ies) → wiki (buffer intact)`. STOP.
- [ ] **ABSTAINED** — `mirror_preservation_ok` returned `ABSTAIN`: the un-mirrored note's
  watermark left UNSTAMPED (retry next run), buffer untouched, `harvest abstained: <reasons>`
  surfaced. STOP.

## Scope of this skill

ONLY mirrors RAW harness-buffer memories (a top-level `<scope>/*.md` with minimal frontmatter)
into the curated `memory/wiki/`, idempotently, in ONE scope per pass. NEVER stubs, trims, or
modifies `MEMORY.md` or any buffer note (they are harness-owned). Does NOT split/merge/repair
existing wiki pages (those are the other passes); never deletes a memory.

## Resources

- `~/.claude/rules/markdown-memory-recall.md` — the coexistence model (buffer ⇄ wiki) +
  memgrep as the unlimited agent-invisible WIKI index.
- `/janitor-memory-write` — the page-authoring discipline this pass applies (its
  wikimem-model reference defines the tiers, the link law, page anatomy, and the lead).
- `/janitor-memory-update` — the correction protocol used when a buffer memory's subject
  already has a wiki page (UPDATE, never duplicate).
