---
trdd-id: XFPOAF2I
title: Nothing detects two open cards attacking one defect without knowing about each other
column: todo
created: 2026-08-13T04:26:15+0200
updated: 2026-08-13T04:26:15+0200
current-owner: unassigned
task-type: feature
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-RG4IUZ6I, TRDD-3QIQ2E6J, janitor#241]
---

# Two cards, one defect, opposite fixes, and no way to notice

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Filed from a live near-miss, not a hypothetical.** TRDD-RG4IUZ6I and TRDD-3QIQ2E6J were filed
4 days apart for the SAME defect (janitor#241), quoting the SAME measurement (221,612 subagent
tokens / zero mutations), and **neither referenced the other**. They agree on one half of the fix
and **prescribe opposite things** on the other: RG4IUZ6I item 1 carries conflict refusals forward
onto split children; 3QIQ2E6J argues that exact move makes the refusal ledger assert verdicts
nobody reached. Building either card in isolation was a live possibility all week.

**It surfaced only because two titles happened to be read back to back** — that is luck, not
process, on a board of 113 open cards. `trdd-state-reconciliation` covers shipped-but-open, stale
blockers, dead symbols, blocked-without-blocker and idle WORK columns. **None of its checks can
see two cards that disagree with each other**, because every one of them judges a card against
the TREE, and this defect lives strictly BETWEEN cards.

## The signal is cheap, mechanical, and measurably non-empty TODAY

Measured 2026-08-13 on the open board — issue ids cited by more than one open card:

```
2 janitor#249 · 2 janitor#246 · 2 janitor#241 · 2 janitor#238 · 2 janitor#237
```

Five live candidate pairs, found with one `grep | sort | uniq -c` over `external-refs:`. Zero
model tokens (PRRD C2: a chore a script can do must be done by a script).

## The predicate — and the two ways to get it wrong

**Flag: a pair of OPEN cards sharing an `external-refs:` entry that do NOT reference each other.**

  - **Sharing a ref is NOT a contradiction** and must never be reported as one. Two cards can
    legitimately cite one issue — a parent and its derived task, a detector and its fix. The
    finding is *"these two may not know about each other"*, and the destination is a human read,
    not an automated merge. SURFACE-ONLY, like every other board check.
  - **Cross-referencing is the correct silencer.** Once each card names the other (frontmatter
    `external-refs:` or a `TRDD-<id8>` in the body), the pair drops out — the agents involved now
    know. This gives the detector a built-in self-test: the #241 pair was cross-linked at
    `854259d8`, so a correct implementation reports **four** pairs today, not five. If it still
    reports #241, the silencer is broken.

## Acceptance

- [ ] Fires on a synthetic pair sharing a ref with no cross-reference; silent once either card
      cites the other
- [ ] Run on the live board reports the four remaining pairs and NOT janitor#241 (the built-in
      self-test above — a run that still names #241 is a broken silencer, not a finding)
- [ ] Terminal/archived cards are excluded (a closed card cannot be re-litigated)
- [ ] Zero model tokens — the whole check is a script, and it names the pair rather than asking
      the model to go and compare the two cards

## Notes and lessons learned
