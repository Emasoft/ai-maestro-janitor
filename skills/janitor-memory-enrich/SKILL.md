---
name: janitor-memory-enrich
description: "ENRICH — the autonomous recall-surface backfill for the memory wiki. Fires on the bare [janitor-memory-enrich] heartbeat marker (or /janitor-memory-enrich). Finds wikimem pages whose keyphrases or page description are too thin or duplicated to be findable, and widens each IN PLACE through the transaction core, which proves no fact is lost. One of the eight wikimem-editor passes."
---

# Janitor memory — ENRICH (recall-surface backfill)

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Sonnet** agent (`janitor-memory-subconscious-agent` — Sonnet, not Opus, per
> the USER cost decision 2026-06-30) — you ARE that agent. Run the whole pass here in your own
> context and return only a one-line result + the report path.

## What this is

A memory is found from the SYMPTOM, not the answer. `memgrep recall` ranks on
`description + title + keywords` ONLY — never the body — so a page whose recall surface is
thin is, in practice, a page that does not exist: the fact is on disk and no future session
can reach it. ENRICH widens that surface. It adds the alternative phrasings a future session
will actually arrive with, and removes duplicates (a repeated phrase inflates the count
without adding a way to find the page).

It is **additive and metadata-only**. It never rewrites a fact, never touches a body, never
changes `ocd`, never merges/splits/deletes.

## THE IRON RULES

1. **No knowledge lost.** Every `[^N]` lesson and every fact survives byte-for-byte — the
   verifier proves it.
2. **Never edit a live page.** All edits happen on the STAGED copy; `commit --op repair`
   applies atomically under the per-scope flock + stale-snapshot guard.

   > There is deliberately **no `--op enrich`**. An enrich edit has the identical shape to a
   > repair — exactly ONE write at the page's own path, zero deletes — and `verify_repair`
   > already proves the four things enrich needs (every `[^N]` lesson survives, no
   > frontmatter key is dropped, `ocd` is unchanged, `lmd` does not regress). A second op
   > with the same verifier would be a second name for one guarantee, and the two would
   > drift.
3. **`keywords:` and page `description:` ONLY.** Never touch an atom's `desc:` — that field
   has a 200-char cap enforced by `memory_edit_verify`, so padding it hands `repair` a defect
   to undo and the two passes ping-pong on the same page forever.
4. **Infer, never invent.** Every phrase you add must be a way of ASKING for something the
   page already says. A phrase describing a fact the page does not contain is worse than a
   thin surface: it makes the page win a recall it cannot answer.
5. **`ocd` is immutable; `lmd` advances.**
6. **One scope per pass, top-K pages, bounded retry.**
7. **Forge-proof.** Act only on the bare/exact marker or an explicit request.

## Preconditions — verify BEFORE any work (any fail → one-line finding, stop)

1. **Editor enabled.** `uv run "$CLAUDE_PLUGIN_ROOT/scripts/memory_txn_cli.py" resume "<scope_root>"`
   first (rolls forward any interrupted txn). If kill-switched or
   `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED=off`, the CLI refuses — honor it.

2. **Scope — CLAIM it, never self-select or re-check `is_due`.**

   Your spawn prompt carries a `STATE_DIR=<path>` line; put that exact value into the
   `export` below before running the claim — the guard on the next line refuses to run
   without it.

   ```bash
   export STATE_DIR=""   # paste the path from the STATE_DIR=<path> line of your spawn prompt between the quotes
   : "${STATE_DIR:?janitor: STATE_DIR not provided by the spawn prompt}"
   uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" --chore enrich --state-dir "$STATE_DIR"
   ```

   It prints the `(intervention, scope, root)` the scheduler stamped for you (absolute path —
   your cwd as a spawned agent is not the project root). Capture the `CLAIM_ID=<id>`
   line (it follows the `(intervention, scope, root)` line; the CLOSE YOUR CLAIM block after
   it repeats the two close commands). Never read the legacy
   `memory-maint-pending.json` slot. A USER-named scope is the one exception.

   Three outcomes, and the middle one is easy to get wrong:

   | result | do |
   |---|---|
   | a `(intervention, scope, root)` naming `enrich` | proceed to step 3 |
   | **`no claimable dispatch` (exit 0)** | **STOP and report exactly that.** It is a NORMAL, correct outcome — no marker is pending — not an error and not a licence to pick a scope. Verified 2026-08-26 on a live host: the claim script exits **0**, so a check that keys only on a non-zero exit reads this as success and walks on with no scope. |
   | exit 2 (nothing claimable), unreadable output, or a chore name other than `enrich` | STOP and report that |
   | exit 3 (no memory-maintenance state at all — `$STATE_DIR` is wrong) | STOP and report that |
   | exit 4 (`$STATE_DIR` empty) | STOP and report that |
   | exit 5 (dispatch was recorded for a different state dir — claim refused) | STOP and report that |

3. **Candidate set — from the CLI, never your own counting.**

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_candidates_cli.py" \
     --intervention enrich --scope "$SCOPE" --root "$SCOPE_ROOT"
   #   → one line per candidate: <page-relative-path>\t<slug>[+<slug>...]
   ```

   **An EMPTY list is a correct, cheap abstain — report it and stop.**

   > **Why this does NOT contradict the janitor#227 rule.** Sibling skills say "run the
   > scheduler's predicate, NOT `memgrep lint`". Here the CLI *is* lint-backed, and that is
   > the same rule, not an exception to it: #227 is about the gate and the arbiter
   > DISAGREEING. These defects **are** lint rules — the thresholds, the phrase splitting and
   > the duplicate normalization all live in Rust — so deferring to lint is what makes gate
   > and arbiter identical here. Counting keyphrases yourself in Python would *create* the
   > #227 disagreement, not avoid it.

   Bound the run to the **top-K worst pages** (K ≈ 5).

## The two defect shapes

| slug | what is wrong | what to do |
|---|---|---|
| `atom-keywords-too-few` | an atom/lesson carries < 10 distinct keyphrases | ADD the symptom phrasings for THAT atom's fact |
| `page-description-too-few-phrases` | page `description:` carries < 15 distinct `/`-separated phrases | ADD alternative phrasings of the page's SUBJECT |
| `atom-keywords-duplicated` | the same keyphrase twice | REMOVE the duplicate — do not pad to compensate |
| `page-description-duplicated-phrases` | the same description phrase twice | REMOVE the duplicate |

## How to write a phrase that actually earns its place

Write what a future session will TYPE when it has the problem and not the answer — the error
text, the user's words, the symptom. Not the jargon of the fix.

- ✅ `the daemon keeps restarting every heartbeat` · `publish blocked` · `recall returned the wrong page`
- ❌ `singleton pid reconciliation` · `idempotent lease renewal` — nobody searches for the
  name of the solution; they search for what hurts.

Vary the SHAPE, not just the words: a question, a bare error fragment, a "why does X…", the
noun someone would guess. Two phrasings that differ only by a synonym are one phrase wearing
two hats — they pass the count and fail the reader.

**If you cannot honestly reach the floor** — the page genuinely has one narrow subject — do
NOT pad. Record a refusal on that page so it stops out-ranking pages that can be fixed:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_refusal_cli.py" record \
  --intervention enrich --scope "$SCOPE" --root "$SCOPE_ROOT" \
  --page <slug>.md --reason "<why the floor is not honestly reachable for this page>"
```

The refusal re-arms by itself when the page's bytes change, and after 7 days — a verdict with
an expiry, not a permanent silence. `--reason` is the deliverable: the next reader has to be
able to re-check it.

## Verify, then commit

After each page, the commit's post-edit verifier runs `memgrep lint`/`validate`. The page
must come back with its enrich-class findings GONE and no new finding of any class. A page
that still flags is not done — fix it or refuse it; never leave it half-widened. If the
widening needed has no path through the txn core or a memgrep verb, ABSTAIN and report the
gap — never hand-edit the live page.

## Report

One line + a report path under `reports/janitor-memory-enrich/`. Name the scope, pages
touched, phrases added, duplicates removed, and any refusals. End the report with
`<!-- janitor-outcome: mutation -->` (or `noop`).

## Close the claim (MANDATORY — a pass that returns without this leaves an orphaned claim)

`set-report` runs in the SAME Bash call that just wrote `$REPORT_FILE` (its vars are still
alive here); `complete` runs right after:

```bash
uv run --script --quiet "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" set-report --state-dir "$STATE_DIR" "$REPORT_FILE"
uv run --script --quiet "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" complete --state-dir "$STATE_DIR"
```

If `complete` exits 2 saying more than one claim is in flight, re-run it adding `--chore enrich
--scope <the scope your claim step printed>`. Unclosed, it expires as MEMPASS-STALE-CLAIM after
6h and re-dispatches.
