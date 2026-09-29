---
trdd-id: WFYJX2XU
title: Board-integrity repairs from issue 320 adjudication
column: backburner
status: tasked
created: 2026-09-29T15:34:39+0200
updated: 2026-09-29T15:40:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-29T15:34:39+0200
---

# Board-integrity repairs from issue 320 adjudication

## Symptom
ai-maestro-janitor#320 adjudicated 4 GRAPH-FALSE-COMPLETE findings (terminal-column cards with open children). Three need repairs; the carrier line on TRDD-XI10BA5D pointed them at the wrong sites.

## Repairs (each names the REAL edit site)
1. I6ZZWVDN (backburner, LIVE) — rewrite its citation of SLFMG704 (archived, terminal-frozen, untouchable) from open-obligation shape to provenance-citation shape. The parent is frozen; the child's body is the only legal edit site.
2. 2C8XFOW9 (blocked, LIVE) — rewrite its citation of EQ792YPX (archived, terminal-frozen) the same way: successor-work provenance, not an open obligation. If the false-complete WARN on the parent persists after the child-side fix, the validator's parent-side state needs the owner's call (carve-out or exception).
3. ULEGRT01 (ERROR-severity false-complete, open child TK1H3LSA) — adjudicate: read both cards, decide child-side provenance fix vs validator disposition; ERROR severity makes this the first repair.

## Proposed, awaiting owner (NOT decided here)
Linter carve-out: superseded parents tolerate open children (GRAPH-FALSE-COMPLETE should target complete/published only). Owner-tier; filed in the #320 comment.

## Carrier provenance
Discharges the ISSUE-320 REPAIR CARRIER line on TRDD-XI10BA5D (record-review REOPEN: that line dispatched work to terminal-frozen cards that will never be touched). This card owns the repairs; XI10BA5D's line gets rewritten to point here.
2026-09-29 mint-review discharge (fork HOLDS-with-findings, CURE-1/2/3): CURE-1 — FIRST step before any edit is to locate the validator's graph-edge source (the rule lives in the ~/.local/bin/trddgrep binary; its source repo was not located this session) and read which side of the edge it keys on: I6ZZWVDN's parent-trdd is ALREADY null yet the validator still names it as SLFMG704's child, so the edge is NOT child-frontmatter — rewriting the child's body citation may be cosmetic if the edge keys on the frozen parent's body (which also greps as containing the id); item (a) now carries the same fallback as (b)/(c) — child-side fix if the edge is child-keyed, owner question if parent-keyed. CURE-2 — backburner is deliberate (drift-eligible resurfacing is the safety net; do NOT mute it with review-after); the 'ERROR makes this the first repair' claim is softened to 'ERROR severity ranks it first WHEN WORKED'. CURE-3 — discharged: follow-up comment linking #320 to this card posted 2026-09-29.
2026-09-29 discharge-record review (HOLDS): CURE-1 corrected on #320 (ULEGRT01 is triaged-not-adjudicated; public drift fixed with one line); CURE-2 — the first step's discovery procedure is now named: strings on the trddgrep binary for the rule code + identify the owning repo (sibling-repo grep came up empty in the writing session; ask the ai-maestro peer if needed) — a pointer to a binary is not a pointer to source. NOTE-1: the issue close-condition is a declaration of linkage, not janitor-controlled — the owner or filer closes. Chain at its limit: WFYJX2XU's landing review is round 4; any further record here is one line, new content only.

## Approval log

- 2026-09-29T15:34:39+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
