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
`C`, written at A's path) and one-or-more deletes (B's copy removed). Two writes
for a merge is an error (`merge expects exactly ONE surviving page`). Backlink-
holder pages you also copied into staging and edited count as *additional* writes —
that is fine and expected (only the *merge sources* are constrained to one
survivor + the retired source(s); holder rewrites are ordinary writes).

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
| `dangling refs to retired slug(s): …` | some live page (C itself OR an `other`) still `[[links]]` a retired slug | redirect that backlink to C's slug in the SAME txn (copy the holder into staging, edit it) |

The dangling check unions C with EVERY other live page in the scope — so a missed
redirect *anywhere in the scope* is caught. This is why step 5 (discover backlinks
via `memgrep links --from`) and step 6 (copy holders into staging and repoint
them) are mandatory, not optional.

**What the catalog does NOT cover — body-fact loss + the lead are YOURS.** Every
failure above is machine-checked. Two page-quality rules are NOT: (1) a distinct
*body* fact dropped while reorganizing — the verifier guards lessons byte-identically
and forbids duplicate lines, but does not diff body facts (a strict body-superset
check would false-fail on every legitimate dedup), so a fact you silently drop is
gone forever; and (2) the one-sentence **lead** that makes C read as one topic.
Both are enforced only by the agent in step 7. No-information-lost is the editor's
first law; for the body, you are its only guardian.

## Why backlink redirect is the load-bearing step

THE LINK LAW: every `[[link]]` is bidirectional and must resolve. When you retire
B's slug, every page that linked `[[B]]` now dangles. The verifier treats that as a
content-loss-class failure (a broken graph), so the commit *cannot* pass until you
have repointed them. The redirect is done IN THE SAME TRANSACTION — copy each
holder page into the staging dir, replace `[[B]]` with the survivor's slug, let it
ride as an extra write. Cross-*scope* PROSE mentions (a USER note that says "see
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
   `oauth-rotator-hub` links `[[rotator-version-skew]]`. That holder must repoint.
6. **begin:**

   ```bash
   out=$(uv run "$CLI" begin "$LOCAL_MEM" merge "rotator-429-deadlock.md" "rotator-version-skew.md")
   TXN=…; STAGING=…
   cp "$LOCAL_MEM/oauth-rotator-hub.md" "$STAGING/oauth-rotator-hub.md"   # the holder
   ```

7. **Edit copies under $STAGING:**
   - overwrite `rotator-429-deadlock.md` with the merged page C: a one-sentence
     lead naming the subject, then both facets as `##` sections; both lesson sets
     unioned + deduped under one `## Notes and lessons learned`; `ocd: min(...)`,
     `lmd: 2026-06-19`; `name:` stays `rotator-429-deadlock`; no
     `[[rotator-version-skew]]` link remains.
   - `rm "$STAGING/rotator-version-skew.md"`.
   - in `oauth-rotator-hub.md`, replace `[[rotator-version-skew]]` →
     `[[rotator-429-deadlock]]`.
8. **commit:** `uv run "$CLI" commit "$LOCAL_MEM" "$TXN" --op merge` → verify
   passes → `committed <id> (merge): 2 write(s), 1 delete(s)`. (2 writes = C +
   the holder; 1 delete = the retired source.)
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
