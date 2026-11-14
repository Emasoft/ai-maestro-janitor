---
trdd-id: 8MVESX28
title: Wikimem increment 2 one Rust page-layout parser and the issue 289 splice point
column: dev
status: tasked
created: 2026-11-15T00:13:22+0100
updated: 2026-11-15T00:13:22+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T00:13:22+0100
parent-trdd: F8EIVTSG
---

# Wikimem increment 2 one Rust page-layout parser and the issue 289 splice point

## STATE

NEXT ACTION: a research worker (2026-11-15) measures, per scope, pages with `## Superseded` above vs below the first link-section heading, reads where `## Superseded` is created (memory.rs:3160-3166, fixers/superseded_move.rs:88), and classifies the seven callers of the earliest boundary by what each inserts (atom, link section, Superseded section) and the insertion point each needs. With that table, write the increment-2 proposal (PROPOSAL FOR ACTION marker), then build.
Open design question: WM-NOTE-07 orders link sections, then Superseded, then Notes. With that order the trailing lint boundary (WM-NOTE-08) is the Notes heading alone on any page with a Superseded section, so an atom in a link section goes unflagged there. If the writers put Superseded above the links, either amend WM-NOTE-07's order or make the trailing walk skip Superseded (which changes lint verdicts and needs an exemption for atoms under it). Decide from the measurement.

## Scope (parent TRDD-F8EIVTSG, design D2 and D3, GitHub #289)

One Rust module owns the page layout. Rules from the advisor consult of 2026-11-15:
1. Increment 2 changes splice points, never a lint verdict: move `footer_section_line` and `footer_section_trailing_line` into the new module UNCHANGED, and add the layout boundary (earliest of the first link-section heading, `## Superseded`, the Notes heading) as a NEW function. Frontmatter skipping goes only into the new function. Python copy 3 (memory_content_precheck.py:697-755) stays until increment 3.
2. Each caller moves to the insertion point that fits what it inserts, per the research table; not all seven go to the layout boundary.
3. The two See-also implementations (mem_reference.rs add_see_also_entry, mem_split.rs ensure_see_also_link) stay for increment 4, where link-mem-topics replaces both; check then whether add_see_also_entry's no-op on a link anywhere on the page explains part of the 58 PROJECT and 141 USER one-sided typed edges.
4. Same commit keeps the spec true: re-tag the parts of WM-NOTE-10 that are not increment 2 (Python copy removal is increment 3, the second See-also implementation is increment 4); update WM-NOTE-08 file:lines and WM-NOTE-07's "Today" sentence when the functions move.
5. Tests (TDD exception, filtered cargo test only, check load first): port the 13 boundary cases at memory.rs:13868-13966 onto the new module; add #289 cases for plain new-mem-atom, merge-mem-topic and split-mem-topic, each with `## Superseded` above and below the link sections.
6. Ship: bump the memgrep crate version from 0.2.0; after `cargo install --path scripts/memgrep`, verify with the bare `memgrep` on a fixture copy, never on a live store.
Not blocking this increment, blocking increment 3: D12's 16 PROJECT placeholders vs the dry run's 28 linkless bullets.

## Approval log

- 2026-11-15T00:13:22+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
