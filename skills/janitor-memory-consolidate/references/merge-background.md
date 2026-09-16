# CONSOLIDATE (MERGE) executor — background: overview, posture, bounds, scope

Non-procedural context moved out of SKILL.md to keep its body under CPV's token
budget (TRDD verify pass, toc-embed-fix follow-up). The 9-step procedure itself
stays in SKILL.md; this file holds the WHY, the framing rationale, and the
boundary/idempotency contract.

## Table of contents

- Execution context and what this is
- Default posture — ABSTAIN unless certain
- Idempotency & bounds
- Scope of this skill

## Execution context and what this is

> **Execution context (TRDD-aebedbff):** the janitor dispatches this pass as a DEDICATED
> background **Sonnet** agent (`janitor-memory-subconscious-agent` — Sonnet, not Opus, per
> the USER cost decision 2026-06-30) — you ARE that agent. Run the whole pass here in your own
> context and return only a one-line result + the report path. A wikimem editorial pass is
> never run inline in a main session (it must not burden CPV or any other session's context).

The MERGE leg of the autonomous wikimem editor. It fuses two memory notes that
describe the **same subject** and **same type/tier** into one page, redirects every
`[[backlink]]`, and preserves all lessons + the oldest origin date — **without
losing a single fact**. `memory-librarian` only *surfaces* candidates; this skill
*performs* the merge through the journaled, hash-guarded **transaction core**
(`scripts/memory_txn_cli.py`).

Know the wiki data model before merging — tiers (hub/aspect/component), the link
law, page anatomy, lessons. The mechanics + worked walkthrough are in the
merge-protocol reference (Resources).

## Default posture — ABSTAIN unless certain

A merge is irreversible-feeling and destroys structure if wrong. The default is
to **do nothing**. Merge a pair ONLY when ALL of these hold; if ANY is in doubt,
**abstain** (leave both pages untouched and, if it looks like a real duplicate,
emit one `[janitor-memory] merge-candidate: <A> + <B> (abstained: <reason>)`
line for a human):

- **Same subject.** Both pages are about the *same element/aspect* — not merely
  sharing keywords (example: [merge-protocol.md](merge-protocol.md)).
- **Same type AND tier.** `is_legal_merge` passes — cross-tier, two-hub, and
  cross-type pairs are **refused**, see step 3.
- **Same scope.** Both pages live under the *same* scope root — cross-scope
  merges are never done (promotion is a deliberate human act).
- **No third page.** No OTHER live page in the scope is also about this subject
  (step 4) — a third would leave a fragment behind → abstain and surface it.

When uncertain about subject sameness, **abstain**. Over-merging is worse than a
missed merge.

## Idempotency & bounds

One scope, one merge per pass; re-running on a merged corpus is a no-op. Disable via
`consolidation_per_day=0`; the editor honors the global kill-switch.

## Scope of this skill

ONLY a same-subject, same-type **pair**, in ONE scope, through the transaction core. Not
page creation (`/janitor-memory-write`), single-page edits (`/janitor-memory-update`),
splitting (`/janitor-memory-split`), or contradictions (`/janitor-memory-conflict`). Never
edits a live page directly, never merges cross-scope or cross-type; LOCAL+USER by default
(PROJECT opt-in, staged-not-pushed).
