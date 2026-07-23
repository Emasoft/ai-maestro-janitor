<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

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
   you update rather than duplicate). When a new fact supersedes an old one, use the **correction
   protocol** (`memgrep add-lesson --supersedes` — see AUTHORING): clean the body to the current
   truth AND demote the old statement to a dated `[^N]` lesson carrying the WHY + the verbatim
   `SUPERSEDED BODY:`. The fact moves forward clean; the error becomes a guardrail.
   **Never delete knowledge — relocate it.**
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

- WRONG: "OAuth creds live in the macOS keychain services." (Findable only if you already
  know the answer is "keychain".)
- RIGHT: "rotator failed, had to log in manually — where are the creds / why did the swap
  fail" — with the keychain fact in the BODY.

Recall is two-hop: a symptom query lands you on the note; the note's BODY gives the answer.
`memgrep recall` ranks on `description + title + tags` ONLY.

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

Reading ANY memory means also reading its `[^N]` lessons — they are *why* the facts are what
they are and *what not to repeat*. FREE: `memgrep recall`/`find` auto-resolve and append them.

## The note format

```yaml
---
name: <kebab-slug>            # == filename stem
description: "<symptom surface — the load-bearing recall field>"
ocd: <YYYY-MM-DD>             # Original Creation Date — set once
lmd: <YYYY-MM-DD>             # Last Modified Date — bump on every edit
metadata:
  node_type: memory
  type: user | feedback | project | reference
  tier: hub | aspect | component      # wiki layer (see below)
---
<body: the one fact; for feedback/project add **Why:** and **How to apply:** lines>

## Notes and lessons learned
[^3]: [id:ATOM-234P-U35Q, status:valid, keywords:"retry_cap guessed_variable_name", ocd:2026-06-09, lmd:2026-06-09]
  DO NOT read a constant off a guessed variable name, BECAUSE `max_attempts` does not exist and
  the real cap is `max_retries` = 3, not 5. DO read the constant from the source instead.
```

`## Notes and lessons learned` is **MANDATORY on every page, even when empty** — it is the
standing landing zone for a correction lesson.

### THE LESSON FORM — a lesson is an ATOM, and a GUARDRAIL, not a story

```
[^N]: [id:ATOM-xxxx-xxxx, status:valid|superseded, superseded-by:ATOM-xxxx-xxxx, keywords:"<key_phrase> …", ocd:<date>, lmd:<date>] DO NOT <X>, BECAUSE <why>. DO <Y> instead.
```

**The metadata block is the lesson's ADDRESS.** `id`, `status`, `keywords`, `ocd`, `lmd`
REQUIRED; `superseded-by` when superseded.

- **`keywords:` is the RECALL SURFACE** — the phrases a future session SEARCHES with (the
  symptom), usually NOT the words the prose uses. **No keywords ⇒ no recall ⇒ the memory does not
  exist.** A **comma** splits FIELDS, **quotes** delimit the keywords VALUE, a **space** splits the
  KEYWORDS in it — so each is a KEY-PHRASE, `underscore_joined`, never shredded.
- **`status:`** `valid` (holds) | `superseded` (history — NEVER apply; follow `superseded-by`).
  **`id:`** is stable and corpus-wide; `[^N]` is page-local and renumbers, so only `id` is a
  durable reference.
- **Prose:** ONE lesson = ONE mistake · ≤3 lines / ~40 words · all three parts (`DO NOT` = the
  act about to be repeated; `BECAUSE` = the WHY, without which it cannot stop the repeat;
  `DO … instead` = the exit). Chronology/evidence go in the page BODY or a TRDD.

Full grammar + supersession: the FULL REFERENCE above.

## AUTHORING — route every write through a memgrep verb, then validate

A HAND-WRITTEN atom is where malformed memories come from — an unquoted `desc:` that breaks
grep, a `[^N]` lesson with metadata but no body that `find --only-notes` can't see, an atom too
long to be one fact. So **do not hand-author wikimem markdown**: the memgrep write verbs
synthesise valid syntax by construction.

- new page → `memgrep new-page --path P --tier hub|aspect|component --name N --description "…" --type …`
- new fact → `memgrep add-atom --page P --keywords "symptom phrases" --desc "quoted ≤200-char prose"` (body on stdin)
- new lesson → `memgrep add-lesson --page P --atom ID --keywords "…"` (DO-NOT/BECAUSE/DO on stdin)
- move an atom → `memgrep migrate <atom> --from A --to B` (NEVER hand-move — it drops lessons and collides footnote numbers)

**Correcting a wrong fact is a SUPERSESSION, never a delete or an overwrite.** Run
`memgrep add-lesson --supersedes --atom <id>` FIRST — it embeds the atom's current body verbatim
as `SUPERSEDED BODY: <old>` (the never-delete rule, enforced) and records the WHY as a dated
lesson — THEN clean the atom's body to the new truth, keeping the SAME id (a `-v2` duplicate is
the anti-pattern). An atom's dated superseded-lessons ARE its changelog and TRAVEL with it on a
`migrate`. Only a pure typo / formatting slip is edited in place.

**After EVERY edit, prove it:** `memgrep validate <page> && memgrep lint <page>`. `lint` is
deterministic + FP-free — it catches an unquoted desc, a body-less lesson, an oversized atom, a
supersession missing its `SUPERSEDED BODY:`, a dangling footnote, and a one-sided `[[link]]`. A
non-zero exit is a defect to fix NOW, before moving on.

## The wiki layer (wikimem)

The corpus is a navigable WIKI, not a pile. A **hub** is one functionality's overview
(carries `globs:` — the files it owns). An **aspect** is a general rule shared by many
elements (it RADIATES an `## Applies to` list down). A **component** is ONE element's page
(it RECEIVES, carrying `## Governed by` up-links, and never re-copies a governing rule).
**One element = one page.**

**THE LINK LAW: every link is bidirectional.** If A links to B, B links to A — `Applies to`
↔ `Governed by` across tiers, `See also` ↔ `See also` laterally. Wire both ends in the same
edit.

## MEMORY.md is a DEPRECATED STUB

The index is memgrep's and ONLY memgrep's (agent-invisible, unlimited SQLite). Do **NOT** add
pointers to the stub, load it as an index, or **hand-trim it** — agents who trimmed the old
ever-growing index lost pointers and corrupted the corpus. That is why the index moved to memgrep.

## Separation of powers

The **janitor** reorganizes structure and *surfaces* contradictions but never edits a fact. An
**agent** creates and corrects content but never reorganizes. Executable protocol: the skills
`/janitor-memory-recall|write|update|bootstrap` (bootstrap stands up a project's wikimem once).
