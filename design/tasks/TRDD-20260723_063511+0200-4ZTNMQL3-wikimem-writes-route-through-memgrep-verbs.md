---
trdd-id: 4ZTNMQL3
title: Every wikimem write must route through a memgrep write verb, then validate+lint
column: complete
created: 2026-07-23T06:35:11+0200
updated: 2026-08-02T06:34:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: high
relevant-rules: [1]
eht: [WN7M829Y]
implementation-commits: [ebd7445, 33a1f7f]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-23

**CORE SHIPPED.** All five of the user's bullets are met by a RULE + an enforcement GATE (the
user offered "improve the skills OR convert them to rules" — I did the rule + the gate):

- **RULE (`ebd7445`)** — `rules/markdown-memory-recall.md` gains an `## AUTHORING` section (the
  global SSOT every agent reads at USER scope): route every write through a memgrep verb
  (`new-page`/`add-atom`/`add-lesson`/`migrate`); correcting a wrong fact is a SUPERSESSION via
  `add-lesson --supersedes` (embeds `SUPERSEDED BODY:`, same atom id — never a `-v2` duplicate),
  never a delete/overwrite; run `memgrep validate <page> && memgrep lint <page>` after EVERY edit.
- **GATE (`33a1f7f`)** — `memory_txn_cli.py commit` runs a DELTA authoring-integrity gate after
  `verify_*`: counts the 4 memgrep-lint authoring classes on before(live) vs after(staged) and
  BLOCKS the 3 unambiguous classes when the count INCREASES (delta → a page's pre-existing
  violation never blocks an unrelated edit); oversized only warns; link-law/required-field noise
  filtered; fail-OPEN. So a hand-edit in ANY editorial pass can no longer COMMIT a new malformed atom.

**ROOT CAUSE (verified):** the write verbs already synthesise valid syntax; the malformed atoms
came from the EDITORIAL passes hand-editing staged markdown (gated only by `verify_*`, which proves
no knowledge lost, NOT syntax). The gate closes that hole; the rule supplies the discipline.

**OPTIONAL REMAINING (not blocking):** add an operational pointer to the editorial `SKILL.md`
files ("correct a wrong fact via `add-lesson --supersedes`, never overwrite"). Low marginal value
now the rule is global. This TRDD can reach `complete` once that call is made.

### 2026-08-02 — CALL MADE: decline the optional pointer. CLOSED.

The card asked for exactly one judgment and then blocked on it, so it sat in `testing` for
10 days waiting for a decision nobody was scheduled to make. Making it: **declined.**

`~/.claude/rules/markdown-memory-recall.md` already carries the instruction verbatim under
AUTHORING — *"Do NOT hand-author wikimem markdown … use the write verbs … Correct a wrong
fact by SUPERSESSION, never a delete/overwrite"* — and that rule is installed at USER scope,
so it loads in every session on this machine regardless of which skill is invoked. Copying it
into each editorial `SKILL.md` would create a second place stating the same contract, i.e. a
place for it to drift out of step with the rule that actually governs. The global rule is the
single source of truth; the skills should keep pointing at it, not restate it.

Nothing else is outstanding: the gate shipped (`ebd7445`, `33a1f7f`) and the rule is global.
Closing `testing → complete`; `release-via:` is absent, so `complete` is the terminal column.

## The defect

Skills author wikimem content as raw markdown strings. A human (or Sonnet agent) writing
`^name [desc: value, keywords: …]` by hand omits the quotes on `desc:` (breaks grep and the
in-body filter), writes a `[^N]` lesson header with no prose body (`memgrep find --only-notes`
then returns nothing), and lets an atom grow past a readable size — exactly the three defects
seen in the wild.

## The fix (this TRDD's scope)

1. **Route every write through a verb.** No skill emits atom/lesson/page markdown by hand.
   - new page → `memgrep new-page`
   - new atom → `memgrep add-atom` (stores `desc` QUOTED, ≤200 chars, id/dates synthesised)
   - new lesson → `memgrep add-lesson` (anchors `[^N]` from the atom body)
   Hand-editing is reserved for in-place REPAIR of an existing page's prose, and even then the
   atom/lesson SYNTAX must match what the verbs emit.
2. **Validate + lint after EVERY change.** Each editorial step ends with
   `memgrep validate <page> && memgrep lint <page>`; a non-zero exit blocks the transaction.
3. **Proactively invite the CLI.** The skill prose tells the agent to recall/add/update via
   memgrep (`recall`, `add-atom`, `add-lesson`, `links`, `atom`) rather than reaching for
   Read/Grep/Edit on the raw page first.
4. **Pick the right SCOPE before writing.** The skill runs the write-gate question ("would
   this be true+useful for a stranger who clones the repo on another machine?") and routes
   LOCAL / PROJECT / USER accordingly — unsure → LOCAL.

Whether this ships as tightened SKILLS or as a new RULE under `~/.claude/rules/` is a
plan-mode decision; the enforcement content is identical either way.

## Verification

- Grep the memory skills: zero hand-emitted `^<name> [desc:` / `[^N]:` string literals remain
  (except documented examples inside code fences).
- A dry-run of each skill ends in a `memgrep validate && memgrep lint` invocation.
- Authoring a fresh atom via the tightened `write` skill produces a page that lints clean with
  a quoted `desc` and a body-bearing lesson.

## Notes and lessons learned
