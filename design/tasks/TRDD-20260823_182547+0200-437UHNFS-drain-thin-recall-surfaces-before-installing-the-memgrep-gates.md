---
trdd-id: 437UHNFS
title: drain the corpus of thin recall surfaces before installing the memgrep metadata gates
column: blocked
pre-block-column: dev
blocked-by: [owner-decision-drain-vs-lower-floors]
created: 2026-08-23T18:25:47+0200
updated: 2026-08-26T07:22:00+0200
current-owner: ai-maestro-janitor-48
task-type: infra
approval-tier: 0
scope: project
project-id: ai-maestro-janitor
implementation-commits: [3461ef6d, a7ea94c5, b4638b14, e647a37a]
---

# Drain thin recall surfaces before installing the memgrep metadata gates

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-26

- **memgrep source is DONE and GREEN.** `cargo test --release` → bin 218/218, cli 145/145
  (`e647a37a` fixed the last four fixtures). The gates themselves are settled and stay.
- **memgrep is deliberately NOT INSTALLED.** `~/.cargo/bin/memgrep` is still the Aug-22 build
  (`0.1.0 (7fddae5, 2026-08-22)`). Installing is the LAST step of this card, not the first.
- **Do NOT run `cargo install --path scripts/memgrep`** until the drain is done. That is the
  whole point of this card.

### ⛔ SUPERSEDED — do NOT carry forward (2026-08-26)

- ~~"add the `enrich` chore, then let the HEARTBEAT drain the corpus"~~ — **the chore cannot
  drain its own backlog.** See the circularity below. The chore is still built, but it is the
  POST-install steady-state guard; the 1188-error backlog is drained by an EAGER batch run.
- ~~The survey's §5 claim that "no `lint`/`validate` rule that flags 'keyphrase count < 10'
  was found"~~ — **FALSE**, verified: `scripts/memgrep/src/memory.rs:5448` emits
  `atom-keywords-too-few` and `:5118` emits `page-description-too-few-phrases`. Believing §5
  leads an implementer to write a Python twin of the counting logic, which is exactly the
  janitor#227 anti-pattern (a second disagreement surface for a rule lint already owns).

### The circularity — MEASURED 2026-08-26, not inferred

An honest `enrich_has_work` must ASK the linter (Rust owns keyphrase parsing, phrase splitting
and dedup normalization — never mirror it in Python, per `oversized_atom_pages` /
TRDD-VOWAUVE5). But `user_mem_lib.find_memgrep()` resolves `MEMGREP_BIN` → PATH → `~/.cargo/bin`,
and during the whole drain window PATH holds the **Aug-22** binary. Measured with `strings`:

| binary | `atom-keywords-too-few` | `page-description-too-few-phrases` |
|---|---|---|
| installed `~/.cargo/bin/memgrep` (7fddae5, 08-22) | **0** | **0** |
| fresh `scripts/memgrep/target/release/memgrep` (961b28f, 08-25) | 1 | 1 |

So a correctly-built chore returns "no work" for every page until the install — and the install
is gated on the drain. **The chore would be silent, and the silence would look like success.**
The escape hatch already exists and needs no new code: `MEMGREP_BIN` is the FIRST branch of
`find_memgrep()` (`scripts/lib/user_mem_lib.py:522-533`).

### The backlog — re-measured 2026-08-26 with the fresh binary

1188 ERROR (was 1184 on 08-23; +4 drift), and **every single one is enrich-class**:

| slug | count | fix shape |
|---|---|---|
| `atom-keywords-too-few` | 910 | ADD keyphrases |
| `page-description-too-few-phrases` | 221 | ADD `/`-separated phrases |
| `atom-keywords-duplicated` | 51 | REMOVE duplicates |
| `page-description-duplicated-phrases` | 6 | REMOVE duplicates |
| **total** | **1188** | |

Per-root: PROJECT 256 lines, LOCAL 148, USER 857. The remaining 59 WARN + 11 INFO
(`publish-globally-missing` 34, `atom-after-footer` 25, `lesson-uncited` 8, `atom-oversized` 3)
are NOT errors and do NOT gate the install.

**This is the good news of the re-measure: `enrich` alone clears 100% of the blocking errors.**
No other chore has to run first. Note it has TWO modes, not one — add-missing AND de-duplicate.

### DONE 2026-08-26 — the chore is BUILT and PROJECT is DRAINED

- **`enrich` chore shipped** (`6fa8b6c4`): precheck predicate, settings, marker (LAST in
  `_MARKERS`), candidates CLI, skill, plus 6 further enumeration sites a sweep found. No
  `--op enrich` — an enrich edit has repair's exact shape and `verify_repair` already proves
  what it needs. `atom-no-keywords` moved from ORPHANED to `enrich`, closing janitor#200's own
  "fix this first" item.
- **PROJECT scope: 256 ERROR → 0.** All 49 pages clear the gates
  (`ac9b56d8`, `4612f82b`, `0e833a2d`, `7f601fb3`). Cost ≈ 1.05M tokens, ≈21k/page.
- **LOCAL + USER are BACKED UP** before anyone edits them — they are outside any repo, so an
  edit there is otherwise unrecoverable:
  `reports_dev/memory-backups/20260826_071901+0200-{local,user}-memory.tgz` (49 and 200
  entries, verified non-empty).

### Load-bearing lessons from the drain — read BEFORE briefing another batch

1. **A verify scoped to the defect you set out to fix cannot see the defect you cause.** The
   first batch's criterion named only `page-description-too-few-phrases`; the edit cleared the
   count and introduced a DUPLICATE, a different slug, so the worker's own check passed. Name
   EVERY enrich slug.
2. **Margin must be mechanical, not requested.** Asking for "12 phrases" while the criterion
   was "clean at 10" produced pages sitting exactly on the floor — raise the floor by one and
   48 findings reappear. Batches verified at RAISED floors
   (`MEMGREP_MIN_KEYWORDS=12 MEMGREP_MIN_PAGE_PHRASES=17`) have real headroom; the earlier
   ones do not. An agent optimises for the criterion it can check.
3. **The description separator is `/`, so a slash-COMMAND name splits one phrase in two.**
   `why did /janitor-pause disappear` becomes `why did` + `janitor-pause disappear`, and a
   second such entry makes `why did` a duplicate. Write `the janitor-pause command`.
4. **`grep -c ERROR` on lint output counts the SUMMARY line** ("none at or above ERROR"), so a
   clean corpus reports 1. Anchor it: `grep -c '^ERROR'`.
5. **The parser's idea of a distinct phrase is stricter than the author's** — one batch needed
   4 passes to converge. Trust the linter's count, never your own.

- **NEXT ACTION (was):** build the `enrich` skill + the 7 survey sites once (with the site-5 predicate
  corrected — `enrich_pages(root) -> list[(path, slug)]` parsing `memgrep lint` stdout and
  failing CLOSED when the binary is missing, NOT an `enrich_defect(text)` text predicate), then
  drain eagerly per scope with
  `MEMGREP_BIN=$PWD/scripts/memgrep/target/release/memgrep`, then `cargo install`, then let the
  chore guard steady state. Enrich must touch only `keywords:` props and page `description:` —
  never an atom `desc:` (200-char cap at `memory_edit_verify.py:1431`), or it ping-pongs with
  `repair`. Put `enrich` LAST in `_MARKERS` so it never starves `repair`.

### ⏸ NEXT ACTION — BLOCKED ON THE OWNER (a cost/meaning call, not a technical one)

LOCAL (39 pages) and USER (185) still fail the gates, and `cargo install --path
scripts/memgrep` needs ALL THREE scopes at zero. Two honest routes, both now evidenced:

- **DRAIN them** — ≈1.2M tokens at the measured 21k/page. Produces genuinely good symptom
  phrasings (spot-checked, not assumed). Backups are already taken, so it is recoverable.
- **LOWER THE FLOORS for those scopes** — `MEMGREP_MIN_KEYWORDS` / `MEMGREP_MIN_PAGE_PHRASES`
  (`0` disables), verified env-tunable at `memory.rs:4287,4318`. Near-zero cost, but the gates
  stop meaning much on the two biggest scopes.

Not decided unilaterally: it spends a large share of the session budget, and the alternative
quietly weakens a gate the owner ratified. Whichever is chosen, the batch brief must carry the
five lessons above.

## The decision (owner, 2026-08-23)

The metadata gates landed in `3461ef6d`: an atom or lesson needs ≥10 distinct keyphrases, a page
`description:` needs ≥15 distinct `/`-separated phrases, and duplicates are refused — a count is
a proxy for COVERAGE, so a repeated phrase inflates it without adding a way to find the memory.

Measured first-hand with the release binary on 2026-08-23, across **277 pages**:

| scope | ERROR | thin atoms | thin page descriptions | duplicated keyphrases |
|---|---|---|---|---|
| PROJECT (`.claude/project/memory`) | 186 | 137 | 44 | 4 |
| USER (plugin DATA `memory/`) | 851 | 695 | 137 | 15 |
| LOCAL (`~/.claude/projects/<slug>/memory`) | 147 | 75 | 39 | 32 |
| **total** | **1184** | **907** | **220** | **51** |

Every scope fails the default lint gate.

**What installing today would actually do — traced, 2026-08-23, correcting the handoff.** The
handoff said `dispatch.py:611` would promote a lint line past quiet mode on every heartbeat
fire. That is **FALSE**, twice over, and the card said it before it was checked:

- Line 611 is an unrelated advisory muzzle list. The memory-marker promotion is at
  `dispatch.py:559-561`, and it is a generic `\[janitor-memory-[a-z0-9-]+\]` regex.
- **No detector surfaces `memgrep lint`'s summary at all.** The only heartbeat-path caller is
  `memory_content_precheck.oversized_atom_pages` (`memory_content_precheck.py:170`), which
  captures the output and parses **stdout** for oversized atoms only; the
  `memgrep lint: N finding(s), …` summary goes to **stderr** (`memory.rs:4597,4608`) and is
  discarded. The janitor#276 guard in `dispatch.py:615-626` (`_NEGATED_SEVERITY_RE`) is a
  standing regression guard for a line no current detector emits.

The real blast radius, verified:

1. **The WRITE gates go hard everywhere** — `new-page`, `add-atom` and `add-lesson` start
   REFUSING below the floors. This is the intended effect and the reason to be deliberate
   about when it lands, not a side effect.
2. `scripts/hooks/post-edit-wikimem-lint.py:144` lints each edited page, so nearly every
   memory page anyone touches would come back dirty until the corpus is drained.
3. The commit-time authoring gate is **unaffected**: `memory_txn_cli._authoring_gate` is a
   DELTA gate over four named classes (`memory_txn_cli.py:127-133`), and neither
   `atom-keywords-too-few` nor `page-description-too-few-phrases` is one of them, so a
   pre-existing violation can never block an unrelated commit.

So the drain still has to come first — because of (1), which is the point of the gates, and
(2), which would make every editorial pass noisy. It does NOT have to come first because of a
heartbeat line, and a future session must not go looking for one.

Three options were put to the owner: (1) install and ship noisy, (2) install with the two new
lint rules downgraded to WARN while the write gates stay hard, (3) **drain the corpus first,
then install**. **The owner chose (3).**

**Why (3) and not (2)** — the cheaper-looking option. (2) leaves the corpus permanently split
into a compliant new half and a silent legacy half, with nothing that ever forces the second to
converge; "drains opportunistically as pages get touched" is a hope, not a mechanism. It also
teaches the linter to under-report the exact defect it was just taught to detect, which is the
failure the severity model exists to prevent.

## The plan

1. **Add an `enrich` memory chore** — the drain mechanism. It raises thin recall surfaces:
   extends an atom's keyphrases to ≥10, a page `description:` to ≥15 phrases, and de-duplicates.
   It is EDITORIAL work (it must write phrasings a future session would actually search with, in
   the words of the SYMPTOM, not the fix), so it belongs to the existing
   `janitor-memory-subconscious-agent` as one more per-chore skill — NOT to a script. A script
   can only pad, and padding is precisely what the gate exists to reject.
2. **Let the heartbeat drain it**, one bounded scope-pass per dispatch, like every other chore.
3. **Install `memgrep` only when all three scopes lint at 0 ERROR**, then re-pin and let the
   gates go live everywhere at once.

## Acceptance criteria

- [ ] An `enrich` chore exists, is scheduled, content-prechecked, claimable, and dispatched by
      the heartbeat exactly like the existing chores.
- [ ] Its skill refuses to satisfy a count with filler — the pass is measured by recall
      coverage gained, and it says what it skipped rather than padding it.
- [ ] `memgrep lint` reports 0 ERROR on PROJECT, USER and LOCAL.
- [ ] `cargo install --path scripts/memgrep` run, and `memgrep --version` on PATH matches.
- [ ] A heartbeat fire after the install is QUIET (no promoted lint line).

## Notes

- **The write gates are not live today either.** Nothing enforces ≥10 keyphrases at write time
  until the install happens, so new pages written during the drain can still be thin. That is
  accepted: the drain pass re-lints, so anything written thin in the meantime is picked up by
  the same sweep rather than escaping it.
