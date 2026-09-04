---
trdd-id: 3BQM5GH7
title: design cards gate the publish even though markdownlintignore excludes them
column: todo
created: 2026-09-04T10:03:19+0200
updated: 2026-09-04T10:48:06+0200
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

**NO TESTED GIT STATE GATES REPORTING (3 probes, 2026-09-04):** three files in
`design/tasks/` — one dirty-but-unchanged-vs-`origin/main`, one untracked, one
gitignored — were each reported. That is the actionable finding, and the
headline claims exactly those three data points: not "git is irrelevant", not a
general property of markdownlint. Note the verb too: the probes read the
FINDINGS LIST, so "selection" is a step further than they reach.

It does NOT settle the five-candidate table further down. Candidates 3
(markdownlint used as a LIBRARY) and 4 (CPV lints a temp checkout) are fully
COMPATIBLE with path-based selection — an earlier draft claimed the probes
retired all five, which is wrong: they retire the git-based readings only, and
3 and 4 are arguably now the leading candidates. Reading CPV's source or
`--help` remains the way to pick among them.

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

**A design card can block a release on the SECURITY gate, not merely the lint
gate — MEASURED 2026-09-04.** Running stage 4 standalone (`uvx --from
git+…claude-plugins-validation@v5.16.2 --with pyyaml cpv-remote-validate plugin
. --strict`, exit 1) reported two **CRITICAL** findings — *"Private path leaked:
macOS private path with username"* — in a `design/tasks/` card. That is
unambiguous and it is the worse failure mode: strictly more blocking than the
NIT this card was filed about.

**SELECTION — one reading ELIMINATED by experiment 2026-09-04, two remain.**
A card unchanged in git history but DIRTY in the working tree IS linted. Probe:
appended a deliberate table-row-followed-by-prose block to
`TRDD-…-ca754708-port-sentinel-rules.md` — a card byte-identical to
`origin/main`, selected by `comm -23` of all `design/tasks/*.md` minus the
`origin/main..HEAD` diff, which is what the experiment actually rests on. (No
count is given on purpose: two attempts produced one refuted number and one that
could not be justified. The `find` total and the diff total have different
membership bases, and the diff lists BOTH ends of an archive `git mv` — measured:
`grep -c 5EHBPH6G` on it returns 2, the `tasks/` and `archived/` paths of one
card — so subtracting them double-counts.)
Ran stage 4 standalone → `exit=4`,
`SUMMARY: … NIT=1 …`, and `ca754708` reported once. File then restored by
`git checkout` and verified byte-identical (blob `cb9058b4…`), tree clean.

| candidate rule | probe predicts | verdict |
|---|---|---|
| (a) working tree vs HEAD | reported | **still live** |
| (b) HEAD vs `origin/main` | NOT reported | **ELIMINATED** |
| (c) whole tree, always | reported | **still live** |

**This table is NOT exhaustive** — it is the three rules tabulated before probe
1, and a probe only discriminates against rules predicting the outcome that did
NOT occur. Rules predicting "reported" all survive it.

**PROBE 2 — the untracked case, and it is the decisive one.** Wrote a NEW
`design/tasks/zz-untracked-selection-probe.md` carrying the same deliberate
MD056 defect, never `git add`-ed (`git status` showed it as `??`), and ran
stage 4 standalone → `exit=4`, `NIT=1`, the probe file reported once. Then
removed via the janitor's `safe_delete.py` into `.trashcan/`, tree clean.

So **a file git has never heard of still gates the release.** That kills every
"everything git tracks" style rule for **the markdownlint check** — which is the
one that blocked the publish, and the only one either probe exercised. CPV runs
several checkers (the same run produced path-leak CRITICALs from a secrets
scanner and drift WARNINGs from a pipeline auditor); nothing here establishes
they share one file-enumeration path, so "the mechanism" is singular only for
markdownlint.

**PROBE 3 — the gitignored case. SELECTION IS NOW DETERMINED.** An earlier draft
here said this probe "needs a `.gitignore` entry under `design/`, i.e. a repo
edit" and skipped it on that basis. **That was false**: `.git/info/exclude`
applies gitignore patterns per-clone, is untracked, and needs no repo edit — the
probe is a local one-liner. A card that invents an obstacle to its own next
experiment is worse than one that just leaves it undone.

Run: appended the probe path to `.git/info/exclude`, confirmed with
`git check-ignore -v` and a silent `git status --porcelain -uall`, created
`design/tasks/zz-gitignored-selection-probe.md` with the same MD056 defect, ran
stage 4 standalone → `exit=4`, `NIT=1`, **the gitignored file reported once**.
Cleanup: file into `.trashcan/` via `safe_delete.py`, `.git/info/exclude`
restored from backup and `diff`-verified identical.

| selection rule | status after 3 probes |
|---|---|
| HEAD vs `origin/main` | eliminated (probe 1) |
| anything tracked-only | eliminated (probe 2 — untracked file reported) |
| everything not gitignored | **eliminated (probe 3 — gitignored file reported)** |
| **path-based selection** (hypothesis — every member of this family predicts "reported" for all three probes, so nothing run so far distinguishes them; it remains to be *tested*, not measured) | **the surviving FAMILY** |

**CPV's markdownlint selects by path, not by git.** Precisely: git's *ignore
rules*, *tracking*, and *diff-vs-origin* are each shown not to gate INCLUSION.
That is narrower than "git is not consulted at any level" — an earlier draft
said that, and no probe supports it; CPV may consult git for other purposes or
for other checkers.

**The surviving row is a FAMILY, not one rule**, and this table is no more
exhaustive than the 3-row one it replaced. These predict "reported" for all three
probes: a glob scoped to `design/`, a glob over the whole repo, a directory list
from a manifest, everything-except-a-denylist, and CPV copying the tree to a
temp dir and globbing there. Probes eliminate; they do not select.

Two of those are only *half* alive, which the row above is too coarse to show —
probe 3 (a GITIGNORED file, reported) already cuts inside them:

- **temp-copy** survives only in a git-UNAWARE form (`cp -r`, rsync). A copy made
  with `git archive` or any git-aware export omits gitignored files, so that
  variant predicts "not reported" and is dead.
- **manifest-listed directories** survives only if `design/` is on the manifest.
  If it is not, that member predicts "not reported" for every probe and was
  dead from probe 1.

So the surviving set is a family of families, and the three probes have already
pruned inside two of its branches.

An attempt to eliminate one of them for free FAILED, and the failure is worth
recording because the reasoning looked sound. The clean run's 47 findings do
span many places — `skills/` 25, `scripts/` 8, `agents/` 4, plus ten naming
`hooks/hooks.json`, `git-hooks/pre-push`, `cliff.toml`, `.mega-linter.yml`,
`scripts/memgrep/build.rs` inline. That was read as "the walk is repo-wide, so
the `design/`-scoped glob is out". **It does not follow.** Each of those
findings comes from a checker that targets its directory BY NAME — a skill
auditor reads `skills/`, an agent auditor reads `agents/`, a pipeline auditor
reads named root files. That is CPV examining many directories on purpose, not
evidence of any glob, and if anything it argues against one uniform walk.

**Not one of the 47 is a markdownlint finding** (`NIT=0` in that run). Counting
genuine findings by their `] markdownlint:` prefix across all seven runs on
disk: **6 findings from 4 defects** — the publish's 3 are three prose lines of
ONE malformed table, plus 1 from each probe — and every path names
`design/tasks/`.

Method note, because the card recommends a probe designed to produce a finding
OUTSIDE `design/`: verify by printing the finding LINES
(`grep -h '] markdownlint:' /tmp/*.txt`), never by matching paths against a
directory alternation. A first pass here used
`grep -oE '/(design|skills|…)/'`, which has no match for a repo-root file or
for `hooks/`, `git-hooks/`, `.github/` — so a real finding outside the list
would have rendered as an EMPTY directory field, visually near-identical to a
run with no findings at all. The count column happened to make it detectable
this time; that was luck, not design.

**That last fact is nearly worthless as evidence, and it is worth saying why.**
Every defect ever planted in these experiments was placed in `design/`. Finding
no markdownlint report outside `design/` is an artifact of probe placement, not
a measurement of scope. It is equally consistent with a `design/`-scoped glob
and with a repo-wide one, because the repo's other markdown is simply clean.
(A first attempt at this count also mis-measured: `grep 'markdownlint'` matched
THIS CARD'S OWN FILENAME — `…-despite-markdownlintignore.md` — inside path-leak
findings about it, inflating the count in runs that had none. Match the finding
prefix, not the word.)

**So the `design/`-scoped glob is fully alive**, and the probe that would settle
it is the obvious one nobody has run: plant the same MD056 defect in a
NON-`design/`, non-ignored location — `skills/`, or a repo-root `.md` — and see
whether markdownlint reports it. Reported ⇒ scope is wider than `design/`; not
reported ⇒ `design/`-scoped. One run, same standalone harness.

**On `.markdownlintignore` specifically — still an INFERENCE, and a different
file from the one probed.** The probes tested `.gitignore` semantics via
`.git/info/exclude`. `.markdownlintignore` was never directly tested. What IS
directly observed, and needs no inference, is the card's title claim: it lists
`design/` and `design/` files are linted anyway. WHY remains open between "never
discovered" and "disregarded" — probe 3 does not settle it, because gitignore
and markdownlintignore are read by different machinery.

Two limits that remain, both from what the probes did NOT do:

- All three probes used files **present on disk**, so presence is **sufficient**
  for inclusion. None tested a file committed but absent from the worktree, so
  presence is not shown **necessary**.
- All three grepped the findings list for a filename, which shows which checker
  **REPORTED**, never which **SCANNED**. A checker that opened the probe and had
  nothing to say is indistinguishable from one that never opened it. So this is
  markdownlint's file source; whether the secrets scanner and pipeline auditor
  share it is undetermined. The cheap discriminator, for whoever runs the next
  probe: give the probe file a home-path line ALONGSIDE the MD056 defect — the
  path detector demonstrably fires on that pattern (it fired on this very card),
  so one file and one run answer both questions.

(a) and (c) cannot be separated this way, and possibly not at all by
experiment: isolating (c) needs a defect in a file nobody has touched, which is
self-contradictory when the defect has to be introduced. Enumerate the rule
instead of sampling it: try `cpv-remote-validate --help` first for a verbose or
file-listing flag (seconds, and untried), then CPV's docs, then its source. The
source is the most authoritative route, not the only one.

**PRACTICAL CONSEQUENCE — the one thing to remember.** A markdown file under
`design/` gates the release **as soon as it EXISTS ON DISK**. Not committed,
not staged, not `git add`-ed. Both probes agree and probe 2 is decisive:
someone drafting a card in an editor can break a release without touching git
at all.

What clears it depends on where the defect lives, and an earlier draft of this
line got it wrong by generalising from probe 2 — `git stash` DOES help in two
of the three cases:

| defect lives in | `git stash` | `git stash -u` |
|---|---|---|
| the committed card | survives, still gates | survives, still gates |
| an uncommitted edit | removed, does not gate | removed, does not gate |
| an untracked new file | survives, still gates | removed, does not gate |

The only state nothing short of an edit or a revert clears is a defect already
committed. (Reasoned from documented `git stash` semantics, not probed — the
probes covered the untracked and dirty rows' PRESENCE, not stash's effect.)

Blast radius is therefore **every markdown file present under `design/`**, not
"the cards you committed". Do not assume a smaller one.

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
- [x] markdownlint **REPORTS** on a `design/` file regardless of git tracking,
      git status, or gitignore — DONE 2026-09-04 by three probes. Deliberately
      NOT phrased as "selection is git-independent": every probe read the
      FINDINGS LIST, so it observes reporting, and a checker could select via
      git and report on a superset (or the reverse) without any probe noticing.
      The distinction is the card's own retained limit and a checked box must
      not quietly widen past it. `cpv-remote-validate plugin . --strict` runs
      standalone, so no publish and no push is needed — that is the harness for
      everything below.
- [ ] WHICH path-based rule — the surviving family is undistinguished, and the
      `design/`-scoped variant is still fully alive (no markdownlint finding has
      ever named a file outside `design/`). `--help` first, then the source.
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
