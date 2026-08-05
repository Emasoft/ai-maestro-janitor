---
trdd-id: OR527LNW
title: PRRD G1.1's recommended byline contains a bare GitHub mention that pages a real org
column: complete
created: 2026-08-02T14:12:34+0200
updated: 2026-08-05T06:14:05+0200
current-owner: claude-ai-maestro-janitor
task-type: security
scope: project
severity: medium
approved: true
approved-by: user
approved-at: 2026-08-05T06:14:05+0200
implementation-commits: [93b6671e]
relevant-rules: [1.2, 11.1]
external-refs: [https://github.com/Emasoft/ai-maestro-janitor/issues/171]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**RESOLVED 2026-08-05. The USER decided in-session and authorized the edit; it landed in
`93b6671e`.** Nothing below needs doing — the rest of this card is kept as the record of why
the change was proposed rather than made, and it is worth reading for the template insight.

**What the USER chose**, which is neither of the two options this card offered: the token is
replaced with **"the gh CLI auth user name"** — no `@`, and no role-word that could later
become a real account either. `G1.1 → G1.2` exactly as predicted below.

**Plus a NEW golden rule the USER added at the same time — `G11.1`**: an agent may open issues
and comment ONLY on repositories owned by the current `gh` CLI auth account; writing anywhere
else needs explicit, per-case MANAGER authorization, permitted in exactly two situations (a
VERIFIED blocking bug, or an authorized ai-maestro USER collaborating on a MAESTRO-USER-owned
project). That generalizes this card's finding from *how a post is signed* to *where a post may
be made at all* — the deeper version of the same risk, since both stem from every agent sharing
one human GitHub identity.

The shipped `rules/prrd-design-rules.md` baseline was aligned to the same wording in the
follow-up commit, so the canonical rule and the rule the janitor installs cannot drift.

## The defect

`design/requirements/PRRD.md` line 29, golden rule **G1.1**, recommends this byline:

> Recommended leading line: _Posted by the Claude developing **<plugin-or-role>** (via the
> shared @owner gh auth)._

That handle is a **real GitHub organization** (reported on janitor#171 as having 58 followers,
unrelated to this project). Every agent that follows G1.1 literally pages it — on every repo,
in every issue, comment, PR and review. A concurrent session swept **27 live mentions** out of
three repos on 2026-08-02: 13 byline placeholders and 14 role-words used as addresses.

Unlike `<plugin-or-role>`, which reads as a placeholder and gets substituted, `@owner` does not
announce itself as one — so it is copied verbatim.

**In this PRRD the line is not even inside backticks**, so it is a live mention in a
git-tracked file, not merely a template that becomes one when copied.

## Why the shipped rule could be fixed but this cannot

The identical line in `rules/prrd-design-rules.md` — the *shipped* rule the janitor installs —
was fixed in `37a3b4c` (it now reads `via the shared repo-owner gh auth`). That file is plugin
content, not a golden rule, so the authority table permits it.

This one is G1.1 itself. Same text, different tier, different permission.

## The load-bearing insight, so the fix is not made too narrowly

**Backticks do NOT protect a TEMPLATE.** They make a literal inert *where it sits* — GitHub does
not linkify inside a code span — which is why `pre-bash-safety.check_outbound_publication`
correctly reads the shipped rule's backticked form as safe. But a template exists to be copied
OUT of its code span, and the backticks do not travel with it. Wrapping G1.1's byline in
backticks would therefore fix the file and NOT fix the harm.

The byline must contain no `@` at all.

## Proposed change (USER decides)

Replace the `@owner` token in G1.1's recommended line with plain words:

```
_Posted by the Claude developing **<plugin-or-role>** (via the shared repo-owner gh auth)._
```

Optionally add one clause to G1.1 stating the general rule, since the byline is not the only
place agents write these: *an `@word` outside a code span pages whoever holds that name; write
roles plainly and backtick any literal that must keep its `@`.* The full rule is the shipped
`~/.claude/rules/github-mentions.md`.

**Version handling:** this is a text change, so it bumps the version and keeps the number and
the letter — `G1.1 → G1.2`. The number never changes and promotion/demotion is not involved.

## Deliberately NOT done

- **The edit itself.** See the top of this card.
- **Rewriting the historical quote** at `design/proposals/TRDD-…-D1UKVNUY-cache-thrash-detector.md`
  line 56, which contains the old byline inside a block quote of a comment that was actually
  posted. That is a RECORD of what was published; editing it would falsify the record rather
  than fix anything, and it is not a template anybody copies.
- **Auditing whether the org was actually notified.** Reporting that would require paging it
  again to check, which is the harm itself. The fix is correct regardless of the count.
