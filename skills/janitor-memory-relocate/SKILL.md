---
name: janitor-memory-relocate
description: 'RELOCATE executor — the duty-14 pass (TRDD-QDYQLM5V) that moves an OFF-TOPIC atom or page-level lesson to the page that owns its topic, or LINKS it and leaves it in place. MOVE versus LINK is a semantic judgment per candidate: if the general form of the lesson already exists on the methodology/owning page, LINK and leave; otherwise MOVE the whole atom via memgrep migrate-mem-atom (relocation, never deletion — the source retains a [[link]]). Runs on a [janitor-memory-relocate] marker, or "move this atom to the right page", "off-topic memory atom", "this lesson is parked on the wrong page".'
---

# Janitor memory — RELOCATE (move an off-topic atom to the page that owns its topic)

## What this is

A wikimem page exists ONLY to collect the atoms about the SAME topic. A general lesson parked
on a case page pollutes that page AND scatters the methodology. RELOCATE is the autonomous pass
that finds such atoms (memgrep's `lesson-uncited` lint finding is the candidate channel) and
either MOVES the atom to the page that owns its subject or — when the general form already
lives on the owning page — writes a `[[link]]` and leaves it.

**Never delete knowledge — relocate it.** A moved lesson leaves a `[[link]]` behind; nothing
is dropped, reworded, or lost. `migrate-mem-atom` is the only write verb for a MOVE.

## The claim step (run this FIRST, before reading any page)

**Use the `STATE_DIR` value passed INSIDE your spawn prompt.** Never resolve it from your own
cwd — your cwd is not the project root, and a self-resolved pool is the wrong project's pool.

```bash
export STATE_DIR=""   # paste the path from the STATE_DIR=<path> line of your spawn prompt between the quotes
: "${STATE_DIR:?janitor: STATE_DIR not provided by the spawn prompt}"
uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" --chore relocate --state-dir "$STATE_DIR"
```

`--chore` is not optional (janitor#275): without it the claim is FIFO-by-age and chore-BLIND,
so this agent would consume another chore's assignment. It prints the scheduler's pinned
`(intervention, scope, root)` (absolute paths) and hands it to you alone. Capture the
`CLAIM_ID=<id>` line — the CLOSE YOUR CLAIM block after it repeats the two close commands.

If it reports no claimable dispatch, STOP: that is a correct outcome, not an error. Write the
report line, close nothing, return.

## The candidate step (the scheduler's own predicate, never your own scan)

```bash
uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/memory_candidates_cli.py" \
  --intervention relocate --scope <scope-from-claim> --root <root-from-claim>
```

Each row is `(page#footnote, "lesson-uncited at :<line> — move or link")`. The CLI names the
page and the lint line as EVIDENCE; it deliberately does NOT guess the destination or the
move-vs-link verdict — that is your semantic judgment. An empty list is a correct abstain.

## MOVE versus LINK — the decision rule (both are legitimate outcomes)

For each candidate, read the lesson and ask the card's own test for off-topic: *is this true
only of THIS page's subject, or would it still be true of a completely different subject?*

- **LINK and leave** — when the general form of the lesson ALREADY exists on the
  methodology/owning page (search the owning page for the same rule before deciding). Wire
  the `[[link]]` with the memgrep link verb — a hand edit of a wikimem page is forbidden
  (only memgrep verbs may edit one, TRDD-XI10BA5D):
  `memgrep reference-mem-topic --page <page> --to <owning-page>` (wires the wikilink BOTH
  ways in one gated write; on a refusal or a stale-memgrep unknown-command, ABSTAIN and
  report the gap — never Edit/Write). Do NOT move.
- **MOVE** — when the general form does NOT yet exist elsewhere. FIRST resolve the
  destination (duty 15, TRDD-VIFQ1LKI): if the owning page does not exist yet, CREATE it
  (the section below), then run:

  ```bash
  memgrep migrate-mem-atom "<ATOM-ID>" --from <src-page.md> --to <dst-page.md> --leave-link
  ```

  The verb moves the whole atom, renumbers what it must, and leaves a `[[link]]` on the source.
  Never hand-edit the two pages around the verb.

## CREATE the destination page (duty 15, TRDD-VIFQ1LKI) — the MOVE else-branch

When the atom's topic has NO page yet, mint one so the MOVE has a target. Creation is the LAST
resort — a page whose subject is already covered under a different name is the near-synonym
failure duty 10 exists to undo.

1. **SURVEY all three roots first** (a single-root recall returns a confident empty
   indistinguishable from a real absence — measured twice, ATOM-W99A-N60G). Compose the roots
   into a bash ARRAY, never a joined string (an unquoted joined string is ONE bogus path and
   silently returns 0 results), then recall the topic by its SYMPTOM words:

   ```bash
   ROOTS=()
   ROOTS+=("<project-root>/.claude/project/memory")            # PROJECT — resolve via memory_scopes
   ROOTS+=("$HOME/.claude/projects/<project-slug>/memory")      # LOCAL — slug = pwd, non-alnum → '-'
   ROOTS+=("$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory")  # USER
   memgrep recall "<topic in symptom words>" "${ROOTS[@]}" --output full --no-notes
   ```

2. **HIT — any row whose line starts with a real `.md` path:** that page IS the destination,
   whatever its name. Mint nothing. Record in the report that the survey found it.
3. **GENUINELY EMPTY across all three roots:** mint through the write verb (never a hand
   scaffold), routing scope by what the ATOM carries — the atom's own scope decides; UNSURE →
   `local`. The `description:` is the new page's RECALL SURFACE: build it from SYMPTOM
   phrasings — the words a future session arrives with when the problem recurs (error text, the
   user's words) — NOT the topic's jargon, `/`-separated, at least 15 DISTINCT phrases:

   ```bash
   memgrep new-mem-topic --tier component --scope <local|private-project|public-project|user> \
     --name <kebab-topic-slug> --description "<symptom 1> / <symptom 2> / … / <symptom 15>" \
     --type reference
   ```

   The verb refuses to overwrite, validates the description floor, and writes atomically.
4. Then run the normal MOVE (above) with the minted page as `--to`.

If memgrep is missing, do NEITHER: no survey, no mint, no move — record a refusal instead.

If you cannot judge honestly (the lesson is ambiguous, or the better page is one of several),
do NOT guess. Record a refusal on that page so it stops re-surfacing:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_refusal_cli.py" record \
  --intervention relocate --scope "$SCOPE" --root "$SCOPE_ROOT" \
  --page <slug>.md --reason "<why the destination or verdict is not honestly decidable>"
```

The refusal is page-granular, re-arms when the page's bytes change, and expires after 7 days.

## Bounds

- One pass on the claimed scope only. The `relocate_per_day` cadence (default 1) already
  bounds frequency; do not loop the pass.
- The candidate list is capped by what lint reports — never widen it with your own lint run
  (`memgrep lint` disagrees with the precheck BY DESIGN, janitor#227).
- Do not relocate an atom whose placement was a DELIBERATE back-link decision (the corpus
  records those in prose); a refusal is the honest verdict there.

## Report

Write the report under `<main-repo>/reports/janitor-memory/<timestamp>-relocate.md`:
candidates seen, the verdict per candidate (move/link/refuse) and its evidence, pages touched,
and any refusals. Then close your claim (`complete --state-dir "$STATE_DIR" --chore relocate
--scope <scope>`) and return ONE line: what moved where, what linked, abstains — plus the
report path.
