---
trdd-id: JPL0JU86
title: A page no chore can ever maintain must say so — silent permanent abstention
column: human_review
blocked-by: []
created: 2026-08-11T20:55:12+0200
updated: 2026-08-22T11:21:01+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#249, TRDD-G4BCRUP7, TRDD-AZ6QRK0D]
---

# An unmaintainable page must not abstain silently

## Why (janitor#249, AgentlensPro peer — reproduced first-hand 2026-08-11)

Four pages in the USER-scope memory root are SYMLINKS resolving outside that root, into this
repo's own git-tracked PROJECT memory:

```
claude-code-{continuity-engineering,continuity-settings,esc-input-semantics,plugin-rollout-staleness}.md
  -> <this repo>/.claude/project/memory/
```

The transaction core's M-10 symlink-escape guard refuses them — correctly. The consequence is
that **no editorial chore can ever maintain those four pages from the scope they live in**, and
the content-hashed refusal that records the abstention is, for content that can never become
eligible, a permanent tombstone rather than the transient de-duplication it was designed to be.

**Cause (which the reporter could not determine, and which is recoverable only from this
repo):** all four are this project's own wikimem pages, named in its `CLAUDE.md` index. Someone
wanted knowledge that is true of EVERY project — Claude Code continuity settings, ESC input
semantics, plugin rollout staleness — recallable from every project, and reached for a symlink
instead of re-scoping the page. Correct intent, wrong mechanism.

## ⏵ 2026-08-13 — SIBLING CARD TRDD-AZ6QRK0D is building a symlink mechanism

Surfaced by hand (the two share no `external-refs:`, so `trdd-cross-card-blindspot` could not
see them). **AZ6QRK0D implements a `published-globally` → USER-scope SYMLINK mechanism, on an
owner directive** — i.e. it generalises the exact mechanism this card calls the wrong one, from
four pages to every page carrying that field.

They are reconcilable, and this card already contains the reconciliation: *"the link goes the
other way."* The constraint has been written onto AZ6QRK0D — canonical REAL FILE at USER scope,
project-side pointers OUT only, and acceptance verified against the M-10 guard ("a chore can
still open and commit the page") rather than against the filesystem ("the symlink resolves"),
since the four broken pages resolve fine today.

**Sequencing risk to watch:** if AZ6QRK0D ships first and is naive about direction, this card's
own fix becomes impossible — the four pages would be re-created as links by the very mechanism
meant to replace them.

## The two halves, and only one of them is reusable

**(a) The four pages are a one-off.** By the scope-routing rule they are machine-agnostic facts
true across all projects, so they belong at USER scope outright: MOVE them, do not link them.
If the janitor's own index still wants them, the link goes the other way. A decision about four
files, not a defect.

**(b) The silence is the defect, and it survives after (a) is fixed.** The reporter's sentence
is the load-bearing one: *a well-behaved abstention looks like success*. A chore that correctly
selects a page, correctly refuses it, correctly records a refusal, and correctly does not
re-dispatch emits exactly the same observable output as a chore that had nothing to do. Nothing
counts tombstones, so "4 of your pages are structurally unmaintainable" is discoverable only by
watching a chore abstain and wondering why.

This is the inverse of the owner's autonomy requirement, not an exception to it: the directive
says inform the main agent only about problems that only it can fix — and a page that no
automated pass can ever touch is EXACTLY such a problem. It is precisely the class that must be
surfaced, and it is the class currently guaranteed to be silent.

## What

1. **Re-scope the four pages** (move to USER scope, delete the symlinks, fix the PROJECT-side
   index links so nothing dangles). One-time. **⚠ ORDER IS LOAD-BEARING — see below; done in the
   wrong order this step UNDOES ITSELF.**

### ⚠ 2026-08-13 — "One-time" IS WRONG. A LIVE mechanism re-creates these, verified in source

**The cause recorded above — *"someone reached for a symlink"* — is not the whole story, and
acting on it as written fails.** The symlinks are the exact output shape of a mechanism that
is ALREADY SHIPPED and runs on every page write (TRDD-AZ6QRK0D, `scripts/memgrep/src/memory.rs`):

- `apply_publish_globally_fix` calls `create_user_symlink(&state.link_path, &state.page_abs)` —
  a link IN the USER mem root pointing AT the project page: byte-for-byte the shape M-10 refuses.
- It runs inside `normalize_page_until_clean`, bracketed around EVERY `atomic_write_page`, before
  and after each change, iterating to a fixed point. There is deliberately no `--fix` opt-in.

**And the trap is sharper than "it re-creates them".** Measured now: all four USER-root entries
ARE symlinks into this repo's `.claude/project/memory/`, while their PROJECT originals carry NO
`publish-globally` field at all. The classifier reads that combination as
`(has_field=false, has_symlink=true) → MissingSymlinkImpliesTrue`, whose documented meaning is
*"a symlink already exists — evidence of intent"*, and whose fix STAMPS `publish-globally: true`
onto the page.

So the first engine write to any of these four pages converts an accident into a DECLARED
intent, after which the symlink is correct by the engine's own rules and maintained forever.
Deleting the symlinks after that point is not a fix, it is a loop.

**Corrected order for step 1 — do not reorder:**
1. Delete the four USER-root symlinks FIRST (or set `publish-globally: false` on the project
   pages first), so the classifier can never see symlink-without-field.
2. Only then move/re-scope the pages.
3. Re-run a write and confirm no symlink reappears — the acceptance test is the engine's
   behaviour, not the filesystem state at one instant.

**This also means acceptance box 1 as written ("the four symlinks are gone") is not sufficient:**
they can be gone and return on the next write. It must assert they stay gone ACROSS a page write.
2. **Surface permanent unmaintainability.** Distinguish a TRANSIENT refusal (unchanged content,
   already judged — the ledger's intended use) from a STRUCTURAL one (symlink escape, unparseable
   frontmatter, over-cap with a tier that forbids splitting — conditions no future content change
   will clear). Structural refusals get counted and reported; transient ones stay silent.
3. **Report through the findings ledger**, not a heartbeat print — same reasoning as R16 in
   TRDD-G4BCRUP7: a finding whose only sink is one drift line dies with the turn that missed it.

## Disposition of a recurring `report-to-trdd` flag (2026-08-12) — do NOT re-investigate

`reports/memory-subconscious-agent/20260811_185204+0200-consolidate-manager-guide-refusal-design-review.md`
is flagged every fire and is a FALSE POSITIVE of a class worth naming, because it will recur.

The detector matches `consolidat` in the filename and exempts only no-op passes; this pass DID
merge, so it looks like an unconverted decision. Investigated twice: the merge is complete and
correct (survivor `manager-is-a-guide-not-a-gate` present, retired page gone, backlinks
redirected). What was genuinely missing was the merge's RATIONALE — nothing on the survivor told
a future reader why two pages became one, so the obvious future move is to "helpfully" re-split
them. That is now `ATOM-VSX6-Q7OC` (a lesson on the survivor), which is a MORE durable home than
a TRDD: corpus knowledge belongs in the corpus, where recall will surface it to whoever is about
to re-split.

So the rule's intent ("the decision must survive the report") is satisfied, and no TRDD is owed.
The residual defect is the detector's: a memory-MERGE report whose decision was captured as a
lesson is indistinguishable from one that was captured nowhere. If it keeps costing
investigations, the fix is for the exemption to consider a merge whose survivor gained a lesson
citing the retired slug — not to file a TRDD nobody will read.

## ⏵ 2026-08-14 — part (b) landed: structural refusals are now a countable finding

`memory_scopes.iter_escaping_note_files()` (the inverse-polarity twin of `iter_note_files`)
finds exactly the pages `iter_note_files` silently drops for escaping their scope root.
`memory-maintenance.py::_surface_scope_escapes` prints one `[memory-scope-escape] SCOPE/name
…` drift line per such page, deduped via the standard `dedupe.emit_once` seen-file (same
once-per-page contract as `_surface_mistiered`/the mis-tier surface) — said once, not every
fire, and never suppressed by a content change since it can never clear structurally. Wired
into `_run()` right after `_surface_mistiered`. Part (a) — re-scoping the four live pages —
is NOT done here (needs the AZ6QRK0D sequencing this card already flags; a live-store
mutation is outside a bugfix's blast radius) and stays open below.

## Acceptance

- [ ] The four symlinks are gone and the pages are maintainable from their new scope — **GATED ON
      A USER DECISION, not on work.** This box presumes option B (move the pages). The competing
      option A (keep the symlink, teach the chores to follow it) would rewrite it instead of
      satisfying it, so building either way now would be picking the answer. The two options and
      their real costs are written up on TRDD-AZ6QRK0D, which is in `human_review` for exactly
      this call — hence `blocked-by: [AZ6QRK0D]`.

      > **⚠ 2026-08-22 — THE GATE DISCHARGED WITHOUT ANSWERING, and executing this box as
      > written would now FIGHT shipped behaviour.** Three things measured today:
      >
      > 1. **TRDD-AZ6QRK0D is `published`, not `human_review`.** It closed 2026-08-18 — but on
      >    the PRIVACY-gate question (where the scan lives), not on the direction question this
      >    box was waiting for. The blocker named here is terminal and the call was never made,
      >    so nothing will arrive to unblock this box on its own. The frontmatter already reads
      >    `blocked-by: []` while this text still claims `[AZ6QRK0D]` — the frontmatter is right.
      > 2. **The symlinks now number SIX, not four**, and two of them point into a DIFFERENT
      >    project (`ai-maestro-assistant-manager-agent`). Those two are not this repo's to touch
      >    at all.
      > 3. **All four janitor pages carry `publish-globally: true`, declared DELIBERATELY** in
      >    `fba278d4` ("declare publish-globally on the 4 pages whose symlinks already existed").
      >    Not an engine accident — a decision. So the symlinks are now correct by the shipped
      >    mechanism's own rules and are MAINTAINED: deleting them makes
      >    `TrueNoSymlink` re-create each one on the next write. This box would be a loop.
      >
      > **The de facto answer is option A**, arrived at by shipping rather than by ruling: the
      > canonical page lives in PROJECT (where it IS maintainable), the USER-scope symlink gives
      > it recall reach, `iter_note_files` excludes it so no chore wastes a dispatch on it, and
      > `_surface_scope_escapes` reports the condition instead of hiding it. That is a coherent
      > end state and it is what runs today.
      >
      > **So this box is not work — it is one question for the USER:** leave it (option A, the
      > status quo, nothing to do), or invert the direction so the canonical file lives at USER
      > scope with project-side pointers out (option B, and note it must then also account for
      > the two foreign-project links, which this repo must not touch). Executing it as written
      > without that ruling would delete symlinks the engine immediately restores.
- [x] A structurally-refused page produces a countable finding; a transient refusal still does not
- [x] Test: a scope-escaping symlink yields exactly one finding, and a second pass over the
      unchanged corpus does NOT duplicate it
- [x] #249 answered with the commit id — `#issuecomment-5304878173`. The earlier close (2026-08-14)
      named the mechanism but not the commit, which is what this box actually asked for: it is
      **`2295a5c6`**, *"a scope-escaping page is a finding, not silence"*, introducing BOTH
      `memory_scopes.iter_escaping_note_files` and `memory-maintenance._surface_scope_escapes`
      (`:434`, wired at `:513`); `fba278d4` then declared `publish-globally` on the four pages.
      The comment also corrects the record: what shipped is the VISIBILITY half. The pages are
      still unmaintainable from USER scope — proven by running `_ensure_rel_inside`, not by
      reading it — so this issue's own ask (stop abstaining silently) is met while the underlying
      condition is unchanged.
