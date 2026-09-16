---
trdd-id: 2OUMEVDS
title: memgrep should ENFORCE the recall technique rather than document it
column: complete
created: 2026-08-14T16:35:38+0200
updated: 2026-08-16T01:48:40+0200
current-owner: janitor-session
task-type: feature
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: [9f1876f1]
---

# memgrep should ENFORCE the recall technique, not document it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

USER directive, 2026-08-14. Implemented in `scripts/memgrep/src/memory.rs` (query
expansion + jargon detection in `cmd_recall_cli`; the write→recall-gap warning in
`cmd_add_lesson_cli`) plus regression tests in `tests/cli.rs` and pure-function unit
tests in `memory.rs`'s `mod tests`. All 6 acceptance boxes ticked.

**Open question resolved (deliberately, not by default):** shipped the HAND TABLE
(7 entries, each traceable to a miss named in this card's own misses table), NOT the
corpus-mined or query-log-mined alternative. Reason: the mined approaches both need
query-logging infrastructure (a privacy surface the card itself flags as "worth
thinking about before adding") that does not exist yet and is out of this card's
scope — building it would be a separate TRDD. The hand table is honest about what it
is (7 small entries, not a general thesaurus) and is proven not to regress recall via
`recall_expansion_is_additive_never_drops_a_literal_match` /
`expand_never_removes_a_literal_word_or_touches_the_phrase`. Growing it beyond
observed misses (the "do not invent" instruction) is left to future cards that
report a *new* real miss, exactly as this card's own table was built.

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

- [x] A bundled synonym table, domain-first, with each entry traceable to a real observed
      miss rather than invented.
- [x] `recall` expands the query through it before ranking.
- [x] Jargon-shaped queries are detected and flagged loudly, with the expanded query shown
      and both result sets printed. No silent rewriting.
- [x] A regression test using THIS session's real misses: querying "server takes over the
      janitor daemon role" must surface `one-daemon-per-host-withdraws-the-whole-daemon`
      and `janitor-daemon-handover-unowned-chores`, which the literal query did not rank
      first. (Implemented against a synthetic fixture built from the same two pages'
      real `description:` text — the live USER-scope corpus is never touched by a test,
      per RULE 0 / the write constraints.)
- [x] Expansion never DROPS a result the unexpanded query would have returned — strictly
      additive, so it cannot make recall worse. Proven at BOTH layers: a pure-function
      unit test (`expand_never_removes_a_literal_word_or_touches_the_phrase`) that fails
      immediately if `expand()` ever replaced `words` instead of extending it, plus a
      CLI-level regression.
- [x] **`add-lesson` refuses (or loudly warns) when the `--keywords` it is handed do not
      appear in the page's `description:`, and offers to extend it.** Earned empirically
      on 2026-08-14, not theorised — see "The write→recall gap" below. Implemented as a
      loud stderr warning (write still succeeds — the keywords remain useful as this
      lesson's own atom-level surface); regression test reproduces the exact 9-keyword
      measured sequence.
- [x] `cargo test` in `scripts/memgrep` green (205 unit + 144 integration, 0 failed);
      `uv run ruff check scripts tests` and `uv run mypy scripts/ --ignore-missing-imports`
      clean.

## The write→recall gap — measured 2026-08-14, the strongest case for this card

Writing the lesson that motivated this card demonstrated the thesis by failing.

`memgrep add-lesson` was handed **nine** symptom key-phrases. It validated clean, linted
clean (0 findings), printed an atom id, and exited 0. The lesson was nonetheless
**unfindable by every one of those nine phrases** — because `recall` ranks on
`description + title + tags`, and `add-lesson` does not touch `description:`.

Three green signals, one silent failure. The protocol documents the trap in bold —
*"APPENDING? EXTEND `description:` — ranking ignores the body; an added fact whose symptom
the description lacks is unfindable"* — and the tool that creates the trap says nothing
while creating it. The only reason it was caught is that a recall was run afterwards to
PROVE the write, which nothing in the flow requires.

That is the same shape as the card's thesis: the tool knows the invariant, the human is
asked to remember it, and the failure is silent and green. `add-lesson` is the sharpest
place to fix it because it has both halves in hand at write time — the keywords, and the
description they must reach.

(Fixed manually for that page by extending its `description:`; the lesson now ranks #1 on
both the seeded phrasing and an unseeded rewording.)

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

## ⏵ CLOSED 2026-08-16 — and the DELIVERY check is what mattered

All seven boxes were already ticked. Before closing, the one thing no box asked was checked:
**had the feature reached the binary anyone on this host actually runs?** `memgrep` is a bundled
Rust crate installed with `cargo install --path scripts/memgrep`, so a merged commit is not a
delivered one — the same shape as TRDD-KVS6K7P9's half-migrated rule window, closed the same day.

It had been delivered (the installed binary carries `9f1876f1`'s literal warning string), but
`memgrep --version` claimed otherwise — `a685cca, 2026-08-07` for a binary containing code from
2026-08-14. That reading was itself a bug, now fixed and tracked as **TRDD-9XMPS8OZ**: the
janitor#164 build stamp was frozen at each checkout's first build, so the tool built to expose a
stale install answered confidently and wrongly. Verified after the fix: installed stamp `a698f16`
== HEAD, and `memgrep recall` on a real corpus returns the expansion-ranked results.

So this card ships as claimed. The lesson it leaves is not about synonyms: **a green box means
merged, and for anything that installs — a Rust crate, a rule file, a plugin — merged and
delivered are different claims.** Checking the second is what surfaced a nine-day-old defect in a
different feature entirely.
