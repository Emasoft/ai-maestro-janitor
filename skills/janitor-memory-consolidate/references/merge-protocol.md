# MERGE protocol — the transaction contract, a worked walkthrough, and the verify catalog

This is the deep reference for `/janitor-memory-consolidate`. The SKILL.md is the
checklist; this doc is the *why* and the exact mechanics. Read it once; the skill
has the runnable steps.

## Table of contents

- The two-phase transaction contract
- What is_legal_merge checks
- What verify_merge enforces at commit
- Why backlink redirect is the load-bearing step
- Slug rules
- Worked walkthrough
- Failure-path walkthrough
- Bounds & safety recap
- Steps 6-10 — the executable sequence (moved from the SKILL body)
- Step 5 — discover the backlinks to redirect (THE LINK LAW, mandatory)

## The two-phase transaction contract (`scripts/memory_txn_cli.py`)

You NEVER mutate a live memory page. You mutate **copies** the CLI stages for you,
and the CLI verifies + applies them atomically. The contract is two-phase so your
semantic editing happens *between* the phases:

```
begin  <scope_root> merge <A-rel> <B-rel>
    → snapshots + copies A and B into a fresh staging dir.
    → prints  txn_id=<id>   and   staging=<abs dir>.
    → you then edit ONLY inside that staging dir:
        overwrite a copied source .md  → counts as a WRITE (a changed page)
        add a brand-new .md            → counts as a WRITE (a new page)
        delete a copied source .md     → counts as a DELETE (a removed page)

commit <scope_root> <txn_id> --op merge
    → RECONSTRUCTS the write/delete set by DIFFING staging vs the recorded sources
      (new-or-changed staged file → write; recorded source whose staged copy was
      removed → delete).
    → runs verify_merge as the commit gate.
    → on PASS: re-hashes sources (stale-snapshot guard), takes the per-scope flock,
      applies writes-BEFORE-deletes via os.replace, prints
      `committed <id> (merge): N write(s), M delete(s)`, exits 0.
    → on FAIL: prints the reasons, ABORTS the txn (live tree untouched), exits 1.

abort  <scope_root> <txn_id>     discard a not-yet-committed txn.
resume <scope_root>              roll forward / clean an interrupted txn (the next
                                 heartbeat runs this; you usually don't).
```

Exit codes: clean `commit`/`abort`/`resume` = 0; verify FAIL = 1; a precondition
error (editor disabled, lock contention, vanished/stale source, "nothing staged")
prints `error:`/the reason and exits 2.

**Merge shape the CLI expects:** exactly **one** surviving write (the merged page
`C`, written at A's path) and one-or-more deletes (B's copy removed). The check is
`len(writes) != 1` over EVERY staged write, with no exemption for any of them.

**So a backlink holder canNOT ride along in the merge transaction.** Copying holder
page `D` into staging to repoint its `[[B]]` makes two writes and the CLI refuses
with `merge expects exactly ONE surviving page, found 2 write(s)`. (An earlier
revision of this paragraph claimed holder rewrites were "fine and expected"; that
was never true of the code, and a CONSOLIDATE pass hit the refusal in practice.)

**Do it as TWO transactions, holder FIRST:**

1. `--op repair` on `D` alone — an in-place edit whose single source is `D`, so it
   passes `verify_repair` trivially. Redirect `[[B]]` → `[[C]]`'s slug. Commit.
2. `--op merge` with ONLY the merge sources. Commit.

The ORDER is not a preference. `verify_merge` runs `no_dangling_refs` and REFUSES a
merge while any live page still links a retired slug — so holder-first is the only
sequence that can commit at all, and it also means the corpus is never left, even
between the two commits, with a link pointing at a page that no longer exists.

Keeping the one-write rule is deliberate rather than a limitation to route around:
`verify_merge` proves knowledge preservation between the SOURCES and the SURVIVOR.
It says nothing about an unrelated holder edit, so allowing that write into the
same transaction would let an UNVERIFIED edit ride inside a verified one.

## What `is_legal_merge` checks (YOUR pre-flight, not the CLI's)

`verify_merge` does NOT re-check legality — it assumes you already gated. So you
MUST run `is_legal_merge(meta_A, meta_B)` before `begin`. It returns `(False, why)`
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

## What `verify_merge` enforces at commit (the failure catalog)

`commit --op merge` builds the inputs (sources = the DELETED pages read at their
begin-time content; result = the single WRITE that is C; `others` = every OTHER
live page in the scope) and calls `verify_merge`. It FAILS — aborting the txn,
mutating nothing — on any of:

| Failure reason (printed) | Cause | The fix in C |
|---|---|---|
| `dropped/reworded lesson(s): …` | a `[^N]` lesson body from A or B is missing/changed in C | copy every source lesson body **byte-identical**; you may append (compound) but never reword/drop |
| `ocd/lmd: result ocd X != min(sources) Y` | C's `ocd` isn't the oldest source ocd | set `ocd: min(A.ocd, B.ocd)` |
| `ocd/lmd: result lmd X regressed below max(sources)` | C's `lmd` older than a source's | set `lmd:` to today (`date +%F`), ≥ both sources |
| `ocd/lmd: missing ocd on a source or the result` | a source or C lacks `ocd` | ensure all three have `ocd` |
| `duplicate content line(s) re-introduced: …` | a substantive line (≥24 chars, not a heading) appears twice in C | intra-page dedup — keep ONE copy (the better-sourced); a merge removes redundancy |
| `dangling refs to retired slug(s): …` | some live page (C itself OR an `other`) still `[[links]]` a retired slug — you skipped or missed a holder in step 6 | **abort this merge txn**, repoint the missed holder in its OWN `--op repair` transaction (step 6), commit it, THEN retry the merge |

The dangling check unions C with EVERY other live page in the scope — so a missed
redirect *anywhere in the scope* is caught. This is why step 5 (discover backlinks
via `memgrep links --from`) and step 6 (repair every holder, one `--op repair`
transaction each, BEFORE the merge) are mandatory, not optional — the merge
transaction itself has no capacity to fix a missed one (a repair there would be a
second write, and `commit --op merge` refuses before verify even runs).

**What the catalog does NOT cover — SHORT-form facts + the lead are YOURS.** Every
failure above is machine-checked, and since issue #48 that INCLUDES body facts:
`body_facts_preserved` requires every substantive body line of every source to
survive as a SUBSTRING of the result. The old objection here — that a strict
body-superset check would false-fail on every legitimate dedup — was solved by
using substring rather than line-equality matching: a deduped fact still appears
once, so it still matches, while a DROPPED or PARAPHRASED fact does not. (A fact
demoted into a `[^N]` lesson also counts as preserved; the haystack is the whole
page, because demotion is the correction protocol's mandated move, not a loss.)

Two things remain YOURS: (1) the COARSE net's two by-design blind spots — it
ignores any line under 24 chars and every `#` heading, so a fact carried only in a
short bullet or a heading can still be dropped or rewritten silently (this is the
documented issue-#91 shape, where a split condensed prose into shorter, WRONG path
bullets and nothing caught it); and (2) the one-sentence **lead** that makes C read
as one topic. Both are enforced only by the agent in step 8. No-information-lost is the editor's
first law; for the body, you are its only guardian.

## Why backlink redirect is the load-bearing step

THE LINK LAW: every `[[link]]` is bidirectional and must resolve. When you retire
B's slug, every page that linked `[[B]]` now dangles. The verifier treats that as a
content-loss-class failure (a broken graph), so the merge commit *cannot* pass
until every holder is already repointed. The redirect happens in each holder's OWN
PRIOR `--op repair` transaction (step 6) — never inside the merge transaction:
`verify_merge` proves knowledge preservation between the merge's SOURCES and
SURVIVOR only, so an unrelated holder edit riding inside the merge txn would be an
UNVERIFIED write inside a verified one, which is exactly what the one-write rule
(janitor#145) forbids. Cross-*scope* PROSE mentions (a USER note that says "see
the LOCAL keychain page" in prose, not as a `[[wikilink]]`) are NOT auto-edited —
those you grep and **surface** for a human, because rewriting prose across scopes
is a judgment call the editor doesn't make autonomously.

## Slug rules

A page's slug is its frontmatter `name:`, falling back to its filename stem
(`_slug_of` in the CLI). Two consequences:

- **Keep the survivor at A's path AND A's `name:`** — that way pages already
  linking `[[A]]` need no redirect; only `[[B]]` holders do. Fewest redirects =
  fewest chances to miss one.
- If you must rename the survivor's `name:`, you also break every `[[A]]` holder —
  redirect those too. Prefer not to rename during a merge.

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
   — in its OWN transaction, BEFORE the merge (janitor#145: the CLI enforces
   exactly one surviving write per merge; a holder cannot ride along).
6. **Repair the holder FIRST (its own transaction):**

   ```bash
   out=$(uv run "$CLI" begin "$LOCAL_MEM" repair "oauth-rotator-hub.md")
   TXN=…; STAGING=…
   # edit $STAGING/oauth-rotator-hub.md: replace [[rotator-version-skew]] -> [[rotator-429-deadlock]]
   uv run "$CLI" commit "$LOCAL_MEM" "$TXN" --op repair   # committed <id> (repair): 1 write(s), 0 delete(s)
   ```

7. **Then begin the merge, sources only:**

   ```bash
   out=$(uv run "$CLI" begin "$LOCAL_MEM" merge "rotator-429-deadlock.md" "rotator-version-skew.md")
   TXN=…; STAGING=…
   ```

   Edit copies under `$STAGING` — nothing else is staged:
   - overwrite `rotator-429-deadlock.md` with the merged page C: a one-sentence
     lead naming the subject, then both facets as `##` sections; both lesson sets
     unioned + deduped under one `## Notes and lessons learned`; `ocd: min(...)`,
     `lmd: 2026-06-19`; `name:` stays `rotator-429-deadlock`; no
     `[[rotator-version-skew]]` link remains.
   - `rm "$STAGING/rotator-version-skew.md"`.
8. **commit:** `uv run "$CLI" commit "$LOCAL_MEM" "$TXN" --op merge` → verify
   passes → `committed <id> (merge): 1 write(s), 1 delete(s)`. (1 write = C;
   1 delete = the retired source — the holder repair from step 6 already landed.)
9. **Reindex + report:** `memgrep reindex` if present (the index is memgrep's — do
   NOT touch `MEMORY.md`), report `merged rotator-version-skew → rotator-429-deadlock
   (4 lessons preserved, 1 backlink redirected, ocd=2026-05-30)`.

## Failure-path walkthrough (verify FAIL → bounded retry)

If step 8 prints `verify FAILED (merge); transaction aborted:` with
`dropped/reworded lesson(s): the config key was misread as max_attempts…`, you
reworded a lesson while folding it. The txn is already aborted (live tree intact).
Begin a **fresh** txn, copy the offending lesson body byte-identical this time, and
retry. After **3** such failures, `abort` any open txn, mutate nothing, and surface
`[janitor-memory] merge rotator-version-skew+rotator-429-deadlock abandoned after 3
verify failures: dropped/reworded lesson(s)` for a human.

## Bounds & safety recap

- ONE scope, ONE merge per pass. Default LOCAL+USER; PROJECT opt-in
  (`edit_project_scope`), staged-not-pushed.
- Kill-gate: `memory_txn.editor_enabled()` (janitor kill-switch +
  `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED`). `consolidation_per_day=0`
  disables the pass entirely.
- Per-scope flock + SHA-256 stale-snapshot guard live INSIDE `commit` — a
  concurrent writer either makes you lose the lock (exit 2 → abstain) or trips the
  stale-hash guard (abort) — you never overwrite a just-written fact.
- Crash-resumable: `resume <scope_root>` (next heartbeat) heals a half-applied
  swap; the completed `txn_id` is the idempotency key.

## Steps 6-10 — the executable sequence (moved from the SKILL body)

The exact command sequence for the transaction half of the merge. Moved here
verbatim from the SKILL body (TRDD-82OP4EN9 token-budget move); the body keeps
only the invariants.

### 6. Repair every holder FIRST — its own transaction, before the merge

janitor#145: the CLI enforces exactly ONE surviving write per merge, with no
exemption for a backlink holder — `commit --op merge` refuses outright
(`merge expects exactly ONE surviving page, found N write(s)`) the instant a
second write rides along. So each step-5 holder is repointed in its OWN
`--op repair` transaction, committed, and done BEFORE the merge even begins.
(A step-5 holder here counts the harness index file `MEMORY.md` too, whenever
it still points at a retired slug.)

```bash
for holder in <holder-rel-paths...>; do
  out=$(uv run "$CLI" begin "$MEMDIR" repair "$holder")
  TXN=$(echo "$out" | sed -n 's/^txn_id=//p')
  STAGING=$(echo "$out" | sed -n 's/^staging=//p')
  # edit $STAGING/$holder: replace [[B]] (and any [[A]] that should now read
  # [[C]]) with the survivor's slug — the ONLY change in this transaction.
  uv run "$CLI" commit "$MEMDIR" "$TXN" --op repair   # committed <id> (repair): 1 write(s), 0 delete(s)
done
```

`verify_merge`'s dangling-refs check (step 8) refuses the merge until NO live
page still links a retired slug, so holder-first is the only sequence that can
commit at all — and it means the corpus is never left, even between the repair
and merge commits, with a link pointing at a page that no longer exists.

### 7. Open the merge transaction — sources only

The survivor keeps A's slug by convention (fewest inbound redirects). Pass
**both sources** to `begin`; you'll overwrite A's staged copy with the merged
page and delete B's staged copy. Nothing else is staged:

```bash
out=$(uv run "$CLI" begin "$MEMDIR" merge "<A-rel-path>" "<B-rel-path>")
TXN=$(echo "$out" | sed -n 's/^txn_id=//p')
STAGING=$(echo "$out" | sed -n 's/^staging=//p')
```

Now edit **only files under `$STAGING`**:

- **Overwrite `$STAGING/<A-rel-path>`** with the merged page `C` (rules below).
- **Delete `$STAGING/<B-rel-path>`** (`rm` — this becomes the source-removal).

### 8. Build the merged page `C`

`verify_merge` (at `commit --op merge`) machine-checks lesson preservation, dedup,
and ocd/lmd — FAILS on any breach. Body-fact preservation and the opening lead are
YOUR responsibility; the verifier does not enforce them. Key constraints: every
`[^N]` lesson from both sources survives byte-identical; `ocd = min(A.ocd, B.ocd)`,
`lmd = today`; no duplicate content lines; open with a one-sentence lead; no
`[[link]]` to a retired slug; merge all `## See also` / `## Governed by` /
`## Applies to` edges (deduped); keep the survivor's slug in `name:`.

See [merge-page-rules](merge-page-rules.md) for the full rule breakdown
(what verify_merge enforces vs. what you must ensure, frontmatter shape).

### 9. Commit — the CLI verifies and applies atomically

```bash
uv run "$CLI" commit "$MEMDIR" "$TXN" --op merge
```

`commit` reconstructs the write/delete set by diffing staging vs the recorded
sources, runs `verify_merge` (lesson preservation, ocd/lmd, no-new-duplicates,
no-dangling-refs across the WHOLE scope — which is why every holder from step 6
must already be repaired and committed by now), and on PASS re-hashes the
sources (stale-snapshot guard), takes the per-scope flock, and applies
writes-before-deletes via `os.replace`. On PASS it prints
`committed <txn> (merge): 1 write(s), M delete(s)` and exits 0 — **done**. (Exactly
one write, always — `C`; `commit` REFUSES before any of this if a second write is
staged, per janitor#145.)

### 10. EXIT / retry / rollback

- **SUCCESS** = `commit` exited 0 (verify passed; LOCAL/USER applied on disk;
  PROJECT, if enabled, staged-not-pushed). `memgrep reindex` if present (the index
  is memgrep's — do NOT touch `MEMORY.md`). Report the one-line result.
- **verify FAILED** (exit 1) — the CLI already **aborted** the txn and left the
  live tree untouched. Read the printed reasons, fix C in a **fresh** transaction
  (begin again), and retry. **Bounded retry ≤ 3.** After 3 failures, `uv run
  "$CLI" abort "$MEMDIR" "$TXN"` (if a txn is still open), mutate NOTHING, and
  surface a finding: `[janitor-memory] merge <A>+<B> abandoned after 3 verify
  failures: <reasons>`.
- **Lock contention / stale source** (the CLI prints `error:` / exits 2) — another
  pass or a concurrent `/janitor-memory-write` is touching this scope. **Abstain**
  this cycle (the next heartbeat retries); do not force it.
- A half-applied crash is **self-healing**: the next heartbeat's
  `uv run "$CLI" resume "$MEMDIR"` rolls forward or discards the interrupted txn.

## Step 5 — discover the backlinks to redirect (THE LINK LAW, mandatory)

Moved out of `SKILL.md` on 2026-08-04 to keep that body inside the 5000-token skill budget.
Read this once you have a legal pair; steps 1-4 in the skill decide whether you do.

On merge A+B→C, every page that links `[[A]]` or `[[B]]` MUST be rewritten to
`[[C]]` — otherwise the corpus is left with dangling links and the commit-time
verify will FAIL. **Redirect each holder in its OWN prior `--op repair`
transaction, before the merge begins** (janitor#145 — see step 6: the CLI
enforces exactly one surviving write per merge, so a holder cannot ride along
in the merge transaction itself). Find the inbound links with `memgrep links
--from` (`--from NOTE` = NOTE's *backlinks* — who points AT it):

```bash
memgrep links --from "$A_SLUG" "$MEMDIR"   # pages linking [[A]]
memgrep links --from "$B_SLUG" "$MEMDIR"   # pages linking [[B]]
```

Note every holder page — you will repoint the link to the survivor `C` inside
that holder's own `--op repair` transaction (step 6). (Slug = the page's
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
`no_dangling_memory_md_refs()` is the matching check.
