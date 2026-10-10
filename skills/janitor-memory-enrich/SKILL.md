---
name: janitor-memory-enrich
description: "ENRICH — the autonomous recall-surface backfill for the memory wiki. Fires on the bare [janitor-memory-enrich] heartbeat marker (or /janitor-memory-enrich). Finds wikimem pages whose keyphrases or page description are too thin or duplicated to be findable, and widens each IN PLACE through memgrep's gated write verbs, which prove no fact is lost. One of the eight wikimem-editor passes."
---

# Janitor memory — ENRICH (recall-surface backfill)

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Haiku** agent (`janitor-memory-subconscious-agent` — Haiku, not Opus, per
> the USER decision 2026-10-10) — you ARE that agent. Run the whole pass here in your own
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
2. **Never edit a page by hand.** Every page write goes through a memgrep write verb:
   atom `keywords:` → `update-mem-atom --keywords` (NEVER `--desc`: rule 3 below forbids
   the atom's `desc:`); page `description:` → `replace-mem-topic --page P --content-file F`
   (whole page). The gate lints, formats, validates and writes atomically — or refuses
   naming every violation. If the installed memgrep does not know a verb
   (unknown-command / usage refusal), ABSTAIN and report the gap — never fall back to
   Edit/Write or the txn core.
   Why there is no `--op enrich`:
   [enrich-background](references/enrich-background.md#why-there-is-no---op-enrich).
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

1. **Editor kill-switch.** If `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED=off` or the
   janitor kill-switch is present, do not mutate anything — that is your hard stop
   (the memgrep verbs do not consult the switch, so this check is where the user's
   emergency stop still bites). Then:

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

   Why a lint-backed list respects janitor#227:
   [enrich-background](references/enrich-background.md#why-lint-backed-candidates-respect-janitor227).

   Bound the run to the **top-K worst pages** (K ≈ 5).

## The defect checklist

For each candidate page, fix ONLY its enrich-class finding. TWO passes, in order:

**Pass 1 — mechanical fixes (run the fixer pipeline FIRST):** `memgrep lint
--apply-fixes <the claimed candidate page paths>` applies every registered Safe
fixer through the write gate, under the scope lock: `atom-keywords-duplicated`
(the same keyphrase twice) and `page-description-duplicated-phrases` (the same
description phrase twice) — duplicates are REMOVED, never padded to compensate.
A refused plan lands in the unfixed ledger and the page is left untouched by
that fix — on a refusal, hand-fix the duplicate through the write verbs (rule
2), or record it via memory_refusal_cli.py if the verb refuses too; re-lint,
and only what lint still reports is yours.

**Pass 2 — additive fixes (no fixer exists):**

| slug | what is wrong | what to do |
|---|---|---|
| `atom-keywords-too-few` | an atom/lesson carries < 10 distinct keyphrases | ADD the symptom phrasings for THAT atom's fact |
| `page-description-too-few-phrases` | page `description:` carries < 15 distinct `/`-separated phrases | ADD alternative phrasings of the page's SUBJECT |

**Verify:** a plain `memgrep lint` after the pass is the post-edit verifier —
run it on the claimed paths, never to DISCOVER candidates (issue #227).

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

## Verify, then move on

After each page, the gate's verdict IS the check: a verb refusal names every violation —
fix the scratch content and re-run (retry ≤3) or record the refusal below. A page that
still flags its enrich-class finding is not done. If the widening needed has no memgrep
verb, ABSTAIN and report the gap — never hand-edit the page.

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
