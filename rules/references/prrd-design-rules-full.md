<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — CONDITIONAL on the janitor being active.** Check the janitor's
> state first (cheap `$HOME` existence checks), then act:
> - **UNINSTALLED** — if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` is
>   ABSENT, the plugin was uninstalled and this file is an ORPHAN it could not remove (Claude
>   Code does not clean a plugin's `~/.claude/rules/` or a project's `.claude/rules/` on
>   uninstall). Treat this rule as INERT, and tell the user it is an orphaned janitor rule they
>   may delete. NEVER delete any MEMORY store — only this rule file, and only with the user's ok.
> - **DISARMED** — else if `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/kill-switch.flag`
>   OR the legacy `~/.claude/janitor-global-state/kill-switch.flag` EXISTS (set by
>   `/janitor-global-disarm`), the janitor is intentionally stopped → treat this rule as INERT
>   this session.
> - **ACTIVE** — otherwise the janitor is running; apply the rule as written below.

# PRRD: Project Requirements & Rules Document

> **Layering note.** This is the UNIVERSAL BASE (IND) of the PRRD
> pillar. In a standalone project the USER owns golden rules and the
> project's own Claude may revise silver rules. When the project is a
> registered ai-maestro agent workdir, the server-installed overlay
> `aimaestro-prrd-governance.md` EXPANDS this base with the per-title
> authority matrix, `$AID_AUTH` enforcement, and COS-routed proposal
> queues — it never restates this base.

**Rule:** Every project has exactly ONE authoritative rules document — the
**PRRD** (Project Requirements & Rules Document) — at
`<project-root>/design/requirements/PRRD.md`. Every agent that authors a
TRDD, writes code, produces an artifact, or proposes a design decision in
that project MUST read the PRRD first and adhere to its rules. The PRRD is
the project's constitution; it overrides any general convention an agent
might otherwise apply.

There is NO substitute for the PRRD. Skills, personas, plugin rules, and
even this file describe **how PRRDs work**; the PRRD itself describes
**what is required of THIS project**.

## Location and shape

**Canonical path:** `<project-root>/design/requirements/PRRD.md`

- `design/requirements/` lives at the project root and is **git-tracked**.
- It MUST NOT be in the project's `.gitignore` — fix the gitignore if it is.
- There is exactly **one** PRRD.md per project. No per-team copies, no
  per-feature variants. Sub-project rules belong inside the single PRRD.

If `design/requirements/` does not exist, create it with `mkdir -p`
and author the initial PRRD on first project bootstrap.

## File anatomy

```markdown
---
prrd-version: 1.42                        # bumped on EVERY edit
updated: 2026-06-02T11:53:00+0200         # ISO 8601 + local TZ
project: my-project-name
canonical-source: design/requirements/PRRD.md
mirrors: []                               # paths of any read-only mirrors of this PRRD
---

# Project Requirements & Rules

<one-paragraph project description so the reader knows what the rules apply to>

## §0. Canonical source + copies

<the §0 mirror-index pattern — see "Mirror discipline" below>

## §I. How to read this document

- Rules are numbered globally across G and S sections (see "Rule identity").
- A citation `PRRD G7.3` means "rule 7, version 3, currently golden".
- A citation `PRRD S7.3` means "rule 7, version 3, currently silver".
- `G` and `S` are LIVE annotations — the rule's status at the moment of
  the citation. The same rule may later be promoted/demoted; lookups by
  number are stable across that change.

## 🥇 GOLDEN — set by the USER (immutable to any agent)

Golden rules CANNOT be changed by any agent. Only the USER can revise,
delete, promote, or demote a golden rule. An agent who thinks a golden
rule needs revision files a **proposal** (see "Proposal queue") and
waits for the user to decide.

- **G1.1** — <rule text, single sentence or short paragraph>
- **G3.2** — <rule text>
- **G7.4** — <rule text>
  Multi-line continuation indented under the bullet.

## 🥈 SILVER — revisable without USER approval

Silver rules can be changed by the project's Claude without user
approval (every revision is committed, so git is the audit trail). The
ai-maestro overlay narrows silver authority to specific titles and adds
proposal routing.

- **S2.4** — <rule text>
- **S4.1** — <rule text>
- **S64.134** — <rule text>
```

That is the whole format. No nested headings inside the GOLDEN / SILVER
sections, no sub-sections, no tables of rules. **One flat list per
section.** The numeric prefix is the rule's identity; the rest is text.

## Rule identity, versioning, and promote/demote

Every rule has three identity pieces, joined as `<letter><number>.<version>`:

| Piece | Meaning | Mutable? |
|---|---|---|
| **`<letter>`** — `G` or `S` | Current authority — golden (user-only) or silver (manager-mutable) | YES — flips on promote/demote |
| **`<number>`** | Globally unique identifier, never reused | NO — once assigned, immutable, even across deletion |
| **`<version>`** | Edit counter, increments on every text change | NO retroactive change — only forward bumps |

**Numbers are globally unique across G and S.** `G7` and `S7` cannot
coexist. Rule 7 is either golden OR silver at any moment; you can flip
the letter, but the number 7 belongs to exactly one rule. If rule 7 is
later deleted, the number 7 is **gone forever** — never reused.
Subsequent additions take the next free number.

**Versions are per-rule.** Editing the text of rule 70 (currently
`S70.3`) bumps it to `S70.4`. Editing it again bumps to `S70.5`.
Promoting it to golden makes it `G70.5` — **number and version
unchanged**, only the letter flips.

### Promote and demote — keep the identity, flip the letter

| Operation | Before | After | What changes |
|---|---|---|---|
| Edit (text revision) | `S70.3` | `S70.4` | Version bumps, letter unchanged |
| Promote (S → G) | `S70.3` | `G70.3` | Letter flips, number and version stay |
| Demote (G → S) | `G70.3` | `S70.3` | Letter flips, number and version stay |
| Delete | `S70.3` | — | Rule is removed from the file; number 70 retires forever |

This is the load-bearing invariant of the whole PRRD model: **a
citation by number always points at the same rule, regardless of the
letter currently in front of it.** A TRDD that cites `PRRD G70.3`
continues to be correct after rule 70 demotes to silver — the rule's
TEXT is unchanged; only its authority changed.

Tools that look up rules MUST accept the number alone (`70.3`,
`70`) and ignore any G/S the caller provided. The letter is for
HUMAN readers; the number is for MACHINES.

## Citation grammar

| Form | Meaning | When to use |
|---|---|---|
| `PRRD G64.134` | Rule 64, version 134, currently golden | Default — pins both the rule and its version |
| `PRRD S64.134` | Rule 64, version 134, currently silver | Same as above but for silver rules |
| `PRRD G64` | Rule 64, latest version, currently golden | When you want to follow future revisions automatically |
| `PRRD 64.134` | Rule 64, version 134, letter omitted | Acceptable but the canonical form keeps the letter for human reading |

**Space is mandatory.** `PRRD G64.134` — not `PRRDG64.134`, not
`PRRD-G64.134`. The space is what makes the citation greppable
(`grep -rn "PRRD G64" .`) without picking up false matches.

**Letter is mandatory in writing** (but ignored by lookup tools). The
agent writing the citation includes the letter to remind readers of the
rule's current authority. If the rule has been promoted/demoted since
the citation was written, the letter is stale but the lookup still
works because the number is the canonical ID.

**Versions are mandatory in writing** for pinned citations. A TRDD
that says "must comply with `PRRD G64.134`" is making a precise claim;
the same TRDD saying `PRRD G64` (no version) is saying "must comply
with whatever rule 64 currently says". Both forms are valid — choose
based on whether you want the claim pinned or floating.

## Mutation rules

| Actor | Can modify GOLDEN rules? | Can modify SILVER rules? |
|---|---|---|
| **USER** | YES — sole authority (edit, add, delete, promote, demote) | YES |
| **The project's Claude** | NO — proposals only | YES — add, revise, delete without USER approval |

`prrd-edit.py --user` trusts the local human user (the standalone mode).
The per-title authority matrix and its `$AID_AUTH` enforcement against
the ai-maestro server are defined by the overlay
(`aimaestro-prrd-governance.md`).

## Proposal queue

When an agent wants to suggest a PRRD change but lacks authority:

1. Agent writes a proposal file at
   `<project-root>/design/requirements/proposals/PROPOSAL-<YYYYMMDD_HHMMSS±HHMM>-<uid-first-8>-<slug>.md`.
2. Proposal frontmatter:

   ```yaml
   ---
   proposal-id: <uuid>
   proposes: revise            # add | revise | delete | promote | demote
   target-rule: 64.134         # bare number+version; null for new-rule proposals
   target-kind: silver         # silver | golden | either
   proposed-by: <agent-session-name>
   status: open                # open | accepted | rejected | superseded
   created: 2026-06-02T11:53:00+0200
   updated: 2026-06-02T11:53:00+0200
   ---
   ```

3. Proposal body: prose explaining the WHY, with the proposed new text
   in a fenced code block.
4. The USER reviews the proposal (the ai-maestro overlay inserts
   COS/MANAGER routing ahead of the USER when installed).
5. The USER decides:
   - **accept** → run `prrd-edit.py revise|add|delete|...`; proposal
     marked `accepted`.
   - **reject** → rationale recorded in the proposal body's
     `## Decision` section; proposal marked `rejected`.

Proposals are git-tracked. The proposal directory is **NEVER** purged —
it is the audit trail for who-asked-for-what-and-why.

## Scripts

Three first-class tools, shipped alongside this rule:

### `get-prrd.py` — read a rule

```bash
get-prrd.py 70.3          # text of rule 70 version 3
get-prrd.py 70            # text of rule 70 at latest version
get-prrd.py --cite 70.3   # formatted citation: "PRRD G70.3 — <text>" or "PRRD S70.3 — <text>"
get-prrd.py --list        # all rules, sorted by number, one per line
get-prrd.py --list --kind silver    # only silver
get-prrd.py --json 70.3   # JSON object: {number: 70, version: 3, kind: G, text: "..."}
```

**Letter (G/S) is ignored on input.** `get-prrd.py G70.3` and
`get-prrd.py S70.3` both look up rule 70.3 and return whatever's actually
there.

### `prrd-edit.py` — mutate the PRRD

```bash
prrd-edit.py add silver "rule text here"          # assigns next free number, version 1
prrd-edit.py add golden "rule text here"          # USER-only (or --user override)
prrd-edit.py revise 70 "new rule text"            # bumps S70.3 → S70.4 or G70.3 → G70.4
prrd-edit.py delete 70                            # removes rule 70; number retired forever
prrd-edit.py promote 70                           # S70 → G70 (USER-only)
prrd-edit.py demote 70                            # G70 → S70 (USER-only)
prrd-edit.py propose silver "text" --target 70    # writes to proposals/, does not touch PRRD
```

Every successful mutation bumps the PRRD's `prrd-version:` (semver-style
`major.minor` — major bumps for golden-rule changes, minor bumps for
silver-rule changes), updates `updated:`, and writes a git-friendly
single-line change. The PRRD is THE source of truth; git is its history.

### `findprrd.py` — search by metadata

```bash
findprrd.py --kind golden                    # all golden rules
findprrd.py --grep "credentials"             # all rules whose text matches
findprrd.py --cited-in design/tasks/*.md     # all rules cited by any TRDD
findprrd.py --unused                         # all rules NOT cited by any TRDD
findprrd.py --since 2026-05-01               # rules whose version was bumped since date
                                             # (requires consulting git log)
```

## Cross-reference with TRDDs

Every TRDD that depends on or is constrained by PRRD rules **MUST** cite
those rules:

1. **Frontmatter** — `relevant-rules: [3, 27, 64.134]` (bare numbers,
   pinned versions allowed). This lets `findtrdd.py --relevant-rule 64`
   find every TRDD that references the rule.
2. **Body** — inline citations as `PRRD G64.134` (or `PRRD S64.134`),
   exactly as written by the agent. The G/S in the body may go stale on
   promote/demote; the number does not.

A TRDD with NO `relevant-rules:` field is a TRDD that claims to be
unconstrained by any project rule. That's possible but uncommon —
the design pass verifies whether this is genuinely unconstrained or an
oversight.

## Mirror discipline (§0 pattern)

Borrowed from `team-governance/references/GOVERNANCE-RULES.md`. Every
PRRD that has read-only mirrors elsewhere (e.g. bundled into a plugin's
documentation, copied into a downstream tool's `--help` output) lists
those mirrors in its §0 section so a future editor knows the full sync
fan-out.

The mirror list lives in the file (not in a separate `MIRRORS.md`) so
nobody reads the rules without seeing the index:

```markdown
## §0. Canonical source + copies

| Path | Role | Update strategy |
|---|---|---|
| `design/requirements/PRRD.md` | **CANONICAL** | Edit first. Bump `prrd-version:`. Update `updated:`. |
| `<plugin>/skills/<skill>/references/PRRD-MIRROR.md` | Bundled mirror in plugin docs | Sync on every PRRD edit + plugin republish |
| `<external-repo>/docs/our-rules.md` | Copy in a downstream tool's docs | Sync on every PRRD edit + external-repo PR |
```

If `mirrors:` in the frontmatter is non-empty, mutation tools warn the
editor at the end of a successful edit:

```
prrd-edit.py revise 70 "..."
✓ Rule 70 revised: S70.3 → S70.4
⚠ Mirrors require sync:
    .../skills/example/references/PRRD-MIRROR.md
    .../docs/our-rules.md
```

## Bootstrap — projects without a PRRD

A project without a PRRD is a project without rules. To bootstrap:

```bash
mkdir -p design/requirements
get-prrd.py --init                    # creates a minimal PRRD with frontmatter only
                                      # the USER (or, for silver rules, the
                                      # project's Claude) then adds the first rules
```

The initial PRRD starts with prrd-version `0.1` (no rules yet). First
rule add bumps to `0.2`; first golden-rule add bumps to `1.0`.

## Grep cheat-sheet

```bash
# Every rule (canonical lookup)
grep -E "^- \*\*[GS][0-9]+\.[0-9]+\*\*" design/requirements/PRRD.md

# Every GOLDEN rule
grep -E "^- \*\*G[0-9]+\.[0-9]+\*\*" design/requirements/PRRD.md

# Every SILVER rule
grep -E "^- \*\*S[0-9]+\.[0-9]+\*\*" design/requirements/PRRD.md

# All TRDDs that cite rule 64 (in frontmatter)
grep -lE "^relevant-rules:.*\\b64\\b" design/tasks/*.md

# All TRDDs that cite rule 64 in body (any version)
grep -rlE "PRRD [GS]64(\\.|\\b)" design/tasks/

# All proposals open against rule 70
grep -lE "^target-rule: 70\\b" design/requirements/proposals/*.md

# Current PRRD version
grep "^prrd-version:" design/requirements/PRRD.md
```

## Anti-patterns

- **Numbering rules in clusters** (`64.1` for "auth rule 1", `64.2`
  for "auth rule 2"). The dot is the VERSION separator, not a topic
  hierarchy. Use plain bullets and let topics emerge from rule text.
- **Reusing a deleted rule number**. Number 64, once deleted, is gone.
  Adding a new rule about the same topic gets a fresh number. The
  previous number 64 lives only in git history.
- **Citing a rule without its version when the claim is pinned**.
  "This code follows `PRRD G64`" promises compliance with whatever rule
  64 currently says — if it's revised tomorrow, the claim auto-updates.
  If you mean "this code follows the rule as it existed today", write
  `PRRD G64.134`.
- **Quietly editing a golden rule under cover of a "minor
  clarification"**. Golden is golden. If the text is wrong, file a
  proposal and wait for the user.
- **Burying multiple rules in one bullet**. Each `- **<id>** — <text>`
  is exactly one rule. If you find yourself writing "and also ..." in
  a rule, split it into two rules.
- **Sub-sections inside GOLDEN or SILVER**. Don't. The flat list is the
  format. Numeric ordering plus the optional `findprrd.py --grep` is
  enough for navigation.

## Why this exists

- **Single source of truth.** Five scattered rule files = five places
  rules drift. One PRRD = one place to mutate.
- **Stable references.** A TRDD authored in May 2026 citing `PRRD G64.134`
  is still a valid citation in November 2027 — the rule's text may have
  been revised (bumping to `G64.140`) but `G64.134` is in git history
  and `findprrd.py` can resolve it.
- **Authority separation.** Golden vs Silver makes it explicit which
  rules can be iterated on without user friction. Without the split,
  the agent either gates everything on user approval (slow) or edits
  everything without approval (risk).
- **Audit trail.** Every mutation lives in `git log design/requirements/`.
  Every proposal lives in `design/requirements/proposals/`. The history
  is complete and reproducible.
- **Compliance is grepable.** "Does this TRDD comply with rule 27?"
  → `grep -E '^relevant-rules:.*\\b27\\b' design/tasks/TRDD-foo.md`. One
  command, no API call, no service round-trip.

## Does NOT apply to

- **Plugin-level conventions** (e.g. persona constraints, CPV
  validation thresholds, hook contracts). Those live in the plugin's
  own docs and skill files. PRRD is for **project-level** rules.
- **General-purpose CLAUDE-Code conventions** (e.g. the rules in
  `~/.claude/rules/`). Those apply across every project; PRRD applies
  only to the project that owns it.
- **One-off design decisions captured in TRDDs**. A decision made in
  TRDD-foo applies only to that TRDD's scope; it doesn't constrain
  future work. To promote a decision to a project-wide rule, file a
  proposal during the design column.
- **Security and compliance frameworks** that the project consumes
  (e.g. OWASP, CIS, GDPR). Reference them inside PRRD rules ("Rule S5:
  follow OWASP A01:2021 for authentication"), but don't paste the
  framework into the PRRD.

## Migration from no-PRRD projects

If a project currently has rules scattered across `CLAUDE.md`,
`README.md`, code comments, or other places:

1. Compile a single proposal listing each found rule and recommending
   Golden or Silver placement.
2. The USER decides Golden/Silver for each.
3. Run `prrd-edit.py add <kind> "<text>"` once per accepted rule, in
   order. Numbers are assigned automatically; the result is the initial
   PRRD.
4. The original rule locations are updated to cite the PRRD instead of
   restating the rule (`See PRRD G3.1` rather than the rule text), so
   future drift becomes impossible.

This migration is itself a TRDD with `task-type: docs` and
`relevant-rules: []` (since PRRD doesn't yet exist).
