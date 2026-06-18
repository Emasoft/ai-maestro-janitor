---
description: Search your PRIVATE user memories with a +/- query DSL (mandatory/optional/exclude, wildcards, quoted phrases). Results are shown to YOU only (via systemMessage) with each memory's number — the agent never sees them.
argument-hint: "<query with +/- operators>"
---

# /janitor-memory-user-search <query>

Searches **only** your private user-memory store (never the agent's memory
corpus) using memgrep's query DSL. Results are printed **to you only** — numbered
so you can pick one to share.

## Query operators (per keyword)

| Prefix | Meaning |
|---|---|
| *(none)* | **OPTIONAL** — contributes to ranking, not required |
| `+` | **MANDATORY** — the result MUST contain this keyword |
| `-` | **EXCLUDE** — drop any result containing this keyword |

## Keyword forms

- **single word** — `debug`
- **wildcard** — `pro*`, `debug*`, or a hyphenated wildcard `pro*-debug*`
  (the `*` is the wildcard; a `+`/`-` that is **not** the leading char is a
  literal part of the word, so `pro*-debug*` is one keyword).
- **verbatim phrase** — `"logistic regression failure"` (quoted, matched with
  the spaces). A phrase may itself be prefixed: `+"logistic regression failure"`,
  `-"old approach"`.

Result set = (has ALL `+` terms) AND (has NONE of the `-` terms), ranked by how
many optional terms matched.

## Examples

```
/janitor-memory-user-search +keychain -coffee rotation
/janitor-memory-user-search "logistic regression failure"
/janitor-memory-user-search +deploy pro*-debug* -staging
```

## How it works (privacy)

The janitor `UserPromptSubmit` hook intercepts this command, runs
`memgrep find <query> <user-mem-dir> --use-index`, and **blocks the prompt** so
the agent never sees the query or the results. The numbered results are surfaced
to **you** via `systemMessage`. Pick a number, then `/janitor-memory-user-share
<number>` to inject that one memory into the agent's context.

> **Legacy name:** `/search-user-mem` still works (deprecated alias). Prefer the
> `/janitor-memory-user-*` names; the old form is kept only so the hook still
> intercepts and blocks it (an unrecognised form would leak your query to the
> agent).
