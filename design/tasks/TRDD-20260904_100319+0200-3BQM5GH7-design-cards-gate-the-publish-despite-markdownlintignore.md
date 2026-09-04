---
trdd-id: 3BQM5GH7
title: design cards gate the publish even though markdownlintignore excludes them
column: todo
created: 2026-09-04T10:03:19+0200
updated: 2026-09-04T10:09:26+0200
current-owner: ai-maestro-janitor-08
task-type: infra
scope: project
project-id: ai-maestro-janitor
relevant-rules: [how-to-fix-issues-of-other-projects]
external-refs: [reports/publish/20260904_100628+0200-publish-exit4-cpv-nit.txt]
external-refs-note: local-only path (reports/ is gitignored) — the load-bearing lines are quoted inline below
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
version. A `git notes` retraction is attached to it on the authoring machine,
but notes live in `refs/notes/commits` and are NOT pushed — so **this card is
the only copy of the retraction a cloner gets.** `d4e5f055` was not rewritten:
that was a choice (non-destructive, after two history rewrites already), not an
impossibility — `reset --soft` and a non-interactive rebase were both available
and unsurveyed.

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

**`design/` IS in scope — MEASURED 2026-09-04, and it is worse than NITs.**
Running stage 4 standalone (`uvx --from git+…claude-plugins-validation@v5.16.2
--with pyyaml cpv-remote-validate plugin . --strict`, exit 1) reported three
findings, all in `design/tasks/` — and two were **CRITICAL**, not NIT: *"Private
path leaked: macOS private path with username"*. So a design card can block a
release on the SECURITY gate, not merely the lint gate.

Whether selection is the changed set or the whole tree is still undetermined:
the only design file reported was the one edited in this session, which is
consistent with both.

`.mega-linter.yml` is **probably not a lever, but that is PHASE-SPECIFIC and the
relevant phase is untested.** Precisely what is established, per the completed
`TRDD-6SIY2VX2`:

- **No workflow runs Mega-Linter.** Verified there 2026-09-04 and re-confirmed
  here: nothing under `.github/workflows/`, `scripts/`, or a Makefile references
  it.
- **CPV's stage-4b `ci-preflight` does NOT read the config.** Proven by
  PERTURBATION, which is why it is trustworthy: `- COPYPASTE_JSCPD` was removed
  from `ENABLE_LINTERS`, the preflight re-run, and jscpd still ran. CPV carries
  its own list and merely labels checks with Mega-Linter sub-linter names.
- **Whether CPV's stage-4 `cpv-remote-validate plugin . --strict` reads it is
  UNTESTED** — and that is the phase that emitted our markdownlint NITs. The two
  phases demonstrably differ: `TRDD-6SIY2VX2` records that markdownlint,
  jsonlint and yamllint **never appeared at all** in the preflight's check list.
  A perturbation of the preflight says nothing about a linter the preflight
  never ran.

So Option 1 is probably dead, not certainly dead — and the same perturbation
method settles it cheaply (see acceptance criteria).

## Mechanism — NOT diagnosed, five candidates

An earlier draft of `d4e5f055`'s commit message asserted "CPV does not honor
`.markdownlintignore`". That claim is **not established** and is the accusatory
reading of the evidence. What is observed is only that CPV lints `design/`
despite the ignore file listing it.

The strongest hint points at the mildest explanation. CPV's output reads:

```
[NIT] markdownlint: ../../../../../../../<absolute repo path, redacted>/design/tasks/…
```

The seven `../` are verbatim and are the whole point; the path after them is
redacted because CPV's own security gate rates a leaked home path CRITICAL —
see the lesson below, which this card learned the hard way.

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

1. **Repo-side — no lever is known to work, and exactly one is cheap to test.**
   The obvious candidate is adding `design/` to
   `MARKDOWN_MARKDOWNLINT_FILTER_REGEX_EXCLUDE` in `.mega-linter.yml`. That is
   probably dead (the file is read by no workflow and not by CPV's preflight)
   but **not proven dead for stage 4**, which is the phase that flags us. Test
   it the same way `TRDD-6SIY2VX2` tested the preflight — perturb and re-run —
   then restore the file byte-identically. If some other lever turns out to be
   the real one, using it still **changes what gates this repo's publish**,
   which is a governance change dressed as a lint tweak and needs sign-off, not
   a drive-by edit.

   **Other candidate levers were NOT surveyed** — "no lever is known" means only
   that nobody looked, not that the space is empty. Unexamined: whether
   `markdownlint-cli` honours a `.markdownlintignore` in a parent directory or
   an env var; whether CPV reads a `.cpvignore` / `.cpvrc` / a `pyproject.toml`
   or `plugin.json` key; whether `publish.py` passes anything through to CPV;
   whether `--strict` has a NIT-severity or path-exclusion flag (checkable from
   `cpv-remote-validate --help`). Start there.
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
      deliberately-broken card: `cpv-remote-validate plugin . --strict` can be
      invoked standalone (see the `uvx --from git+…claude-plugins-validation@…`
      line in the preserved log), so no publish and no push is needed.
- [ ] Perturbation test on stage 4: add `design/` to
      `MARKDOWN_MARKDOWNLINT_FILTER_REGEX_EXCLUDE`, re-run stage 4 standalone,
      record whether the NIT disappears — then restore the file byte-identically
      and confirm a clean `git status`. This answers Option 1 outright.
- [ ] A decision is recorded on which side of the mismatch is wrong — CPV
      linting `design/`, or `.markdownlintignore` claiming it should not.

## Notes and lessons learned

The last acceptance box matters more than it looks: the mismatch could equally
be resolved by deciding the ignore file is wrong. Nobody has established which
side of the mismatch expresses the current intent — the comment in
`.markdownlintignore` is from whenever it was written, not necessarily now.

**Quoting tool output verbatim into a `design/` card can BLOCK THE RELEASE.**
This card's first version pasted CPV's `[NIT] markdownlint:` line complete with
the machine's real home path and username. A review had explicitly argued for
keeping it verbatim,
since the seven `../` is the load-bearing evidence and genericizing the path
would destroy the argument. That reasoning was right about the evidence and
wrong about the consequence: CPV's security gate rates a leaked home path
**CRITICAL**, and CRITICAL blocks `--strict`. A card written to document a
publish blocker became a worse one — two CRITICALs where the original was three
NITs. **Redact the identifying part, keep the structural part**: the `../`
prefix carries the whole argument and no username. Verified by re-running stage
4 standalone, which is cheap and needs no publish.

**I broke the speaking-vs-quoting rule in the same edit that added it.** Having
caught the `# Only lint changed files` misread, I then took `.mega-linter.yml`'s
own header — *"NOTHING in this repo parses this file"* — at face value and wrote
"INERT" into this card. That is a document's self-description, exactly the kind
of claim the rule says to verify. It happens to be backed by a real perturbation
test recorded in `TRDD-6SIY2VX2`, but I did not know that when I asserted it, and
the backing turned out to be NARROWER than the claim (preflight only, and
markdownlint never ran there). Catching a defect does not immunise the next
paragraph against it.

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
