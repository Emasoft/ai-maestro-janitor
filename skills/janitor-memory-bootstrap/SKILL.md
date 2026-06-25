---
name: janitor-memory-bootstrap
description: BOOTSTRAP — stand up the three-scope wiki-memory system in a project that doesn't have it yet (the one-time adoption / fleet-rollout step). Creates the git-tracked PROJECT-scope memory dir, seeds the project's overview entry page (never a MEMORY.md stub — that file is the harness-owned buffer the harvest mirrors into the wiki), and points the agent at the recall rule + the write/recall/update skills. Use when a project has no wikimem and you want to "set up memory for this project", "bootstrap the wiki memory", "adopt the memory system", or onboard the project's memory. Run ONCE per project; idempotent if re-run.
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
| **USER** | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` (the janitor's FIXED data dir — hard-coded, NOT `${CLAUDE_PLUGIN_DATA}`, which is the *running* plugin's dir) | never in any repo (global) | — (created lazily on first USER write) |

This skill bootstraps the **PROJECT** scope — the one that lives in the repo and
is shared with every dev. LOCAL and USER need no setup.

## Prerequisites

- Run inside the project (a git repo is ideal — PROJECT scope is in-repo).
- The USER scope is the janitor's FIXED data dir `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` (always present once the janitor is installed; resolved by this explicit path, NOT via `${CLAUDE_PLUGIN_DATA}`).

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

## Step 3 — seed the `<project>-overview` entry page (NOT a MEMORY.md stub)

Don't overwrite an existing wikimem. Only seed when the dir is empty of pages:

```bash
ls "$PROJECT_MEM"/*.md >/dev/null 2>&1 && echo "wikimem already exists — skip seeding"
```

If empty, create the overview page with the **Write tool** (real content, not echo).
**Do NOT create or seed `MEMORY.md`** — in the coexistence model (TRDD-ab232dbd) `MEMORY.md`
is Anthropic's native, harness-owned memory BUFFER (the `# Memory` directive writes + auto-
loads it). The janitor never stubs/seeds/trims it; the harvest chore READS it and mirrors new
buffer memories into the curated wiki. Bootstrap seeds only the wiki entry page.

The project's **overview ENTRY POINT** page — file `<project-name>-overview.md` in
`$PROJECT_MEM/`, its `name:` is `<project-name>-overview` (Step 4 stages the exact
path). This is the Wikipedia-style overview the reader enters through (`memgrep
overview <memdir>` prints it): a concise story of the whole project with links OUT to
the deeper pages — **not an index**, no exhaustive pointer list, kept small. Fill the
placeholders from what you know about THIS project; leave the links sparse — they grow
as pages are added. Set `ocd`/`lmd` to today (`date +%F`), and `globs:` to the source
roots the project owns:

```yaml
---
name: <project-name>-overview
description: "how does <PROJECT> work — the overall story + where the deeper pages are"
ocd: <YYYY-MM-DD>
lmd: <YYYY-MM-DD>
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: <project-name>-overview
  globs: ["src/**", "scripts/**"]
---
<PROJECT> — a short overview: what it is, what it does, how its parts fit. Link OUT to
the deeper pages below rather than detailing them here.

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

`MEMORY.md` is **not** created here — it is the harness-owned buffer (see Step 3). If a
`MEMORY.md` already exists in the scope it stays exactly as the harness left it; bootstrap
neither stubs nor touches it.

## Step 4 — index it (optional) + commit guidance

```bash
command -v memgrep >/dev/null 2>&1 && memgrep reindex "$PROJECT_MEM"   # optional; recall auto-reindexes
```

Stage the new PROJECT-scope files **by name** (never `git add -A`) when the user
wants them committed — this scope is meant to be pushed so every dev shares it:

```bash
git -C "$REPO" add .gitignore "$PROJECT_MEM"/*-overview.md
# then commit when the user asks — do NOT auto-commit. (MEMORY.md is the harness-owned
# buffer — bootstrap never creates it, so it is not staged here.)
```

## Step 5 — point the agent at the system (the payload of bootstrap)

After the dir exists, tell the agent (and record in your report) that this project
now USES the **Wikimem** (the markdown memory system), governed by THE
PROACTIVE-USE CONTRACT in
`~/.claude/rules/markdown-memory-recall.md`:

- **RECALL BEFORE ACTING** — before debugging a recurring problem / a design
  decision / acting on a recurring alert, run `/janitor-memory-recall` first,
  indexed by the symptom (the user's words), across all 3 scopes. Unprompted.
- **WRITE / UPDATE AFTER SOLVING** — after solving a non-trivial problem or making
  a decision, capture it with `/janitor-memory-write` (MEMORIZE) or
  `/janitor-memory-update`, using the clean-the-fact-in-place + demote-the-error-
  to-a-`[^N]`-lesson correction protocol. Unprompted.
- **MAINTAIN THE PROJECT WIKIMEM** — keep the PROJECT-scope pages current as you
  work: the `<project>-overview` entry page (seeded above), the key-solution component
  pages, the publish/deploy pipeline page — so the knowledge is git-tracked and shared.
- **SCOPE ROUTING** — machine-private → LOCAL; project-shared (no secrets) →
  PROJECT; cross-project → USER; UNSURE → LOCAL.

## Output

One line: `Wikimem bootstrapped: PROJECT scope at <repo>/.claude/project/memory/
(gitignore exception <added|already present|not needed>; seeded
<project>-overview <created|already existed>).` Do NOT echo the seeded
page bodies back into the conversation.

## Examples

<example>
User: set up memory for this project
→ create .claude/project/memory/, add the `!.claude/project/memory/**` gitignore
  exception (the repo's .gitignore had `.claude/**`), seed the `<project>-overview`
  page (NOT a MEMORY.md stub — that file is the harness-owned buffer), and tell the
  agent recall-first / write-after.
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
- The wiki data model the seeded hub follows (tiers, hub/aspect/component, the
  bidirectional link law, page anatomy) — see the `/janitor-memory-write` skill,
  which owns and fully documents the model.
- `/janitor-memory-write` (MEMORIZE) · `/janitor-memory-update` (UPDATE) ·
  `/janitor-memory-recall` (RECALL) — the day-to-day legs this bootstrap enables.
