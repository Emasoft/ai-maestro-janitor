---
trdd-id: ZQ02QG1L
title: Compose every janitor handoff out of process — no model turn spent authoring one
column: blocked
blocked-by: [L46IG69Y]
pre-block-column: complete
created: 2026-09-03T18:09:45+0200
updated: 2026-09-04T03:40:00+0200
current-owner: main-session
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: [L46IG69Y]
implementation-commits: []
---

# Compose every janitor handoff out of process — no model turn spent authoring one

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

- **Audit is done.** `reports/handoff-cost-audit/20260903_175606+0200-handoff-zero-cost-audit.md`
  holds the per-surface cost table. Read it before touching anything.
- **CORRECTED 2026-09-03, after tracing the live pipeline.** An earlier revision of this
  block named `run_llm_ext_summary` + `compose_handoff` as the engine to reuse. That was
  wrong, and the mistake came from a grep that EXCLUDED the file the caller would live in.
  Those two, plus `compose_template_handoff` and `HandoffInputs`, have **no production
  caller anywhere** — they are fully tested but unwired, a richer composer that was
  designed and never landed. Do not build on them without deciding that question first.
- **The LIVE zero-cost pipeline, end to end, is three steps.**
  1. `scripts/summarize_previous_session.py` — the ONLY writer of handoff files. It calls
     `external_clear.summarize_with_retry(transcript, deadline)` (not `run_llm_ext_summary`)
     and writes the raw llm-ext text via `handoff_files.write`.
  2. `external_handoff_clear.py` does NOT compose synchronously. It captures the transcript
     as the summary source, writes `summary-pending.json`, takes a hold, and delegates.
  3. The cleared session's SessionStart hook `_inject_post_clear_handoff` reads the whole
     group with `handoff_files.newest_group(sd)` and injects it before the first turn.
- **So the gap is smaller than the card first claimed.** A zero-cost transcript-to-handoff
  path already runs in production. It is aimed at the PREVIOUS session at SessionStart.
  What is missing is the same thing aimed at the CURRENT session, on demand.
- **NEXT ACTION** — write `scripts/compose_agent_handoff.py` modelled directly on
  `summarize_previous_session.py`, differing in one respect: resolve the CURRENT transcript
  rather than excluding it. Verified 2026-09-03 that newest-by-mtime does return the live
  session's own `.jsonl` mid-session. Reuse `summarize_with_retry` and `handoff_files.write`;
  do not reach for the unwired composers.
- Then collapse `skills/janitor-write-handoff/SKILL.md` step 2 to a call of that script.
- Then point `skills/janitor-handoff-and-clear/SKILL.md` step 2 at the existing
  external composer instead of asking the model to author the link-only index.

## Why

The owner's directive of 2026-09-03: every janitor command must cost zero model tokens.
Where intelligence is genuinely needed, it comes from the `llm-ext` CLI running against
its own free models, out of process, never from this session's window.

The audit found three surfaces that violate this. All three ask the model to author prose
that a script plus `llm-ext` can produce from material already on disk.

| surface | what the model does today |
|---|---|
| `janitor-write-handoff` | authors a rich six-section semantic handoff by hand |
| `janitor-handoff-and-clear` | authors the link-only handoff index by hand |
| `janitor-compact-context` | composes a one-line resume directive |

## The three zero-cost engines that already exist

Nothing new has to be invented. The work is routing.

- `scripts/external_handoff_clear.py` composes a handoff from on-disk facts, TRDD `## STATE`
  blocks, git log and the findings ledger, then upgrades the prose through `llm-ext`.
  Reached today by exactly one skill, `janitor-externalized-compaction`.
- `scripts/summarize_previous_session.py` summarizes a completed session transcript through
  `llm-ext` at SessionStart. Proves the transcript-to-summary path works unattended.
- `scripts/hooks/pre-compact-handoff.py` writes the mechanical handoff on every compact,
  free, from git and the filesystem.

The gap is a semantic handoff for the CURRENT session. That is the only new code.

## Scope boundaries

- The resume push is **not** overhead. A resume must eventually hand control to the model,
  so that turn is the work itself.
- Native `/compact` re-reads the whole window. That cost is inside Claude Code and cannot
  be removed from this plugin. `janitor-compact-context` already tells the model to prefer
  the cheaper siblings.
- The harvest precondition in `janitor-handoff-and-clear` step 1 stays. It captures
  knowledge that is not yet on disk, which no out-of-process composer can see. Deleting it
  would lose facts, not save tokens.

## Scope widened by owner directive, 2026-09-03

> *"all operations of compacting/handoff/etc. are executed by scripts (via llm-ext if
> necessary) and never by agents. no token should be used or consumed in the operations
> related to resume/clear/compact/rearm/etc."*

| operation | reachable at zero model cost? | why |
|---|---|---|
| compose a handoff | **yes** | script + `llm-ext`, out of process. The engine exists. |
| clear / compact trigger | **already is** | `clear_trigger.py` / `compact_trigger.py` are pure scripts. |
| verify across the clear | **already is** | `handoff_clear_verify.py` is a pure script. |
| inject the handoff on resume | **already is** | the SessionStart hook injects it before the first turn. |
| decide to shrink | **yes, not yet wired** | `external_handoff_clear.py` decides in-script, but only a model invoking the skill calls it. A hook or the daemon could. |
| **the resume turn itself** | **no — and it is not overhead** | a resume exists to hand control back to the model; that turn IS the work. |
| **re-arm** | **NO — platform limit** | `CronCreate` is a MODEL tool. No script can schedule a cron; the janitor's own bootstrap types `/janitor-arm` into the pane for exactly this reason. Make it RARE (7-day expiry + SessionStart re-plumb), not free. |
| native `/compact` | **no** | Claude Code internal; it re-reads the window. Avoid it, cannot cheapen it. |

**The honest summary: everything except the resume turn and the re-arm is reachable, and
most of it is already there but unreachable without a model deciding to call it.** The
remaining work is therefore mostly WIRING, not building — move the trigger from "a skill the
model invokes" to "a hook or daemon task that fires on its own".

## MEASURED 2026-09-03 — the raw summary is 31,897 bytes, and that decides the design

A real `compose_agent_handoff.py --dry-run` on this session produced **31,897 bytes**
against `HANDOFF_MAX_BYTES = 4096`. Nearly 8× over, and 4× worse than the "7 KB in
practice" figure in `compose_handoff`'s own comment — which is why this was measured
instead of assumed.

**Consequence 1 — the clear path must NOT reuse `compose_agent_handoff.py`.**
`clear_trigger.check_handoff_concise` would return `too-large` on every run, immediately
before an UNRECOVERABLE `/clear`. `janitor-handoff-and-clear` therefore needs
`external_clear.compose_handoff`, which allocates the scriptable facts first, then a
guaranteed tail slice, then hands the summary whatever budget remains, and emits an
unconditional `memgrep recall` line so the result always carries a reference. That is
precisely this problem, already solved and already tested.

**So the four "unwired" functions are not dead weight — three of them are the answer.**
`compose_handoff` + `compose_template_handoff` + `HandoffInputs` should be LANDED for the
clear path, not deleted. Only `run_llm_ext_summary` remains a genuine duplicate of the
live `summarize_with_retry`.

**Consequence 2 — a size gate is owed on the path already shipped.**
`janitor-write-handoff` now writes the raw summary with no bound, and
`on-session-start.py::_inject_post_clear_handoff` injects the whole handoff group into the
fresh context. A 32 KB handoff therefore rides forward on every later turn — trading the
authoring cost for a per-turn read cost, which is the trade `token-economy-agents-and-scenarios.md`
warns against. Not wrong for `/compact` (the window survives either way), but it should be
bounded. Simplest fix: give `compose_agent_handoff.py` a `--max-bytes` defaulting to
`HANDOFF_MAX_BYTES` and route it through `compose_handoff` too.

## Deliberately NOT in this task

The owner also asked that skills and files stop being reloaded each session, with the agent
merely told what was read last time. That is a separate and larger change, and the saving is
unproven: a note costs a line, and if the model re-reads anyway the cost is paid twice.
Measure first, in its own TRDD.

## Acceptance

Box status re-verified against code on disk 2026-09-04 (delegated read-only
audit, then the load-bearing negative re-checked by hand — report:
`reports/board-drain/20260904_031250+0200-zq02qg1l-box-verification.md`).

- [x] `scripts/compose_agent_handoff.py` exists, writes a handoff with no model turn.
      — landed in `f9bf82ed`.
- [x] `janitor-write-handoff` no longer instructs the model to author prose.
      — `skills/janitor-write-handoff/SKILL.md:17` describes the composer and
      `:45` invokes it (`uv run --script --quiet
      "${CLAUDE_PLUGIN_ROOT}/scripts/compose_agent_handoff.py"`).
- [x] `janitor-handoff-and-clear` step 2 delegates to the external composer.
      — DONE 2026-09-04. Was verified NOT done by hand first (a grep for
      `compose_agent_handoff|llm-ext|llm_ext` over the skill returned nothing,
      and step 2 read `### 2. Write the CONCISE, LINK-ONLY handoff` — only ONE
      of the two skills was converted in `f9bf82ed`). Step 2 is now the same
      one-command `compose_agent_handoff.py --project-root` invocation
      `/janitor-write-handoff` uses.
      **It fixed a SECOND defect in the same edit**: the step wrote to the FIXED
      `agent-handoff.md`, the path retired by TRDD-5RXBI65T for having several
      independent writers and no coordination — one silently destroying another,
      measured twice in two days. The sibling skill already carried an explicit
      "never Write to `agent-handoff.md`" warning while THIS skill still
      instructed exactly that. The composer writes the per-session/ts/pid name
      through `handoff_files.write`, the only writer.
      Swept the repo for the retired path per the breaking-change rule: fixed a
      further 3 references in this skill (the `clear_trigger.py --directive`,
      the resume-flow description, the Resources entry) and 1 in `README.md`.
      The remaining hits are all in TRDD cards that DOCUMENT the retirement and
      are correctly historical.
- [x] Each converted skill degrades to the on-disk template when `llm-ext` is absent,
      exactly as `external_handoff_clear.py` already does. A missing CLI is never a
      reason to skip the handoff.
      — DONE 2026-09-04, unblocked by the box above. Both skills now carry the
      same stdout table: a path → proceed; `SUMMARY_FAILED <reason>` → NOT an
      error, the free mechanical `precompact-handoff.md` still covers the
      resume, say so and proceed; `NO_TRANSCRIPT` → report, nothing written.
      Both also carry the explicit prohibition that matters more than the table:
      **do not fall back to authoring the handoff yourself** — that is the cost
      the card exists to remove, and on the clear path it would be spent at the
      worst possible moment. The degradation is to the mechanical handoff, never
      to the model.
      The table was VERIFIED against the script, not transcribed from the
      sibling on faith (a review correctly flagged that I had copied it):
      `compose_agent_handoff.py:69` prints `NO_TRANSCRIPT` and `:77` prints
      `SUMMARY_FAILED {reason}`. What is NOT verified is the box's comparative
      clause — "exactly as `external_handoff_clear.py` already does" — since I
      did not read that script's absent-CLI path. The tick rests on the two
      skills sharing one composer whose literals are now confirmed, not on a
      comparison to `external_handoff_clear.py`.
- [x] `uv run pytest` green; `uv run ruff check scripts tests` and
      `uv run mypy scripts/ --ignore-missing-imports` clean.
      — TICKED AGAINST A NAMED SHA: `f2599bb0`, working tree clean
      (`git status --porcelain` empty, so HEAD and the tree are identical), all
      three run on THAT tree after every other box was closed:
      `ruff check scripts tests` → All checks passed; `mypy scripts/
      --ignore-missing-imports` → no issues in 504 source files; the full suite
      → 16370 passed, 1 skipped, 8 subtests passed.
      The earlier refusal to tick was correct and is why this reads the way it
      does: the delegated audit was told not to run these, so the box had no
      independent verification, and this session was twice caught citing a suite
      run that predated part of what it claimed to cover. A gates box is only
      meaningful against a tree you can name.

> **COLLAPSE THIS CARD when L46IG69Y closes and it returns to `complete`.** It now
> carries five layers — why-blocked, what-was-traded, two retracted findings, and
> acceptance boxes with their own embedded corrections — and a reader must
> reconstruct four reversals to extract the three facts that matter: the second
> skill is converted, it is unpublished, and a concision interaction is unresolved
> (L46IG69Y). Collapsing NOW risks dropping a correction that is still
> load-bearing; collapsing at the unblock is one clean pass. Do not add a sixth
> layer instead.

## Why this card is `blocked`, not `complete` — the SAME rule violation, one card later

Every acceptance box is closed. The card was moved to `complete` and archived
anyway, and that was wrong for exactly the reason S7FIQTCO was wrong hours
earlier: it carries an unfixed consequence THIS card's change introduced (the
concision-check interaction below), and an effect of a change is that change's
post-condition — an EHT. `eht:` was `[]`.

The rescuing argument does not work, and it is worth naming because it is
tempting: *S7FIQTCO's regression was in shipped code, this one is only a
downstream WARNING.* The EHT rule is about effects, not severity — and I
explicitly rejected the structurally identical "but the defect is broader"
argument on S7FIQTCO. Applying a rule to one card and finding an exception for
the next is how a rule stops being one.

Worse, the consequence was living only as PROSE on an ARCHIVED card: no
acceptance box, no `todo` entry, nothing that would ever surface it again.
Archiving made it strictly less likely to be fixed than leaving it open.

Now filed as TRDD-L46IG69Y with its own acceptance criteria; this card is
`blocked` on it with `pre-block-column: complete` recording that acceptance was
already met.

## What the conversion TRADED AWAY, recorded because it is a real consequence

The old step 2 imposed a shape by construction: link-never-inline, exhaustive by
reference, no duplicated TRDD `## STATE` blocks, "a few hundred bytes to low KB".
`compose_agent_handoff.py` imposes none of that — it is an `llm-ext` PROSE
SUMMARY of the transcript. So the link-only contract is gone from this path, and
that was not a stated goal of the card.

**This skill is the first to put composer output in front of the concision
check**, which makes it a NEW interaction rather than an inherited one: the
already-converted `/janitor-write-handoff` feeds `/compact`, which checks
nothing, whereas this skill's step 3 feeds `clear_trigger.py`, which does:

- `_HANDOFF_MAX_BYTES = 4096` (`clear_trigger.py:124`)
- `_REFERENCE_RE = re.compile(r"\[\[|ATOM-[A-Z0-9]|TRDD-[A-Za-z0-9]|memgrep|#\d+")`
  (`:130`)

Nothing in the composer emits those tokens BY CONSTRUCTION, and a prose summary
can exceed 4 KB. So `no-references` and/or a bloat warning may now fire on every
clear.

**Not a blocker, and the reason is verified rather than assumed:**
`clear_trigger.py:791` states the contract as *"ABSENCE IS FATAL; shape is
WARN-only"* — an absent handoff REFUSES the clear (owner invariant 2026-08-28,
after a session woke blank mid-migration), while a bloated or reference-free one
still clears, because losing the session to enforce concision is the worse
trade. So the failure mode is stderr noise, not a lost context.

**It is still worth fixing, for a reason this repo already learned once:** a
warning that fires on every run carries no information and trains its reader to
ignore it (the same argument `stage_install_smoke` makes about its async-lag
note). Either the composer should emit reference tokens, or the check should
recognise composer-authored handoffs, or the constants should move. UNCERTAIN
and not measured: an `llm-ext` summary of a session that discusses TRDD ids
would likely reproduce them, so `_REFERENCE_RE` may match incidentally — which
would make the warning INTERMITTENT, which is worse than always. Settling it
needs one real `/janitor-handoff-and-clear` run with the composer's output fed
to `check_handoff_concise`.

Deliberately NOT fixed here: the card's boxes are about removing model
authorship, this is a downstream shape contract, and guessing at a fix without
the measurement above would be the same shape as the remedies this session had
to retract.

## A second interaction I asserted and then DISPROVED with one grep

Briefly recorded here as a WRONG finding, because the way I reached it is worth
more than the finding was.

`compose_agent_handoff.py:95` writes `.janitor/state/resume-directive.txt`, the
one-shot pointer `post-compact-resume.py` consumes on PostCompact. I reasoned
that on the CLEAR path no compaction follows, so the file would be left armed
for an unrelated later compaction — and wrote ~25 lines about it, deferring the
fix as "not fixed blind".

**It is not a bug.** `clear_trigger.py` already owns that file — and the
load-bearing evidence is the SUCCESS path, not the failure path. `:219` is
`_write_directive`, *"Persist the one-shot resume pointer (shared with the
compact path)"*, which `_atomic_write`s `resume-directive.txt` with
`clear_trigger`'s OWN `--directive`. So on the clear path the composer's
directive is not left stale; it is overwritten by the one that belongs to this
path.

**Two earlier drafts of this retraction cited `:503-506` and BOTH were wrong,
in opposite directions.** The first said it "unlinks on chain failure"; the
second kept that while noting failure-path evidence proves nothing about the
success path. Reading `:498-514` to the end shows it does not unlink at all —
it is a comment explaining why there is **deliberately NO cleanup**, because a
2026-08-02 review found the old unconditional unlink "was deleting a directive
another flow owned, breaking its pending resume". That comment is affirmative
support for the conclusion: the sharing of this file was already reasoned about
carefully by someone who chose NOT to touch it.

So the finding is retracted on `:219` alone, and the lesson compounds: I
retracted a hazard using a line reference I had not read, then defended the
retraction with the same unread reference, and the actual settling fact was in a
different function. Three passes over one file, each stopping at the first thing
that looked like an answer. Two further facts I had not checked also blunt it: the recorded
directive points at a GLOB (`the newest agent-handoff-*.md`), so it self-corrects
to whatever handoff is newest when read; and any intervening compaction
overwrites the file via `state.atomic_write` on the same path.

**The lesson, which is the reason this stays on the card:** the fix here was one
grep, and I wrote a paragraph instead. "Recorded, not fixed blind" is the right
call when the choice between fixes genuinely needs a measurement — as it does
for the concision-check finding above. It is a hedge when the question is
answerable by reading one file, and using it there produces confident prose
about a hazard that does not exist. If the prose explaining a finding would be
longer than the check that settles it, run the check.

## RETRACTED — "the benefit is zero on this host" was FALSE. Measured below.

The section that follows was committed in `9df68b77` and is WRONG. Kept, because
how it was wrong is the actual finding.

**What I checked:** one file — `.../3.4.13/skills/janitor-write-handoff/SKILL.md`
— found zero `compose_agent_handoff` refs, and generalised to "the installed
cache predates the conversion; the benefit is zero here". I did that in a commit
whose own stated lesson was *"check the loader, not the file."*

**TWO DIFFERENT KINDS OF EVIDENCE, kept apart on purpose** — conflating them is
how the original error happened:

*What the LOADER says* — `~/.claude/plugins/installed_plugins.json`: no
local-scope entry names this project, one `user`-scope entry, version **3.4.14**.
That is the resolution fact.

*What the FILES contain* — grep counts below. That is a fact about contents, and
it only matters once the loader fact tells you which version to grep:

| | `janitor-write-handoff` | `janitor-handoff-and-clear` |
|---|---|---|
| **3.4.13** — what THIS SESSION loaded | 0 composer refs | 0 |
| **3.4.14** — what is INSTALLED (user scope) | **2 refs — LIVE** | 0, still hand-authors |

So box 2's conversion (`f9bf82ed`) SHIPPED in 3.4.14 and IS live on this host.
Only box 3's — `janitor-handoff-and-clear`, converted this session — is
unpublished. The benefit is HALF realised, not zero.

**The real finding, which is the one worth keeping:** this session loaded
**3.4.13** while **3.4.14** is installed — so the hand-author instruction I
obeyed came from a version already superseded on disk. That is the
rollout-staleness family this repo already documents
(`memgrep recall "the fix is published but the bug keeps happening"`).

**That is a STATE, and the mechanism behind it is NOT established here.** A
draft of this line asserted "a session's skill text is fixed at start and does
not follow an upgrade". That is one explanation; a cached conversation prefix,
or skills resolving differently from the cron stub (which this repo documents as
auto-rolling to the newest cached version on each fire), would look identical
from inside the session. Measured: 3.4.13 text loaded, 3.4.14 installed. NOT
measured: why. Saying which would need a controlled upgrade mid-session, and
asserting it from one observation is the same move this whole section retracts.

VERIFIED rather than inferred, since the retraction turns on it:
`installed_plugins.json` has ZERO local-scope entries whose `projectPath` is this
repo, and exactly one `user`-scope entry, at 3.4.14. A local entry would have
outranked user scope — several exist for OTHER project paths — so this was worth
checking rather than assuming.

**Two lessons, and the second is sharper than the first:**
1. "Installed" has THREE distinct values here — what is in the repo, what is in
   the installed cache, and what THIS SESSION loaded. A claim about any one of
   them says nothing about the others.
2. I asserted a lesson and violated it in the same commit. Writing "check the
   loader, not the file" does not constitute checking the loader; `installed_plugins.json`
   is one read and settles which version a project resolves to.

## THE ORIGINAL (WRONG) SECTION FOLLOWS — see the retraction above

Measured 2026-09-04, one hour after the conversion landed: I invoked
`/janitor-write-handoff` and it told me to author the prose myself, so I did —
by hand, with Write, which is exactly what this card exists to stop.

That is not a lapse, it is the deploy boundary. The skill that LOADED was the
installed cache
(`~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.4.13/skills/janitor-write-handoff/SKILL.md`),
which contains **zero** occurrences of `compose_agent_handoff` and still says at
line 53: *"Author a dense, semantic handoff and Write it"*. My conversion is in
the SOURCE tree, unpublished. Skills load from the cache; only a publish+install
updates it.

**So this card's saving is currently unrealised on this machine**, and will stay
so until a release ships. Anyone reading the closed boxes and expecting
zero-model-cost handoffs today would be wrong.

The pairing with TRDD-CN62E66F is what makes this worth recording: both asked
"is the committed fix in effect?" and the answer differed by mechanism. The hook
runs from the TRACKED SOURCE (`core.hooksPath = git-hooks`), so its fix was live
the moment the file was saved. A skill runs from the CACHE, so its fix is live
only after a publish. **"Committed" and "in effect" are different facts, and
which one you have depends on the loader — check the loader, not the file.**

## Notes and lessons learned
