# MERGE protocol — the verb contract, a worked walkthrough, and the verify catalog

This is the deep reference for `/janitor-memory-consolidate`. The SKILL.md is the
checklist; this doc is the *why* and the exact mechanics. Read it once; the skill
has the runnable steps.

## Table of contents

- No-third-page check (pre-merge)
- Claim exit codes
- The memgrep verb contract (no staged copies, no hand edits)
- What is_legal_merge checks
- What the merge write gate refuses
- Why backlink redirect is the load-bearing step
- Slug rules
- Worked walkthrough
- Failure-path walkthrough
- Bounds & safety recap
- Steps 6-10 — the executable sequence (moved from the SKILL body)
- Step 5 — discover the backlinks to redirect (THE LINK LAW, mandatory)
- Recording an abstain
- Candidate selection details

## Claim exit codes

`memory_dispatch_claim.py --chore consolidate --state-dir "$STATE_DIR"` reports its
outcome via exit status: **2** = nothing claimable right now; **3** = no
memory-maintenance state at all (`$STATE_DIR` is wrong); **4** = `$STATE_DIR` was
empty; **5** = the dispatch was recorded for a different state dir, so the claim
was refused. Any of these, an unreadable result, or a printed chore name other than
`consolidate` means STOP and report — never pick a scope yourself, never re-derive
what is due, and never read the legacy `memory-maint-pending.json` slot.

## The memgrep verb contract (no staged copies, no hand edits)

You NEVER mutate a live memory page by hand — memgrep's write verbs are the ONLY page
writers (TRDD-XI10BA5D). A consolidation is a TWO-VERB sequence, holder redirects FIRST:

```
memgrep merge-mem-topic --from <A-rel> --into <B-rel> [--base-sha256 <B's sha256>]
    → moves EVERY atom (+ its `[^N]` lessons) from A into B, in source order,
      renumbering moved labels to free ones on B; carries every footnote def,
      cited or not (GitHub #304).
    → wires the reciprocal See-also link BOTH ways (the LINK LAW) in the same batch.
    → TOMBSTONES A in place: the tombstone keeps A's `name:` + `ocd`, reads
      "Merged into [[<B>]]", and holds NO atoms — the page survives as a pointer,
      never a deletion (nothing is retired to .trashcan/ by this verb; that is
      `delete-mem-topic`, which this chore must never use — it folds nothing).
    → the whole batch (B + the A tombstone) passes ONE shared write gate before
      any commit: a refusal names every violation content-free and writes NOTHING.
    → stdout: merged-atom count line; sha256 + disclosure on stderr.

memgrep reference-mem-topic --page <holder> --to <survivor> [--base-sha256 H]
    → the HOLDER REDIRECT verb: wires the wikilink both ways in one gated write.
      Used for a backlink holder whose link must repoint (step 6 below).
```

Both verbs take `--dry-run` (print the plan, mutate nothing) and `--base-sha256` (CAS:
refuses with a STALE message when the target changed since you last read it — re-read,
recompute, retry, never force). If the installed memgrep does not know the verb
(unknown-command / usage refusal), ABSTAIN and report the gap (page + operation) — never
fall back to Edit/Write, a shell writer, or the txn core.

**Holder-first ordering is NOT a preference.** The batch's one-sided-link rule refuses a
merge whose reciprocal is not wired in-batch, on disk, or pre-existing — and
`merge-mem-topic` wires its OWN pair's ends, but a THIRD page still linking the retiring
name must be repointed first, because a link pointing at a page whose content just left
is the exact broken graph the LINK LAW forbids. So: repoint every holder (step 6), THEN
merge (step 9). Between the two the corpus is never left with a link into a hollowed page.

**No holder rides inside the merge itself.** `merge-mem-topic` touches exactly its two
named pages (`--from` tombstone + `--into` survivor); a holder edit is its OWN
`reference-mem-topic` call. The old one-write-per-transaction rule (janitor#145) exists
for the same reason the verb split does: an UNVERIFIED holder edit must never ride
inside a verified merge.

## What `is_legal_merge` checks (YOUR pre-flight, not the verb's)

The write gate does NOT re-check legality — it assumes you already gated. So you
MUST run `is_legal_merge(meta_A, meta_B)` before merging. It returns `(False, why)`
for:

- **cross-tier** — `meta.tier` differs (e.g. `aspect` vs `component`). An aspect
  is a radiating rule; a component is a terminal element; they never fuse.
- **non-mergeable tier** — either tier is not in `{aspect, component}`, i.e. a
  `hub`. A hub is a functionality's single overview, not a mergeable leaf.
- **cross-type** — `metadata.type` differs (e.g. `project` vs `reference`). Same
  words, different *kind* of memory → not the same page.

Same-scope is guaranteed structurally (the txn is per-scope; you only ever pass
two paths under the same root). Same-*subject* is YOUR judgment — neither predicate
nor verifier can decide it; when unsure, **abstain**.

**Run it** on A's and B's frontmatter, refuse on `False` (the CLI's commit gate also
re-checks — wikimem audit M-2 — but pre-flight refuses EARLY and cheap, before any
verb runs):

```bash
uv run --quiet - <<PY
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_edit_verify as v
A = v.parse_frontmatter(open("$A_PATH").read())
B = v.parse_frontmatter(open("$B_PATH").read())
ok, why = v.is_legal_merge(A, B)
print("legal:" if ok else "REFUSE:", why)
sys.exit(0 if ok else 1)
PY
```

On a refusal, abstain and surface a one-line note.

## What the merge write gate refuses (the failure catalog)

`merge-mem-topic` prepares the whole batch (survivor + tombstone) through the shared
write gate before anything touches disk. It FAILS — writing NOTHING anywhere — on any
of:

| Failure reason (printed) | Cause | The fix |
|---|---|---|
| a `[^N]` lesson/fact lost in the merge result | the gate's id-set + body rules see a source lesson absent from the survivor | the verb itself moves every lesson; if you pre-edited content (you should not), restore it byte-identical |
| `--base-sha256` STALE | the `--into` page changed since you read it | re-read, recompute, retry (CAS guard — never force) |
| atom id collision(s) already on `--into` | the moved ids already exist there | the verb refuses up-front, nothing written; resolve the id conflict first |
| introduced one-sided link | the batch or a neighbor would gain a link with no reciprocal | wire the other end in-batch (`reference-mem-topic`) or skip the link |
| an ERROR-level lint finding in the result | the gate's strict rule (recorded default) | fix the defect on the source page first, through a memgrep verb |

Content violations name COUNTS/IDs only — never page text. This is the same
knowledge-preservation shape `verify_merge` used to enforce at commit, now enforced by
the gate BEFORE any write lands (nothing to "abort" — a refusal leaves disk untouched).

**What the catalog does NOT cover — SHORT-form facts + the lead are YOURS.** The gate
machine-checks lesson and body-fact preservation (`body_facts_preserved` requires every
substantive body line of every source to survive as a SUBSTRING of the result; a fact
demoted into a `[^N]` lesson also counts as preserved). Two things remain YOURS: (1) the
COARSE net's two by-design blind spots — it ignores any line under 24 chars and every `#`
heading, so a fact carried only in a short bullet or a heading can still be dropped or
rewritten silently (this is the documented issue-#91 shape, where a split condensed prose
into shorter, WRONG path bullets and nothing caught it); and (2) the one-sentence
**lead** that makes the survivor read as one topic — the merge verb preserves bodies but
does not compose prose. Both are enforced only by you in step 8. No-information-lost is the editor's
first law; for the body, you are its only guardian.

## Why backlink redirect is the load-bearing step

THE LINK LAW: every `[[link]]` is bidirectional and must resolve. When B's content
moves into the survivor, every page that linked `[[B]]` now points at a hollowed
tombstone. The gate treats an unresolved introduced link as a refusal-class failure, so
every holder must be repointed BEFORE the merge (step 6) — never inside it:
`merge-mem-topic` touches exactly its two named pages, and an unrelated holder edit
inside a verified merge would be an UNVERIFIED write riding a verified one (the reason
the old one-write rule, janitor#145, existed). Cross-*scope* PROSE mentions (a USER note
that says "see the LOCAL keychain page" in prose, not as a `[[wikilink]]`) are NOT
auto-edited — those you grep and **surface** for a human, because rewriting prose across
scopes is a judgment call the editor doesn't make autonomously.

## Slug rules

A page's slug is its frontmatter `name:`, falling back to its filename stem
(`_slug_of` in the CLI). Two consequences:

- **Keep the survivor at A's path AND A's `name:`** — that way pages already
  linking `[[A]]` need no redirect; only `[[B]]` holders do. Fewest redirects =
  fewest chances to miss one. (The merge moves B's content INTO A; the tombstone
  sits at B's path keeping B's `name:`.)
- If you must rename the survivor's `name:`, you also break every `[[A]]` holder —
  redirect those too. Prefer not to rename during a merge.

**Non-subject example (moved from the SKILL body):** `reference` "keychain
location" and `project` "rotator 429" share the word "keychain"/"429" but are
different SUBJECTS → abstain. Same-word overlap is not same-subject.

## Worked walkthrough (LOCAL scope, two `project` `component` notes)

Suppose the most-recent LOCAL notes include
`rotator-429-deadlock.md` (subject: rotator let a 429 happen) and
`rotator-version-skew.md` (subject: the same incident from the version-skew angle).
Both `metadata: {tier: component, type: project}`. A reader says "same incident,
one page".

1. **Narrow:** `memgrep recall "" "$LOCAL_MEM" --sort lmd --top 12` surfaces both;
   `memgrep find "+rotator +429" "$LOCAL_MEM"` returns exactly these two. (In the
   live SKILL these recursive memgrep calls are piped through `grep -v '/user-mem/'`
   — the private store is never a merge candidate; see the SKILL's privacy guard.)
2. **Subject:** read both — same incident, different facets → mergeable.
3. **Legality:** `is_legal_merge` → `(True, "ok")` (same tier `component`, same
   type `project`).
4. **No third page:** `memgrep find "+rotator +429" "$LOCAL_MEM" --top 10` returns
   only these two → proceed. (If `rotator-keychain.md` also matched on "rotator"
   but is a *different* subject, that's fine — the no-third-page test is about the
   *subject*, confirmed by reading, not raw keyword hits.)
5. **Backlinks:** `memgrep links --from rotator-version-skew "$LOCAL_MEM"` →
   `oauth-rotator-hub` links `[[rotator-version-skew]]`. That holder must repoint
   — with its OWN `reference-mem-topic` call, BEFORE the merge (janitor#145
   lineage: a holder edit never rides inside the merge verb's two-page batch).
6. **Redirect the holder FIRST (its own gated verb call):**

   ```bash
   memgrep reference-mem-topic --page "oauth-rotator-hub.md" --to "rotator-429-deadlock.md" \
     --base-sha256 "$(sha256 -q oauth-rotator-hub.md)"
   # wires the wikilink BOTH ways in one gated write; a refusal writes nothing
   ```

7. **Then the merge itself:**

   ```bash
   memgrep merge-mem-topic --from "rotator-version-skew.md" --into "rotator-429-deadlock.md" \
     --base-sha256 "$(sha256 -q rotator-429-deadlock.md)"
   ```

   The verb moves every atom + lesson into the survivor (source order, moved
   labels renumbered, every footnote def carried), unions the lesson sets, wires
   the reciprocal See-also BOTH ways, and tombstones the source in place — run
   `--dry-run` first if you want the plan printed before anything lands; the
   survivor keeps `rotator-429-deadlock` as its `name:`, and no
   `[[rotator-version-skew]]` link remains anywhere.
8. **Reindex + report:** `memgrep reindex` if present (the index is memgrep's — do
   NOT touch `MEMORY.md`), report `merged rotator-version-skew → rotator-429-deadlock
   (4 lessons preserved, 1 backlink redirected, ocd=2026-05-30)`.

## Failure-path walkthrough (gate refusal → bounded retry)

If the merge verb refuses — say a lesson-preservation violation — it wrote NOTHING
anywhere (the batch is gated before any commit; there is no partial state to clean
up). Read the named violations, fix at the source (a defect on a page goes through a
memgrep verb, never a hand edit), and retry. After **3** such failures, mutate nothing,
and surface
`[janitor-memory] merge rotator-version-skew+rotator-429-deadlock abandoned after 3
gate refusals: <reasons>` for a human.

## Bounds & safety recap

- ONE scope, ONE merge per pass. Default LOCAL+USER; PROJECT opt-in
  (`edit_project_scope`), staged-not-pushed.
- Kill-gate: the janitor kill-switch +
  `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED`. `consolidation_per_day=0`
  disables the pass entirely.
- The verbs scope-lock and take `--base-sha256` CAS guards — a concurrent writer
  trips the stale-hash refusal (re-read, recompute, retry); you never overwrite a
  just-written fact. Lock contention is a normal abstain, not a failure.

## Steps 6-10 — the executable sequence (moved from the SKILL body)

The exact command sequence for the verb half of the merge. Moved here
verbatim from the SKILL body (TRDD-82OP4EN9 token-budget move); the body keeps
only the invariants.

### 6. Redirect every holder FIRST — its own verb call, before the merge

janitor#145 lineage: a holder edit never rides inside the merge verb's two-page
batch (`merge-mem-topic` touches exactly `--from` + `--into`; anything else is an
UNVERIFIED write inside a verified one). So each step-5 holder is repointed with
its OWN `reference-mem-topic` call, done BEFORE the merge even begins.
(A step-5 holder here counts the harness index file `MEMORY.md` too, whenever
it still points at a retired slug.)

```bash
for holder in <holder-rel-paths...>; do
  memgrep reference-mem-topic --page "$MEMDIR/$holder" \
    --to "$MEMDIR/<survivor>" \
    --base-sha256 "$(sha256 -q "$MEMDIR/$holder")"
  # wires the wikilink BOTH ways (holder → survivor, survivor → holder) in one
  # gated write; the ONLY change this call makes.
done
```

The gate's one-sided-link rule refuses a merge whose retiring name is still
pointed at by an unwired holder, so holder-first is the only sequence that can
commit at all — and it means the corpus is never left, even between the holder
redirects and the merge, with a link into a hollowed page.

### 7. Open the merge — the two named pages only

The survivor keeps A's slug by convention (fewest inbound redirects). The verb
takes exactly the two page paths:

```bash
memgrep merge-mem-topic --from "$MEMDIR/<B-rel-path>" --into "$MEMDIR/<A-rel-path>" \
  --base-sha256 "$(sha256 -q "$MEMDIR/<A-rel-path>")"
```

`--dry-run` first prints the plan (survivor text + tombstone) and mutates
nothing — use it whenever the pair is unusual. No staged copy exists; you never
hand-build the merged page.

### 8. What the verb builds (and what stays yours)

`merge-mem-topic` moves EVERY atom (+ its `[^N]` lessons) from B to A in source
order, renumbers moved labels, carries every footnote def (cited or not), unions
the lesson sets, wires the reciprocal See-both-ways link, and tombstones B in
place (B keeps its `name:` + `ocd`, reads "Merged into [[A]]", holds no atoms).
The gate machine-checks lesson preservation and the id-set before anything lands.
STILL YOURS: the one-sentence lead that makes the survivor read as one topic, and
the short-line/heading blind spots (see the catalog above) — check both in the
`--dry-run` output.

See [merge-page-rules](merge-page-rules.md) for the full rule breakdown
(frontmatter shape, what you must ensure).

### 9. The gate is the commit point

The batch (survivor + tombstone) passes ONE shared write gate before anything
touches disk; on a refusal NOTHING is written anywhere and the violations are
named content-free. On a pass the two atomic writes land (crash between them
leaves a recoverable duplicate, never a loss) — **done**.

### 10. EXIT / retry / rollback

- **SUCCESS** = the verb exited 0 (LOCAL/USER applied on disk;
  PROJECT, if enabled, staged-not-pushed). `memgrep reindex` if present (the index
  is memgrep's — do NOT touch `MEMORY.md`). Report the one-line result.
- **Gate refusal** — nothing was written anywhere (gated before any commit). Read
  the printed reasons, fix at the source, and retry. **Bounded retry ≤ 3.** After 3
  failures, mutate NOTHING, and surface a finding: `[janitor-memory] merge <A>+<B>
  abandoned after 3 gate refusals: <reasons>`.
- **Lock contention / stale `--base-sha256`** — another
  pass or a concurrent `/janitor-memory-write` is touching this scope. **Abstain**
  this cycle (the next heartbeat retries); do not force it.

## Step 5 — discover the backlinks to redirect (THE LINK LAW, mandatory)

Moved out of `SKILL.md` on 2026-08-04 to keep that body inside the 5000-token skill budget.
Read this once you have a legal pair; steps 1-4 in the skill decide whether you do.

On merge A+B→C, every page that links `[[A]]` or `[[B]]` MUST be rewired to
`[[C]]` — otherwise the corpus is left with links into a hollowed page and the
gate will refuse. **Redirect each holder with its OWN prior `reference-mem-topic`
call, before the merge begins** (janitor#145 lineage — see step 6: a holder edit
cannot ride along in the merge verb's two-page batch). Find the inbound links with `memgrep links
--from` (`--from NOTE` = NOTE's *backlinks* — who points AT it):

```bash
memgrep links --from "$A_SLUG" "$MEMDIR"   # pages linking [[A]]
memgrep links --from "$B_SLUG" "$MEMDIR"   # pages linking [[B]]
```

Note every holder page — you will repoint the link to the survivor `C` with that
holder's own `reference-mem-topic` call (step 6). (Slug = the page's
frontmatter `name:`, else its filename stem.)

Separately, **prose** mentions of the retired names across OTHER scopes are NOT
auto-edited — grep for them and **surface** any hits as
`[janitor-memory] prose mentions of retired slug <A>/<B> in <scope>: <files> (review)`.
Do not edit other scopes.

**THE SECOND INDEX — `MEMORY.md` (janitor#182, mandatory).** `memgrep links` sees only the
wikimem `[[wikilink]]` graph. The harness `MEMORY.md` at the scope root is a SEPARATE index with
its own `- [Title](<page-slug>.md) — hook` lines, and a merge that deletes the retired page leaves
its line pointing at a file that no longer exists. A future session follows it, finds nothing, and
reads the note as **missing** rather than **merged** — the one outcome consolidation exists to
prevent. Check it, and stage it whenever it points at a retired slug:

```bash
grep -n "](${B_SLUG}.md)" "$MEMDIR/MEMORY.md"   # and $A_SLUG if A is the one retiring
```

If it matches, redirect it in its OWN `--op repair` transaction — same as any
other holder (step 6), never inside the merge transaction — and **redirect the
target only**: `](retired.md)` → `](survivor.md)`, leaving the title and hook
text byte-for-byte. This is a POINTER REPAIR, not curation: you are fixing a
link your own deletion broke. It does not license editing, reordering, or
pruning any other line in that file, which remains the harness's.
`memory_edit_verify.redirect_memory_md_links()` performs exactly this rewrite, and
`no_dangling_memory_md_refs()` is the matching check. (MEMORY.md is the harness's
file, NOT a wikimem page — the memgrep-verbs-only rule does not forbid fixing a
pointer here; it is the one sanctioned non-verb edit, and only in this redirect
shape.)

## No-third-page check (pre-merge)

A merge fuses exactly two sources. A THIRD live page also about this subject would
leave a fragment behind — confirm only A and B match:

```bash
# Drop user-mem/ (private, recursive) so a private note can't masquerade as a third page.
memgrep find "+<subject-term-1> +<subject-term-2>" "$MEMDIR" --top 10 | grep -v '/user-mem/'   # expect only A and B
```

If a third page appears, **abstain** and surface all three for a human. Never silently
drop or ignore the third.

## Recording an abstain

Every step 1–4 abstain — not convincing, different facets, no topic page, illegal
merge, a third page found — must be written to the refusal ledger before you move
on. The librarian re-surfaces the same candidate pair on every run and the pages'
bytes do not change between runs, so a verdict you keep to yourself is re-derived
by a fresh agent at full dispatch cost, producing the identical "no", forever.
That idle burn was measured at ~200k–280k tokens per pass (janitor#212, #227).

The refusal is keyed on the WHOLE candidate group, so pass one `--page` per page in
the pair — a one-page key matches no group and is silently inert.

It is a verdict with an EXPIRY, not a permanent silence: the entry re-arms by itself
when either page's bytes change, and again after 7 days. So a wrong "no" costs at
most one cycle, while a right one stops costing anything.

`--reason` is the deliverable, not a formality: the next reader must be able to
re-check your judgement from it without re-reading both pages.

The invocation, keyed on the whole pair:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_refusal_cli.py" record \
  --intervention consolidate --scope <LOCAL|PROJECT|USER> --root <memdir> \
  --page <A>.md --page <B>.md --reason "<why A and B do NOT merge>"
```

## Candidate selection details

Moved here verbatim from the SKILL body (token-budget move) — Step 1's picking
rule, the privacy guard, and the description-named-singleton special case.

Each group is every SAME-`(tier, type)` page the structural gate + size gate (#210) allow — a
merge fuses exactly TWO, so pick the pair inside the printed group that most plausibly shares a
subject (favor the most-recently-modified pair when several look equally plausible). If a group
has no convincing pair, or the CLI prints nothing, abstain — that is success, not failure.

**Privacy guard:** NEVER open, read, merge, or even name a page whose path contains
`user-mem/` — that is the user's PRIVATE agent-invisible store; it is not part of the
curated wiki and must never enter a consolidation (`memory_content_precheck`'s own
candidate scan already excludes it, but re-verify before touching any printed path).

**Description-named singletons are PRIME candidates (TRDD-NM4TPCQ9).** A page NAMED
like one memory's description (`implementation-of-…`, `how-to-…`, `fix-for-…`) is
the recurring agent naming error — one stranded atom. Treat it as candidate A and
search for its broad TOPIC page (`agents-tracing`) as B. **Survivor rule:** the
TOPIC-named page survives; the singleton retires (redirect `[[links]]`, ref-count
footnotes per the move rule). No topic page → abstain and surface
`[janitor-memory] rename-candidate: <page> (description-named, no topic page)`.
