# REPAIR — background and rationale

## Table of contents

- Why REPAIR exists
- What REPAIR is (and is not)
- Claim exit codes
- desc: quoting grammar (TRDD-3SOO1RWE)
- desc-trim keyword incident (747b8bef)
- Superseded-atom delimiter mechanics
- Why `publish-globally` is NOT a repair defect
- Pre-transaction verb fixes — full mechanics
- Repair checklist — full detail
- Execution context and what this is
- EXIT / SUCCESS / idempotency contract
- Scope

## Why REPAIR exists

The wikimem corpus accumulates malformed pages: notes the harness `# Memory`
directive wrote with a partial schema, pages an agent created before the skill
enforced the full frontmatter, pages whose tier is inverted (an `aspect` built
with `## Governed by` instead of `## Applies to`), pages with no frontmatter at
all (invisible to ranked recall), or a one-sided `[[link]]`. REPAIR is the
autonomous pass that completes and corrects ONE page at a time, in place,
through the transaction core so it can never lose a fact. It is the 4th
wikimem-editor pass (alongside split / consolidate / conflict) and the executor
for priority #4 of the memory-curation mission (TRDD-87935f21).

## What REPAIR is (and is not)

REPAIR is additive and structural — it backfills metadata, adds the standing
Notes section, sets/corrects the tier, makes a page findable, and adds a page's
OWN missing edges. It NEVER rewrites a fact, never changes `ocd` (a page's birth
date), never merges/splits/deletes. Editorial judgment that changes meaning is
the job of the other three passes; REPAIR only makes a page well-formed.

## Claim exit codes

`memory_dispatch_claim.py --chore repair --state-dir "$STATE_DIR"` reports its
outcome via exit status: **2** = nothing claimable right now; **3** = no
memory-maintenance state at all (`$STATE_DIR` is wrong); **4** = `$STATE_DIR` was
empty; **5** = the dispatch was recorded for a different state dir, so the claim
was refused. Any of these, an unreadable result, or a printed chore name other than
`repair` means STOP and report — never pick a scope yourself, never re-derive what
is due, and never read the legacy `memory-maint-pending.json` slot.

## desc: quoting grammar (TRDD-3SOO1RWE)

QUOTED form is `desc:"…"` — the write verbs emit `desc: "…"`; the parser trims
after the colon, so the space is immaterial. The unquoted-slug bar is exactly
memgrep's `atom-unquoted-desc` check (`[a-z0-9_]+` only). Quote unquoted-prose
descs verbatim rather than rewording them; trim an over-cap desc by tightening,
never by dropping a fact the body lacks elsewhere.

## desc-trim keyword incident (747b8bef)

Review of commit 747b8bef, 2026-09-06: 16 desc trims, one dropped the `fact`
subcommand from a desc with no keyword carrying it — the recall surface lost that
symptom entirely. This is why every desc trim must check the cut clause is still
in `keywords:` before committing.

## Superseded-atom delimiter mechanics

TRDD-QKWU26ZG — the readability layer of the status-keyed default-exclude; memgrep
lint's `superseded_heading_line` is the SSOT for the exact `## Superseded` spelling.
Moving a superseded atom's block (marker line + body, up to the next
marker/heading) below that delimiter is purely for humans reading current facts
first — correctness does NOT depend on position, since the recall exclude keys on
the atom's own `status:` prop, not on where it sits in the file. Lessons stay
pooled in the page's Notes section throughout, so a within-page move keeps every
`[^N]` reference resolving.

## Why `publish-globally` is NOT a repair defect

The SKILL body says do not add or flip it by hand. The reasoning, and the two ways this
instruction has already been written down WRONG here:

**The write path owns the field.** `atomic_write_page` (`memgrep/src/memory.rs`) is the sole
choke point every write verb funnels through, and it runs `normalize_page_until_clean` both
BEFORE and AFTER every single write, unconditionally — the only other caller of the byte-writer
is that normalizer itself. So a page you touch through any verb comes back with the field
correct, and a page you do not touch does not need it.

**Trap 1 — `metadata.type` is NOT the discriminator.** This checklist used to say "add it when
`type: project`". Wrong: `type` is the CONTENT class (`user|feedback|project|reference`) and is
independent of which ROOT a page lives in — a page under `.claude/project/memory/` may
legitimately carry `type: reference`. memgrep decides from the PATH
(`scope_layer(page_abs) == SCOPE_PROJECT`). Measured on this repo 2026-08-27: **10 of the 50
PROJECT-root pages (20%) carry `type: reference` or `type: feedback`**, so the old wording told
the agent to skip a fifth of exactly the pages memgrep flags.

**Trap 2 — the value is not decidable from page text.** memgrep splits "field missing" on
whether a USER-root SYMLINK exists: no field + no symlink is `MissingDefaultFalse` (→ `false`),
no field + a symlink already there is `MissingSymlinkImpliesTrue` (→ `true`, the symlink being
evidence of intent). You cannot see the symlink from the page text.

CALIBRATION (measured 2026-08-27, so nobody re-inflates this): of the 29 PROJECT pages then
missing the field, **0** had a symlink — every one was the unambiguous `MissingDefaultFalse`
case. The ambiguity is real in the CODE, not in the corpus. The reasons the repair GATE
(`memory_content_precheck.repair_defect`) still does not carry this check are the durable ones:
it is gate-silent so it can never cause a dispatch or a loop, and it self-heals on the next
write. See the rejection comment above `repair_defect` for the full record (TRDD-AO8MPK5D).

## Pre-transaction verb fixes — full mechanics

The SKILL body keeps the two verb commands inline (run them BEFORE
`memory_txn_cli.py begin`, never inside the staged copy, never after `commit`).
This section is the full mechanics behind those two steps.

**Re-read the page and recompute `--base-sha256` immediately before EACH verb call** —
never reuse one sha for both. The first verb's write changes the page's bytes, so a sha
computed once up front is already stale for the second verb: on a page needing both
fixes, that stale sha makes the second call refuse every time.

1. **The one-sided link — dry-run first, and only write if the TARGET is unaffected.**
   `reference-mem-topic` always wires both ends, but repair is single-page (IRON RULE 3)
   and a live write to the TARGET page could stale another chore's open transaction on
   it. Check before writing:

   Compute `sha` FIRST, from the page's current bytes, THEN read the page (the dry-run
   itself reads it live) and decide from that read — never decide first and checksum
   after, or a concurrent write between the two lands unnoticed:

   ```bash
   sha=$({ sha256sum <this page> 2>/dev/null || shasum -a 256 <this page>; } | cut -d' ' -f1)
   if [ -n "$sha" ]; then memgrep reference-mem-topic --page <this page> --to <target page> --dry-run; else echo "unreadable: <this page> — report and skip its verb fixes"; fi
   #   → "would link <this page> <-> <target page> (page {gains a link|unchanged}, to {gains a link|unchanged})"
   ```

   - `to unchanged` (only THIS page would change, or neither would — `page unchanged, to
     unchanged` means the link is already bidirectional, nothing to do) → safe, run it
     for real (a no-change run is harmless, but skip it outright if you can tell from
     the dry-run text that nothing would change):

     ```bash
     if [ -n "$sha" ]; then memgrep reference-mem-topic --page <this page> --to <target page> --base-sha256 "$sha"; else echo "unreadable: <this page> — report and skip its verb fixes"; fi
     ```
   - `to gains a link` (the TARGET would also change) → do NOT run it live. Skip this
     verb and report the one-sided link as a finding instead (the librarian/another
     pass owns the target-side write). **This is the common outcome, not an edge case**
     — most one-sided-link defects are THIS page having the only copy of the link, so
     expect most of them to end up reported, not auto-fixed, here. That is IRON RULE 3
     (single-page) working as intended, not a malfunction.

2. **The atom `desc:` backfill.** Repeat the same pair — sha first, then re-read the
   page to confirm the atom still needs it — even if verb 1 just ran; its write changed
   the page's bytes, so step 1's `sha` is now stale for this call:

   ```bash
   sha=$({ sha256sum <page> 2>/dev/null || shasum -a 256 <page>; } | cut -d' ' -f1)
   if [ -n "$sha" ]; then memgrep update-mem-atom --page <page> --atom <id> --desc "<text>" --base-sha256 "$sha"; else echo "unreadable: <page> — report and skip its verb fixes"; fi
   ```

**On refusal** (stale sha, or any other error) from either verb: report the refusal and
continue with whatever other fixes the page still needs — a refused pre-transaction fix
is not a reason to skip the rest of the checklist, nor to abandon the staged-copy pass
for this page.

**Re-read the page again after the pre-transaction step, before `begin`.** A verb call
that wrote changed the page's bytes; re-diagnose the checklist against the CURRENT page
so the candidate set handed to the staged-copy pass reflects what's actually still
broken, not what was broken before the pre-transaction fixes landed. This re-diagnosis
happens BEFORE the "does this page still need `begin`/`commit`" decision below, not
after — the decision is made from the post-fix diagnosis, never the stale one that
selected the page as a candidate.

A page whose ONLY defects were these two verb-covered fixes (and both were applied, or
correctly skipped/reported) needs no `begin`/`commit` at all — the pre-transaction step
alone completed the repair. It still prints the normal per-page Output line and still
closes the claim (`set-report` + `complete`), exactly as a page that went through the
transaction core (see Output and Close the claim below).

**Interaction with a verify FAIL:** if `commit --op repair` later exits non-zero and
self-aborts, the STAGED-COPY portion of the repair is discarded but a pre-transaction
verb fix (link/desc) already landed before `begin` and is NOT rolled back by this
abort; the page is left with that fix applied and its remaining defects still open.

## Repair checklist — full detail

The SKILL body's checklist condenses each of these to a trigger → action line; this
is the full wording, including the parts trimmed for the token cap.

- **No frontmatter at all** → add the full block: `name` (= filename stem),
  `description` (the page's topic as a SYMPTOM/question — derived from the body),
  `ocd`/`lmd`, `metadata.{node_type: memory, type, tier}`.
- **`publish-globally` — DO NOT ADD OR FLIP IT BY HAND. Not a repair defect; not yours**
  (the write path normalizes it on every write). A believed-wrong VALUE is a real
  finding — record it as a refusal. Reasoning: [repair-background § publish-globally](#why-publish-globally-is-not-a-repair-defect).
- **Missing `ocd`/`lmd`** → `lmd` = today (`date +%F`); `ocd` = the page's earliest
  known date (an existing `lmd`, else today). Never lower an existing `ocd`.
- **Nested `metadata.ocd` / `metadata.lmd`** → MOVE them to the TOP level (canonical
  shape). VALUE preserved verbatim (rule 4: `ocd` immutable) — only the LOCATION
  moves: `metadata:` keeps `node_type`/`type`/`tier`/`originSessionId`; `ocd`/`lmd`
  become top-level keys above it.
- **Missing `node_type`** → `node_type: memory`. **Missing `type`** → infer
  `project|reference|feedback|user` from the content.
- **Missing/invalid `tier`** → infer: has `globs:` → `hub`; has `## Applies to`
  (radiates) → `aspect`; otherwise → `component` (the default).
- **Inverted tier shape** → a `hub`/`aspect` page carrying only `## Governed by`
  (receiving): give it the `## Applies to` ray-list it radiates, or re-tag it
  `component` if it governs nothing. A `component` with `## Applies to` is the
  mirror error.
- **Missing `## Notes and lessons learned`** → append the empty section.
- **Answer-shaped `description`** → rewrite as the QUESTION/symptom a future
  search will use (findability — the page stays found by recall).
- **A page's OWN one-sided link** → a PRE-TRANSACTION fix, run live before `begin`
  (details + `--base-sha256` and refusal handling in the SKILL body's PRE-TRANSACTION
  section): `memgrep reference-mem-topic --page <this page> --to <target page>`. It
  wires both ends of the `[[wikilink]]` in one locked write; repair is single-page, so
  only fix the reciprocal FROM this page.
- **Superseded atom above / without the `## Superseded` delimiter** (`memgrep lint`
  WARNs it): ensure a `## Superseded` section exists (exactly that spelling), after
  the live atoms and BEFORE `## Notes and lessons learned`, and MOVE each
  `status:superseded` atom's whole block below it **VERBATIM** — byte-identical,
  order preserved. Never change props while moving; never move a `status:valid`
  atom. Full rationale: [repair-background § superseded atoms](#superseded-atom-delimiter-mechanics).
- **Atom `desc:` incomplete** (`verify_repair` refuses a repair that leaves one): every
  `^id [...]` atom marker needs a `desc:` that is PRESENT, ≤200 chars, QUOTED or an
  unquoted clean legacy slug (`[a-z0-9_]+` only). **Backfill by SUMMARIZING the atom's
  own body** (rule 5: infer, never invent), then apply it as a PRE-TRANSACTION fix,
  run live before `begin` (details in the SKILL body's PRE-TRANSACTION section):
  `memgrep update-mem-atom --page <page> --atom <id> --desc "<text>"`. Before
  trimming a `desc:`, check every cut symptom/cause/name is already in that atom's
  `keywords:` — add it if not. Full grammar + incident: [repair-background §
  desc](#desc-trim-keyword-incident-747b8bef).

## Execution context and what this is

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Sonnet** agent (`janitor-memory-subconscious-agent` — Sonnet, not Opus, per
> the USER cost decision 2026-06-30) — you ARE that agent. Run the whole pass here in your own
> context and return only a one-line result + the report path. A wikimem editorial pass is
> never run inline in a main session (it must not burden CPV or any other session's context).

REPAIR autonomously completes/corrects ONE malformed wikimem page at a time, IN
PLACE, through the transaction core — additive and structural only (backfills
metadata, adds the Notes section, fixes tier/links); it never rewrites a fact,
never changes `ocd`, never merges/splits/deletes. See "Why REPAIR exists" and
"What REPAIR is (and is not)" above for the full additive-vs-editorial distinction.

## EXIT / SUCCESS / idempotency contract

- **SUCCESS = verify-pass + applied** (LOCAL/USER atomically via the txn; PROJECT,
  if opted-in, staged-not-pushed — rides `publish.py`).
- **Retry ≤3 then abort** (staging discarded, one-line finding); other pages are
  independent.
- **Idempotent + crash-safe:** every run starts with `resume`; a well-formed page
  is a no-op (nothing to fix → skip it, never write a no-change commit).
- **Bounded + disable-able:** one scope/pass, top-K pages; `repair_per_day=0` or
  the kill-switch / `WIKIMEM_EDITOR_ENABLED=off` stops it.

## Scope

ONLY completes/corrects the SHAPE of malformed wikimem pages in ONE memory scope
per pass, IN PLACE through `memory_txn_cli.py --op repair`. Does NOT create pages
(`/janitor-memory-write`), merge same-subject pages
(`/janitor-memory-consolidate`), split oversized pages (`/janitor-memory-split`),
or resolve contradictions (`/janitor-memory-conflict`). Never moves a page across
scopes. PROJECT-scope editing is opt-in, never pushed standalone.
