---
trdd-id: AP2X9A0H
title: Atom desc metadata field + proactive memgrep-recall invite on every user prompt
column: backburner
created: 2026-07-15T19:12:40+0200
updated: 2026-07-15T19:12:40+0200
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

### Feature 2 — proactive memgrep-recall INVITE on every user prompt (for-now version)

A `UserPromptSubmit` hook injects, as `additionalContext`, a short INVITATION for the agent to
proactively `memgrep recall`/`find` for memories related to the user's prompt BEFORE acting. It does
**NOT** suggest specific memories — it only PROMPTS the agent to search itself (with keywords/phrases
derived from the prompt). This is the "for now" version.

- **Future (not this TRDD):** a more powerful Rust hook extracts keywords/keyphrases from the prompt
  PROGRAMMATICALLY and auto-suggests the most relevant ATOMS and whole-topic WIKIMEM PAGES. This TRDD
  ships only the invitation; the keyword-extraction+auto-suggest hook is a follow-up.
- **Existing surface to reconcile:** there is already an autorecall hook
  (`scripts/hooks/on-prompt-submit-autorecall.py`, issues #16/#45) that surfaces relevant notes by
  symptom. Decide whether Feature 2 is (a) a new invite-only hook, or (b) a mode/enhancement of the
  existing autorecall (the existing one already auto-surfaces; the user's ask is an INVITE, which is
  lighter). Prefer extending/aligning with the existing hook over adding a parallel one — audit it
  first (it already injects context each prompt, per the SessionStart memory breadcrumb).

## NEXT ACTION
1. Audit `on-prompt-submit-autorecall.py` — does it already inject an invite, or only auto-surface
   notes? Decide Feature-2 shape against it (extend vs new).
2. Spec the `desc` format in the memory-write skill + the atomize/harvest procedures; enforce ≤200.
3. memgrep (Rust, `scripts/memgrep`): parse `desc`; show it in `recall`/`find` listings; body-prefix
   fallback for legacy atoms. Add a test.
4. Ship Feature 2 (invite injection), aligned with the existing autorecall hook.
5. Publish (the skill + hook + memgrep binary live in the plugin → a release + cache update is
   required for them to take effect, per `macos-keychain.md [^2]` / TRDD-EQJPPZ2L: repo ≠ deployed).

## Verification
- A page's atoms each carry a ≤200-char `desc`; `memgrep recall "<symptom>" <dir>` LISTS atoms by
  their `desc`, not full body; a targeted read still returns the full body.
- On a fresh user prompt, the agent sees an invite to `memgrep recall` before acting (no specific
  memory named by the hook).
- `cargo test` (memgrep) + the plugin test suite green; publish gates green.

## Notes and lessons learned
