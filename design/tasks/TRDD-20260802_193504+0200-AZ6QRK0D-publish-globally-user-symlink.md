---
trdd-id: AZ6QRK0D
title: Publish-globally pages get a real USER-scope symlink mechanism
column: todo
created: 2026-08-02T19:35:04+0200
updated: 2026-08-02T19:35:04+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
created-by: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
---

# `published-globally` frontmatter value → a real USER-scope symlink

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Child 2 of 4 split out of TRDD-87RKBYJ8 (duty 21, second in the parent's own
priority order). Coordinate with issue **#52**'s cross-project design before building.

## The ask (parent duty 21 — the publishing half is MISSING)

A page whose frontmatter carries the `published-globally` value must be **symlinked at
USER scope** so every project's recall sees it. Scope classification + privacy direction
already exist (`memory.rs::scope_layer`, cross-scope lint, `memory-scope-leak` detector);
what does NOT exist is the publishing executor.

## Verified facts (2026-08-02 audit, spot-checked)

- The symlink appears ONLY as a test fixture
  (`memory.rs:7027-7051`, `lint_does_not_report_one_file_twice_when_reached_by_two_paths` —
  proves the linter TOLERATES a symlink; nothing CREATES one).
- No `publish` subcommand exists in `main.rs` (grep: zero hits).

## Smallest shippable step (audit recommendation)

A `memgrep publish-globally <page>` subcommand that creates/refreshes the USER-root symlink,
plus the inverse (unpublish), plus lint enforcement that a `published-globally` page without
its symlink (or an orphaned symlink) is flagged. Respect the memory-scope-leak direction:
publishing must run the privacy scan first — a page with machine-private content REFUSES.

## Verification

- Round-trip: mark a page `published-globally` → publish → visible in USER-scope recall from a
  different project root → unpublish → gone; lint flags the inconsistent states.
- A page with an absolute `$HOME` path refuses to publish (privacy gate).

## Notes and lessons learned
