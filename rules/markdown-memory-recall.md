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
> It holds the disk inventory, the full `memgrep` flag surface, the wikimem data model, and
> the rationale — read on demand. Everything here is normative on its own.

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
always **USER** scope. A general lesson parked in a case page pollutes it AND scatters the
methodology. SURVEY before minting a methodology page; a MOVED lesson leaves a `[[link]]`,
not a hole (nothing deleted, only relocated). Rationale + routing: the FULL REFERENCE above.

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
        # ARRAY — zsh passes an unquoted string "$ROOTS" as ONE bogus path (silent 0 results).
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

Other commands: `memgrep find` (keyword DSL; `--only-notes` = lessons), `overview` (the
entry-point page), `reindex` (refresh the SQLite sidecar).

**Recall is TWO HOPS.** Hop 1 prints a lean triage row per hit —
`<lmd>⇥<id-or-path>⇥<description>`, TAB columns so `cut -f2` is exact. The description is a
triage surface, **not the answer**: pick ONE, then hop:

```bash
memgrep recall <ATOM-ID> <dir>     # that ONE atom in full, with its lessons
```

`--output medium|full` / `--with-keywords` / `--with-notes` widen it (details: the FULL
REFERENCE).

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

Reading ANY memory includes its `[^N]` lessons (the why + the what-not-to-repeat). They arrive
with the SECOND HOP — take the hop on the note you chose.

## The note format

Frontmatter (the write verbs emit it — you rarely type it): `name` == filename stem ·
`description:` **QUOTED** (the load-bearing recall field) · `ocd`/`lmd` dates ·
`publish-globally:` **on every PROJECT page** (see below) ·
`metadata: {node_type: memory, type, tier}`. Body = the one fact (feedback/project add
`**Why:**` / `**How to apply:**`). `## Notes and lessons learned` is **MANDATORY on every page,
even when empty** — the standing landing zone for a correction lesson. Full frontmatter grammar +
a worked atom/lesson example: the FULL REFERENCE above.

### `publish-globally:` — how ONE project's knowledge becomes visible to ALL of them

**Every PROJECT-scope page carries `publish-globally: true|false`.** It is not optional and not
inferred: a page without it is a lint finding, and `memgrep lint --fix` inserts it.

`true` means this page is ALSO reachable from every other project on the machine, via a
**symlink** in the USER memory root pointing at the PROJECT page. That symlink IS the mechanism —
there is no copy, so there is no second version to drift. Without it, a project's features and
APIs are unknowable to any other project's agent, which is the gap the field exists to close.

Two invariants, both reconciled by `memgrep lint --fix`:

| state | meaning | fix |
|---|---|---|
| `true`, no symlink | published in name only | CREATE the symlink |
| symlink exists, no field | the symlink is the intent | ADD `publish-globally: true` |
| `false` + a symlink | a contradiction | **reported, never auto-resolved** — dropping the symlink and flipping the flag are both defensible, so it is a human's call |

**The default is `false`.** Publishing is opt-in because PROJECT memory is git-tracked and
**pushed** while USER scope is machine-private: a default of `true` would be an opt-OUT privacy
decision made on the user's behalf. Set it `true` deliberately, for the pages that describe what
OTHER projects need to know about this one — its public surface, not its internals.

**Maintain the page at its PROJECT home, never through the alias.** The symlink escapes the USER
scope root, so that scope's transaction guard refuses to write it (correctly), and the chore
candidate lister skips it for the same reason (janitor#249). One element, one page, one place it
is edited.

### THE LESSON FORM — a lesson is an ATOM, and a GUARDRAIL, not a story

A `[^N]:` footnote whose bracketed block is the lesson's ADDRESS
(`id`/`status`/`keywords`/`ocd`/`lmd` REQUIRED), then `DO NOT <X>, BECAUSE <why>. DO <Y>
instead.` ONE lesson = ONE mistake, ≤3 lines, all three parts.

**`keywords:` is the RECALL SURFACE** — the SYMPTOM phrases a future session will search with,
not the words the prose uses. **No keywords ⇒ no recall ⇒ the memory does not exist.**

**Two syntaxes.** The VERB's `--keywords` is **COMMA-separated** (spaces ok; it underscore-joins
each phrase). The **STORED** props block is space-separated — a hand-written comma there silently
DROPS the rest (another reason not to hand-author).

Full field grammar + supersession: the FULL REFERENCE above.

## AUTHORING — COLLABORATIVE; write through a memgrep verb, then validate

**Authorship confers NO ownership.** UPDATE another agent's USER/PROJECT page rather than fork a
near-synonym or hedge beside a wrong fact — safe: verbs SUPERSEDE, never overwrite. The real
failure is a known-false fact nobody corrected.

Never hand-author wikimem markdown — use the write verbs (`new-page`/`add-atom`/`add-lesson`/
`migrate`/`edit`); correct a wrong fact with `add-lesson --supersedes`, SAME id. Run `memgrep
validate <page> && memgrep lint <page>` after EVERY edit. Verb flags, supersession/travel, and
why collaboration is safe: the FULL REFERENCE above.

**CONCURRENT EDITING (TRDD-7YHT3FNK).** Write verbs are scope-LOCKED + `--base-sha256` CAS;
`memgrep edit` = exact-unique-match replace. Edit pages ONLY via memgrep verbs or the Edit tool —
never raw shell. On the "changed since enqueued" refusal: re-read, recompute, retry.

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

`MEMORY.md` is the **harness's**, not deprecated. The janitor maintains **exactly ONE line** in
it — the bridge link to `<project>-overview.md`: VERIFY, RE-ADD if deleted, **touch nothing
else**. "Recall runs through memgrep" is NOT a licence to empty or stub it.

## Separation of powers

The **janitor** reorganizes structure and *surfaces* contradictions but never edits a fact. An
**agent** creates and corrects content but never reorganizes. Executable protocol: the skills
`/janitor-memory-recall|write|update|bootstrap`.
