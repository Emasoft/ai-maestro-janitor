<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — CONDITIONAL on the janitor being active.** Check the janitor's
> state first (cheap `$HOME` existence checks), then act:
> - **UNINSTALLED** — if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` is
>   ABSENT, the plugin was uninstalled and this file is an ORPHAN it could not remove. Treat
>   this rule as INERT, and tell the user it is an orphaned janitor rule they may delete.
>   NEVER delete any MEMORY store — only this rule file, and only with the user's ok.
> - **DISARMED** — else if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/kill-switch.flag`
>   OR the legacy `~/.claude/janitor-global-state/kill-switch.flag` EXISTS, the janitor is
>   intentionally stopped → treat this rule as INERT this session.
> - **ACTIVE** — otherwise the janitor is running; apply the rule as written below.

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

1. **RECALL BEFORE ACTING.** Before you debug a recurring problem, make a design decision,
   or act on a recurring alert — RECALL FIRST ("have we hit this before?"). It is cheap,
   and it is the entire reason a memory exists.
2. **WRITE / UPDATE AFTER SOLVING.** After you solve a non-trivial problem or make a
   decision that isn't derivable from the code, capture it into the page that OWNS the
   subject (RECALL first, so you update rather than duplicate). When a new fact supersedes
   an old one, use the **correction protocol**: clean the body to the current truth AND
   demote the old statement to a dated `[^N]` lesson carrying the WHY. The fact moves
   forward clean; the error becomes a guardrail. **Never delete knowledge — relocate it.**
3. **MAINTAIN THE PROJECT WIKIMEM.** Keep the PROJECT-scope pages current (architecture
   hub, key-component pages, the publish/deploy pipeline) so the knowledge is git-tracked
   and shared with every dev, not stranded in one session's head.
4. **SCOPE ROUTING — decide BEFORE writing** (see the table below). **UNSURE → LOCAL.**

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
USER_MEM="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory"  # global (HARD-CODED path;
                                    # never ${CLAUDE_PLUGIN_DATA} — that is the RUNNING plugin's dir, not the janitor's)
ROOTS=(); for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS+=("$d"); done
# ARRAY, not a space-joined string: zsh does NOT word-split an unquoted "$ROOTS", so the string
# form passes every root as ONE bogus path and silently returns 0 results. "${ROOTS[@]}" works in both shells.
SYMPTOM="the user's words / the error / the symptom"   # NOT the answer's jargon

if command -v memgrep >/dev/null 2>&1; then
  memgrep recall "$SYMPTOM" "${ROOTS[@]}"   # ranked: path — description (+ its lessons)
else
  grep -rliE "$SYMPTOM" "${ROOTS[@]}"       # fallback: degrade, never break
fi
```

Read the top 1–3 notes it returns. When two scopes conflict, the MORE SPECIFIC wins:
**LOCAL > PROJECT > USER**. Nothing returned ⇒ the memory doesn't exist yet — write one
after you solve the problem.

If `memgrep` is missing, install once:
`cargo install --path <…>/ai-maestro-janitor/scripts/memgrep`.

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

When you read ANY memory you MUST also read the notes/lessons attached to it — every `[^N]`
reference and the `## Notes and lessons learned` entries they point at. The lessons are
*why* the facts are what they are and *what errors not to repeat*. This is FREE: `memgrep
recall` and `find` auto-resolve and append them.

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
[^3]: [ocd:2026-06-09 lmd:2026-06-09] earlier this said "retries 5x"; wrong, the cap is 3 —
  the config key was misread. Lesson: verify the constant against the source, not the name.
```

`## Notes and lessons learned` is **MANDATORY on every page, even when empty** — it is the
standing landing zone for a correction lesson.

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

The index is memgrep's and ONLY memgrep's (an agent-invisible, unlimited SQLite index).
Do **NOT** add pointers to the stub, do **NOT** load it as an index, and **NEVER
hand-trim it** — agents who trimmed the old ever-growing index lost pointers and corrupted
the corpus, which is exactly why the index moved into memgrep.

## Separation of powers

The **janitor** reorganizes structure and *surfaces* contradictions but never edits a fact.
An **agent** creates and corrects content but never reorganizes. The executable protocol is
the skills `/janitor-memory-recall`, `/janitor-memory-write`, `/janitor-memory-update`, and
`/janitor-memory-bootstrap` (stands up a project's wikimem once).
