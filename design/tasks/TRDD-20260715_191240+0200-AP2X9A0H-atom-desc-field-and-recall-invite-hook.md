---
trdd-id: AP2X9A0H
title: Atom desc metadata field — required <=200-char prose summary shown in memgrep listings
column: backburner
created: 2026-07-15T19:12:40+0200
updated: 2026-07-15T19:55:48+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: major
labels: [wikimem, memgrep, memory-recall, hooks, token-economy]
relevant-rules: []
---

# Atom `desc` metadata field + proactive memgrep-recall invite on every user prompt

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**Two USER-directed improvements to the memory system (stated 2026-07-15), both motivated by a
concrete failure THIS session: I re-hit a trap ALREADY documented in `macos-keychain.md` (`[^2]`,
2026-07-09 — the L0-keepalive staged-closure/cache-vs-repo trap) because I did NOT recall it before
acting. The memory existed; nothing prompted me to read it. These two features close that gap.**

### Feature 1 — the `desc` atom metadata field (≤200 chars)

> **UPDATE 2026-07-15:** `desc` ALREADY EXISTS in the memory-write skill — but as an *optional
> ≤64-char snake_case slug*. This feature UPGRADES it to a *REQUIRED ≤200-char PROSE summary of the
> atom body*. **DONE this session:** `skills/janitor-memory-write/SKILL.md` updated (body-atom desc
> + lesson-form desc both now required ≤200-char prose; checklist synced) — commit follows. **STILL
> TODO:** (a) sync `skills/janitor-memory-write/references/atom-authoring.md` (the full schema still
> says ≤64 slug); (b) sync the subconscious agent's atomize/harvest procedures; (c) the memgrep Rust
> display of `desc` in `recall`/`find` LISTINGS (verify it shows the ≤200 summary, body-prefix
> fallback for legacy atoms). Items (a)-(c) need a publish+cache-update to deploy.

Every ATOM (both the `[^N]:` footnote-lesson form AND the `^id ⟦…⟧` block-property form) gains a
`desc` metadata key: a SHORT (max 200 chars) summary of that atom's body — the per-atom analogue of a
skill's `description`. WHY: `memgrep recall`/`find` today must show either just the page
`description` (too coarse — you can't tell WHICH atom matched) or the whole atom body (too many
tokens when many atoms match a query). The `desc` is the middle layer: when memgrep LISTS the atoms
matching a query, it prints each atom's `desc` (not its full body), so the agent can pick the ONE
atom worth reading in full — cutting recall token cost and improving hit precision.

- **Format:** add `desc:"<≤200-char summary>"` to the atom metadata block, e.g.
  `[^N]: [id:ATOM-…, status:valid, keywords:"…", desc:"<summary>", ocd:…, lmd:…] <body>`.
- **Skill change:** the memory-CREATION skills (`janitor-memory-write`, and the harvest/atomize
  procedures the subconscious agent loads) MUST instruct: write a ≤200-char `desc` that summarizes
  the atom body. Enforce the cap.
- **memgrep (Rust) change:** parse the `desc` key; in `recall`/`find` LISTINGS show `desc` per atom
  (fall back to a body-prefix when `desc` is absent, for legacy atoms). Full body only on the
  targeted read of a chosen atom.
- **Back-compat:** legacy atoms without `desc` still work (memgrep falls back). New/edited atoms get
  `desc`. No mass migration required; atoms gain `desc` as pages are touched.

### Feature 2 — SPLIT OUT to its own TRDD

The proactive memgrep-recall INVITE hook (a `UserPromptSubmit` nudge to search before acting) was
split into **TRDD-7B1THXTB** so each TRDD is one atomic task (per the USER's "a series of TRDD" +
the one-atomic-task rule). This TRDD now covers ONLY the `desc` atom field (Feature 1). The
subconscious-agent wikimem-maintenance duties the USER also specified are **TRDD-87RKBYJ8**.

## NEXT ACTION
1. DONE this session: `skills/janitor-memory-write/SKILL.md` now requires the ≤200-char prose `desc`
   on every body atom + `[^N]` lesson (committed 383ddac).
2. Sync `skills/janitor-memory-write/references/atom-authoring.md` (still says ≤64 slug) + the
   atomize/harvest procedures the subconscious agent loads (also covered by TRDD-87RKBYJ8 duty 2).
3. memgrep (Rust, `scripts/memgrep`): parse `desc`; show it in `recall`/`find` LISTINGS; body-prefix
   fallback for legacy atoms. Add a test.
4. Publish (the skill + memgrep binary live in the plugin → a release + cache update is required for
   them to take effect, per `macos-keychain.md [^2]` / TRDD-EQJPPZ2L: repo ≠ deployed).

## Verification
- A page's atoms each carry a ≤200-char `desc`; `memgrep recall "<symptom>" <dir>` LISTS atoms by
  their `desc`, not full body; a targeted read still returns the full body.
- On a fresh user prompt, the agent sees an invite to `memgrep recall` before acting (no specific
  memory named by the hook).
- `cargo test` (memgrep) + the plugin test suite green; publish gates green.

## Notes and lessons learned
