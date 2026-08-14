---
trdd-id: 2OUMEVDS
title: memgrep should ENFORCE the recall technique rather than document it
column: todo
created: 2026-08-14T16:35:38+0200
updated: 2026-08-14T16:35:38+0200
current-owner: janitor-session
task-type: feature
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: []
---

# memgrep should ENFORCE the recall technique, not document it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

USER directive, 2026-08-14. Not yet started. Design below is the starting point, not
a settled spec — the synonym source (item 2) is the open question.

## The problem, stated as a mechanism rather than a complaint

The corpus already holds the governing principle, twice over:

- `ATOM-7W2N-M6L8`: *"A recorded lesson prevents nothing by existing — recall must be
  TRIGGERED by the action class."*
- `janitor-keepalive-test-isolation-fsevents` lesson [3]: *"Opt-in test isolation fails
  silently and forever… only refusing the write at the SYSCALL, with no opt-out, actually
  holds."*

Both say the same thing in different domains: **discipline documented is discipline that
fails; only enforcement in the tool holds.** The recall protocol is currently documented
discipline. `memgrep recall --help` even states the correct technique — *"the words you
HAVE, not the answer's jargon"* — and then does nothing whatsoever to enforce it.

Measured cost on 2026-08-14, one session: the corpus already contained the daemon
alternation model, the ownership tell (`stopping (server-owns-host)`), the bug's whole
class (`ATOM-4GQU-0C9J`), and the timestamp-attribution correction. All four were
re-derived by hand across many turns, and an advisor was briefed from the reconstruction
— so the USER had to correct the architecture twice. The knowledge was not missing. The
lookup was. This is the same failure recorded on 2026-08-05 in
`janitor-daemon-handover-unowned-chores` lesson [5], repeating.

## Design sketch — two mechanisms

### 1. QUERY EXPANSION (the "extra keywords from a dictionary of synonyms" half)

Before ranking, expand the query with domain synonyms and morphological variants, so a
query phrased in one vocabulary still reaches a page indexed in another.

The general-English part matters far less than the DOMAIN part. Real misses from this
session, each a synonym set worth shipping:

| queried as | indexed as |
|---|---|
| takes over | absorbs · claims · owns · is in charge |
| stops · sleeps | stands down · withdraws · suppressed · yields |
| dead · gone | absent · died · not respawned · stale |
| test wrote it | pollution · leak · escaped isolation |
| who wrote this file | attribution · provenance · breadcrumb |

Ship as a small bundled table, not a general thesaurus: a general one adds noise, and
recall's ranking surface (`description + title + tags`) is short enough that noise hurts.

### 2. TECHNIQUE ENFORCEMENT (the "forcing" half — the part that actually fixes it)

Detect a query written in the ANSWER's jargon and refuse to answer it silently.
Heuristics for jargon: identifiers (`snake_case`, `CamelCase`), file paths, function or
symbol names, version strings.

On detection: **still run the search**, but prepend a loud line —
`⚠ that query is in the ANSWER's jargon; recall ranks on SYMPTOM. Also tried: <expanded>`
— and show BOTH result sets. Never silently substitute: a tool that quietly rewrites the
query teaches nothing and hides its own behaviour.

## Acceptance criteria

- [ ] A bundled synonym table, domain-first, with each entry traceable to a real observed
      miss rather than invented.
- [ ] `recall` expands the query through it before ranking.
- [ ] Jargon-shaped queries are detected and flagged loudly, with the expanded query shown
      and both result sets printed. No silent rewriting.
- [ ] A regression test using THIS session's real misses: querying "server takes over the
      janitor daemon role" must surface `one-daemon-per-host-withdraws-the-whole-daemon`
      and `janitor-daemon-handover-unowned-chores`, which the literal query did not rank
      first.
- [ ] Expansion never DROPS a result the unexpanded query would have returned — strictly
      additive, so it cannot make recall worse.
- [ ] `cargo test` in `scripts/memgrep` green; `uv run ruff check scripts tests` and
      `uv run mypy scripts/ --ignore-missing-imports` clean.

## Open question — the synonym source

A hand-maintained table is honest and small but goes stale. Alternatives: derive it from
the corpus itself (terms co-occurring in descriptions of pages that link to each other),
or mine it from recall queries that returned nothing and were followed by a successful
rephrase. The mined option is self-improving and needs no dictionary — but needs query
logging, which is a privacy surface worth thinking about before adding. **Decide before
implementing; do not default to the hand table just because it is easiest.**

## Notes

Complements the skill-side change committed alongside this card (pushed rows are hop 1
already done; the trigger taxonomy now covers RECONSTRUCTION as well as RISK). That
change is documentation and will therefore decay exactly like the advice already in
`--help`. This card is the version that cannot decay, which is why it exists.
