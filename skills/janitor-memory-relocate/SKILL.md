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
  methodology/owning page (search the owning page for the same rule before deciding). Write a
  `[[link]]` on the source page pointing at the owning page. Do NOT move.
- **MOVE** — when the general form does NOT yet exist elsewhere. Run, through the transaction
  core per the consolidate skill's shape:

  ```bash
  memgrep migrate-mem-atom "<ATOM-ID>" --from <src-page.md> --to <dst-page.md> --leave-link
  ```

  The verb moves the whole atom, renumbers what it must, and leaves a `[[link]]` on the source.
  Never hand-edit the two pages around the verb.

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
