---
name: janitor-memory-harvest
description: HARVEST executor — the daily NON-DESTRUCTIVE chore that re-files STRAY memory into the wiki. When a scope's MEMORY.md carries added memories (beyond the deprecation stub) or an agent left loose .md memory files outside the wikimem model, harvest each into proper wikimem pages (editorial model + scope routing), then — only after a verify proves no memory was lost — reduce MEMORY.md to the stub, keeping a backup. Use on a [janitor-memory-harvest] marker, or "harvest the memory", "incorporate MEMORY.md / stray notes into the wiki".
---

# Janitor memory — HARVEST (incorporate stray memory artifacts into the wiki)

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **opus** agent — you ARE that agent. Run the whole pass here in your own
> context and return only a one-line result + the report path. A wikimem editorial pass is
> never run inline in a main session (it must not burden CPV or any other session's context).

## What this is

The memory index moved entirely into `memgrep` (the agent-invisible SQLite index);
`MEMORY.md` is a deprecation stub and recall is memgrep-only (see
`~/.claude/rules/markdown-memory-recall.md`). But agents WILL keep mis-adding memories to
`MEMORY.md`, and some leave loose memory `.md` files outside the wikimem model. HARVEST is
the permanent DAILY chore that re-files those stray artifacts into the proper wiki —
**without ever deleting a memory**.

It is NON-DESTRUCTIVE by construction: it CREATES proper wikimem pages for any memory not
yet in one, and only reduces `MEMORY.md` to the stub AFTER a verify proves every memory it
held now lives in a wikimem page — and it ALWAYS keeps a backup of the original first.

**THE IRON RULE: never lose a memory.** When unsure a memory is safely in the wiki, leave
the artifact intact, keep the backup, and surface a finding. A missed re-file is
recoverable next run; a deleted memory is not.

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
(rides the next `publish.py`). Otherwise restrict to LOCAL + USER.

## The procedure

### 1. Find the stray artifacts in the ONE scope

Two sources:

- **A non-stub `MEMORY.md`** — it carries pointer lines (each a markdown list item
  linking a page Title to its note file, with a one-line hook) or
  actual memory content beyond the deprecation notice. (A MEMORY.md that already IS the
  stub — it contains "index retired (managed by memgrep)" and nothing else — is skipped.)
- **Loose memory `.md` files** outside the model — a note with no/partial wikimem
  frontmatter sitting outside the wiki. EXCLUDE the stub `MEMORY.md`, the generated index
  files (`memory-index.md`, `memory-reorg-proposed.md`), and the private `user-mem/`.

If neither exists, nothing is due — STOP cleanly (emit nothing).

### 2. Back up FIRST (RULE 0 — recoverability before any reduction)

Before touching anything, copy each artifact you will reduce to a sibling backup:

```bash
cp "$MEMDIR/MEMORY.md" "$MEMDIR/MEMORY.md.pre-harvest-$(date +%F).bak"
```

The backup is the guarantee — the original is always recoverable even if the harvest is
imperfect. (In PROJECT scope the git history is an additional backup.)

### 3. Harvest each memory into a proper wikimem page (the editorial work)

For each memory the artifact holds:

- **A pointer to an EXISTING note** → that note already IS the memory; nothing to create
  (the repair pass fixes its shape). Just confirm the target file exists in the scope.
- **Content NOT yet in a page** → CREATE a proper wikimem page for it — this is the
  `/janitor-memory-write` discipline applied here:
  - **One subject per page; same-theme memories share ONE page** — group the strays by
    subject BEFORE creating, so you never fragment one topic across pages.
  - **Complete frontmatter** — `name`, symptom-indexed `description`, `ocd`, `lmd`,
    `metadata.{node_type: memory, type, tier}`.
  - **Tier expand/reduce** — a general rule → `aspect` (radiates `## Applies to`); one
    element → `component` (receives `## Governed by`); a functionality overview → `hub`.
  - **Bidirectional links** — every `[[link]]` wired on BOTH ends (the link law);
    `## See also` for lateral relations.
  - **Atomic memories, each with its own `## Notes and lessons learned`** section.
  - **Scope routing** — machine-private (local paths / hostnames / secrets) → LOCAL;
    project-shared (no secrets) → PROJECT; cross-project → USER; **UNSURE → LOCAL**.
  Create pages through the transaction core (`memory_txn_cli.py` — the same crash-safe,
  flock-guarded path the other passes use) or the write skill; then `memgrep reindex
  "$MEMDIR"`.

### 4. Verify EVERY memory is now in the wiki (BEFORE any stub reduction)

Prove preservation with the formal check — it GATES the stub reduction:

```bash
uv run --quiet - <<PY
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_edit_verify as v, pathlib
memdir = pathlib.Path("$MEMDIR")
mem = (memdir / "MEMORY.md").read_text(encoding="utf-8")
notes = {p.name for p in memdir.glob("*.md") if p.name != "MEMORY.md"}
corpus = "\n".join(p.read_text(encoding="utf-8") for p in memdir.glob("*.md"))
ok, missing = v.harvest_preservation_ok(mem, corpus, notes)
print("PRESERVED" if ok else "ABSTAIN: " + "; ".join(missing))
sys.exit(0 if ok else 1)
PY
```

`harvest_preservation_ok` confirms every MEMORY.md memory now lives in the wiki — a
POINTER's target note exists; a CONTENT memory is a substring of some page. If it prints
`ABSTAIN`, leave `MEMORY.md` + the `.bak` intact, do NOT reduce, and surface
`[janitor-memory] harvest abstained: <reasons>`. Only on `PRESERVED` proceed to step 5.

### 5. Reduce MEMORY.md to the stub (only after step 4 passes)

Overwrite `MEMORY.md` with the canonical deprecation stub from the recall rule (it carries
the `memgrep overview` entry-point + `memgrep recall` commands). A loose `.md` that became
its own proper wikimem page stays as that page (it is not deleted — it BECAME the page); a
loose `.md` whose content was folded into another page is reduced the same way (backup +
the content now lives in the surviving page). PROJECT-scope writes are staged-not-pushed.

## EXIT / idempotency / bounds

- **SUCCESS** = every memory re-filed into a wikimem page AND `MEMORY.md` reduced to the
  stub (backup kept). Report `[janitor-memory] harvested <N> memory(ies) → wiki; MEMORY.md
  stubbed (backup kept)`.
- **Idempotent + daily** — a stub `MEMORY.md` with no stray files is a no-op; runs once/day
  (`harvest_per_day`, default 1; `0` disables). The chore is PERMANENT — it re-files
  whatever agents mis-add, forever.
- **Bounded** — one scope per pass; honors the kill-switch + `harvest_per_day=0`.
- **Never destructive** — backup before any reduction; ABSTAIN when preservation is
  unproven. A crash mid-pass is safe: the backup remains and the next daily run re-files
  whatever is still stray.

## Done when (terminating conditions)

This pass is complete when ONE of these holds (one scope per pass; it never deletes a
memory and never reduces `MEMORY.md` without both a verify AND a backup):

- [ ] **NOTHING DUE** — no non-stub `MEMORY.md` and no stray `.md` in the scope: STOP
  cleanly, emit nothing.
- [ ] **HARVESTED** — every stray memory re-filed into a proper wikimem page AND
  `harvest_preservation_ok` returned `PRESERVED` AND `MEMORY.md` reduced to the stub
  (backup kept): emit `harvested <N> … MEMORY.md stubbed (backup kept)`. STOP.
- [ ] **ABSTAINED** — `harvest_preservation_ok` returned `ABSTAIN`: `MEMORY.md` + the
  `.bak` left intact, nothing reduced, `harvest abstained: <reasons>` surfaced. STOP.

## Scope of this skill

ONLY incorporates STRAY memory artifacts (a non-stub `MEMORY.md`, loose `.md` memory files)
into the proper wikimem, then stubs `MEMORY.md` — non-destructively, in ONE scope per pass.
Does NOT split/merge/repair existing wiki pages (those are the other passes); never deletes
a memory; never reduces `MEMORY.md` without both a verify AND a backup.

## Resources

- `~/.claude/rules/markdown-memory-recall.md` — the memgrep-only index model + the stub.
- `/janitor-memory-write` — the page-authoring discipline this pass applies (its
  wikimem-model reference defines the tiers, the link law, page anatomy, and the lead).
