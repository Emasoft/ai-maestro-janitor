---
trdd-id: FE6W36WL
title: memgrep trio — one block-props spelling, a bumped page lmd, and a per-page lint that can see cross-page rules
column: complete
created: 2026-08-14T06:14:33+0200
updated: 2026-08-14T16:24:00+0200
current-owner: main
task-type: bugfix
external-refs: [janitor#266, janitor#265, janitor#262, janitor#260]
relevant-rules: []
implementation-commits: [ae7f32a8, 22ed55f7, 88390fc2]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

**ALL THREE PARTS ARE IMPLEMENTED, TESTED AND COMMITTED — LOCALLY ONLY.**

| part | commit | verified by |
|---|---|---|
| A — one `render_block_props`, three writers | `ae7f32a8` | round-trip test; the spaced lesson bracket had never been emitted before |
| B — `bump_page_lmd` in add-atom/add-lesson/edit/migrate | `ae7f32a8` | unit tests + the existing test that had ENCODED the bug now asserts the bump |
| B-derived — `lmd` dropped from `corpus_digest` | `22ed55f7` | test asserts an lmd-only change does NOT churn, a description change DOES |
| C — per-page lint sees cross-page rules | `88390fc2` | the original reproduction now reports; `cargo test` 194+136 green |

**NEXT ACTION:** nothing on this card until the tree is PUSHED. The three GitHub issues stay
OPEN deliberately — 222 commits are unpushed, so the fixes are not public and closing them
would be a false claim. Close #266/#265/#262 only after the push, and when closing #266 say
that pre-change pages keep the unspaced spelling forever, or someone will "fix" a wrong grep
count against old pages a second time.

**COLUMN CORRECTED 2026-08-14T16:24 — `dev` → `complete`.** The work finished at 07:41 but
the card kept asserting `dev`, so the board claimed someone was actively working it. That
cost real effort: two lean-workers were dispatched at this card, both correctly read this
STATE block, found NEXT ACTION = "nothing until pushed", and wrote nothing — and their
silence was then misread as failure, nearly triggering a third attempt to redo committed
work. **A card that stops moving must stop claiming otherwise; an untrue column is worse
than an unstarted one, because it hides the truth from the only view anyone checks.**
Awaiting `complete → publish`, which is where the issue-closing above belongs.

**Measured after the fact, worth keeping:**
- Every real page already carries `lmd:`/`updated:` — across all three live scopes (236 files)
  the only five without it are `MEMORY.md` and `memory-reorg-proposed.md`, the index/report
  family `lint_paths` already excludes. So "maintain, never repair" costs nothing in practice.
- Per-page lint on the largest live scope (146 pages, DEBUG build): **0.69 s, 0 ERROR
  findings** — the PostToolUse hook filters `ERROR ` only, so the pre-existing WARN cluster
  cannot flood it. The cost objection to C was unfounded.

**STILL OPEN (not this card's scope):** the installed `memgrep` binary is older than HEAD, so
none of this is live until `cargo install --path scripts/memgrep` runs.

**FOUND WHILE DOGFOODING — a residual `atom-after-footer` FP class, in BOTH implementations.**
Running the new Rust check on a real USER page
(`debugging-methodology-verify-before-concluding-cross-repo-probes-and-peer-reports.md`) flags
two genuine body atoms at lines 109 and 127. Its headings are `## See also` (69) and
`## Notes and lessons learned` (143) — nothing else. Both are footer-family, so the "maximal
suffix of footer headings" walk starts the footer region at 69, even though 74 lines of real
atoms sit between the two headings.

The Python gate agrees exactly (0-based 68 = the Rust 1-based 69), so janitor#227's
gate-vs-arbiter divergence is genuinely closed — this is a shared, faithful reproduction, NOT a
port bug, and it predates the port.

The rule computes the run over the HEADING LIST alone; it never asks whether content intervenes.
A `## See also` with atoms after it is a mid-page section, not a trailing footer. The likely fix
is to break the run when non-blank, non-heading content separates two footer headings — but that
re-opens boundary semantics this card declares settled, so it must be a separate card WITH a
before/after count on the live corpus, not an inline tweak. Do NOT "obviously fix" it in passing.

**Design decisions already settled — do NOT re-litigate:**

**Design decisions already settled — do NOT re-litigate:**

- **A's canonical form is SPACED, with `desc` the only quoted value.** Two earlier
  proposals were killed by measurement, both mine: "unspaced+quoted everywhere" (it puts
  frontmatter on the wrong side of the seam forever) and "quote `keywords` for
  colon-safety" (measured: an unquoted, spaced lesson keyword carrying a colon still
  indexes — `memgrep find step_two` matched it — so the safety it was buying does not
  exist).
- **No corpus rewrite.** The parser keeps accepting both spellings; pre-change lessons
  keep the unspaced form permanently. Say so when closing #266, or someone will "fix" a
  wrong grep count against old pages a second time.
- **C is default-on, NOT behind a `--cross-page` flag.** An opt-in flag recreates #262
  exactly: the mandated per-page command stays the blind default.

**Load-bearing facts measured on a scratch corpus (installed memgrep 0.1.0, a685cca —
five commits behind HEAD; all three defects re-verified present in HEAD's source):**

- #262 reproduced: `memgrep lint <page>` printed `0 finding(s)` while `memgrep lint <dir>`
  reported `link-one-sided` on that same page at that same line.
- #266 reproduced in one page: atom `keywords: a b, ocd: D, lmd: D` vs lesson
  `keywords:"a b", ocd:D, lmd:D`.
- #265 reproduced: two writes today (atom + lesson) both stamped today at block level while
  the page frontmatter kept `lmd: 2026-01-01`.
- There is a THIRD raw-props write site: the `--retire-atom` branch injects
  `, status: superseded, superseded-by:{id}` — itself mixing both spellings in one string.
  It must route through the renderer too.
- `parse_note_props` already accepts the space-then-quote spelling (`desc: "…"`), citing
  TRDD-AP2X9A0H. So the spaced form is parser-supported on the lesson path.
- The per-page lint's link check is blind because `build_graph(paths)` is handed the SAME
  single path, so wikilink targets never resolve and `e.target` is `None`.
- `link-one-sided` anchors on `rel(&e.from)` — the page CARRYING the unreciprocated link.
  This is what makes C's "report only findings anchored on the named file" filter viable;
  had it anchored on the backlink-missing side, the filter would hide every fix.

**Non-obvious risk, already checked:** the PostToolUse hook
(`scripts/hooks/post-edit-wikimem-lint.py::error_findings`) filters `ERROR ` lines only, and
`link-one-sided` is WARN — so C cannot flood it with the ~42 pre-existing WARNs.

**DERIVED TASK, do not skip:** `repomap/claudemd_slim.corpus_digest` mixes `lmd`, and its
own docstring says page CONTENT is deliberately excluded so that "every atom edit" does not
churn CLAUDE.md. B makes `lmd` a content proxy, so B re-introduces exactly that churn
through the back door. Decide it explicitly when B lands — the digest already mixes
`description`, which is the only other field the index renders.

**SUPERSEDED — do NOT carry forward:** the idea that per-page lint should gain a
`--cross-page` opt-in; the idea that lesson `keywords` needs quoting.

## The three defects

**A — janitor#266.** `build_atom_marker` and the lesson writer are two independent format
strings in one file, emitting the same fields two ways. A consumer matching one spelling
silently misses the other, and returns a confident number either way. It already produced a
wrong answer in #265's investigation.

**B — janitor#265.** No verb bumps a page's frontmatter `lmd:`; the only writer is page
creation. `ocd` is creation (correct, leave it), `st_birthtime` is destroyed by the atomic
tmp+rename, and `mtime` moves on a mirror sync — so `lmd` is the only content-recency signal
the corpus has, and it is wrong. Worse, it is *asserted*: an absent field invites a check, a
confident stale date is believed.

**C — janitor#262.** Per-page lint cannot evaluate cross-page rules and reports a bare
`0 finding(s)` — indistinguishable from "clean". The installed memory rule MANDATES exactly
that blind form after every edit, so following the protocol exactly returns green on a page
violating THE LINK LAW.

## Acceptance

- [ ] One renderer emits every block-props site; atom, lesson, and retire-atom agree.
- [ ] A round-trip test proves the SPACED lesson spelling parses (never emitted before, so
      its parseability is asserted, not proven, until the test runs).
- [ ] `add-atom` / `add-lesson` / `edit` bump the page `lmd:`; `ocd` untouched; a mechanical
      repair pass does NOT bump it.
- [ ] `memgrep lint <page>` reports a `link-one-sided` finding for a link added to a
      backlink-less page, anchored on the edited page.
- [ ] The lint summary can never print a bare `0` for a check it did not run — when no scope
      resolves, it names what was skipped.
- [ ] `cargo test` green; the Python suites that read memgrep output stay green.
