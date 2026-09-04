---
trdd-id: 3BQM5GH7
title: design cards gate the publish even though markdownlintignore excludes them
column: todo
created: 2026-09-04T10:03:19+0200
updated: 2026-09-04T10:03:19+0200
current-owner: ai-maestro-janitor-08
task-type: infra
scope: project
project-id: ai-maestro-janitor
relevant-rules: [how-to-fix-issues-of-other-projects]
external-refs: [/tmp/pub.txt]
---

# design cards gate the publish even though markdownlintignore excludes them

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-04

**NEXT ACTION:** decide between the two candidate fixes in "Options" below. Both
require a decision that is not the janitor's to make alone — one changes what
gates this repo's publish, the other files an issue on a different project.

**Nothing is broken right now.** `design/` currently lints clean, so the next
publish will not trip on this. The card exists because the *next* card
containing a markdown table will, and because the mechanism is undiagnosed.

**Not yet done:** the CPV issue is NOT filed. The five candidate mechanisms are
NOT distinguished.

## Symptom

`uv run scripts/publish.py --patch` exited 4 at stage `[4/11] Validating plugin
(remote CPV)`:

```
! NIT issues found - blocked by --strict
SUMMARY: CRITICAL=0 MAJOR=0 MINOR=0 NIT=3 WARNING=47
```

All three NITs were `MD056/table-column-count` at 563:86, 564:84, 565:29 of
`design/tasks/TRDD-…-8BXMNQ4T-verified-actuation-blocks-the-single-threaded-daemon-beat.md`
(`/tmp/pub.txt` lines 404–406). Fixed by one blank line in commit `d4e5f055`.

## The mismatch

`.markdownlintignore` at the repo root lists `design/`, with this comment:

> Internal / ephemeral markdown that is NOT shipped plugin content — exclude from
> markdownlint so design notes don't gate the publish like distributed docs do.

So the repo's stated intent is that design cards **do not** gate the publish.
They do. All 436 `.md` files under `design/` are in CPV's stage-4 markdownlint
scope, and any one of them can block a release on a NIT.

`.mega-linter.yml` does not close the gap either: its `FILTER_REGEX_EXCLUDE`
lists `tests_dev/ docs_dev/ scripts_dev/ …` but **not** `design/`, and the only
markdown-specific key is `MARKDOWN_MARKDOWNLINT_FILTER_REGEX_EXCLUDE:
'CHANGELOG\.md'`.

## Mechanism — NOT diagnosed, five candidates

An earlier draft of `d4e5f055`'s commit message asserted "CPV does not honor
`.markdownlintignore`". That claim is **not established** and is the accusatory
reading of the evidence. What is observed is only that CPV lints `design/`
despite the ignore file listing it.

The strongest hint points at the mildest explanation. CPV's output reads:

```
[NIT] markdownlint: ../../../../../../../Users/emanuelesabetta/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/design/tasks/…
```

Seven `../` before the repo path means CPV runs from a working directory seven
levels below — a `uvx`/venv temp dir, not the repo root. `markdownlint-cli`
discovers `.markdownlintignore` **in its own cwd**, not in an ancestor of the
files it is given. So the likeliest mechanism is that the ignore file is never
discovered, not that it is disregarded.

| # | candidate mechanism | would produce identical output? | ruled out? |
|---|---|---|---|
| 1 | CPV runs from a different cwd, finds no ignore file | yes | no — and the `../../../` prefix is direct evidence FOR it |
| 2 | CPV passes an explicit `-p` / `--config` | yes | no |
| 3 | CPV uses markdownlint as a LIBRARY (no CLI ignore-file logic at all) | yes | no — and the `[NIT] markdownlint:` prefix is CPV's own formatting, weak evidence for this |
| 4 | CPV lints a temp checkout or extracted tarball | yes | no |
| 5 | CPV reads the file and deliberately disregards it | yes | no |

Five hypotheses, one observation, zero discrimination. Diagnosing this is the
first task on the card, because it decides which of the two options below is
even applicable.

## Options (a decision is required — do not pick one unilaterally)

1. **Repo-side.** Express the exclusion somewhere CPV *does* read — most likely
   adding `design/` to `.mega-linter.yml`'s `FILTER_REGEX_EXCLUDE`. One line,
   but it **changes what gates this repo's publish**, which is a governance
   change dressed as a lint tweak. Needs sign-off, not a drive-by edit.
2. **Upstream.** File an issue on `Emasoft/claude-plugins-validation` (CPV is a
   DIFFERENT project — per `how-to-fix-issues-of-other-projects`, never edit its
   tree from here; issue first, PR only if asked). The reproducer is already in
   hand: `/tmp/pub.txt` lines 404–406 plus this repo's `.markdownlintignore`.

These are not exclusive — 2 is right regardless if the mechanism turns out to be
CPV-side, and 1 is a local mitigation either way.

## Acceptance criteria

- [ ] The mechanism is narrowed to one of the five candidates, with evidence.
- [ ] A decision is recorded here on option 1, option 2, or both.
- [ ] If option 2: the CPV issue is filed and its URL recorded in `external-refs:`.
- [ ] A publish runs green with a deliberately-malformed table in a `design/`
      card, OR the card records that design cards are intended to gate after all
      and `.markdownlintignore` should drop the `design/` line instead.

## Notes and lessons learned

The last acceptance box matters more than it looks: the mismatch could equally
be resolved by deciding the ignore file is wrong. Nobody has established which
side of the mismatch expresses the current intent — the comment in
`.markdownlintignore` is from whenever it was written, not necessarily now.

Verification tooling gotcha, recorded because it cost three detours: given paths
that are **all** excluded by `.markdownlintignore`, `markdownlint-cli` prints its
usage text and exits **0** — a clean-looking run that processed zero files. A
path outside the ignore list (`README.md`) lints normally, which is the control
that distinguishes this from the CLI simply being broken. Use `--stdin`, or
`-p /dev/null` to override the ignore file, and always pair a "clean" result with
a positive control that proves files were read.
