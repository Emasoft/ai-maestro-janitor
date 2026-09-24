# REPAIR — background and rationale

## Table of contents

- Why REPAIR exists
- What REPAIR is (and is not)
- Claim exit codes
- desc: quoting grammar (TRDD-3SOO1RWE)
- desc-trim keyword incident (747b8bef)
- Superseded-atom delimiter mechanics
- Why `publish-globally` is NOT a repair defect
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

## Resources per-heading link inventory (moved from SKILL.md)

Moved verbatim out of SKILL.md's Resources section (token-cap margin pass,
TRDD-D7RLXAN1). The [wikimem-model](../janitor-memory-write/references/wikimem-model.md)
per-heading anchors:

  - [A wiki, not a pile — and collaborative like Wikipedia](../janitor-memory-write/references/wikimem-model.md#a-wiki-not-a-pile--and-collaborative-like-wikipedia)
  - [The editorial decision flow (run this on any change worth remembering)](../janitor-memory-write/references/wikimem-model.md#the-editorial-decision-flow-run-this-on-any-change-worth-remembering)
  - [EXPAND and REDUCE — radiating suns vs receiving terminals](../janitor-memory-write/references/wikimem-model.md#expand-and-reduce--radiating-suns-vs-receiving-terminals)
  - [The three tiers (a page's role in the pyramid)](../janitor-memory-write/references/wikimem-model.md#the-three-tiers-a-pages-role-in-the-pyramid)
  - [The edge model — EVERY link is bidirectional (the link law)](../janitor-memory-write/references/wikimem-model.md#the-edge-model--every-link-is-bidirectional-the-link-law)
  - [Page anatomy](../janitor-memory-write/references/wikimem-model.md#page-anatomy)
  - [Atoms — first-class body elements (block-properties)](../janitor-memory-write/references/wikimem-model.md#atoms--first-class-body-elements-block-properties)

This file's own `## Table of contents` above already names the same 10
repair-background sections; these are the same entries as clickable per-heading anchors,
for a reader who wants to jump straight to one of them:

  - [Why REPAIR exists](references/repair-background.md#why-repair-exists)
  - [What REPAIR is (and is not)](references/repair-background.md#what-repair-is-and-is-not)
  - [Claim exit codes](references/repair-background.md#claim-exit-codes)
  - [desc: quoting grammar (TRDD-3SOO1RWE)](references/repair-background.md#desc-quoting-grammar-trdd-3soo1rwe)
  - [desc-trim keyword incident (747b8bef)](references/repair-background.md#desc-trim-keyword-incident-747b8bef)
  - [Superseded-atom delimiter mechanics](references/repair-background.md#superseded-atom-delimiter-mechanics)
  - [Why `publish-globally` is NOT a repair defect](references/repair-background.md#why-publish-globally-is-not-a-repair-defect)
  - [Execution context and what this is](references/repair-background.md#execution-context-and-what-this-is)
  - [EXIT / SUCCESS / idempotency contract](references/repair-background.md#exit-success-idempotency-contract)
  - [Scope](references/repair-background.md#scope)

## Pre-transaction verb fixes — extended rationale

Moved verbatim out of SKILL.md's PRE-TRANSACTION section (token-cap margin pass,
TRDD-D7RLXAN1) — read this before the two PRE-TRANSACTION verb calls, or when deciding
whether a one-sided-link dry-run is safe to run live.

Why `--base-sha256` is recomputed before EACH verb call rather than once: "The first
verb's write changes the page's bytes, so a sha computed once up front is already stale
for the second verb: on a page needing both fixes, that stale sha makes the second call
refuse every time."

Why a `to gains a link` dry-run result is skipped and reported rather than auto-fixed:
"(the librarian/another pass owns the target-side write). **This is the common outcome,
not an edge case** — most one-sided-link defects are THIS page having the only copy of
the link, so expect most of them to end up reported, not auto-fixed, here. That is IRON
RULE 3 (single-page) working as intended, not a malfunction."

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
