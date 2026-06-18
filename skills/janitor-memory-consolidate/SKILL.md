---
name: janitor-memory-consolidate
description: CONSOLIDATE (MERGE) executor — fuses two duplicate memory notes about the SAME subject + same type into one page (dedup lessons, redirect backlinks, keep the oldest origin date), through the crash-safe transaction core, never editing a live page. ABSTAINS on uncertainty, cross-type/cross-scope/two-hub, or a third page sharing the subject. Use on a [janitor-memory-consolidate] marker, or "consolidate / merge / deduplicate the memory", "two notes cover the same thing", "fold these memory pages together".
---

# Janitor memory — CONSOLIDATE (MERGE executor)

## What this is

The MERGE leg of the autonomous wikimem editor. It finds two memory notes that
describe the **same subject** and are the **same type/tier**, fuses them into one
page, removes the redundancy, redirects every `[[backlink]]`, and preserves all
lessons + the oldest origin date — **without losing a single fact**. It is the
executor half of the librarian: the `memory-librarian` detector only *surfaces*
candidates; this skill *performs* the merge, but only through the journaled,
hash-guarded, flock-serialized **transaction core** (`scripts/memory_txn_cli.py`).

**THE ONE HARD RULE: never edit a live memory page directly.** Every change is
made to *copies* inside a staging dir that the CLI hands you; the CLI verifies the
result lost nothing and applies it atomically. If you `Edit` a file under a memory
root directly, you have broken the contract — undo it.

Know the wiki data model before merging — tiers (hub/aspect/component), the link
law, page anatomy, lessons. The mechanics + worked walkthrough are in the
merge-protocol reference (Resources).

## Default posture — ABSTAIN unless certain

A merge is irreversible-feeling and destroys structure if wrong. The default is
to **do nothing**. Merge a pair ONLY when ALL of these hold; if ANY is in doubt,
**abstain** (leave both pages untouched and, if it looks like a real duplicate,
emit one `[janitor-memory] merge-candidate: <A> + <B> (abstained: <reason>)`
line for a human):

- **Same subject.** Both pages are about the *same element/aspect* — not merely
  sharing keywords. (`reference` "keychain location" and `project` "rotator 429"
  share words but are different subjects → abstain.)
- **Same type AND tier.** `is_legal_merge` passes (same `metadata.tier`, both in
  {aspect, component}, same `metadata.type`). Cross-tier, two-hub, and cross-type
  pairs are **refused** — see step 3.
- **Same scope.** Both pages live under the *same* scope root. Cross-scope merges
  are never done (the transaction is per-scope; a LOCAL note and a USER note stay
  separate — promotion is a deliberate human act).
- **No third page.** No OTHER live page in the scope is also about this subject
  (the "no-third-page" check, step 4). If a third exists, the merge would leave a
  fragment behind → abstain and surface all three for a human.

When uncertain about subject sameness, **abstain**. Over-merging is worse than a
missed merge.

## Preconditions (cheap gate, run first)

```bash
JANITOR_ROOT="$(git -C "$CLAUDE_PLUGIN_ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$CLAUDE_PLUGIN_ROOT")"
CLI="$JANITOR_ROOT/scripts/memory_txn_cli.py"        # the transaction CLI you drive
# Kill-gate: respect the editor master switch + janitor kill-switch. If disabled,
# STOP (the CLI's `begin` also refuses, but check up front to avoid wasted work).
uv run --quiet - <<'PY' || { echo "wikimem editor disabled — abstain"; exit 0; }
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_txn
sys.exit(0 if memory_txn.editor_enabled() else 1)
PY
```

If a `[janitor-consolidate]` marker drove this turn, the scheduler already chose
ONE scope for this heartbeat and holds nothing you need — you pick the scope from
the marker context (LOCAL or USER). Do **one** scope, **one** merge per pass
(bounded; the next cycle handles the rest).

## Scope roots — and the PROJECT gate (default OFF)

```bash
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
USER_MEM="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory"  # janitor's FIXED data dir (hard-coded, NOT ${CLAUDE_PLUGIN_DATA})
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/project/memory"  # in-repo, PUSHED
```

**LOCAL and USER are the only scopes edited by default.** PROJECT memory is
in-repo and the pre-push hook blocks every pusher except `publish.py`; a routine
merge committing there would drift from origin. So PROJECT is **opt-in** — gated
by the `edit_project_scope` setting (default `False`). Even when enabled, a
PROJECT merge is **staged-not-pushed**: the atomic swap lands on disk, the commit
rides the *next* `publish.py`, never a standalone push. Confirm the gate before
touching PROJECT:

```bash
uv run --quiet - <<'PY'
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_settings
print("project-edit:", "ON" if memory_settings.get("edit_project_scope") else "OFF (skip PROJECT)")
PY
```

## The procedure

### 1. Narrow the candidate pair (recent-N → memgrep → read the small set)

Do NOT read the whole corpus. Start from the most-recently-modified notes (a fresh
duplicate is the common case), then narrow with memgrep:

```bash
MEMDIR="$LOCAL_MEM"   # or $USER_MEM — the ONE scope for this pass
# Most-recently-touched pages (the likely fresh dup), newest first:
memgrep recall "" "$MEMDIR" --sort lmd --top 12 2>/dev/null || \
  ls -t "$MEMDIR"/*.md 2>/dev/null | head -12
# For a recent page's apparent subject, find same-scope notes that overlap:
memgrep find "+<subject-term-1> +<subject-term-2>" "$MEMDIR" --top 8
```

Read ONLY the handful memgrep returns (their bodies + frontmatter). Pick at most
ONE pair `(A, B)` that looks like the same subject. If none is convincing,
abstain — that is success, not failure.

### 2. Decide subject sameness (the human judgment)

Read A and B fully. They are the same subject iff a reader would say "these two
pages are about the *same thing* and should be one page" — same element, same
aspect, same scope. Different facets of different things ⇒ abstain. Uncertain ⇒
abstain.

### 3. Legality gate — `is_legal_merge` (BEFORE you open a transaction)

`is_legal_merge` is **your** pre-flight check; the CLI's commit-time `verify_merge`
does NOT re-check legality. Run it on A's and B's frontmatter and refuse on a
`False`:

```bash
uv run --quiet - <<'PY'
import sys; sys.path.insert(0, "$JANITOR_ROOT/scripts/lib")
import memory_edit_verify as v
A = v.parse_frontmatter(open("$A_PATH").read())
B = v.parse_frontmatter(open("$B_PATH").read())
ok, why = v.is_legal_merge(A, B)
print("legal:" if ok else "REFUSE:", why)
sys.exit(0 if ok else 1)
PY
```

`is_legal_merge` refuses: cross-tier (`aspect` vs `component`), two `hub`s (a hub
is a functionality's overview, not a mergeable leaf), and cross-type (`project` vs
`reference`, etc.). On a refusal, abstain and surface a one-line note.

### 4. No-third-page check (pre-merge)

A merge fuses *exactly two* sources into one survivor. If a THIRD live page in the
scope is also about this subject, merging only A+B leaves a fragment — wrong. Grep
the scope for the subject and confirm only A and B match:

```bash
memgrep find "+<subject-term-1> +<subject-term-2>" "$MEMDIR" --top 10   # expect only A and B
```

If a third page appears, **abstain** and surface all three for a human (they may
need a different reshape). Never silently drop or ignore the third.

### 5. Discover backlinks to redirect (THE LINK LAW — mandatory)

On merge A+B→C, every page that links `[[A]]` or `[[B]]` MUST be rewritten to
`[[C]]` **in the same transaction** — otherwise the corpus is left with dangling
links and the commit-time verify will FAIL. Find the inbound links with
`memgrep links --from` (`--from NOTE` = NOTE's *backlinks* — who points AT it):

```bash
memgrep links --from "$A_SLUG" "$MEMDIR"   # pages linking [[A]]
memgrep links --from "$B_SLUG" "$MEMDIR"   # pages linking [[B]]
```

Note every holder page — you will edit its *staged copy* to repoint the link to
the survivor `C`. (Slug = the page's frontmatter `name:`, else its filename stem.)

Separately, **prose** mentions of the retired names across OTHER scopes are NOT
auto-edited — grep and **surface** them so a human can decide:

```bash
grep -rIl -- "$A_SLUG\|$B_SLUG" "$LOCAL_MEM" "$USER_MEM" "$PROJECT_MEM" 2>/dev/null
```

Report any cross-scope hits as `[janitor-memory] prose mentions of retired slug
<A>/<B> in <scope>: <files> (review)`. Do not edit other scopes.

### 6. Open the transaction (copies only — never the live tree)

The survivor keeps A's slug by convention (fewest inbound redirects). Pass **both
sources** to `begin`; you'll overwrite A's staged copy with the merged page and
delete B's staged copy:

```bash
out=$(uv run "$CLI" begin "$MEMDIR" merge "<A-rel-path>" "<B-rel-path>")
TXN=$(echo "$out" | sed -n 's/^txn_id=//p')
STAGING=$(echo "$out" | sed -n 's/^staging=//p')
# Plus the backlink-holder pages from step 5 — copy each into staging so you can
# repoint its [[A]]/[[B]] to [[C]] as part of THIS txn:
for holder in <holder-rel-paths...>; do cp "$MEMDIR/$holder" "$STAGING/$holder"; done
```

Now edit **only files under `$STAGING`**:

- **Overwrite `$STAGING/<A-rel-path>`** with the merged page `C` (rules below).
- **Delete `$STAGING/<B-rel-path>`** (`rm` — this becomes the source-removal).
- **In each holder copy under `$STAGING`,** replace every `[[B]]` (and any
  `[[A]]` that should now read `[[C]]`) with the survivor's slug. (If the survivor
  keeps A's slug, only `[[B]]`→`[[A]]` redirects are needed; holders already
  linking `[[A]]` are correct.)

### 7. Build the merged page `C` (the content rules verify_merge enforces)

`verify_merge` (run automatically by `commit --op merge`) will FAIL the txn unless
ALL hold — so build C to satisfy them:

- **Every `[^N]` lesson from BOTH A and B survives, byte-identical.** Copy each
  lesson's substantive body verbatim (you MAY compound — append later history —
  but never reword or drop; a substring check catches both). Keep each lesson's
  leading `[ocd:… lmd:…]` stamp unchanged.
- **Intra-page dedup — keep the better-sourced duplicate.** When A and B carry the
  *same* lesson/fact, keep the copy with the richer WHY / the citation / the
  newer `lmd` and drop the other — the result must contain **no duplicate content
  line** (a naive A+B union that re-introduces a duplicate FAILS
  `no_new_duplicate_lines`). Merging *removes* redundancy; it never adds it.
- **`ocd = min(A.ocd, B.ocd)`** (origin is never lost) and **`lmd = today`**
  (`date +%F`), and `lmd` must be ≥ both sources' `lmd`.
- **Subjects become sections.** Fold A's and B's bodies into one coherent page
  with their facets as `##` sections; keep one `## Notes and lessons learned`
  holding the union of both lesson sets (deduped).
- **No `[[link]]` to a retired slug** anywhere — C itself must not link `[[B]]`
  (the slug you're retiring), and the holder edits in step 6 cover the rest.

Keep the frontmatter shape (`name`, `description`, `ocd`, `lmd`, `metadata.{tier,
type,…}`); `name` stays the survivor's slug. Merge `## See also` / `## Governed
by` / `## Applies to` edges from both (deduped) so the link web stays intact.

### 8. Commit — the CLI verifies and applies atomically

```bash
uv run "$CLI" commit "$MEMDIR" "$TXN" --op merge
```

`commit` reconstructs the write/delete set by diffing staging vs the recorded
sources, runs `verify_merge` (lesson preservation, ocd/lmd, no-new-duplicates,
no-dangling-refs across the WHOLE scope), and on PASS re-hashes the sources
(stale-snapshot guard), takes the per-scope flock, and applies
writes-before-deletes via `os.replace`. On PASS it prints
`committed <txn> (merge): N write(s), M delete(s)` and exits 0 — **done**.

### 9. EXIT / retry / rollback

- **SUCCESS** = `commit` exited 0 (verify passed; LOCAL/USER applied on disk;
  PROJECT, if enabled, staged-not-pushed). Update the survivor's `MEMORY.md` index
  line and remove B's line. Report the one-line result.
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

## Idempotency & bounds

One scope, one merge per pass. Re-running on an already-merged corpus is a no-op
(the duplicate is gone, so no candidate pair is found). The candidate-set +
journal `txn_id` make a re-fire safe. Every per-day frequency is disable-able
(`consolidation_per_day=0`), and the editor honors the global kill-switch.

## Output

One line: the survivor page + retired page + "(N lessons preserved, M backlinks
redirected, ocd=<date>)" on success; or the abstain/refuse reason. Never echo full
page bodies into the conversation.

## Scope of this skill

ONLY consolidates a same-subject, same-type **pair** in ONE scope, through the
transaction core. It does NOT create pages (`/janitor-memory-write`), edit a
single page (`/janitor-memory-update`), split oversized pages
(`/janitor-memory-split`), or resolve contradictions (`/janitor-memory-conflict`).
It never edits a live page directly, never merges cross-scope or cross-type, and
defaults to LOCAL+USER (PROJECT opt-in, staged-not-pushed).

## Resources

- [merge-protocol](references/merge-protocol.md) — the worked walkthrough, the CLI
  two-phase contract, and the verify_merge failure catalog. Its sections:
  - The two-phase transaction contract
  - What is_legal_merge checks
  - What verify_merge enforces at commit
  - Why backlink redirect is the load-bearing step
  - Slug rules
  - Worked walkthrough
  - Failure-path walkthrough
  - Bounds & safety recap
- `~/.claude/rules/markdown-memory-recall.md` — the recall law + lessons
  conventions + the LOCAL/PROJECT/USER scope table.
