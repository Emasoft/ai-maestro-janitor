---
trdd-id: 98ISATJZ
title: Memory-system discoverability — own the design (janitor#62)
column: published
created: 2026-07-09T14:53:03+0200
updated: 2026-08-02T07:05:00+0200
current-owner: janitor-dev
assignee: janitor-dev
priority: 4
severity: LOW
effort: M
labels: [memory, discoverability, wikimem, coordination]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: pull-request
target-branch: main
test-requirements: [unit]
review-requirements: [human-review]
runtime-targets: [macos, linux]
impacts: []
implementation-commits: [b92e388]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/62", "Emasoft/ai-maestro-plugin:TRDD-202ccfa2"]
---

# Memory-system discoverability — own the design (janitor#62)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-11

**Origin:** janitor#62 (coordination, from ai-maestro-plugin core) asked the
**janitor** — as the memory-system owner — to OWN the discoverability design:
decide which surface(s) to strengthen so a fresh session/new Claude discovers
(a) that the 3-scope wikimem exists, (b) what's in it here + globally, (c) how
to navigate it. #62 is the standalone split of complaint A; complaint B
(cross-project reach) is #52 + ai-maestro-plugin TRDD-202ccfa2 (whose Phase 3
is filed as this coordination). This TRDD IS the design deliverable #62 asked
for.

**2026-07-11 — PHASE 1 IMPLEMENTED (S1 + S2). Built inline, no NPT children:**
each surface was one lib + one wiring point, so splitting them into child TRDDs
would have cost more than the work.

**S1 (autorecall) — was ALREADY DONE in code; the MANIFEST was lying.** The hook
already composes all three scopes (LOCAL → PROJECT → USER, deduped,
most-specific-first) and already defaults ON (issue #45). But `plugin.json` still
declared `"default": false`, titled the option "(OPT-IN)", and described it as
searching only THIS project's corpus — for seven releases. Claude Code does **not**
export a userConfig default into the hook env (verified empirically: autorecall
fires in live sessions with no user config set), so the code default governed and
the feature really was on — but every user reading the manifest, and the config UI
rendering it, was told the opposite, and the opt-OUT was undiscoverable.
`post_mcp_sanitizer_enabled` had the identical drift (ON in code, `false` +
"(OPT-IN)" in the manifest). Both manifests are now truthful.

**S2 (SessionStart breadcrumb) — BUILT.** `scripts/lib/memory_breadcrumb.py` +
one wiring point in `on-session-start.py`. ONE line at session start: per-scope
note counts + the `memgrep overview <dir>` entry point (live on this project:
*"Memory corpus: 39 local + 17 project + 41 user-global notes"*). Printed BEFORE
the global-stop early-return on purpose — memory works while the heartbeat is
disarmed, so a stopped machine must still get its corpus pointer. **Counts only,
never note content**: a PROJECT-scope page is untrusted git input, and this line
lands in the session PREFIX, so there is deliberately no interpolation slot a
poisoned note could ride. Silent when every scope is empty. Opt out with
`memory_breadcrumb=false`.

**Ratchet (the real deliverable of the S1 finding):**
`test_no_boolean_option_manifest_default_contradicts_its_code_default` scans every
`CLAUDE_PLUGIN_OPTION_*` boolean read in `scripts/` and asserts its code default
equals the manifest default — 25 options checked, so this drift class cannot recur.

**NEXT ACTION:** none for Phase 1. **S3 stays BLOCKED on #52** (ai-maestro-plugin
must ship the memgrep `publish-sync`/`link` engine first — do NOT build it here);
it will be its own TRDD when that engine lands. Post the Phase-1 result to #62.

### 2026-08-02 — CLOSED (`dev → published`)

The card's own NEXT ACTION was *"none for Phase 1 … Post the Phase-1 result to #62"*, and that
post happened on **2026-07-16** — the janitor's Claude commented on #62 naming the four shipped
surfaces and **closed the issue as ADDRESSED** (verified against the live issue, not from memory:
`gh issue view 62` → `CLOSED 2026-07-16T01:15:50Z`). The deliverable this card exists for — OWN
the discoverability design, and land Phase 1 — is complete, and the requester considered it
answered 17 days ago. It has sat in `dev` since.

**Implementation verified, not assumed.** `b92e388` (breadcrumb lib + the two manifest-default
corrections + the ratchet test) is contained in tag `ai-maestro-janitor--v0.45.0`, so this is a
released card; `implementation-commits:` was empty and is now recorded, which is what let the
reconciler read this as unshipped work in progress.

**About the "S3 stays BLOCKED on #52" line — that is the prose/frontmatter mismatch, and the
frontmatter was right.** S3 is not held work on THIS card: the same paragraph already rules that
*"it will be its own TRDD when that engine lands"*, and rule 13 is one atomic task per card. #52
is still OPEN and lives in another repo (ai-maestro-plugin must ship the memgrep
`publish-sync`/`link` engine first), so making this card `blocked` on it would park a delivered
design behind an external dependency it does not own, indefinitely. The blocked language describes
a FUTURE card's precondition, not this one's state — which is exactly the trap of writing a
sibling's status into a card's STATE block.

`release-via: publish` and the work is in a released tag ⇒ terminal column is **`published`**, not
`completed` (TRDD rule 12 — published archives AS ITSELF, or the fact that it shipped is erased).

**Coupling / do-NOT-duplicate:** S3 (published-note discovery) couples to #52 —
it cannot ship until ai-maestro-plugin's memgrep `publish-sync`/`link` engine
(TRDD-202ccfa2) exists (verified 2026-07-09: those verbs are unimplemented in
BOTH the canonical ai-maestro-plugin source AND the janitor's vendored
`scripts/memgrep/` — they live only in the ai-maestro-plugin design TRDD). Do
not build the engine here.

## The problem (from #62)

The 3-scope wikimem (LOCAL / PROJECT / USER · `memgrep` recall-by-symptom ·
the hub/aspect/component model) is powerful, but knowledge is stranded unless
the agent already knows to look. Four gaps:

1. **Recall-before-acting is easy to skip.** It lives in a rule
   (`markdown-memory-recall.md`); the only push-surface is the heartbeat/prompt
   auto-recall hint. There is no task-scoped "did you recall for THIS?" nudge.
2. **No one-shot "what do I have?" entry.** Seeing the corpus requires already
   knowing `memgrep`. A fresh agent has no breadcrumb to the overview page.
3. **Cross-project / USER-scope notes are invisible until queried** — and this
   widens once `publish-globally` (#52) ships.
4. **Adoption is uneven** — the proactive contract is per-`CLAUDE.md`; projects
   without it get no nudge.

## The existing surfaces (landscape)

| Surface | What it is | Where |
|---|---|---|
| **auto-recall hint** | UserPromptSubmit hook injecting `[janitor-memory] Possibly-relevant notes …` by symptom | `scripts/hooks/on-prompt-submit-autorecall.py` (issue #16, **opt-in**) |
| recall rule | the proactive "recall before acting" contract + scope model | `~/.claude/rules/markdown-memory-recall.md` (janitor-shipped) |
| MEMORY.md stub | deprecation stub pointing at `memgrep` | per-scope `MEMORY.md` |
| overview page | `<project>-overview.md` navigation page | `memgrep overview <memdir>` |
| per-CLAUDE.md contract | the "PROACTIVE MEMORY CONTRACT" where projects adopt it | project `CLAUDE.md` |

The **auto-recall hint is by far the strongest surface** — it pushes notes by
symptom without the agent asking (this design doc's own session saw it fire).
So the highest-leverage design decisions are about IT.

## The design — 3 surfaces (S1/S2 janitor-owned; S3 couples to #52)

### S1 — Strengthen the auto-recall hint (highest leverage; janitor-owned)
The push-surface that already works; make it fire precisely, on all corpora,
for everyone.
- **All 3 scopes:** confirm the hook queries LOCAL + PROJECT + USER roots (per
  the recall protocol), not just one. Audit `on-prompt-submit-autorecall.py`
  against `memory_scopes.resolve_scope_dirs()`.
- **Precision/cadence:** fire on substantive prompts; suppress on trivial/
  one-word turns (it is time-agnostic today — driven per-prompt, which is
  correct; the tuning is relevance-threshold, not cadence).
- **Adoption (gap 4):** it is currently OPT-IN (issue #16). DECISION NEEDED —
  make it default-on (with an opt-out env), or document the enable path
  prominently in the shipped rule so every project gets the push. Leaning
  default-on with opt-out, mirroring the other default-on janitor hooks.

### S2 — Session-start breadcrumb to `memgrep overview` (janitor-owned)
Addresses gaps 2+3 (the "what do I have?" entry) WITHOUT the agent needing to
know `memgrep`.
- A SessionStart hook line (or an addition to the existing
  `on-session-start-trdd-state.py` surfacing) that, when a project/LOCAL/USER
  memdir has ≥1 note, emits a one-line breadcrumb: *"This project has N memory
  notes (+M USER-global). Navigate: `memgrep overview <memdir>`; they also
  auto-surface by symptom."*
- Zero-cost, fires once per session, points at the overview page — the missing
  first breadcrumb.

### S3 — Published-note discovery (couples to #52 — BLOCKED on the engine)
Once `publish-globally` ships, globally-visible PROJECT notes need a DISCOVERY
path, not just a recall path. Design the surface now so it is ready:
- The S2 breadcrumb's "+M USER-global" count already includes published notes
  (via the machine-local `published/<slug>/` symlinks the engine will create).
- No janitor code until ai-maestro-plugin's engine (TRDD-202ccfa2) lands; then
  wire S3 in the same pass as the #52 janitor-side asks.

## Phased plan
- **Phase 1 (now, janitor-owned, no external dep):** ratify S1 + S2. Spawn NPT
  children: (a) audit+strengthen `on-prompt-submit-autorecall.py` (S1), (b)
  the SessionStart overview breadcrumb (S2). Both `test-requirements: [unit]`.
- **Phase 2 (blocked on #52):** S3 published-note discovery, wired with the
  #52 janitor-side asks when the engine ships.

## Cooperation
- **ai-maestro-plugin** owns the memgrep engine (TRDD-202ccfa2) + hosts the
  canonical `scripts/memgrep/`; the janitor vendors it. S3 waits for their
  engine; the janitor offers to wire its half the moment the verbs land.
- This design is posted back to janitor#62 as the "owned design"; #62 stays
  open as the tracking issue until S1+S2 ship.

## Notes and lessons learned
