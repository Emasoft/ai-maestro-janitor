---
trdd-id: 4334aad0-c5b2-4990-8214-11e654032cd7
title: User private memories — /to-user-mem + /search-user-mem with +/- query operators
column: backburner
created: 2026-06-09T18:47:51+0200
updated: 2026-06-09T18:52:00+0200
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 4
severity: MEDIUM
effort: M
labels: [memory-system, user-memory, privacy, slash-command, memgrep, search-dsl]
task-type: feature
parent-trdd: TRDD-ce195129
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, integration]
runtime-targets: [macos, linux]
external-refs: []
---

# TRDD-4334aad0 — User private memories

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-09

**Status:** captured from a USER directive 2026-06-09; NOT started. A SEPARATE
subsystem from the agent memory corpus + the librarian (TRDD-c77dae09): memories
the **USER** authors, stored privately (NOT in agent context), with two slash
commands and a +/- search query language. Shares memgrep as the search engine.

**NEXT ACTION when picked up:** design the two commands + the privacy intercept
(how `/to-user-mem` keeps the text out of agent context) + the query parser, then
implement. Read TRDD-c77dae09 (memory system) + TRDD-d151fe52 (memgrep) first.

## USER directive (verbatim intent, 2026-06-09)

> The user must have the option to save memories too. Those memories must be
> saved in a different subfolder dedicated to user memory, and they should be
> saved simply with the command `/to-user-mem <memory text not visible to agent
> context>`, and searched with `/search-user-mem <keywords to search>`. The
> syntax must accept the + and - operator. Nothing [no prefix] will make the
> keyword optional. Plus + will make the keyword mandatory, and minus - will
> filter out all search results containing that keyword. Also the keywords can
> be single words, words with wildcards (i.e. `pro*-debug*`) and sentences
> verbatim (i.e. `"logistic regression failure"`). The sentences will be simply
> treated like keywords but with the space included, so they can be also
> prefixed with + or -. Note that the command `/to-user-mem` can be used without
> arguments, and in that case it will automatically use the whole previous user
> message as text of the memory to store.

## The subsystem

### Storage — a dedicated, private subfolder

- User memories live in their **own subfolder**, separate from the agent corpus
  — e.g. `<memdir>/user-mem/` (sibling of the agent notes, NOT mixed in). The
  librarian (c77dae09) does NOT reorganize user memories; they are the user's,
  not the agent's, to curate.
- Same on-disk markdown shape can be reused (frontmatter + body), but the
  CONTENT is user-authored and **opaque to the agent**.

### `/to-user-mem [<text>]` — save a private memory

- **With argument:** `/to-user-mem <memory text>` saves `<text>` to a new file
  under `user-mem/`.
- **Without argument:** `/to-user-mem` (bare) automatically uses the **whole
  previous USER message** as the memory text to store. (Convenience: say
  something, then `/to-user-mem` to file it.)
- **PRIVACY — the text is NOT visible to agent context.** This is the
  load-bearing property. The memory text must NOT enter the agent's context
  window. Implementation: a janitor **`UserPromptSubmit` hook** (the janitor
  already owns `on-prompt-submit`) intercepts a prompt beginning with
  `/to-user-mem`, extracts the argument (or, if bare, the previous user
  message — the hook has the transcript), writes it to `user-mem/`, and
  **replaces/suppresses** the prompt so the agent only ever sees a redacted
  confirmation (e.g. `[user-mem] saved (N chars) — content withheld from
  context`). The raw text reaches disk, never the model.
  - Open design Q: the bare-form "previous user message" — the hook must read
    the transcript to recover it; confirm the hook has access (it does — the
    on-prompt-submit hook receives session context) and that the *previous*
    message (not the `/to-user-mem` line itself) is the target.

### `/search-user-mem <query>` — search the private memories

Searches ONLY the `user-mem/` subfolder. Powered by memgrep's query engine.

**Query operators (per-keyword prefix):**

| Prefix | Meaning |
|---|---|
| *(none)* | **OPTIONAL** — contributes to match/ranking, not required |
| `+` | **MANDATORY** — the result MUST contain this keyword |
| `-` | **EXCLUDE** — drop any result that contains this keyword |

**Keyword forms** (each may carry a `+`/`-` prefix):
- **single word** — `debug`
- **wildcard word** — `pro*`, `debug*`, or a hyphenated wildcard `pro*-debug*`
  (the `*` is the wildcard; a `-`/`+` that is NOT the leading char is a LITERAL
  part of the word, so `pro*-debug*` is one keyword, not `pro*` minus `debug*`).
- **verbatim phrase** — `"logistic regression failure"` (quoted; matched with the
  spaces included = phrase match). A phrase is "just a keyword with spaces", so it
  too can be prefixed: `+"logistic regression failure"`, `-"old approach"`.

**Parsing rules (the disambiguation that matters):**
- A leading `+`/`-` on a token (word OR quoted phrase) is the OPERATOR.
- `+`/`-`/`*` INSIDE a token are literal/wildcard, not operators.
- Tokens are whitespace-separated EXCEPT inside quotes (quotes group spaces).
- Result set = (has ALL `+` terms) AND (has NONE of the `-` terms), ranked by how
  many optional terms matched. Empty `+` set ⇒ ranking is by optional matches.

### Full invisibility + immutable global numbering + `/share-user-mem` (USER, 2026-06-09)

**The entire user-memory system is INVISIBLE to agents — including search
results.** Nothing about user memories ever enters the agent's context window
unless the user *explicitly* shares it. Specifically:

- **`/search-user-mem` results are emitted to the USER via a `systemMessage`
  pipe**, NOT into the conversation — the same mechanism the **claude-menu-system**
  plugin uses (a Stop/Stop-hook that emits post-turn via `systemMessage` at zero
  context cost; ref `github.com/Emasoft/claude-menu-system`). The user reads the
  results; the agent sees nothing. (This RESOLVES the earlier open question:
  results are ALWAYS private, never agent-visible.)
- The agent therefore cannot read, recall, summarize, or leak user memories. They
  are the user's private store that merely lives alongside the project.

**Immutable global numbering.** Every user memory is assigned a **permanent,
globally-unique, never-reused number** at save time (a monotonic counter in the
`user-mem/` store — like the PRRD rule-numbering invariant: once N is assigned to
a memory it is that memory forever; deleting a memory retires N, never recycles
it). The number is stable across the librarian-free lifetime of the memory and
is what the user references to act on a specific memory.

- `/search-user-mem` results (in the systemMessage) are printed WITH each
  memory's immutable number, so the user can pick one.

**`/share-user-mem <number>` — the explicit, deliberate opt-in to share.** The
user flow is: `/search-user-mem <query>` → read the numbered results in the
systemMessage → pick a number → `/share-user-mem <N>` → memory #N's text is
injected into Claude's context (the ONLY path by which the agent ever sees a user
memory). The user may equally just paste a memory's text manually — `/share-user-mem`
is the convenience that avoids re-typing.

So the privacy model is **default-opaque, explicit-share**: save (invisible),
search (results to the user only, numbered), share-by-number (the single
deliberate gate that lets a chosen memory into the agent's context).

## Relationship to the rest of the memory system

- **Agent memories** — authored by the agent, organized by the librarian
  (c77dae09), recalled by `memgrep recall`.
- **User memories (THIS TRDD)** — authored by the USER, **private to the user**
  (out of agent context), NOT touched by the librarian, searched by
  `/search-user-mem`.
- **Shared engine** — memgrep (TRDD-d151fe52) provides BOTH the `+`/`-`/wildcard/
  phrase query parser (useful for agent recall too) AND the user-mem search. The
  query DSL is a memgrep feature; the two commands are thin janitor wrappers.

## Open design questions

- **Search-result privacy:** RESOLVED (USER, 2026-06-09) — results are ALWAYS
  invisible to the agent, emitted to the user via a `systemMessage` pipe
  (claude-menu-system pattern). The only path into agent context is the explicit
  `/share-user-mem <number>`. See the "Full invisibility" section above.
- **Index:** reuse the same git-incremental memgrep index (c77dae09) but as a
  SEPARATE index/namespace for `user-mem/` (never co-mingled with agent notes).
- **Commands location:** two new slash commands shipped by the janitor plugin
  (`commands/to-user-mem.md`, `commands/search-user-mem.md`) backed by the
  on-prompt-submit hook (for the privacy intercept) + a memgrep call (for search).
