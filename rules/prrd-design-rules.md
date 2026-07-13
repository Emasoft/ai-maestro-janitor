<!-- ai-maestro-janitor:installed-rule — copied into your rules dir by the ai-maestro-janitor
     plugin. SAFE TO REMOVE if the plugin is uninstalled; removing it never affects any MEMORY
     store, only this rule file. -->

> [!IMPORTANT]
> **ai-maestro-janitor rule — INERT unless the janitor is active.** Check (cheap `$HOME` stats),
> where `DATA` = `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`:
> **UNINSTALLED** (`DATA` absent) → this file is an orphan the plugin could not remove: treat as
> INERT and tell the user they may delete it — but NEVER any MEMORY store, only this rule file, and
> only with their ok. **DISARMED** (`DATA/global-state/kill-switch.flag` or legacy
> `~/.claude/janitor-global-state/kill-switch.flag` exists) → the janitor is intentionally stopped:
> INERT this session. **ACTIVE** (otherwise) → apply the rule below.

# PRRD: Project Requirements & Rules Document

> **Layering note.** This is the UNIVERSAL BASE (IND) of the PRRD
> pillar. In a standalone project the USER owns golden rules and the
> project's own Claude may revise silver rules. When the project is a
> registered ai-maestro agent workdir, the server-installed overlay
> `aimaestro-prrd-governance.md` EXPANDS this base with the per-title
> authority matrix, `$AID_AUTH` enforcement, and COS-routed proposal
> queues — it never restates this base.

**Rule:** every project has exactly ONE authoritative rules document — the **PRRD** — at
`<project-root>/design/requirements/PRRD.md`, git-tracked and never gitignored. Every agent
that authors a TRDD, writes code, produces an artifact, or proposes a design decision in
that project MUST read the PRRD first and adhere to it. The PRRD is the project's
constitution; it overrides any general convention an agent would otherwise apply. There is
no substitute for it.

> **FULL REFERENCE (read on demand — do NOT paste it here):**
> `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/rules-reference/prrd-design-rules-full.md`
> It holds the complete file anatomy, the proposal-queue schema, the `get-prrd.py` /
> `prrd-edit.py` / `findprrd.py` command surfaces, the mirror (§0) discipline, the
> bootstrap + migration procedures, the grep cheat-sheet, and the anti-patterns. Read it
> when you need one of those. Everything below is normative on its own.

## The two tiers

- **🥇 GOLDEN — set by the USER, immutable to everyone else.** Not even the MANAGER may
  edit, add, delete, promote, or demote a golden rule. An agent that thinks one is wrong
  files a **proposal** and waits for the user.
- **🥈 SILVER — MANAGER-mutable.** The MANAGER may add/revise/delete/promote silver rules
  without user approval. Every other agent proposes; team-internal agents route their
  proposal through their CHIEF-OF-STAFF.

Both live as one flat bullet list per section in `PRRD.md`. No sub-sections, no nested
headings, no tables of rules.

## Rule identity — `<letter><number>.<version>`

```
- **G7.4** — <rule text, one rule per bullet>
- **S64.134** — <rule text>
```

| Piece | Meaning | Mutable? |
|---|---|---|
| **letter** `G`/`S` | current authority — golden or silver | YES — flips on promote/demote |
| **number** | globally unique id, **never reused** (even after deletion) | NO |
| **version** | edit counter, bumped on every text change | forward only |

**Numbers are unique across BOTH tiers** — `G7` and `S7` cannot coexist. Promote/demote
flips ONLY the letter; the number and version are unchanged (`S70.3` → `G70.3`). Editing
the text bumps only the version (`S70.3` → `S70.4`).

**This is the load-bearing invariant:** a citation by number always points at the same rule
regardless of the letter in front of it. Tools MUST accept the number alone and ignore any
G/S the caller supplied — the letter is for human readers, the number is for machines.

## Citation grammar

`PRRD G64.134` — space mandatory (that's what makes it greppable), letter written for the
human reader, version pinned. `PRRD G64` (no version) means "whatever rule 64 says now" —
a floating claim. Use the pinned form when the claim is about the rule as it exists today.

## Authority

| Actor | GOLDEN | SILVER |
|---|---|---|
| **USER** | edit/add/delete/promote/demote | yes |
| **MANAGER** | **NO** — may only forward the user's intent | add/revise/delete without user approval |
| every other agent | no | no — **propose** instead |

`prrd-edit.py` enforces this: a non-MANAGER silver edit is refused (`403 — propose via
COS`); a MANAGER golden edit is refused (`403 — golden rules are user-only`). Outside AI
Maestro (a solo project with no manager session) the human user IS the manager —
`prrd-edit.py --user` skips the check.

## Cross-reference with TRDDs

Every TRDD constrained by PRRD rules MUST cite them:
- **frontmatter** — `relevant-rules: [3, 27, 64.134]` (bare numbers; pinned versions ok),
- **body** — inline as `PRRD G64.134`.

A TRDD with no `relevant-rules:` claims to be unconstrained by any project rule. That is
possible but uncommon — verify it is genuine and not an oversight.

## Recommended baseline golden rule G1.1 — GitHub authorship self-identification

Every AI Maestro project's PRRD SHOULD carry this as its first golden rule: every agent
that writes to GitHub (issue, comment, PR, review, discussion, release note) MUST begin the
body with a one-line self-identification of which agent/role/plugin authored it, because
all AI Maestro agents share the single human-owner GitHub identity. Recommended line:
`_Posted by the Claude developing **<plugin-or-role>** (via the shared @owner gh auth)._`
Commits SHOULD carry an `Agent: <plugin-slug>` trailer. It is GOLDEN because it is an
anti-impersonation convention the MANAGER must not be able to weaken.

## Does NOT apply to

Plugin-level conventions (they live in the plugin's own docs), the general-purpose rules in
`~/.claude/rules/` (those apply across every project), one-off decisions captured in a TRDD
(they constrain only that TRDD's scope), or security frameworks the project merely consumes
(reference them **inside** a PRRD rule; don't paste the framework in).
