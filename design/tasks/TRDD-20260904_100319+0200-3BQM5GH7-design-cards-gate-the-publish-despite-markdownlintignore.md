---
trdd-id: 3BQM5GH7
title: design cards gate the publish even though markdownlintignore excludes them
column: todo
created: 2026-09-04T10:03:19+0200
updated: 2026-09-04T10:06:28+0200
current-owner: ai-maestro-janitor-08
task-type: infra
scope: project
project-id: ai-maestro-janitor
relevant-rules: [how-to-fix-issues-of-other-projects]
external-refs: [reports/publish/20260904_100628+0200-publish-exit4-cpv-nit.txt]
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

**⚠ Commit `d4e5f055` carries a SUPERSEDED mechanism claim.** Its message says
CPV "does NOT honor `.markdownlintignore`" and that all 435 design cards gate
the publish. Both are retracted here: the mechanism is undetermined (five
candidates below, the mildest likeliest), and the number of cards in scope is
unknown. A reader arriving at `d4e5f055` from `git blame` sees only the wrong
version — this card is the correction, and a `git notes` on that commit points
back here.

## Symptom

`uv run scripts/publish.py --patch` exited 4 at stage `[4/11] Validating plugin
(remote CPV)`:

```
! NIT issues found - blocked by --strict
SUMMARY: CRITICAL=0 MAJOR=0 MINOR=0 NIT=3 WARNING=47
```

All three NITs were `MD056/table-column-count` at 563:86, 564:84, 565:29 of
`design/tasks/TRDD-…-8BXMNQ4T-verified-actuation-blocks-the-single-threaded-daemon-beat.md`
(the preserved publish log in `external-refs:`, lines 404–406). Fixed by one blank line in commit `d4e5f055`.

## The mismatch

`.markdownlintignore` at the repo root lists `design/`, with this comment:

> Internal / ephemeral markdown that is NOT shipped plugin content — exclude from
> markdownlint so design notes don't gate the publish like distributed docs do.

So the repo's stated intent is that design cards **do not** gate the publish. At
least one of them did.

**How many are in scope is UNKNOWN.** CPV's stage-4 file selection was never
determined — only that it included one `design/` card. Do not assume all 437.

`.mega-linter.yml` is **not a lever here, and reasoning from it is a trap.** That
file is INERT: its own header records the measurement — *"NOTHING in this repo
parses this file — measured by deleting COPYPASTE_JSCPD from ENABLE_LINTERS and
re-running: jscpd still ran. So no value below is in force."* Its
`FILTER_REGEX_EXCLUDE` (which omits `design/`) and its `VALIDATE_ALL_CODEBASE:
false` therefore describe nothing that runs. See the completed
`TRDD-6SIY2VX2` — *decide the fate of a mega-linter config that no workflow in
this repo runs*.

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

1. **Repo-side — and NO working lever is currently known.** The obvious one
   (adding `design/` to `.mega-linter.yml`'s `FILTER_REGEX_EXCLUDE`) is DEAD:
   that file is parsed by nothing, so editing it changes nothing. Finding a
   real repo-side lever requires first knowing how CPV selects files and which
   ignore mechanism it honors — i.e. it depends on the mechanism question
   above. Whatever the lever turns out to be, using it **changes what gates
   this repo's publish**, which is a governance change dressed as a lint tweak
   and needs sign-off, not a drive-by edit.
2. **Upstream.** File an issue on `Emasoft/claude-plugins-validation` (CPV is a
   DIFFERENT project — per `how-to-fix-issues-of-other-projects`, never edit its
   tree from here; issue first, PR only if asked). The reproducer is already in
   hand: the preserved publish log in `external-refs:`, lines 404–406 plus this repo's `.markdownlintignore`.

These are not exclusive — 2 is right regardless if the mechanism turns out to be
CPV-side, and 1 is a local mitigation either way.

## Acceptance criteria

- [ ] The mechanism is narrowed to one of the five candidates, with evidence.
- [ ] A decision is recorded here on option 1, option 2, or both.
- [ ] If option 2: the CPV issue is filed and its URL recorded in `external-refs:`.
- [ ] CPV's stage-4 file selection is determined — the changed set, or the whole
      tree — and recorded here. This decides the blast radius and therefore
      which option is proportionate. Do NOT test it by running a release with a
      deliberately-broken card: a publish pushes to a public repo under a shared
      identity, and the question is answerable from CPV's own source.
- [ ] A decision is recorded on which side of the mismatch is wrong — CPV
      linting `design/`, or `.markdownlintignore` claiming it should not.

## Notes and lessons learned

The last acceptance box matters more than it looks: the mismatch could equally
be resolved by deciding the ignore file is wrong. Nobody has established which
side of the mismatch expresses the current intent — the comment in
`.markdownlintignore` is from whenever it was written, not necessarily now.

**A comment quoted inside tool output is not the tool's own log line.** The
publish log contains the line `# Only lint changed files (faster, less noise)`.
I read it as CPV announcing its file-selection policy and told the user CPV
lints changed files only. It is nothing of the kind — it is a comment *inside
`.mega-linter.yml`*, echoed because CPV was displaying that file's content. The
surrounding lines carry `+`/`-` diff markers; the give-away was one column wide.
Two conclusions were built on the misread (that CPV lints changed files, and
that `FILTER_REGEX_EXCLUDE` was a usable lever) and both were wrong. Before
quoting a line out of a tool's output, establish whether the tool is *speaking*
or *quoting*.

Verification tooling gotcha, recorded because it cost three detours: given paths
that are **all** excluded by `.markdownlintignore`, `markdownlint-cli` prints its
usage text and exits **0** — a clean-looking run that processed zero files. A
path outside the ignore list (`README.md`) lints normally, which is the control
that distinguishes this from the CLI simply being broken. Use `--stdin`, or
`-p /dev/null` to override the ignore file, and always pair a "clean" result with
a positive control that proves files were read.
