---
trdd-id: 3BQM5GH7
title: design cards gate the publish even though markdownlintignore excludes them
column: blocked
pre-block-column: todo
unblock-when: [decision:user]
min-approval-requirement: user
created: 2026-09-04T10:03:19+0200
updated: 2026-09-04T14:08:26+0200
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

**COLUMN — `blocked`, `unblock-when: [decision:user]`, `pre-block-column: todo`.**
I first moved this card to `human_review` and that was **wrong**: the transition
matrix admits `human_review` only from `ai_review`, and it is a WORK-group column
asserting active review after tests and AI review passed. None of that is true
here. `blocked` + a `decision:` predicate is this repo's established shape for a
card waiting on a human, and `decision:` never auto-clears (`trdd-drift.py:192`
returns `False` unconditionally — *"the ONLY human-only kind"*). Restore to
`todo` when the decision lands.

**On the apparent tension with the base rule** — `trdd-design-tasks.md` §6 says
*"`blocked` applies whenever `blocked-by:` is non-empty"*, and this card has no
`blocked-by:` at all. That is deliberate, not an omission: `trdd-drift.py:303,307`
scopes `blocked-by:` to **TRDD-to-TRDD dependencies only**, so a wait on a human
decision is literally inexpressible there, and `unblock-when: [decision:user]` is
the form that exists for it. `pre-block-column: todo` names the last
**legitimate** column — the column immediately prior was `human_review`, which
was my own illegal move and is not something to restore into.

**NEXT ACTION:** a USER decision on the Options table below, which the
2026-09-04 source read has REWRITTEN. Option 1's only named lever is measured
DEAD, and a third option — *the findings are real markdown defects, not false
positives* — has displaced both originals as the recommendation.

**MECHANISM — NARROWED 2026-09-04 from three-of-five to two, by READING THE
PINNED SOURCE. Not closed.** At `v5.16.2` (uv git-cache checkout `9ef873ee6335afa1/c441703c`,
`git describe` → `claude-plugins-validation--v5.16.2`, the exact ref
`.cpv-version` pins):

- `cpv_lint_engine.py::lint_markdown` builds `invocation = list(cmd)` and
  extends it with `["--config", <abs path>]` and **nothing else**. No
  `--ignore-path`, no `-p`, no `--ignore` is ever constructed — a grep of every
  `.py` in the checkout for `markdownlintignore` / `ignore-path` / `ignorePath`
  returns zero markdownlint-related hits (every `ignorePaths` hit belongs to
  cSpell, an unrelated linter).
- It then calls `_run_linter(invocation + file_paths, cwd=Path(_isolated_cwd))`
  — an **explicit absolute file list**, from an isolated temp cwd.
- Discovery is `detect_languages` → `collect("markdown", ["*.md", "*.mdx"])` →
  `gi.rglob(pattern)` with `gi = GitignoreFilter(plugin_root)`; `lint_markdown`
  then drops any path containing a `fixtures` segment.

**The selection rule, in full: a gitignore-filtered `rglob` of `*.md`/`*.mdx`
from the repo root, minus `fixtures` paths.** Nothing else.

**THE ANSWER IS A SIXTH CANDIDATE THE CARD NEVER LISTED: `cmd =
_resolve("markdownlint-cli2")` (`:1350`). `markdownlint-cli2` HAS NO
`.markdownlintignore` SUPPORT AT ALL.** `.markdownlintignore` is a
**markdownlint-cli (v1)** file. cli2 is a different tool: it takes exclusions as
`!`-negated globs or an `ignores:` array in a `.markdownlint-cli2.*` config, and
its `--help` lists no ignore-file flag of any kind (only `--no-globs`).

Measured directly, under conditions maximally favourable to the ignore file
being honoured — cwd = the file's own directory, relative wildcard glob.
**Version caveat:** the probe ran `npx --yes markdownlint-cli2`, i.e. **latest**,
while CPV calls `_resolve("markdownlint-cli2")`, which may return a pinned local
install or a `bunx` resolution at another major. The verdict does not lean on
the version — `.markdownlintignore` is a **cli v1** file, a tool boundary rather
than a version-drift artifact — but the probe establishes *identity*, not
*version*, and the lesson below asks for both:

| `.markdownlintignore` content | result |
|---|---|
| *(absent — control)* | `Summary: 1 issue in 1 file` |
| `*.md` (ignore everything) | `Summary: 1 issue in 1 file` — **zero effect** |

| # | candidate | verdict |
|---|---|---|
| **6** | **CPV runs cli2, which never supported this file** | **✅ THE ANSWER** — measured above + `--help` |
| 1 | different cwd, ignore file not discovered | **MOOT** — no cwd would honour it |
| 1b | explicit absolute file list bypasses ignore matching | **MOOT** — same reason |
| 2 | explicit `-p` / `--config` overrides it | `--config` IS passed *conditionally*, sets RULES not paths — not the cause |
| 3 | markdownlint used as a LIBRARY | **FALSE** — a `markdownlint-cli2` subprocess |
| 4 | lints a temp checkout or tarball | **FALSE** — absolute paths into this working tree |
| 5 | reads the file and deliberately disregards it | **FALSE** — it never reads it |

**Nobody was ever ignoring anything. The repo has been writing an ignore file
for a tool it does not run.** Corroboration CPV hands you and this card walked
past twice: its own comment at `:1395-1396` — *"the cwd governs ONLY module
resolution, never WHICH files get linted"* — answers candidate 1 outright, and
`_LANG_CONFIG_FILENAMES["markdown"]` (`:2230-2240`) omits `.markdownlintignore`,
so editing it does not even bust CPV's lint cache.

**⚠ THREE retracted claims of my own, all published here today, all from
reasoning past the evidence.** (i) I wrote "1b is the cause, 1 is not operative"
— unestablished. (ii) The probe meant to settle it (`markdownlint-cli2
<ABSOLUTE path>` from two cwds) printed `Summary: 0 issues in 0 files` in
**both** arms, which I read as "ignored in both" — wrong. (iii) I then retracted
(ii) **with a wrong reason**, writing *"nothing matched the glob — an absolute
path is not a glob cli2 resolves"*. That is also false: a later control proved
an absolute path from a temp cwd returns `Linting: 1 file` / `1 issue in 1
file`. Absolute paths resolve fine.

**The actual reason both arms were degenerate: the target file had already been
restored to CLEAN** by the perturbation worker's `git checkout --`. Both arms
linted a defect-free file, so `0 issues in 0 files` meant *linted, nothing
wrong*. The no-defect case discriminates nothing.

**And the discriminator was on screen and I filtered it out.** `Summary: N
issues in M files` counts files **with issues**, not files linted — the
`Linting: K files` line carries that, and I had grepped `^Summary` only. **Do
not filter a tool's output down to the field you already expect to reason
about**; the dropped line is disproportionately often the one that would have
stopped you. **(ii), (iii), and the spurious "independent behavioural
confirmation" I reported to the USER all trace to that one habit — but (i) does
NOT.** (i) was a reasoning error from the source read, asserted before any probe
ran. Blaming it on output filtering would credit the habit with a failure it did
not cause — sloppy attribution in a lesson about sloppy attribution.

**The root error under all of it: I never checked WHICH BINARY was involved.**
`markdownlint-cli` and `markdownlint-cli2` are different tools with different
config surfaces, and one line of the source (`:1350`) names the one CPV runs.
Three probes and two wrong verdicts were spent on a question the tool's identity
answers for free. **Establish the identity and version of the binary under test
before designing any probe of its behaviour.**

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

**⚠ "Nothing is broken right now" was FALSE, and was false when written.** This
line used to read *"`design/` currently lints clean, so the next publish will
not trip on this."* A stage-4 run at 13:36 on 2026-09-04 measured
`NIT=20 → exit=4`: **19 LISTED MD056 findings in
`TRDD-…-Q8PNPRTW-…md`** (lines 35–50 and 87–89), plus 1 from the deliberate
probe defect planted for that run. **"19" is the truncated DISPLAY, not the
count** — see the ceiling below; the file actually held **37**.

**Why 19 + 18 legitimately compose to 37**, given the two were measured on
different file states: the four regions are independent block structures (35–50,
87–89, 221, 790–806), and a blank line inserted at line 35 cannot manufacture or
mask a table defect 750 lines later. Both measurements are commensurable for
MD056 specifically, which neither config disables, and the sets are disjoint.
Consistency check — **and note what it does and does not show**: 19 Q8PNPRTW +
1 planted probe = **exactly 20** = the cap, so CPV stopped precisely at the
ceiling. That confirms the list was **cut**, not the **total**; it establishes
that more existed, never how many. The weight for 37 is carried entirely by
disjointness and structural independence above.
(This justification is stated because the earlier "stateful parser" story — the
only reason the states might NOT have composed — was retracted, and removing it
silently would have left a composed total with no composition argument.) The card predicted *"the **next** card
containing a markdown table will [trip it]"* — that card already existed and had
been edited earlier the same day, so the prediction was about the present tense
and nobody checked it. **A claim of "clean" that was never measured is the same
defect this card keeps documenting in others.**

All of them were the same defect as `d4e5f055`: a table whose last row is
followed *immediately* by prose, so markdownlint reads each prose line as a
1-cell row. **Fixed in this session** by one blank line at each site (a bare `>`
inside a blockquote; a plain blank line in an indented list).

**FOUR sites, not two — because `NIT=20` IS A TRUNCATION CEILING, NOT A COUNT.**
CPV's run named 19 findings at two regions (35–50, 87–89); after fixing those, a
local lint surfaced **18 more** at two further regions (221, 790–806). I first
recorded that as an open loose end and guessed at a stateful parser. **It is
neither open nor a parser artifact:** `cpv_lint_engine.py:1450-1457` reads
`surfaced += 1; if surfaced >= 20: break`. The run reported **exactly** `NIT=20`,
so the list was cut off at 20 and the remaining defects were simply never
printed.

> **⚠ OPERATIONAL RULE, and the most reusable thing on this card: a CPV run
> reporting exactly `NIT=20` CANNOT BE RELIED ON as a complete list. Treat it as
> "≥20, possibly truncated" and never as a work-list. Only a result strictly
> BELOW 20 is a complete count.**
>
> **The implication runs one way only, and that is what makes it usable.**
> `SUMMARY: NIT` aggregates every linter while the cap sits on markdownlint's
> own loop, so: aggregate `< 20` ⟹ that loop never reached `break` ⟹ its list is
> complete. The converse fails — an aggregate of exactly 20 could be 20 across
> mixed linters with markdownlint at 5, uncapped. (In `phase1-baseline.txt` all
> 20 happened to be markdownlint, so that one *was* capped; do not generalise
> from it.)

That is the sharp form of the softer lesson: **a re-run that goes green after a
PARTIAL fix does not prove the fix is complete.** Here a second, independent
linter pass caught the remainder — and the reason a second pass was needed was
sitting as a hard-coded `break` in the very function this card claims to have
read line by line. **Reading a function is not the same as reading the loop that
emits its output.** Stage 4 was re-run standalone after all four repairs:
`CRITICAL=0 MAJOR=0 MINOR=0 NIT=0 WARNING=47` — and `NIT=0`, being below the
ceiling, is a trustworthy complete count.

**Not yet done:** the CPV issue is NOT filed.

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
| everything not gitignored | ~~eliminated (probe 3)~~ — **RETRACTED 2026-09-04; probe 3 is void, and this rule is in fact CONFIRMED. See below.** |
| **path-based selection** (hypothesis — every member of this family predicts "reported" for all three probes, so nothing run so far distinguishes them; it remains to be *tested*, not measured) | **the surviving FAMILY** |

**⚠ RETRACTION 2026-09-04 — probe 3 measured the wrong mechanism, and the
conclusion drawn from it is backwards.** Probe 3 excluded its file via
`.git/info/exclude`. CPV's `gitignore_filter.py` parses **`.gitignore` files
only** — the root one plus every ancestor directory's own nested one (its
issue #226) — with no reference anywhere to `.git/info/exclude`,
`core.excludesFile`, or `git check-ignore`. So CPV **structurally cannot see**
the exclusion probe 3 applied, and the probe could only ever have reported the
file. It discriminates nothing.

The truth is the opposite of what the row claimed: `.gitignore` **is** consulted,
and it is the only **git-based** gate (there is a second, non-git one: the
`fixtures`-segment filter in `lint_markdown`). Corroborated independently by the
preserved publish log — `reports/` and `.trashcan/` are gitignored
(`git check-ignore -v` → `.gitignore:91`, `.gitignore:97`), hold many `.md`
files with tables, and contribute zero findings.

**That corroboration is valid for a reason worth stating, because the same
evidence from a different run would be worthless:** the publish log reported
`NIT=3` — **below** the 20-finding ceiling — so its list is complete, and an
absence in it is real evidence of absence. Had the same point been argued from
`phase1-baseline.txt` (`NIT=20`, capped), it would prove nothing: **a truncated
list cannot evidence an absence.** Check a report against its cap before
reasoning from what is missing.

So the earlier headline — *"CPV's markdownlint selects by path, not by git"* —
is **overstated**. Selection is by path *within a gitignore-filtered walk*.
Tracking and diff-vs-origin genuinely do not gate inclusion (probes 1 and 2
stand); git's **ignore rules do**, via `.gitignore` proper. **The lesson is
about the instrument, not the answer**: probe 3 substituted a mechanism that is
equivalent *to git* (`info/exclude` vs `.gitignore`) for the one under test, and
CPV never used git. Two probes were built and cleaned up carefully to measure
nothing — the same "void instrument" failure logged on `TRDD-Q8PNPRTW`.
That is narrower than "git is not consulted at any level" — an earlier draft
said that, and no probe supports it; CPV may consult git for other purposes or
for other checkers.

**The surviving row is a FAMILY, not one rule**, and this table is no more
exhaustive than the 3-row one it replaced. These predict "reported" for all three
probes: a glob scoped to `design/`, a glob over the whole repo, a directory list
from a manifest, everything-except-a-denylist, and CPV copying the tree to a
temp dir and globbing there. Probes eliminate; they do not select.

Two of those are only *half* alive, which the row above is too coarse to show.
Note WHICH observation kills each — a first draft here credited the wrong one
in both cases, and the correct attribution is earlier and stronger:

- **temp-copy** survives only in a fully git-UNAWARE form (`cp -r`, rsync with
  no git filter). "Git-aware export" is not one thing, and **each probe kills a
  different sub-variant** — no probe kills the family alone:

  | export variant | probe 1 (tracked, DIRTY) | probe 2 (untracked) | probe 3 (gitignored) |
  |---|---|---|---|
  | materialises a committed tree (`git archive HEAD`, or the index) | **REFUTED** — carries the CLEAN blob, so nothing to report; it was reported | (also refuted) | (also refuted) |
  | copies the working tree, filtered by `git ls-files` | consistent — tracked file, dirty content copied | **REFUTED** — untracked, so omitted | (also refuted) |
  | copies the working tree, filtered by gitignore | consistent | consistent | **REFUTED** — ignored, so omitted |

  Probe 1's contribution is the strongest in kind — it refutes on CONTENT, not
  presence: `git archive` has no working-tree mode, so a committed-tree export
  hands markdownlint the clean version of a tracked-but-dirty file. But a copier
  that reads the working tree and consults git only for EXCLUSION is git-aware in
  the sense this row means, carries the dirty defect, and probe 1 says nothing
  about it. That one needs probe 2.

  **These three rows are common implementations, NOT a partition** — the third
  table in this card to need that warning, so treat it as the card's standing
  defect. At least one more shape exists: a copier filtered by
  `git ls-files --others --exclude-standard` (tracked ∪ untracked-unignored),
  which probe 1 and probe 2 are both consistent with and only probe 3 refutes.
  The conclusion is unchanged — every copier shape found so far is refuted by
  some probe — but the space is open.

  (A draft listed sparse-checkout here as a fourth shape "orthogonal to all
  three probes", which was both a contradiction — an orthogonal shape is an
  UNREFUTED one, against the sentence beside it — and a category error.
  Sparse-checkout governs how the USER'S worktree was materialised, not how CPV
  copies it; the probe files were demonstrably on disk regardless. It is not a
  member of this family.)

  And the refutations are **many-to-many, not a diagonal**: probe 3 refutes all
  three rows, probe 2 refutes two, probe 1 refutes one. What is true, and is the
  load-bearing part, is that two rows have exactly ONE refutation each, so no
  probe is redundant. An earlier phrasing of "each probe kills exactly one" read
  as a bijection and was wrong.

  Attribution history, kept because it is the instructive part: credited to probe
  3, corrected to probe 2, then to probe 1 alone ("2 and 3 redundant" — wrong),
  then to a diagonal table (also wrong), now to this. Five answers. Do NOT read
  the latest as terminal — each previous one looked settled too, and every
  correction moved toward newer evidence, which is a confirmation-order
  signature rather than random error.
- **manifest-listed directories** survives only if `design/` is on the manifest.
  A manifest without `design/` was refuted by the **ORIGINAL PUBLISH**, which
  reported three NITs in a `design/` card — before any probe existed. The
  refutation transfers because the publish and every probe ran the SAME pinned
  `cpv-remote-validate@v5.16.2` and the same `plugin . --strict` subcommand; had
  the versions or subcommands differed it would need re-testing. (The card's
  stage-4 vs stage-4b distinction is not in play — 4b is `ci-preflight`, a
  different subcommand, and no markdownlint finding ever came from it.)

So the surviving set is a family of families and two of its branches are already
half-pruned. The lesson is NOT "the oldest evidence did the work" as a rule about
evidence age. It is a rule about SEARCH ORDER: **check whether an earlier
observation already discriminates before crediting the newest one** — and, the
harder half, **check whether the question has more than one answer.** The
manifest branch has a single killer (the publish). Temp-copy has three, one per
sub-variant, and four successive attempts each named exactly one because the
question was read as "which probe killed it" rather than "what is *it*". A
hypothesis that turns out to be a family needs an answer per member; naming one
probe for a family is a category error no amount of re-attribution fixes.

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

## Mechanism — NOT diagnosed, five candidates (⚠ SUPERSEDED 2026-09-04)

> **SUPERSEDED — kept as provenance, do not read as current.** The mechanism IS
> diagnosed: the answer is a sixth candidate this section never contemplated
> (CPV runs `markdownlint-cli2`, which never supported `.markdownlintignore`).
> The STATE block holds the current version. Everything below — including "five
> hypotheses, one observation, zero discrimination" and "diagnosing this is the
> first task on the card" — describes the state of knowledge at 10:03, not now.
> The three-row selection table further up and the "two remain" text are
> likewise superseded.

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

1. **Repo-side — ONE named lever is dead; TWO OTHERS WORK. ⚠ I recorded this
   option as "MEASURED DEAD … no lever could have worked" and that
   generalisation was FALSE — retracted 2026-09-04 after review.** What was
   measured dead is the one candidate below. Two working levers exist:

   | lever | measured |
   |---|---|
   | `.markdownlint-cli2.jsonc` at repo root with `{"ignores": ["**/design/**"]}` | **WORKS in CPV's exact shape** — abs path + isolated temp cwd → `0 issues`; control without it → `1 issue`. cli2 resolves `.markdownlint-cli2.*` by walking up from **each linted file's own directory**, which survives the temp cwd that defeats `.markdownlintignore` |
   | inline `<!-- markdownlint-disable-next-line MD0xx -->` | **CPV uses it on its OWN TRDDs — 30 files** under the pinned checkout's `design/`, every one `<!-- markdownlint-disable-next-line MD025 -->` (counted here, 2026-09-04). That it is *in use by the tool's own author* is strong; that it *suppresses under CPV's invocation* is inferred, **not probed** |
   | `MARKDOWN_MARKDOWNLINT_FILTER_REGEX_EXCLUDE` in `.mega-linter.yml` | **DEAD** — see below |

   Both were measured on a **synthetic** repo, in throwaway temp dirs, not on
   this one. Confirm with one real `cpv-remote-validate` run before adopting
   either. Adopting one is still a governance change — it alters what gates this
   repo's publish — and needs sign-off, which is why they are listed here rather
   than applied.

   The dead one was tested exactly as `TRDD-6SIY2VX2` tested the preflight —
   plant a known MD056 defect, run stage 4 standalone, apply the lever, re-run:

   | phase | exit | SUMMARY |
   |---|---|---|
   | baseline (defect planted) | 4 | `CRITICAL=0 MAJOR=0 MINOR=0 NIT=20 WARNING=47` |
   | lever applied | 4 | `CRITICAL=0 MAJOR=0 MINOR=0 NIT=20 WARNING=47` (unchanged) |

   Byte-identical NIT count — **zero effect**. Both files restored via
   `git checkout --` and verified against their recorded blob hashes, with
   `git status --porcelain` silent. This also closes the narrower gap the Notes
   flagged: `.mega-linter.yml` was previously only shown inert for the
   *preflight*; it is now shown inert for **stage 4 markdownlint** too, which is
   the phase that actually flags us.

   **⚠ Caveat, from the truncation ceiling above: BOTH rows read `NIT=20`, which
   is the cap — so both lists were cut off, and a lever with a PARTIAL effect
   would look identical to one with none.** The conclusion survives only because
   this particular lever is all-or-nothing (a path exclusion for `design/` would
   have taken the count to ~0, not shaved it), and it did not move. A
   perturbation test whose two arms both sit on a truncation ceiling is not
   generally sound; this one is, for that specific reason, and the reason has to
   be stated or the next reader will copy an unsound pattern.

   A root `.markdownlint.json` is a **fourth, untested** lever and is the one to
   avoid. CPV passes its own relaxed bundle via `--config` *only when the target
   repo has none* (`:1377-1383`); adding one flips CPV to passing **no**
   `--config`, and CPV's own comment at `:1373-1376` records what happened last
   time that occurred — cli2 *"fell back to ITS defaults (MD013/MD012/MD032 all
   enabled)"*. The risk direction is a repo-wide NIT **explosion**, not a quiet
   MD056 disable. Note this repo **already has** a root `.markdownlint.json`, so
   this branch is the one in force today.

   **⚠ "The lever space is now SURVEYED, from source rather than guessed at" —
   RETRACTED, it was wrong within hours.** The survey read CPV's argv and
   concluded nothing else could participate. It missed **both** working levers
   above, because both act on markdownlint-cli2's own per-file config discovery,
   which never appears in CPV's argv at all. Reading the caller's argv does not
   survey the callee's configuration surface — a fact the missed evidence makes
   embarrassing: the pinned CPV checkout uses inline suppression on its own
   TRDDs, so the counter-example was inside the tree being read.

   What the argv read does establish, and this part stands: the argv is
   `list(cmd)` plus at most `["--config", <abs>]`, so no env var and no
   `.cpvignore` / `.cpvrc` / `pyproject.toml` / `plugin.json` key participates,
   and `publish.py` passes nothing beyond `plugin . --strict`. Still unexamined:
   whether `--strict` has a NIT-severity threshold flag — a blunter instrument
   than either working lever, since it would suppress *all* NITs repo-wide.
2. **Upstream.** File an issue on `Emasoft/claude-plugins-validation` (CPV is a
   DIFFERENT project — per `how-to-fix-issues-of-other-projects`, never edit its
   tree from here; issue first, PR only if asked). The reproducer is already in
   hand: the preserved publish log in `external-refs:`, lines 404–406 plus this repo's `.markdownlintignore`.

3. **Change nothing; keep `design/` cards clean. ← RECOMMENDED, on its own
   merits.** **Every markdownlint finding this card has ever seen was a genuine
   defect** — a table row followed immediately by prose, which renders wrong in
   any viewer, not only under a linter. MD056 was correct every time it fired.
   So for *markdownlint* the ignore file would have hidden a real defect rather
   than spared a false one.

   **That claim is scoped to markdownlint and must not be widened.** The card
   also measured two **CRITICAL** *"Private path leaked"* findings on a
   `design/` card. There, "a design note is not shipped content" remains a
   perfectly defensible position, and this option does not settle it.

   **⚠ COST — larger than first written, and this is the part that needs your
   eyes.** I wrote *"one blank line after every table, forever"*. The true price
   is that **every design card must satisfy CPV's entire `--strict` gate**,
   including the path/secret scanner — so no verbatim tool output containing a
   real home path may ever be pasted into a card. That constraint has already
   bitten once, on THIS card, and it is far heavier than the table rule. Risk:
   it recurs silently until the next publish; mitigated by running stage 4
   standalone (cheap, no publish, no push) after editing a card.

**Recommendation: 3, plus 2 as a courtesy — but note the argument changed.** I
first recommended 3 *because* no lever existed. Two levers do exist, so that
reasoning is struck; 3 now stands only on its own merit, which is that the
findings were real. That is a weaker and more honest basis, and it is genuinely
your call whether it outweighs adopting a `.markdownlint-cli2.jsonc`.

Applying 3 needed no sign-off — inserting four blank lines changes nothing about
what gates the publish. Adopting lever 1 **would**, which is why it is not
applied.

2 is still worth filing, with the framing corrected: CPV does not "disregard"
`.markdownlintignore`; it runs `markdownlint-cli2`, which has never supported
that file. The report is *"CPV's markdown lint silently does not honour
`.markdownlintignore`, because cli2 uses `.markdownlint-cli2.*` `ignores`
instead"* — a documentation/UX gap, not a bug.

**What needs a USER decision:** (a) adopt lever 1, adopt inline suppression, or
neither; (b) file 2 or not; (c) what to do about `.markdownlintignore` itself,
which promises an exclusion **no tool MEASURED in this pipeline implements** —
delete it, or convert it to a `.markdownlint-cli2.jsonc`. (Scoped deliberately:
CPV's markdownlint is measured; mega-linter's markdownlint and whatever the
pre-push hook runs are **not**. An unscoped "no tool has ever" would be the same
universal-from-a-sample that "the lever space is now SURVEYED" already cost this
card once today.)

Note also that adopting **inline suppression** is a governance change of the same
kind as lever 1 — it changes what gates the publish, per card rather than
repo-wide — so it needs the same sign-off. The recommendation paragraph above
names only lever 1; that was an omission, not a distinction.

## Acceptance criteria

- [x] The mechanism is narrowed to one candidate, with evidence — **CLOSED
      2026-09-04, and the answer was none of the five.** CPV runs
      `markdownlint-cli2` (`:1350`), which has no `.markdownlintignore` support
      at all — measured under maximally favourable conditions (zero effect) and
      confirmed by its `--help`. #1 and #1b are moot, #3/#4/#5 false, #2
      irrelevant. Two earlier verdicts of mine on this box were wrong; both are
      retracted in the STATE block rather than deleted.
- [x] WHICH path-based rule — DONE 2026-09-04, and it is not purely path-based:
      a gitignore-filtered `rglob` of `*.md`/`*.mdx` from the repo root, minus
      any path with a `fixtures` segment. The `design/`-scoped variant is
      eliminated: nothing in the source names `design/`; the reason no finding
      has ever landed outside it is that everything else is either gitignored or
      already clean.
- [x] Perturbation test on stage 4 — DONE 2026-09-04.
      `MARKDOWN_MARKDOWNLINT_FILTER_REGEX_EXCLUDE` produced an **identical**
      `NIT=20 / exit=4` before and after. Both files restored via
      `git checkout --`, blob hashes matched, `git status --porcelain` silent.
      Option 1 is answered: dead.
- [x] markdownlint **REPORTS** on a `design/` file regardless of git tracking or
      git status — DONE 2026-09-04 by probes 1 and 2. **The original box said
      "or gitignore" and that clause is RETRACTED**: probe 3 excluded via
      `.git/info/exclude`, which CPV's `.gitignore`-only parser cannot see, so it
      measured nothing. `.gitignore` proper DOES gate inclusion. Kept deliberately
      narrow otherwise: every probe read the FINDINGS LIST, so it observes
      reporting, and a checker could select via git and report on a superset
      without any probe noticing. `cpv-remote-validate plugin . --strict` runs
      standalone — no publish, no push — and is the harness for all of the above.
- [x] `design/` lints clean — RE-ESTABLISHED 2026-09-04 after **37** MD056
      findings were fixed in `TRDD-…-Q8PNPRTW-…md` across four regions. **Not
      19** — 19 was the truncated display; the first draft of this very box said
      "19 real", repeating the exact error the truncation rule below warns
      against, two screens away from that rule. This box did not exist before
      because the card asserted "lints clean" without measuring; it exists now
      so the next session re-measures rather than re-assumes.
- [ ] A decision is recorded here on option 1, option 2, or option 3.
      **Option 3 is applied and recommended**; 1 is dead; 2 awaits the USER.
- [ ] If option 2: the CPV issue is filed and its URL recorded in `external-refs:`.
- [ ] A decision is recorded on which side of the mismatch is wrong — CPV
      linting `design/`, or `.markdownlintignore` claiming it should not. The
      evidence now favours **neither being "wrong" about linting**: the findings
      were real defects. What IS wrong is the ignore file's comment, which
      promises an exclusion no tool has ever honoured.

## Notes and lessons learned

**A COMMIT MESSAGE MUST CARRY THE SAME HEDGE THE CARD CARRIES — history is
where an over-confident claim survives longest.** Commit `595a3a9d` says
*"repairing 37 MD056 defects"* and *"cli2 has **never** supported
`.markdownlintignore`"*. Both are correct, and both are stated more firmly than
the card behind them: 37 is a **derived** total (19 listed + 18 found after,
with a composition argument), and "never" quantifies over cli2's whole history
from a probe of exactly one version, which the card explicitly caveats. Neither
is worth rewriting history for — the TRDD id in the subject leads to the
qualified version, which is the mechanism working. But this is `d4e5f055`'s
defect in miniature, committed by the very card that documents it: **write a
derived count as derived ("19 listed + 18 found after"), and if the card hedges,
the message hedges.** A commit message is read by people who will never open the
card.

**IDENTIFY THE BINARY BEFORE PROBING ITS BEHAVIOUR.** The entire card — five
candidate mechanisms, three probes, two of my own wrong verdicts — existed
because nobody asked *which tool runs*. One line, `cmd =
_resolve("markdownlint-cli2")`, answers it, and `markdownlint-cli2` simply has
no `.markdownlintignore` support. `markdownlint-cli` (v1) and `markdownlint-cli2`
are different programs with different config surfaces and different flags, and
a probe run against the wrong one measures a different program than the one
under test. **Establish identity and version first; it is one grep and it
retires whole hypothesis families.**

**Reading the CALLER's argv does not survey the CALLEE's configuration
surface.** I read CPV's argv, found no ignore flag, and wrote "the lever space
is now SURVEYED". Both working levers act on markdownlint-cli2's *own*
per-file config discovery, which by definition never appears in CPV's argv.
The counter-example was inside the tree I was reading: the pinned checkout uses
inline `markdownlint-disable-next-line` on ~15 of its own TRDDs. **An absence
in the caller is evidence about the caller only.**

**Read the loop that EMITS the output, not just the function that computes it.**
`NIT=20` was a hard `if surfaced >= 20: break`, so the finding list was
truncated and 18 real defects were never printed. I had read `lint_markdown`
and still recorded the short list as an unexplained "loose end". **Any capped
or paginated report is "≥ N", never "N"** — and a report sitting exactly on a
round number deserves a grep for the cap before any conclusion is drawn from
its size.

**Source reading is stronger than probing and is not sufficient.** Probes 1–3
cost real effort and settled little; reading `cpv_lint_engine.py` retired three
candidates in twenty minutes. But the same reading *also* produced two wrong
verdicts and missed both working levers and the truncation cap. **Read the
source first, then still probe the specific behaviour you intend to rely on** —
the reading tells you where to point the probe, it does not replace it.

**A probe is only evidence if it manipulates the variable it names.** Probe 3
excluded a file with `.git/info/exclude` and concluded about `.gitignore`. Those
are the same thing *to git* and different things to a hand-rolled parser — and
the system under test never used git. The probe was well-run, cleanly reverted,
and void, which is the dangerous combination: nothing about running it signals
that it measured the wrong variable. **Before running a probe, state what a
NEGATIVE result would look like and check the mechanism could produce one.**

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
