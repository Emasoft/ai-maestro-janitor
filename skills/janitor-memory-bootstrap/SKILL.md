---
name: janitor-memory-bootstrap
description: BOOTSTRAP — stand up the wiki-memory system in a project that doesn't have it yet (the one-time fleet-rollout step). Creates the git-tracked PROJECT-scope memory dir under .claude/project/memory/ (adding the gitignore exception when .claude/ is ignored), seeds a starter architecture-hub page + a MEMORY.md index, and points the agent at the recall rule + the write/recall/update skills + the proactive-use contract. Use when a project has no wikimem and you want to "set up memory for this project", "bootstrap the wiki memory", "adopt the memory system", or onboard the project's memory. Run ONCE per project; idempotent if re-run.
---

# Janitor memory — BOOTSTRAP

## Overview

BOOTSTRAP is the one-time **adoption** step: it stands up the three-scope memory
wiki in a project that doesn't have one yet, so the day-to-day legs
(`/janitor-memory-recall`, `/janitor-memory-write`, `/janitor-memory-update`)
have a place to read and write. It is the fleet-rollout mechanism — run it once
per project to adopt the system; thereafter the agent maintains the wiki as part
of normal work (see the proactive contract below). Re-running is safe and
idempotent: it never clobbers an existing wikimem.

The three scopes (final design, TRDD-4c3733d9):

| Scope | Root | Git | This skill creates |
|---|---|---|---|
| **LOCAL** | `~/.claude/projects/<slug>/memory/` | never pushed (harness-owned) | — (the harness owns it; no action here) |
| **PROJECT** | `<repo>/.claude/project/memory/` | **tracked + PUSHED** (in-repo) | ✅ dir + gitignore exception + seed pages |
| **USER** | `${CLAUDE_PLUGIN_DATA}/memory/` | never in any repo (global) | — (created lazily on first USER write) |

This skill bootstraps the **PROJECT** scope — the one that lives in the repo and
is shared with every dev. LOCAL and USER need no setup.

## Prerequisites

- Run inside the project (a git repo is ideal — PROJECT scope is in-repo).
- `${CLAUDE_PLUGIN_DATA}` resolves (it always does when the janitor is installed).

## Step 1 — create the PROJECT memory directory

```bash
REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PROJECT_MEM="$REPO/.claude/project/memory"
mkdir -p "$PROJECT_MEM"
```

## Step 2 — ensure the gitignore exception (only if `.claude/` is ignored)

The PROJECT scope MUST be git-tracked. If the repo's `.gitignore` ignores
`.claude/` (very common), the memory dir would be silently dropped — so re-include
it. Three cases; handle them in order, using the Edit tool (never sed) on
`$REPO/.gitignore`:

1. **`.claude/` is NOT ignored at all** → nothing to do; the dir is already
   trackable.
2. **A bare `.claude/` (or `.claude`) ignore line exists** → it prunes the whole
   tree so git never descends to honor a re-include. Change that line to the deep
   form `.claude/**`, THEN add the four exception lines below. (The bare form must
   become `.claude/**` first — exceptions under a bare-pruned dir are inert.)
3. **`.claude/**` already present** → just add the four exception lines below if
   they're missing.

Detect which case applies:

```bash
grep -nE '^\.claude(/|/\*\*)?$' "$REPO/.gitignore" 2>/dev/null   # shows the ignore line, if any
grep -qxF '!.claude/project/memory/**' "$REPO/.gitignore" 2>/dev/null && echo "exception already present"
```

The canonical exception block to ensure is present (each parent dir re-included
first, then the whole tree — order matters):

```gitignore
# The PROJECT memory scope lives in-repo under .claude/ and MUST be tracked +
# pushed (the shared, cross-dev wiki memory). Re-include it via these exceptions.
!.claude/project/
!.claude/project/memory/
!.claude/project/memory/**
```

Use the **Edit tool** to make these changes (so you see the diff). If no
`.gitignore` exists and `.claude/` is not ignored anywhere, skip this step
entirely.

### Verify the exception actually took effect

```bash
git -C "$REPO" check-ignore -v ".claude/project/memory/MEMORY.md"; echo "exit=$?"
# exit 1 (no match) = GOOD: the path is trackable. exit 0 = still ignored → the
# exception is wrong (usually a bare `.claude/` line that was never widened to
# `.claude/**`); fix it and re-check.
```

## Step 3 — seed a starter architecture HUB + the MEMORY.md index

Don't overwrite an existing wikimem. Only seed when the dir is empty of pages:

```bash
ls "$PROJECT_MEM"/*.md >/dev/null 2>&1 && echo "wikimem already exists — skip seeding"
```

If empty, create two files with the **Write tool** (real content, not echo).

`$PROJECT_MEM/architecture.md` — the project's root architecture HUB. Fill the
placeholders from what you actually know about THIS project (its name, what it is,
its top-level parts); leave the parts map sparse — it grows as pages are added.
Set `ocd`/`lmd` to today (`date +%F`), and set `globs:` to the source roots the
project owns:

```yaml
---
name: architecture
description: "how does <PROJECT> work — overview, the main parts, where the key pieces live"
ocd: <YYYY-MM-DD>
lmd: <YYYY-MM-DD>
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: architecture
  globs: ["src/**", "scripts/**"]
---
<PROJECT> — one paragraph: what it is and what it does.

## Parts map
- (add component/aspect pages here as they're created — e.g. the data model, the
  API surface, the publish/deploy pipeline)

## Applies to
- (radiates down to the component/aspect pages of this functionality — empty until
  the first one is written; wire the reciprocal `## Governed by` on each)

## See also
- (lateral links to other functionality hubs, once they exist)

## Notes and lessons learned
```

`$PROJECT_MEM/MEMORY.md` — the human index loaded each session (one line per
page; the canonical loaded index):

```markdown
# Project memory (wikimem) — PROJECT scope

The git-tracked, cross-dev memory wiki. Recall surfaces these pages by symptom;
the protocol lives in `~/.claude/rules/markdown-memory-recall.md` (run
`/janitor-memory-recall`). One line per page below.

- [architecture](architecture.md) — how <PROJECT> works: overview + the parts map.
```

## Step 4 — index it (optional) + commit guidance

```bash
command -v memgrep >/dev/null 2>&1 && memgrep reindex "$PROJECT_MEM"   # optional; recall auto-reindexes
```

Stage the new PROJECT-scope files **by name** (never `git add -A`) when the user
wants them committed — this scope is meant to be pushed so every dev shares it:

```bash
git -C "$REPO" add .gitignore "$PROJECT_MEM/architecture.md" "$PROJECT_MEM/MEMORY.md"
# then commit when the user asks — do NOT auto-commit.
```

## Step 5 — point the agent at the system (the payload of bootstrap)

After the dir exists, tell the agent (and record in your report) that this project
now USES the memory system, governed by THE PROACTIVE-USE CONTRACT in
`~/.claude/rules/markdown-memory-recall.md`:

- **RECALL BEFORE ACTING** — before debugging a recurring problem / a design
  decision / acting on a recurring alert, run `/janitor-memory-recall` first,
  indexed by the symptom (the user's words), across all 3 scopes. Unprompted.
- **WRITE / UPDATE AFTER SOLVING** — after solving a non-trivial problem or making
  a decision, capture it with `/janitor-memory-write` (MEMORIZE) or
  `/janitor-memory-update`, using the clean-the-fact-in-place + demote-the-error-
  to-a-`[^N]`-lesson correction protocol. Unprompted.
- **MAINTAIN THE PROJECT WIKIMEM** — keep the PROJECT-scope pages current as you
  work: the architecture hub (seeded above), the key-solution component pages, the
  publish/deploy pipeline page — so the knowledge is git-tracked and shared.
- **SCOPE ROUTING** — machine-private → LOCAL; project-shared (no secrets) →
  PROJECT; cross-project → USER; UNSURE → LOCAL.

## Output

One line: `Wikimem bootstrapped: PROJECT scope at <repo>/.claude/project/memory/
(gitignore exception <added|already present|not needed>; seeded
architecture hub + MEMORY.md <created|already existed>).` Do NOT echo the seeded
page bodies back into the conversation.

## Examples

<example>
User: set up memory for this project
→ create .claude/project/memory/, add the `!.claude/project/memory/**` gitignore
  exception (the repo's .gitignore had `.claude/**`), seed architecture.md +
  MEMORY.md, and tell the agent recall-first / write-after.
</example>

<example>
User: bootstrap the wiki memory
→ same; if a wikimem already exists, skip seeding and just confirm + restate the
  proactive contract.
</example>

<example>
User: adopt the memory system in this repo
→ run all five steps; verify `git check-ignore` says the memory dir is trackable.
</example>

## Scope

ONLY stands up the PROJECT-scope memory dir + gitignore exception + seed pages,
once per project (idempotent). Does NOT create LOCAL/USER scopes (the harness /
first-write own those), does NOT commit on its own, and does NOT author topic
pages beyond the starter hub — that is the day-to-day job of
`/janitor-memory-write` / `/janitor-memory-update`. To FIND pages use
`/janitor-memory-recall`.

## Resources

- `~/.claude/rules/markdown-memory-recall.md` — THE PROACTIVE-USE CONTRACT + the
  recall law (index by the question) + the three scopes.
- [../janitor-memory-write/references/wikimem-model.md](../janitor-memory-write/references/wikimem-model.md)
  — the wiki data model (tiers, hub/aspect/component, the bidirectional link law,
  page anatomy) the seeded hub follows.
- `/janitor-memory-write` (MEMORIZE) · `/janitor-memory-update` (UPDATE) ·
  `/janitor-memory-recall` (RECALL) — the day-to-day legs this bootstrap enables.
