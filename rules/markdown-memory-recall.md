<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active.** Check (cheap `$HOME` stats),
> where `DATA` = `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`:
> **UNINSTALLED** (`DATA` absent) → this file is an orphan the plugin could not remove: treat as
> INERT and tell the user they may delete it — but NEVER any MEMORY store, only this rule file, and
> only with their ok. **DISARMED** (`DATA/global-state/kill-switch.flag` or legacy
> `~/.claude/janitor-global-state/kill-switch.flag` exists) → the janitor is intentionally stopped:
> INERT this session. **ACTIVE** (otherwise) → apply the rule below.

# Markdown memory — recall protocol (the search half)

The harness `# Memory` directive tells you how to **WRITE** memories. This rule is the
missing half: how to **RECALL** them, and the discipline that makes recall work.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/markdown-memory-recall-full.md`
> It holds the file/folder inventory ("I found this on disk — is it safe to touch?"), the
> complete `memgrep` flag surface, the wikimem data model, the dual-test evaluation method,
> and the rationale. Read it when you need a detail below expanded. Everything here is
> normative on its own.

## THE PROACTIVE-USE CONTRACT (do this UNPROMPTED — the whole point of memory)

The memory system is **worthless if it is only used when the user asks**. Four standing
commitments, for every agent, in every project:

1. **RECALL BEFORE ACTING.** Before you debug a recurring problem, make a design decision, or
   act on a recurring alert — RECALL FIRST ("have we hit this before?"). It is cheap, and it is
   the entire reason a memory exists.
2. **WRITE / UPDATE AFTER SOLVING.** After solving a non-trivial problem, or making a decision
   not derivable from the code, capture it into the page that OWNS the subject (RECALL first, so
   you update rather than duplicate). A new fact that supersedes an old one uses the **correction
   protocol** (see AUTHORING — supersede, never overwrite; the old statement becomes a dated
   `[^N]` guardrail). **Never delete knowledge — relocate it.**
3. **MAINTAIN THE PROJECT WIKIMEM.** Keep PROJECT-scope pages current (architecture hub,
   key components, the publish/deploy pipeline) so knowledge is git-tracked and shared, not
   stranded in one session's head.
4. **SCOPE ROUTING — decide BEFORE writing** (table below). **UNSURE → LOCAL.**

## STAY ON TOPIC: a case page holds CASE facts; METHODOLOGY lives in its own page

**One page = one subject.** Ask of EVERY lesson before writing it: *is this true only of THIS
subject, or would it still be true of a completely different bug in a completely different
system?* Subject-specific → the subject's page. A transferable way of WORKING (how to diagnose,
verify, falsify) → **the methodology page that owns it** (`debugging-methodology`), nearly
always **USER** scope. A general lesson parked in a case page is off-topic pollution AND scatters
the methodology, so the page that should own it owns nothing. SURVEY before minting a new
methodology page; when you MOVE a lesson, leave a `[[link]]`, not a hole (nothing is deleted,
only relocated). Rationale + routing table: the FULL REFERENCE above.

## The one law that makes memory work: index by the QUESTION, not the answer

A memory is found from the SYMPTOM, not the solution. A note's `description:` (and
`title`/`tags`) MUST carry the words a future session will have when the problem RECURS —
the user's words, the error text, the symptom — NOT the jargon of the fix.

Recall is two-hop: a symptom query lands you on the note; the note's BODY gives the answer.
`memgrep recall` ranks on `description + title + tags` ONLY. Hence:

- **APPENDING? EXTEND `description:`** — ranking ignores the body; an added fact whose symptom
  the description lacks is **unfindable**.
- **A CODE lesson ships with an executable check** — a note explains a guard, it is not one.

## Recall BEFORE acting — the protocol

```bash
LOCAL_MEM="$HOME/.claude/projects/<project-slug>/memory"                          # machine-private
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null)/.claude/project/memory" # git-tracked, shared
USER_MEM="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory"  # global; HARD-CODED —
        # never ${CLAUDE_PLUGIN_DATA}, that is the RUNNING plugin's dir, not the janitor's
ROOTS=(); for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS+=("$d"); done
        # ARRAY, not a space-joined string: zsh does not word-split an unquoted "$ROOTS", so the
        # string form passes every root as ONE bogus path and silently returns 0 results.
SYMPTOM="the user's words / the error / the symptom"   # NOT the answer's jargon

if command -v memgrep >/dev/null 2>&1; then
  memgrep recall "$SYMPTOM" "${ROOTS[@]}"   # ranked: path — description (+ its lessons)
else
  grep -rliE "$SYMPTOM" "${ROOTS[@]}"       # fallback: degrade, never break
fi
```

Read the top 1–3 notes. On conflict the MORE SPECIFIC scope wins: **LOCAL > PROJECT > USER**.
Nothing returned ⇒ the memory doesn't exist yet — write one after solving the problem. No
`memgrep`? `cargo install --path <…>/ai-maestro-janitor/scripts/memgrep`.

Other commands: `memgrep find "+must -exclude \"exact phrase\"" <dir>` (keyword DSL;
`--only-notes` searches the lessons), `memgrep overview <dir>` (the project's entry-point
page), `memgrep reindex <dir>` (refresh the SQLite sidecar).

**Recall is TWO HOPS.** Hop 1 prints a lean triage row per hit —
`<lmd>⇥<id-or-path>⇥<description>`, TAB columns so `cut -f2` is exact. The description is a
triage surface, **not the answer**: pick ONE, then hop:

```bash
memgrep recall <ATOM-ID> <dir>     # that ONE atom in full, with its lessons
```

Measured 247 tokens/query vs 441 always-rich, same accuracy. `--output medium|full` and
`--with-keywords`/`--with-notes` widen it (details: the FULL REFERENCE).

## Memory scopes — pick by what the note CONTAINS

| Scope | Root | Git | Put here |
|---|---|---|---|
| **LOCAL** | `~/.claude/projects/<slug>/memory/` | outside any repo — never pushed | machine-private: local paths, usernames, hostnames, an account/plan, install state, "on THIS machine…", secret-adjacent hints |
| **PROJECT** | `<git-root>/.claude/project/memory/` | **tracked + PUSHED** to every cloner | machine-AGNOSTIC project knowledge: architecture, code gotchas, project lessons — **zero** private data |
| **USER** | the janitor's fixed plugin-DATA memory dir (above) | never in a repo | knowledge true across ALL projects |

**THE WRITE GATE — ask before writing to PROJECT:** *"Would this be TRUE and USEFUL for a
stranger who clones this repo on a DIFFERENT machine?"* If no → **LOCAL**. Red flags that
each force LOCAL: an absolute home path (`/Users/…`, `/home/…`, `C:\Users\…`), a username /
hostname / email / secret, a private project name, the phrasing "on THIS machine" / "the
owner decided", or one box's install state. PROJECT memory is **pushed to GitHub**, so one
machine's private config written there is inherited by every future cloner — a real leak.
Split a note if needed: machine-agnostic fact → PROJECT, per-machine state → LOCAL,
cross-linked. **UNSURE → LOCAL.**

## Read-the-notes rule — a memory's lessons ARE part of the memory

Reading ANY memory means also reading its `[^N]` lessons — *why* the facts are what they are and
*what not to repeat*. They arrive with the SECOND HOP, not with every search hit: "read the
notes" means take the hop on the note you chose, not skim whatever the search dumped.

## The note format

Frontmatter (the write verbs emit it — you rarely type it): `name` == filename stem ·
`description:` **QUOTED** (the load-bearing recall field) · `ocd`/`lmd` dates ·
`metadata: {node_type: memory, type, tier}`. Body = the one fact (feedback/project add
`**Why:**` / `**How to apply:**`). `## Notes and lessons learned` is **MANDATORY on every page,
even when empty** — the standing landing zone for a correction lesson. Full frontmatter grammar +
a worked atom/lesson example: the FULL REFERENCE above.

### THE LESSON FORM — a lesson is an ATOM, and a GUARDRAIL, not a story

A `[^N]:` footnote whose bracketed block is the lesson's ADDRESS
(`id`/`status`/`keywords`/`ocd`/`lmd` REQUIRED), then `DO NOT <X>, BECAUSE <why>. DO <Y>
instead.` ONE lesson = ONE mistake, ≤3 lines, all three parts.

**`keywords:` is the RECALL SURFACE** — the SYMPTOM phrases a future session will search with,
not the words the prose uses. **No keywords ⇒ no recall ⇒ the memory does not exist.** A comma
splits FIELDS, a space splits the KEY-PHRASES, so each phrase is `underscore_joined` — written
`a phrase, another phrase` everything after the first comma is silently DROPPED.

Full field grammar + supersession: the FULL REFERENCE above.

## AUTHORING — route writes through a memgrep verb, then validate

Do NOT hand-author wikimem markdown (the source of unquoted `desc:`, body-less `[^N]`, oversized
atoms) — use the write verbs (`new-page`/`add-atom`/`add-lesson`/`migrate`). Correct a wrong fact
by SUPERSESSION, never a delete/overwrite: `add-lesson --supersedes` embeds the verbatim
`SUPERSEDED BODY:` and keeps the SAME id (a `-v2` duplicate is the anti-pattern). Run
`memgrep validate <page> && memgrep lint <page>` after EVERY edit. Verb flags + the
supersession/travel protocol: the FULL REFERENCE above.

## The wiki layer (wikimem)

The corpus is a navigable WIKI, not a pile. A **hub** is one functionality's overview
(carries `globs:` — the files it owns). An **aspect** is a general rule shared by many
elements (it RADIATES an `## Applies to` list down). A **component** is ONE element's page
(it RECEIVES, carrying `## Governed by` up-links, and never re-copies a governing rule).
**One element = one page.**

**THE LINK LAW: every link is bidirectional.** If A links to B, B links to A — `Applies to`
↔ `Governed by` across tiers, `See also` ↔ `See also` laterally. Wire both ends in the same
edit.

## MEMORY.md — the two systems COEXIST; the janitor maintains ONE line

`MEMORY.md` is the **harness's** and **not deprecated**. The janitor maintains **exactly ONE line**
in it: a link to the project's main wikimem page (`<project>-overview.md`) — the bridge between the
two systems. VERIFY it is there, RE-ADD if deleted, **touch nothing else**. *"Recall runs through
memgrep"* = where SEARCH happens, NOT a licence to empty or stub it.

## Separation of powers

The **janitor** reorganizes structure and *surfaces* contradictions but never edits a fact. An
**agent** creates and corrects content but never reorganizes. Executable protocol: the skills
`/janitor-memory-recall|write|update|bootstrap` (bootstrap stands up a project's wikimem once).
