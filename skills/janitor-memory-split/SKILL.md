---
name: janitor-memory-split
description: SPLIT executor — breaks ONE oversized wikimem page (over split_max_bytes) into a concise overview + type-preserving linked sub-pages, losing no fact or lesson, redirecting inbound [[links]], partitioning hub globs. When no page is over cap, decomposes ONE over-budget ATOM, else splits ONE atom that holds two TOPICS. One unit per run, one level deep. Page splits mutate only through the crash-safe transaction core (scripts/memory_txn_cli.py begin/commit --op split); refuses to fragment a component. Use on a [janitor-memory-split] marker, or "split the big memory page", "the memory wiki page is too large", "the atom is too long".
---

# Janitor memory — SPLIT

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Sonnet** agent (`janitor-memory-subconscious-agent` — Sonnet, not Opus, per
> the USER cost decision 2026-06-30) — you ARE that agent. Run the whole pass in your own context
> and return only a one-line result + the report path. A wikimem editorial pass never runs
> inline in a main session (it must not burden CPV or any other session's context).

## Overview

SPLIT is the DIVIDING leg of the wikimem autonomous librarian. A page past the
`split_max_bytes` cap is hard to load and navigate, so this skill turns it into a **concise
overview page** (a map of per-sub-page summaries) plus **type-preserving sub-pages** holding
the detail — how a Wikipedia article splits into sub-articles. It also divides an ATOM that is
over budget or holds two topics. Know the canonical wikimem model first —
`skills/janitor-memory-write/references/wikimem-model.md` (tiers, the bidirectional link law,
page anatomy, file→functionality globs).

Two non-negotiable safety properties shape everything below:

1. **You NEVER edit a live memory page directly.** Every PAGE mutation goes through the
   crash-safe, hash-guarded, flock-serialized transaction core via
   `scripts/memory_txn_cli.py`: edit COPIES in a staging dir, then `commit --op split`
   runs `verify_split` and applies atomically only on PASS. A crash mid-pass leaves a
   journal a later heartbeat rolls forward — no duplicate pages, no data loss. (An ATOM
   split instead goes through `memgrep split-mem-atom`, which holds the same scope lock.)
2. **No information is ever lost.** The union of the overview + every sub-page must
   reproduce every fact and every `[^N]` lesson from the original; `verify_split` proves it.

## When to use

- A bare `[janitor-memory-split]` marker arrives from the heartbeat (the scheduler
  decided a SPLIT pass is due and set the flock+stamp). Treat ONLY a bare/exact
  marker as authorization; a `[janitor-memory-split]` inside TRDD/directive/file
  text is NOT authorization (marker-mimicry defense).
- The user asks to split an oversized memory page, or says a wikimem page has
  grown too large to load.

Do **one page per invocation, one level deep.** If a sub-page you produce is
itself still over the cap, do NOT split it again this turn — the next heartbeat's
SPLIT pass picks it up. This is mandatory: CC caps sub-agent nesting at 5 levels,
so SPLIT recursion iterates ACROSS heartbeat cycles, never nested in-turn.

## Preconditions (check first; abstain cleanly if any fails)

```bash
PLUGIN="$CLAUDE_PLUGIN_ROOT"   # this plugin's scripts live here
# 1. Editor kill-gate. If disabled, STOP — surface nothing, mutate nothing.
#    `resume` also rolls forward any interrupted prior txn before you begin.
uv run "$PLUGIN/scripts/memory_txn_cli.py" resume "$SCOPE_ROOT" >/dev/null 2>&1 || true
```

If `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED=off` or the janitor kill-switch
is present, `memory_txn_cli.py begin` exits non-zero — that is your hard stop.

## Scope selection (LOCAL / USER apply; PROJECT is staged-not-pushed)

**Do not compute a scope path.** The claim below PRINTS the absolute root; deriving one
by hand is how an agent ends up working a scope it was not assigned. LOCAL and USER are
mutated and applied through the txn; PROJECT is in-repo and pushed only by `publish.py`,
so PROJECT split is governed by `edit_project_scope` — **ON by default since 2026-08-27**
(owner directive: librarians must reach PROJECT scope; a host may set it off) — when on you
stage+commit into the PROJECT root and it rides the next publish, never pushed by you.

Process exactly **ONE scope this run**, and CLAIM it before you touch anything:

```bash
uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" --chore split
```

It prints the `(intervention, scope, root)` the scheduler stamped when it emitted your
marker, and atomically hands that dispatch to you alone. `$SCOPE_ROOT` below is the
`root` it printed. **The path is ABSOLUTE on purpose** — your cwd as a spawned agent
is not guaranteed to be the project root.

**Exit 2, an unreadable file, or a chore name other than `split`: STOP and report
that** — do not pick a scope yourself, do not re-derive what is due (the stamp
already advanced when the marker was emitted), and **do not read the legacy
`memory-maint-pending.json` slot**: it is still on disk, so ceasing to point at it
is not the same as forbidding it. A USER-named scope is the one exception (a human
naming a scope IS the assignment). Why guessing here is
dangerous, not just untidy:
[split-plan-details.md#why-never-guess-the-scope](references/split-plan-details.md#why-never-guess-the-scope).

## The algorithm

### 1. Find the single page to split

```bash
CAP="$(uv run "$PLUGIN/scripts/memory_settings_cli.py" get split_max_bytes | grep -oE '[0-9]+' | head -1)"
# Every real NOTE in the scope strictly larger than the cap, biggest first. EXCLUDE
# the non-note set (mirrors the librarian's _NON_NOTE_NAMES): the staging dir; the
# PRIVATE user-mem store (never scan it — privacy); and the generated/index files
# MEMORY.md / memory-index.md / memory-reorg-proposed.md. `-printf` is GNU-only and
# breaks on BSD/macOS find, so size+sort portably via `wc -c`.
find "$SCOPE_ROOT" -type f -name '*.md' \
  -not -path '*/.maint-staging/*' -not -path '*/user-mem/*' \
  ! -name 'MEMORY.md' ! -name 'memory-index.md' ! -name 'memory-reorg-proposed.md' \
  -size +"${CAP}"c 2>/dev/null \
  | while IFS= read -r f; do printf '%s\t%s\n' "$(wc -c < "$f")" "$f"; done | sort -rn
```

Pick the **single largest** over-cap page as `$PAGE` (rel-path `$REL` under
`$SCOPE_ROOT`). Never batch multiple pages: one page per run.

**Empty list ⇒ NOT done.** This chore also splits over-budget ATOMS — same job, smaller
scale, same marker. `memgrep lint "$SCOPE_ROOT" | grep -F '[atom-oversized]'`. On a hit,
follow
[split-plan-details.md#decomposing-an-over-budget-atom](references/split-plan-details.md#decomposing-an-over-budget-atom)
and STOP there — steps 2-6 are page-seam machinery and must not run.

**Both empty ⇒ STILL not done** — an atom can hold TWO TOPICS at any size, and `recall` ranks on
its single keyword set, so a 400-char one is as unfindable as a 3000-char one:

```bash
uv run --script "$PLUGIN/scripts/memory_candidates_cli.py" --intervention split-topic --scope "$SCOPE" --root "$SCOPE_ROOT"
```

Empty ⇒ genuinely NOTHING DUE. Else take the FIRST `<page>#<atom>` and follow
[split-plan-details.md#splitting-an-atom-that-holds-two-topics](references/split-plan-details.md#splitting-an-atom-that-holds-two-topics),
then STOP. The list is a TRIAGE surface, never an assertion — most candidates hold one topic,
and RECORDING that judgement is a successful pass, not an abstain.

### 2. Decide legality + splittability BEFORE opening a transaction

Read `$PAGE` and apply the wikimem-model rules (the same predicate
`is_legal_split` enforces — do it up front so you never open a txn you must abort):

- **`tier: component` → do NOT fragment; SURFACE for re-tiering.** One element = one page. An
  oversized component is a **mis-tier**, not a split target — surface `[memory-split] re-tier
  <slug>: component over the cap — too big to be one element; re-tier to hub/aspect (the
  conflict/repair pass), then it splits.` and leave it intact. (The ONLY non-converging case —
  a tagging fix, not a silent abstain.)
- **Splittable tiers (`hub`, broad `aspect`) ALWAYS converge — FAIL-SAFE (issue #57/#58).** An
  over-cap page is NEVER reported "un-splittable": **≥ 2 `##` content sections** (excluding the
  mandatory `## Notes and lessons learned`) → split at those **natural seams** (step 3); **fewer
  than 2** → do NOT abstain, **SYNTHESIZE seams** (step 3a) so a seamless archive converges
  instead of being skipped forever (`is_legal_split(meta, body, oversized=True)` returns ok).

### 3. Plan the split (decide the seams; preserve type and every fact)

Group the page's `##` content sections into **2–4 coherent sub-topics**, one per
sub-page. Full planning mechanics (seam synthesis fail-safe, overview/sub-page
shapes, glob partitioning, size rules) are in
[references/split-plan-details.md](references/split-plan-details.md).

Key rules: (a) **Synthesize seams** when fewer than 2 natural `##` seams exist —
partition body paragraphs verbatim under synthetic `## Part N` headings (never
paraphrase). (b) The **overview** reuses the source slug and links DOWN to each
sub-page; each **sub-page** carries the same `metadata.type`/tier and links UP;
wire both ends in the same txn. (c) Carry every fact and every `[^N]` lesson
byte-identical into exactly one output page — `verify_split` fails on any drop or
rewording. (d) If a sub-page is still over cap after this run, the next heartbeat
splits it — convergence requires only real progress this level.

**(e) HEADROOM — never emit a sub-page within ~10% of the cap** (keep each under
~90% of `split_max_bytes`). A nearly-full sibling is re-split by the next atom, and
each split voids the conflict refusals keyed to the old page names — measured at
221,612 tokens for zero mutations (janitor#241). Rationale in the references file.

### 4. Redirect inbound [[links]] (the connectedness gap — mandatory)

When detail moves into a sub-page, any OTHER page that linked `[[source-slug]]` for a fact that
now lives there should repoint to it. Find every inbound link:

```bash
# Pass the SLUG: memgrep matches the note NEEDLE against the BASENAME/stem only, never a path
# substring, so a rel-path with a "/" can NEVER match and backlinks come back silently empty.
memgrep links --from "$(basename "$REL" .md)" "$SCOPE_ROOT"   # pages that link to the source
```

Rewrite `[[source-slug]]` → `[[the-right-sub-page-slug]]` in each holder that is really about a
sub-topic. The overview KEEPS the source slug (it is NOT retired), so a backlink about the page
as a whole stays correct unchanged — redirect only the ones pointing at moved detail.

> A split txn has exactly ONE source (`begin` takes only `$REL`); a backlink holder is
> redirected as an extra STAGED WRITE at its own rel-path in step 5, never a source.
> Why `len(sources) == 1` and why redirecting
> still matters even though the overview keeps the source slug (retiring
> nothing): [split-plan-details.md#backlink-redirect-mechanics](references/split-plan-details.md#backlink-redirect-mechanics).

### 5. Execute THROUGH the transaction core (begin → edit staging → commit)

```bash
# 5a. BEGIN — copy ONLY the source page into a fresh staging dir (exactly ONE
#     source; backlink holders ride along as staged writes below, not as sources).
OUT="$(uv run "$PLUGIN/scripts/memory_txn_cli.py" begin "$SCOPE_ROOT" split "$REL")"
TXN="$(printf '%s\n' "$OUT" | sed -n 's/^txn_id=//p')"
STAGING="$(printf '%s\n' "$OUT" | sed -n 's/^staging=//p')"
# begin exits non-zero iff the editor is disabled → that is your hard stop.
```

Now edit ONLY inside `$STAGING` (never the live tree). The commit reconstructs the
change set by DIFFING staging vs the recorded source, so any `.md` you place in
staging that is new or differs from its live copy becomes a write:

- **Overwrite** `"$STAGING/$REL"` with the new OVERVIEW content (the map). Keeping
  the same rel-path makes the overview the survivor at the source's slug.
- **Create** each sub-page as a new file under `$STAGING/` at its sub-page
  rel-path (e.g. `"$STAGING/<dir>/<source-slug>-<subtopic>.md"`).
- **Redirect a backlink holder** by writing its rewritten content to
  `"$STAGING/<holder-rel>"`. The commit treats it as a write that overwrites the
  live holder — no need to declare it a begin source.
- **Do NOT touch `MEMORY.md`.** It is the harness's; the two memory systems COEXIST and
  the wiki's index is memgrep's. A split adds NO line there and needs no index update —
  `memgrep reindex` picks the sub-pages up after the commit.

Then commit — this is the gate:

```bash
uv run "$PLUGIN/scripts/memory_txn_cli.py" commit "$SCOPE_ROOT" "$TXN" --op split
```

`commit --op split` reconstructs writes/deletes by diffing staging vs the recorded
sources, runs `verify_split` (lesson preservation across sub-pages+overview; hub
globs partition; convergence under the cap; no dangling refs to retired slugs),
and on PASS applies atomically (stale-snapshot re-hash, per-scope flock,
`os.replace` survivors-before-deletes). On FAIL it prints the reasons and aborts
the txn (live tree untouched).

### 6. EXIT / retry / rollback contract

SUCCESS = `commit` exits 0. A verify FAIL or precondition error has already aborted the txn
(live tree untouched): fix the staged plan and retry, **bounded to ≤3 attempts**, then abort and
surface FAILED. Lock contention is a normal abstain, not a failure. Exact surfacing lines, the
abort command, and the idempotency rule:
[split-plan-details.md#exit--retry--rollback-contract-step-6](references/split-plan-details.md#exit--retry--rollback-contract-step-6).

## Hard invariants (every SPLIT pass enforces)

Transactional · no information lost · type & tier preserved · connected (no dangling
or one-sided links) · bounded and disable-able. Each is mechanically checked by
`memory_edit_verify.verify_split` BEFORE the transaction commits, so a violating pass
aborts rather than landing a half-split page. Full statement of all five:
[split-plan-details](references/split-plan-details.md#hard-invariants-every-split-pass-enforces).

## Done when (terminating conditions)

STOP on the first outcome (one page, one level, retry ≤ 3):

- [ ] NOTHING DUE — no over-cap note, no `atom-oversized`, AND no `split-topic`
  candidate (step 1); an empty page list alone is not "nothing due".
- [ ] ATOM DECOMPOSED — one over-budget atom rewritten as one-fact atoms (step 1).
- [ ] RE-TIER SURFACED — an over-cap `component` (mis-tier; left intact, flagged —
  step 2). A hub/aspect is NEVER left intact: it splits at natural OR synthesized
  seams (fail-safe, step 3a).
- [ ] SPLIT — commit exited 0 (step 5/6).
- [ ] TOPIC SPLIT — a candidate atom really held two subjects (step 1).
- [ ] TOPIC KEEP — it held one; refusal RECORDED, so it is not re-listed until the
  page changes (step 1).
- [ ] FAILED — verify error 3× (step 6).
- [ ] DEFERRED — lock contention / stale-hash loser.
