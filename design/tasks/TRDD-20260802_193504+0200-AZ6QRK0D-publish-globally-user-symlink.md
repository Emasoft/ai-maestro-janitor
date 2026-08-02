---
trdd-id: AZ6QRK0D
title: Publish-globally pages get a real USER-scope symlink mechanism
column: blocked
pre-block-column: todo
created: 2026-08-02T19:35:04+0200
updated: 2026-08-02T23:36:00+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
created-by: 87RKBYJ8
external-refs: [52]
npt: []
eht: []
implementation-commits: []
---

# `published-globally` frontmatter value → a real USER-scope symlink

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-02

**BLOCKED — do NOT build (the #52 coordination the card mandated was done 2026-08-02
and it FORBIDS building this here).** The publishing verbs (`publish-sync` / `link`)
belong to the UPSTREAM memgrep engine roadmap — ai-maestro-plugin **TRDD-202ccfa2**,
tracked as **ai-maestro-plugin#18** — and the engine owner has not shipped them
(re-verified in #52's thread: memgrep 0.1.0, verbs absent; design-text-only upstream).
The janitor VENDORS `scripts/memgrep/`; a prior session's recorded ownership decision on
janitor#52 (correct, per `how-to-fix-issues-of-other-projects.md`) is that building
these verbs in the vendored copy would FORK the engine and pre-empt the owner's design.
The janitor's standing OFFER to implement them as a branch→PR on ai-maestro-plugin sits
on #18 awaiting the owner's go.

**Unblock condition:** ai-maestro-plugin#18 lands a released memgrep with the verbs (or
the owner accepts the PR offer) → re-sync the vendored copy → then wire this card's
janitor half (symlink lint + privacy-gate + skills/heartbeat wiring) in one pass.
**NEXT ACTION on unblock:** re-read janitor#52's last two comments (the held asks
1/2/4/5 land together with the wiring), then implement per the audit steps below.

**SUPERSEDED — do NOT carry forward:** "Not started. … Coordinate with issue #52 …
before building" (the coordination happened; its outcome is the block above).

---

Child 2 of 4 split out of TRDD-87RKBYJ8 (duty 21, second in the parent's own
priority order).

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
