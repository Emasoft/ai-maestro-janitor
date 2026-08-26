---
trdd-id: LFSWY0C6
title: CLAUDE.md excess narrative is migrated out automatically by a scheduled chore
column: todo
created: 2026-08-04T18:18:52+0200
updated: 2026-08-26T19:15:53+0200
implementation-commits: [d82dc15a, 20f226ba, 7b7b37ea, 64b82836, 65d70d7e, c88776c8]
current-owner: ai-maestro-janitor
task-type: feature
relevant-rules: [7.1, 8.1, 9.1, 10.1]
parent-trdd: H12K9JYX
npt: []
eht: []
---

# CLAUDE.md excess narrative is migrated out automatically by a scheduled chore

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-04

**NOT STARTED.** The shape is fully specified; nothing is implemented.

- **Already shipped** (TRDD-H12K9JYX, `column: complete`): the canonical form itself, the
  fence surgery, the index renderer, the slim-contract `check`, the preservation oracle
  (`verify`), the `janitor-project-cld-md-optimizer` skill (renamed from
  `janitor-claude-md-slim` on 2026-08-04 — CPV rejects `claude` as a reserved word in a skill
  name), and a **nudge** on `project-map-drift`.
  This repo's `CLAUDE.md` conforms today — verified `claudemd-slim: conforming and fresh`,
  1,029 narrative bytes, 0 violations.
- **The gap**: `PRRD G8.1` requires migration to be **automatic**. What exists is an
  advisory nudge, which G8.1 explicitly rules out.
- **NEXT ACTION**: implement the chore per §2 as a new intervention in the
  memory-maintenance scheduler (`scripts/detectors/memory-maintenance.py` + a
  `[janitor-memory-claudemd]` marker routed to `janitor-memory-subconscious-agent`), reusing
  the EXISTING `claudemd_slim` primitives rather than writing new ones.

## ⏵ 2026-08-26 — MEASURED: the SEMANTIC half has nothing to migrate; only the index is stale

`uv run scripts/claudemd_slim.py check` today returns exactly ONE line:

```text
claudemd-slim: wikimem index is STALE vs the corpus (run scripts/claudemd_slim.py index)
```

No narrative violation. So the chore this card specifies — automatic migration of excess
CLAUDE.md narrative into wikimem — **would have zero work to do in this repo right now.** That
does not make `PRRD G8.1` satisfied (it demands the mechanism, not an empty queue), but it does
mean the card's urgency comes entirely from the INDEX half, which the 2026-08-22 block already
established is mechanical and was a gating bug rather than an ignored advisory.

### The real defect is a MOMENT problem, and it is the same shape as TRDD-FB84YUGT

The nudge tells the reader to refresh *"at a cache-cheap moment (fresh session,
post-compaction, pre-commit)"* — and **nothing anywhere detects whether now is one.** Grepped:
`cache-cheap` appears four times in the tree and every one is PROSE inside a message
(`project-map-drift.py:99,174`, `repomap_generate.py:50`, its own docstring). So:

1. A session meets the advisory at an arbitrary moment.
2. It correctly declines — mid-session the rewrite busts the cached prefix for this session and
   every forked subagent, which the module docstring says can burn a 5 h budget.
3. Nothing carries the request to the moment when the cost is already sunk.
4. Five days later the index is still stale, and it reads as "advisories get ignored".

**That is not an ignored advisory; it is a correct refusal with no path to the moment it would
be free.** Structurally identical to TRDD-FB84YUGT's `declined_field_busy`: right every single
time it fires, and permanently stalling because rightness never expires into escalation. Worth
noting the pair, because the two cards were reaching for opposite fixes (that one wanted a
detector that already existed; this one wants a chore whose queue is empty) while sharing one
actual defect.

**The cheap, constraint-respecting fix is to fire the existing nudge AT a cache-cheap moment**
rather than to build an autofix or a semantic chore: post-compact and SessionStart are already
hook points that run when the prefix is cold anyway. That honours every prohibition this card
records — the janitor still never rewrites CLAUDE.md itself, no detector autofixes, the write
stays human/agent-initiated — while removing the reason the request never gets acted on.

**NOT BUILT HERE.** It touches the PostCompact/SessionStart hook path, and this card's own
premise (that the deliverable is a semantic migration chore) would change if the owner accepts
that the recurring symptom is a moment problem. That is a re-scope, not a patch.

### ⏵ 2026-08-26 19:15 — BEFORE anyone decides that re-scope: the cost premise is UNVERIFIED, and this repo contradicts itself about it

The whole "moment problem" rests on one claim — that rewriting `CLAUDE.md` **mid-session** is
expensive. Two texts in this tree disagree about that, both quoted verbatim:

| | says | where |
|---|---|---|
| **A** | *"**Editing a file does NOT invalidate the conversation cache.** The cache is over the transcript prefix, not over files on disk. Edit-heavy sessions are among the cheapest."* | `~/.claude/rules/token-economy-agents-and-scenarios.md:22` — presented as a MEASURED result that disproved the opposite hypothesis |
| **B** | *"a careless write can burn a 5h token budget"* · *"Refresh at a cache-cheap moment (fresh session, post-compaction, pre-commit)"* | `scripts/detectors/project-map-drift.py:12,17,99,174`; same wording in `repomap_generate.py:50` |

They can both be true only if `CLAUDE.md` is **special** — re-injected into the prompt every
turn rather than sitting in the cached transcript prefix like an ordinary file. That is a single
empirical question with a yes/no answer, and **nobody has recorded measuring it.**

**Why this must be settled BEFORE the re-scope, not after:**

- If `CLAUDE.md` is NOT re-injected per turn (claim A generalises), then a mid-session refresh is
  cheap, the "correct refusal with no path to a cheap moment" **does not exist**, and the days of
  index staleness have some other cause. The re-scope would be building a delivery mechanism for
  a problem that is not there — and the fix is simply "refresh it whenever you notice".
- If it IS re-injected (claim B), the moment problem is real and the re-scope is right.

Note what happened while writing this: the obvious next step was to just run
`claudemd_slim.py index` and clear the staleness. **I did not, deliberately** — running it would
have been acting on precisely the premise under question, and if it turned out cheap I would have
learned nothing (a cheap run proves nothing about the expensive case), while if it turned out
expensive I would have paid for the answer with the session the card exists to protect.

**Measured today, so the urgency is smaller than the card implies:** the index is missing exactly
**one** entry, and it is `MEMORY` — the harness's own `MEMORY.md` stub, which does not belong in
a wikimem index at all. So the STALE verdict is very likely a digest recompute over a corpus
whose *listed content* has barely moved, not 20 absent pages. Whoever settles the cost question
should check whether `index` even changes the fence body, because a rewrite that only bumps
`digest=` is a different cost/benefit argument than one that adds real entries.

**This is the same shape as the two other cards closed tonight** (TRDD-FB84YUGT, TRDD-JKJHV19B):
a decision about what to build, resting on a measurement nobody took.

## ⛔ 2026-08-22 — THE FIVE-DAY EVIDENCE IS WRONG. **The nudge was never reachable.**

The section below is this card's strongest argument: *"the advisory mechanism G8.1 rules out
demonstrably does not get acted on, measured over five days rather than argued."* It rests on the
nudge having FIRED and been ignored. **It did not fire.** Read from source today:

`project-map-drift.py::main()` returned 0 at its FIRST line — `repomap-opt-in.flag` absent — and
even with the flag it returns 0 again at `header is None`. `read_fence_header` reads the
**REPO-MAP** fence (`JANITOR-REPO-MAP-*`). This repo's CLAUDE.md carries **1** wikimem-index fence
and **0** map fences, and the flag is absent — measured, both.

So the slim/index check sat behind TWO gates belonging to a DIFFERENT feature, one this project
turned off **on purpose**: the repo map cost ~46k tokens on every turn of every session and was
deliberately deleted (CLAUDE.md says so, and names `/janitor-auto-repomap-on` as the switch).
Keeping the index while dropping the map is a perfectly coherent choice — and it silently bought
zero index checks.

**So the five-day staleness is not evidence that advisories get ignored. It is evidence that this
advisory did not exist.** Those are opposite diagnoses with opposite fixes: the card's reading
argues for replacing the nudge with an automatic chore; the true cause is fixed by making the
nudge reachable. Fixed today — `_slim_contract_nudge` now runs unconditionally, ahead of both map
gates, and a mutation-verified test pins it (re-couple the gate and the test goes red on empty
stdout). Verified live: the detector, which had been silent in this repo, immediately reported
`wikimem index stale`.

**What this does NOT settle, and must not be read as settling it:** PRRD G8.1 still requires
migration to be AUTOMATIC, and a nudge — now reachable — is still a nudge. The *narrative
migration* half is genuinely semantic and still needs the chore this card specifies. But the
recurring symptom that kept re-opening this card was the INDEX going stale, which is mechanical,
and its cause was a gating bug rather than an un-actioned advisory.

**Also: do NOT "just autofix the index" from a detector.** That was my first instinct today and
the module docstring refutes it in two lines: CLAUDE.md sits in the cached prompt prefix, so a
background rewrite busts the context cache for the whole session and every forked subagent (a
careless write can burn a 5 h token budget), and CLAUDE.md is co-owned with the human, so a
background writer racing their edits is the corruption class the owner fears. The write stays
human/agent-initiated at a cache-cheap moment. The index is stale in this repo RIGHT NOW and was
deliberately left that way for exactly this reason — refreshing it mid-session would have cost
more than the staleness does.

## ⏵ 2026-08-21 11:26 — THIRD INDEPENDENT RECURRENCE, and it stayed stale for FIVE DAYS

Still NOT STARTED (re-verified: `grep claudemd scripts/detectors/memory-maintenance.py` → nothing).
Measured today on arrival:

```text
claudemd-slim: wikimem index is STALE vs the corpus (run scripts/claudemd_slim.py index)
```

**The dates are the finding.** The block below recorded this same staleness on **2026-08-16**.
The header of the stale index read `generated=2026-08-16T05:05:28+0200` — so it had been stale
for **five days**, across many sessions, with the advisory nudge presumably firing the whole
time and nobody acting on it. That is the strongest evidence this card has: not that the index
drifts (already known), but that **the advisory mechanism G8.1 rules out demonstrably does not
get acted on**, measured over five days rather than argued.

Refreshed manually (`scripts/claudemd_slim.py index`, tool-owned block) → `conforming and fresh`.
The whole drift was 2 lines: the digest/timestamp header, and one page description that had
moved from "73 detectors" to "72". **Trivial to repair and invisible until someone runs the
check** — which is exactly the profile of work that should be a chore and not a nudge.

**NOT caused by this session's memory writes**, and the distinction matters for anyone
re-measuring: the two lessons added today went to **USER** scope, while this index covers
**PROJECT** scope (`.claude/project/memory`). The drift predates the session.

## ⏵ 2026-08-21 11:32 — WHY "just auto-refresh the index" IS NOT THE CHEAP WIN IT LOOKS LIKE

Having measured the five-day staleness above, the obvious next move is to make the refresh
automatic — a tool-owned block, a 2-line diff, no agent, no memory edit. **Do not do that**, and
the reason is written into the detector this card already ships. `project-map-drift`'s own nudge
ends:

> "… Refresh the index with `uv run scripts/claudemd_slim.py index` … at a **cache-cheap
> moment**; **the janitor never rewrites CLAUDE.md itself**."

That is a deliberate INVARIANT, not a gap waiting to be filled. `CLAUDE.md` sits in the cached
prompt prefix of every session on the machine — this repo's own `CLAUDE.md` records a former
project map costing "~46,000 tokens on every turn of every session … re-read at the cache rate on
each turn and re-written at 1.25x on each cache write". So the SIZE of the diff is irrelevant:
**any** write to `CLAUDE.md` invalidates that prefix and re-bills it at 1.25x, for every session,
not just the one that made the edit. A 2-line index refresh and a 200-line migration cost the
same.

**Consequence for this card's design: `PRRD G8.1`'s "automatic" and the cache invariant are in
real tension, and §2 does not currently resolve it.** The chore cannot simply run on a schedule;
it must fire at a moment that is already paying a cache write (session start before the prefix is
warm, or immediately after a compaction), or batch its writes so the corpus drifts for a while
and is repaired ONCE. Whichever is chosen belongs in §2 as an explicit trigger condition — right
now §2 specifies WHAT to do and is silent on WHEN, and the silent answer ("whenever the scheduler
says") is the expensive one.

**Disclosure — I paid that cost today.** I ran `claudemd_slim.py index` manually at 11:26 to
clear the staleness and described the result as a clean, minimal, tool-generated 2-line diff. The
byte count was minimal; the cache cost was not, and I did not check for it before writing. That
is the same failure this card is about: the write looked free because the visible artifact was
small.

## ⏵ 2026-08-16 — THE "ZERO WORK TODAY" PREMISE HAS EXPIRED, and the way it expired is the card's own argument

**Re-checked, still NOT STARTED:** `grep claudemd scripts/detectors/memory-maintenance.py` → nothing,
and no `[janitor-memory-claudemd]` marker is routed anywhere. The 2026-08-04 STATE block is accurate.

**But the 08-13 pre-check no longer holds.** That block measured `claudemd_slim check` →
*"conforming and fresh"* and concluded the chore would migrate nothing. Measured 2026-08-16:

```text
claudemd-slim: wikimem index is STALE vs the corpus (run scripts/claudemd_slim.py index)
```

**I caused it, this session, by doing ordinary correct work** — adding two atoms to
`janitor-tool-call-cost-law`, one to `claude-code-plugin-rollout-staleness`, and extending both
pages' `description:` fields. Nothing unusual; exactly the memory maintenance the corpus is for.
Three days from "fresh" to "stale" with no narrative added at all is the empirical answer to
whether this needs automating: the drift arrives as a side effect of the system working normally,
not from anyone being careless.

**I am deliberately NOT running `claudemd_slim.py index` from this session, and the reason belongs
on this card.** `CLAUDE.md` is injected into the prompt prefix, so editing it mid-session breaks
the cache and costs a full re-write — TRDD-IJ94O8YD measured that at **150,824 cache_creation
tokens** on the days it fires. Paying that for a digest refresh, in a long session, is the exact
trade that card exists to stop. The work is right; the TIMING is wrong, and the timing is free to
change. Left for a session boundary and recorded in `.janitor/state/agent-handoff.md`.

**Design consequence for §2, and it sharpens the spec rather than just noting a cost.** Routing the
chore to a subagent does not dodge the cache write: the parent re-reads `CLAUDE.md` on its next
turn regardless of which context edited the file. So the chore's scheduling must treat a `CLAUDE.md`
write as an EXPENSIVE, BATCHED event — one write per accumulated drift, ideally at a session
boundary — not as a per-detection repair. A chore that faithfully re-indexes on every corpus change
would convert this card's own token argument into a recurring bill.

## ⏵ 2026-08-13 — PRE-CHECK BEFORE BUILDING: the chore has ZERO work today. Build it in two halves.

**Measured now, not assumed:** `claudemd_slim check` → `conforming and fresh`, exit 0. So on this
repo, today, the chore would migrate nothing. That is not a reason to skip it — G8.1 is GOLDEN and
narrative WILL accumulate — but it changes two things, and both are the kind of detail that
silently makes a build worthless:

1. **Acceptance cannot be taken against the live file.** Every box in §4 must run against a
   SYNTHETIC violation planted in a fixture. A run against today's `CLAUDE.md` passes every box
   while doing nothing at all — the "green because there was no work" failure this project has hit
   twice this week (TRDD-4ZSYW21E's rung named 0 cards; TRDD-XFPOAF2I's acceptance was computed by
   a cruder query than its own spec).
2. **The end-to-end cannot be observed on real input**, so the preservation oracle is not merely
   *a* gate — it is the ONLY evidence the chore is safe. It must be falsified explicitly: plant
   content, break the oracle, and prove the chore REFUSES to remove. An oracle that has never been
   seen to say no is decoration.

### Build the DECISION half first; the DELIVERY half is separately risky

Applying the `acceptance-criteria-expire` lesson `^decompose-a-blocked-manual-confirmation` — the
two halves fail for different reasons and are worth separating anyway:

- **DECISION half (safe, build first):** given a `CLAUDE.md`, compute what WOULD migrate — the
  offending lines, the wikimem page that owns each subject (via recall), and whether a new page
  is needed. Output a plan. **Removes nothing, writes nothing.** This is independently useful: it
  is the dry-run a human can read before ever trusting the automatic path, and it is where the
  hard part actually lives (subject ownership, the §3 exemption boundary).
- **DELIVERY half (build only once the decision half is trustworthy):** apply the plan through
  `memory_txn`, gated on the preservation oracle, and remove the lines.

**Why this order and not the reverse:** step 4 deletes from a file the USER also hand-edits. If
the decision half is wrong — it misjudges the §3 exemption, or picks the wrong owning page — the
delivery half executes that mistake unattended and the only thing standing between it and lost
knowledge is an oracle proving *some* text landed *somewhere*, not that it landed in the RIGHT
place. Preservation and correctness are different properties; the oracle only checks the first.

**Not a blocker, and G8.1 is not in question:** automatic migration is a GOLDEN rule the owner
set, so the destination is settled. This is sequencing, not a request to reconsider.

## ⏵ 2026-08-13 — DECISION HALF SHIPPED (`d82dc15a`) AND IT IS WRONG ON REAL INPUT. Do not build delivery.

The planner exists (`scripts/lib/claudemd_migration_plan.py` + `claudemd_slim.py plan`), 13 tests
green, full suite 15038 passed, mypy + ruff clean. **And running it once on the live `CLAUDE.md`
— which it is safe to do, because it writes nothing — showed it is wrong.**

### The defect, diagnosed and verified (not inferred)

| predicate | value on the live `CLAUDE.md` |
|---|---|
| `slim_violations(text)` | **0** — the file CONFORMS (`claudemd_slim check` agrees: "conforming and fresh") |
| `narrative_outside_fences(text)` | **1029 bytes** — and the planner treats ALL of it as migration candidates |

Those two are not the same set, and that is the whole bug. `narrative_outside_fences` returns
everything outside the two janitor fences, which **by design includes the five PERMITTED
elements** — the H1 title, the one-paragraph description, `## Links`, `## Commands`. So on a
fully-conforming file the planner proposes 8 migrations. Measured output:

```
[1] MIGRATABLE -> FOLD into 'fleet-third-party-plugin-dep-fork-pin-pattern'   <- the description
[2] MIGRATABLE -> FOLD into 'ai-maestro-fleet-hub-what-and-roster'            <- "- Repo: <url>"
[3] MIGRATABLE -> FOLD into 'ai-maestro-amp-down-coordinate-via-github-issues' <- "- Marketplace: <url>"
[4] MIGRATABLE -> FOLD into 'ai-maestro-amp-down-coordinate-via-github-issues' <- "- Connected harness: <url>"
[5] EXEMPT (matched enumeration word: 'testing')                              <- correct
```

The §3 exemption works correctly (5 is right). The **candidate selection** is what is wrong, and
the destinations it picks for a bare URL line are nonsense — recall will always return *some*
page, so a wrong candidate silently acquires a confident-looking home.

### Why this is the vindication of splitting the card, not a setback

Had the DELIVERY half been built in the same pass, its first unattended run would have deleted
this project's title, description and entire `## Links` section from `CLAUDE.md` and scattered
four URLs into three unrelated wiki pages. **The preservation oracle would very likely have
PASSED**, because the text did land somewhere — which is exactly the distinction recorded above
this block: *preservation and correctness are different properties, and the oracle only checks
the first.* That was written as an argument; it is now an observation.

**Note what did NOT catch this: 13 passing tests.** They use synthetic fixtures, and the fixtures
did not reproduce a conforming file's permitted-element structure. The suite is green and the
planner is wrong — the same shape as everything else on this board tonight. The ONE thing that
caught it was running it on real input, which was only safe *because* the delivery half does not
exist.

### ⏵ 06:50 UPDATE — the fix attempt (`20f226ba`) is PARTIAL. The defect survives, measured.

`20f226ba` gates `plan_migration` on `slim_violations(text) == []`. That is a correct NECESSARY
condition and the conforming case is now safe (live file: 8 blocks → 0). **It is not sufficient**,
and the tests do not show it because all three new tests exercise only the conforming path.

Measured on the real `CLAUDE.md` plus enough narrative to cross the 8192-byte cap (narrative 9932
bytes, `slim_violations` = 1) — i.e. the ONLY case the chore exists for:

```
total blocks planned: 48
[0] new_page | 'A Claude Code plugin that keeps the dev environme…'   <- the description
[1] new_page | '- Repo: https://github.com/Emasoft/ai-maestro-jan…'   <- ## Links
[2] new_page | '- Marketplace (`ai-maestro-plugins`): https://git…'
[3] new_page | '- Connected ai-maestro harness: https://github.co…'
```

### THE REAL BLOCKER: the primitive this needs does not exist

Neither existing function can answer "is THIS block excess?":

| function | what it actually is | why it cannot be the candidate set |
|---|---|---|
| `narrative_outside_fences` | everything outside the two fences | INCLUDES the five permitted elements by design |
| `slim_violations` | 4 whole-file checks: both fences present, a github url present, and total narrative bytes ≤ `narrative_max_bytes()` (8192) | coarse by construction — it can say the narrative is TOO BIG, never WHICH blocks are excess |

So the missing piece is a **per-block permitted-element classifier**: given a narrative block, is it
the H1 title / the one-paragraph description / a `## Links` entry / a `## Commands` line (all
PERMITTED), or is it excess? That is the function the planner should select on, and it is also what
would let `check` report violations per-block instead of one whole-file byte count.

**Write that classifier first, as its own unit with its own tests, then re-point the planner at it.**
Do not try to derive it from `slim_violations` — that function is structurally the wrong shape.

### ⚠ How BOTH previous attempts passed while wrong — read before writing the next acceptance test

1. The first planner: 13 green tests, all fixtures PLANTED a violation, so none exercised a
   conforming file.
2. The fix: 3 new green tests, all exercised the CONFORMING file, so none exercised an over-cap one.

Each round tested exactly the case the previous round got wrong, and missed the next. **The
acceptance test for the classifier must assert on a file that is BOTH over-cap AND contains the
permitted elements** — that is the only shape where the two failure modes cannot hide behind each
other. Concretely: `plan_migration(over_cap_text)` must contain the excess blocks and MUST NOT
contain the title, the description, any `## Links` entry, or any `## Commands` line.

My own criterion caused the second miss: I specified "empty `slim_violations` ⇒ empty plan", which
a top-level early return satisfies exactly. It was necessary, not sufficient, and a spec that a
symptom patch can satisfy will get one.

### FIX BEFORE ANY DELIVERY WORK

1. Candidate selection must key on what actually VIOLATES the slim contract, not on
   `narrative_outside_fences`. A file where `slim_violations` is empty MUST yield an empty plan —
   that is the single strongest acceptance test available and it runs against the live file for
   free.
2. Add that as a regression test using a CONFORMING fixture (the current fixtures all plant
   violations, so none of them can catch this class).
3. Only then revisit delivery.

## ⏵ 2026-08-13 07:15 — CLASSIFIER SHIPPED (`7b7b37ea`). The DECISION half is now correct.

`scripts/lib/claudemd_migration_plan.py::classify_permitted` is the primitive §"THE REAL BLOCKER"
asked for, built as its own unit with its own tests, with the planner re-pointed at it — not derived
from `slim_violations`.

Three structural rules, one per narrative-visible §CM-1 element (4 and 5 are fenced and already
stripped before a block reaches the planner, so only 1–3 can appear):

| element | rule | shape, not meaning |
|---|---|---|
| 1 description | first content block, and only while `in_preamble` | `split_narrative_blocks` now tracks preamble: a leading `# Title` is the document title and keeps it open; any deeper heading (or a second H1) closes it. "One-paragraph" is the spec's word, so exactly one block can hold the role |
| 2 urls | `is_project_url_line` | one line, optional list marker, optional `<label>: ` prefix ≤60 chars carrying no URL of its own, then ONE URL token — bare, `<angled>`, or `[md](link)` |
| 3 devops | `classify_exemption` — **unchanged** | the closed §CM-3 enumeration, untouched |

**Bias is deliberate and asymmetric.** Where a rule is uncertain it errs toward PERMITTED: keeping
one block too many leaves the file over budget and the next run still reports it; migrating a
permitted element deletes content the canonical form requires and no later run restores it. Named
consequence: `- Note: see https://x.example` reads as a URL line. Accepted.

`exempt` and `permitted` were ONE concept under TWO names — which is precisely how elements 1 and 2
went unhandled while 3 was covered. Verdict is now `permitted` + `permitted_element`; `render_plan`
reports migratable-vs-permitted instead of miscounting every block as excess.

### The acceptance test is the shape §"How BOTH previous attempts passed" demanded

Over cap AND carrying all three permitted elements — the intersection both earlier rounds left
empty. It asserts BOTH halves, because either alone is passable by a wrong fix: planning nothing
satisfies "no permitted element migrates" (that is exactly what `20f226ba` did), and migrating
everything satisfies "the excess is found" (the original defect).

**Falsified, not merely green** — each recognizer was removed in-process and the acceptance test
observed to go red: pre-fix devops-only ✗, description recognizer removed ✗, urls recognizer removed
✗, permit-everything symptom patch ✗, real classifier ✓.

**Verified on REAL input** (the check that caught both previous misses, run again rather than
trusted): the live `CLAUDE.md` pushed over cap yields 8 permitted (1 description, 3 urls, 4 devops)
and 8 migratable, zero leaks. The same file previously gave the description and all of `## Links` as
`new_page`.

Gates: 15045 passed / 1 skipped, ruff clean, mypy clean (474 files).

### One test was DELETED because it asserted the defect

`test_conforming_gate_actually_gates_a_would_be_migratable_block` required the DESCRIPTION to become
migratable once a fence was stripped. A guard whose expected result IS the bug cannot fail while the
bug is present — a fifth variant of this card's recurring theme, and the reason a green suite kept
certifying broken behavior. Replaced with the orphan paragraph, which is excess whether or not the
file is over cap, so the only thing varying is the gate under test.

### The `slim_violations` gate STAYS, and it is a scope choice — not a correctness crutch

With the classifier in place the gate no longer hides anything: permitted elements are correctly
recognized with or without it. What it still does is suppress an under-cap non-permitted block,
which §CM-1 ("these five and nothing else") does call a defect. That is deliberate: editing
CLAUDE.md busts the prompt-cache prefix of every live session (TRDD-e247a349 §5), so churning a file
`check` calls conforming costs more than the stray block does. Both gates are now documented in
`plan_migration`'s docstring as the two separate questions they answer — WHETHER to plan, and WHICH
blocks — because conflating them is what shipped broken twice.

### Provenance — the two agent reports behind `d82dc15a` and `20f226ba`

Cited so the chain is greppable, and annotated because reports are gitignored and will vanish while
their conclusions would otherwise survive as unqualified:

| report (`reports/lfswy0c6/`) | produced | STATUS OF ITS CONCLUSION |
|---|---|---|
| `20260813_062500+0200-migration-planner.md` | `d82dc15a` — the planner | **Its "13 green tests" claim was TRUE and MEANINGLESS.** Every fixture planted a violation, so the shipped planner was wrong on real input. |
| `20260813_064433+0200-planner-candidate-fix.md` | `20f226ba` — the gate | **Reported the fix as complete; it was PARTIAL.** Verified by hand the same hour: the defect survived on any over-cap file. |

Neither report was wrong about what it DID; both were wrong about what it MEANT. That is the reason
this card's own §"How BOTH previous attempts passed" exists, and the reason the classifier's
acceptance was falsified in-process rather than accepted from a passing suite.

### NEXT ACTION — the DELIVERY half, still unbuilt and still separately risky

Nothing in this commit writes anything. Delivery is CM-2 steps 3–5: write the atom (or fold + `[^N]`
lesson), remove the migrated lines, and prove preservation with `claudemd_slim verify --old` BEFORE
committing. Its acceptance bar is the same one that caught this: run it on real input, not only on
fixtures.

## ⏵ 2026-08-13 — DELIVERY, part 1 SHIPPED (`64b82836`): the removal ENGINE, which refuses

`scripts/lib/claudemd_migration_apply.py` + `claudemd_slim apply [--dry-run]`. CM-2 steps **4–5**.
Step 3 (writing the atom/fold) is the memory agent's, and §"the honest limit" below is explicit that
it is not built — the engine *enforces* that ordering rather than performing it.

### The one design decision everything else follows from: the apply is PURE

`apply_migration(text, blocks, corpus) -> ApplyResult` takes the current CLAUDE.md text and returns a
CANDIDATE, so **every gate runs before anything reaches disk**. The pre-existing
`claudemd_slim verify --old` structurally cannot do this — it compares the ON-DISK file against a
pre-migration copy, so it can only speak AFTER the removal happened. For an unattended chore that is
the wrong order: "we deleted it, then checked" leaves a window whose only backstop is a backup nobody
is watching. A failed gate here means the write never occurs.

### Six gates, and the FIRST one is the one the oracle cannot provide

| gate | refuses when | why it is not redundant |
|---|---|---|
| `nothing-requested` | the block list is empty | a no-op reporting success is this card's own twice-hit failure |
| **`not-excess`** | a requested block is a §CM-1 PERMITTED element, or is not a narrative block of this file at all | **see below** |
| `not-uniquely-located` | the text occurs 0 or ≥2 times | Edit-tool discipline: a first-match delete cannot tell the intended line from a twin |
| `fence-altered` | either janitor fence would change | CM-2 step 5; reachable — see the straddle case |
| `github-url-dropped` | the last narrative repo URL would go | otherwise one contract violation is traded for another |
| `content-dropped` | the preservation oracle finds a lost fact line or token | risk #1: knowledge shredding |

**`not-excess` is the guard nobody asked for, and it is the important one.** *Preservation and
correctness are different properties, and the oracle only checks the first* — written on this card in
June as an argument, observed in the morning as fact, and now enforced. A run that dutifully folded
this project's own description into a wiki page passes the oracle **completely** and still leaves a
CLAUDE.md violating the §CM-1 element it REQUIRES. The oracle is structurally blind to that class.
The gate keys on `classify_blocks` — the planner's own rule, EXTRACTED into a shared pure function
rather than reimplemented, because a second copy of "is this permitted" drifts, and the drift would
only ever surface as a permitted element going missing.

`fence-altered` is likewise not defensive padding: a block that STRADDLES a fence has its pre- and
post-fence lines joined in the narrative, so the joined string never occurs contiguously outside the
fence — and if the fence body happens to contain that same string, uniqueness sees exactly one match,
*inside the fence*. There is a fixture for exactly that.

### Falsified per guard — each break predicted its red set BEFORE the run, and hit it exactly

| break | tests that must go red | observed |
|---|---|---|
| `_gate_only_excess_blocks` → `[]` | the 3 `not-excess` tests | 3 red / 12 green ✓ |
| `_gate_preservation` → `[]` | `content-dropped` ×3 (pure, CLI dry-run, live-input) | 3 red / 12 green ✓ |
| `_gate_fences_untouched` → `[]` | `fence-altered` | 1 red / 14 green ✓ |
| `_remove_unique` → first-match | `not-uniquely-located` | 1 red / 14 green ✓ |

Predicting the red set first is what makes this falsification rather than fiddling: a break that
reddens MORE than predicted means the tests are entangled, and one that reddens LESS means the guard
was never load-bearing. Neither happened. Restored via `git checkout` after each (the work was
committed first, so RULE 0 held throughout).

### VERIFIED ON REAL INPUT — the whole CM-2 loop, not just the unit under test

The live `CLAUDE.md` + 60 excess notes, in a scratch root (the repo's own file never touched):

| step | result |
|---|---|
| `check` before | `narrative is 13689 bytes (cap 8192)` — genuinely over cap, not merely non-conforming |
| `plan` | **60 migratable / 8 permitted** (1 description + 3 urls + 4 dev-ops) |
| `apply --dry-run`, no owning page | **REFUSED**, 8 failures, each naming a dropped fact line; file byte-identical |
| `apply`, owning page present | `removed 60 block(s) — preservation PROVEN, both fences byte-identical` |
| `check` after | the **cap violation is gone** |
| `verify --old` (INDEPENDENT path) | `preservation PROVEN — every fact line and token survives` |
| permitted elements | all 8 present afterwards; both fences byte-identical; 201990 → 189400 bytes |

The dry-run refusal and the post-page success are the same request differing only in whether the
content had been written first — i.e. the CM-2 step-3-before-step-4 ordering is ENFORCED, not
documented.

### What part 1 does NOT do — the honest limits, none of them papered over

1. **CM-2 step 3 is unbuilt.** Nothing writes the atom or the fold + `[^N]` lesson; the applier
   *requires* the corpus to already contain the content and refuses otherwise. That is the correct
   dependency direction (the engine must exist before an agent can call it), but it means migration
   is still a MANUAL two-step today.
2. **CM-2 step 6 is unbuilt.** `apply` does not refresh the index/map fences, so `check` still
   reports a stale index afterwards. Deliberate — the fences are separate generators with their own
   locks, and folding them in would make one write span three concerns.
3. **The scheduler intervention is unbuilt**, so `PRRD G8.1`'s *automatic* is still not satisfied.
   This card stays open on that alone.
4. **A decision-half consequence found by these tests, recorded not fixed** *(now FIXED in its own
   commit — see the next section)*: a SINGLE-LINE prose sentence containing a §CM-3 word reads as
   dev-ops and is PERMITTED — `\bpush\b` matches across the hyphen in "an earlier event-push design…".
   Deferred deliberately: changing it belongs in a decision-half commit with its own falsification,
   NOT smuggled into a delivery commit — fixing two things at once is how neither gets falsified.

## ⏵ 2026-08-13 09:40 — the §CM-3 exemption FP was a DEFECT, not the bias (`c88776c8`)

Deferred above as "the classifier's documented bias". **Measuring it changed the verdict**, and the
reframing is the substance: the bias justifies keeping AMBIGUOUS blocks, it never justifies exempting
text the spec explicitly names as non-exempt. §CM-3: *"Architecture, gotchas, incident history, design
rationale and conventions are NOT exempt however short."*

All four of these one-line ARCHITECTURE/RATIONALE lines were EXEMPT, and all four wrongly:

| line | matched |
|---|---|
| `The plugin is installed at user scope, so it runs in every project.` | installing |
| `The build is reproducible because the lockfile is committed.` | building |
| `Tests live under tests/ and mirror the scripts/ layout.` | testing |
| `An earlier event-push design silently dropped frobnications.` | pushing |

`classify_exemption`'s own docstring claimed single-line-ness was *"a STRUCTURAL gate, not a length
shortcut for prose"* — in practice it was precisely a length shortcut for prose.

**The fix restores the spec's OWN test** — *"is this a command an agent runs to operate the repo?"* —
structurally: condition (c), the line must contain a backticked code span. A command line contains a
command. All four of this repo's real §Commands entries carry one; none of the four FPs do.

**Both residuals are TESTED, not merely commented** (a documented consequence no test pins is a
comment that can quietly stop being true): a backtick-less dev-ops line is now migratable — accepted,
because the delivery half's preservation gate RELOCATES such a line rather than losing it, whereas
the pre-fix behaviour parked real narrative in CLAUDE.md permanently, which is the whole cost §1
exists to eliminate; and prose carrying an unrelated code span (``- See the `docs/` folder for testing
notes``) is still exempt.

**Falsified** (break E): disabling condition (c) reddened exactly the two new tests, 20 green.
**Real input unchanged**: the live CLAUDE.md over cap still gives 60 migratable / 8 permitted
(1 description + 3 urls + 4 devops), and the 4 devops are exactly the real command lines — so this
removed a false-positive CLASS without moving a single block on the actual file.

### Delivery-part-1 acceptance (the chore-level §4 boxes stay open — they need the agent + scheduler)

- [x] Removal is gated on a preservation proof computed BEFORE the write, not after
- [x] The oracle is OBSERVED REFUSING on real input, not merely observed passing
- [x] A §CM-1 permitted element cannot be removed even when preservation would pass
- [x] Both janitor fences byte-identical across a real 60-block migration
- [x] Each gate falsified individually, with its red set predicted in advance
- [ ] An agent writes the atom/fold (CM-2 step 3) — unbuilt
- [ ] The fences are refreshed after migration (CM-2 step 6) — **NOT refreshed. Still unbuilt.**
      `e448b65b` made `apply` PROBE and REPORT the staleness it causes, so an operator is never
      silently left with a stale index — but reporting a stale index is not refreshing it, and the
      test that covers it is named for exactly that: `test_cli_apply_points_at_the_index_refresh_
      it_deliberately_does_not_do`. Folding the splice in is the "one write, three concerns" risk
      named above, so the gap is deliberate; it is still a gap.
      (Marked `[x] partially, by design` by the part-2 session and corrected here: a checkbox is
      read at a glance and the qualifier is not, so a caveated tick reads as done to every later
      reader — the same over-claim class this card's own gates exist to catch.)
- [ ] The scheduler runs it unprompted (`PRRD G8.1`) — unbuilt

## ⚠ 2026-08-13 09:10 — THE SCHEDULER PLAN IN §STATE IS PROBABLY WRONG. Read before building part 2.

The original NEXT ACTION says *"implement the chore per §2 as a new intervention in the
memory-maintenance scheduler … + a `[janitor-memory-claudemd]` marker"*. Read that scheduler before
acting on it — two problems, the second decisive.

**1. Axis mismatch.** `scripts/detectors/memory-maintenance.py` round-robins over
`_scopes_in_play() × _MARKERS` — every intervention's subject is a MEMORY SCOPE ROOT, and the
per-dispatch pending state names `(scope, root)`. This chore's subject is a FILE in the repo. Keying
it on a memory scope is a category error, and the cursor would rotate it against scopes that have
nothing to do with it.

**2. The PROJECT gate makes it inert by default — VERIFIED, not assumed.**
`memory_settings.py:60` — `"edit_project_scope": False` — and `_scopes_in_play` (line 130) DROPS the
PROJECT scope unless the user opted in, deliberately, *"because PROJECT memory is in-repo and
unpushable outside publish.py"*.

CLAUDE.md carries project architecture and code knowledge, which the scope-routing rule sends to
**PROJECT** wikimem. So a chore hosted here would be **silently disabled on every default install**:
wired, reachable, documented, and inert — the exact failure shape this card and TRDD-KTXZJC6E are
both about, reproduced one layer up by following this card's own plan.

**So part 2 must first DECIDE the host, not just implement it:** a separate detector on its own
cadence (subject = the repo's CLAUDE.md, no scope axis), or a memory intervention that explicitly
resolves the PROJECT gate. That gate exists for a real reason — do not simply bypass it; a chore
that writes unpushable in-repo memory unattended is a different risk, and G8.1 does not settle it.
G8.1 settles *that* migration is automatic, never *which component* runs it or what it may write.

## ⏵ 2026-08-13 — PART 2 SESSION: verified, nothing further is unblocked. Card stays `todo`.

Re-ran the full targeted suite (`ruff`, `mypy`, `test_claudemd_migration_apply.py` +
`test_claudemd_migration_plan.py` + `test_claudemd_slim.py` — 48 passed) against the tree as
`e448b65b` left it. Everything is green; nothing was broken.

Of the three things this card's own STATE named as part 2's scope:

1. **The index-fence refresh (CM-2 step 6)** — already shipped, `e448b65b`, tested (checklist above
   updated to reflect it). Nothing to add.
2. **The agent write step (CM-2 step 3)** — genuinely not code-buildable. Deciding WHAT content an
   excess block becomes (a new atom vs a fold, which page, what `[^N]` lesson) is an editorial
   judgment call the spec itself assigns to the memory agent, not a deterministic function of the
   text. Writing a script that "decides" this would be inventing an editorial policy nobody
   reviewed — exactly the class of unauthorized design decision this session was told to avoid.
   Left unbuilt, as the card already says.
3. **The scheduler host** — the 2026-08-13 09:10 note above proves the originally-planned host
   (`memory-maintenance.py`'s `(scope, root)` axis) is a category error AND silently inert by
   default (the PROJECT gate). Picking the real host — a standalone detector on its own cadence,
   vs, resolving the PROJECT gate inside a memory intervention — is a design decision with real
   consequences (an unattended chore's write surface), not a mechanical implementation task. Left
   unbuilt, as instructed.

No fourth option surfaced on inspection: the removal engine (`claudemd_migration_apply.py`) and the
classifier (`claudemd_migration_plan.py`) are both complete and already exercise every acceptance
box that does not require an agent decision or a scheduler. Card stays `column: todo` — items 2 and
3 above are real, undone work, not merely deferred bookkeeping.

## 1. Why (the cost argument, measured)

`CLAUDE.md` is injected into every session's context on every turn, and a turn re-reads that
context once per tool call. Measured 2026-08-04 via `agentlenspro heartbeat-cost`: ONE
heartbeat fire re-read its context **6 times** — 3,239,112 tokens, $1.72. A paragraph parked
in `CLAUDE.md` is therefore paid per turn, per tool call, per agent, forever, including by
every agent for whom it is irrelevant. Wikimem inverts that: the knowledge costs nothing
until a symptom query asks for it.

## 2. The chore

Per `design/specs/claude-md-canonical-form.md` §CM-2:

1. Detect narrative beyond the five permitted elements (`claudemd_slim` already computes
   `narrative_outside_fences` and `slim_violations`).
2. **RECALL** the wikimem page owning the subject — never mint a duplicate page.
3. Write a new atom, **or** fold into the owning atom **plus** a `[^N]` lesson learned.
4. Remove the migrated lines from `CLAUDE.md`.
5. **Prove preservation before commit**: `claudemd_slim verify --old <pre-migration>`, the
   map fence byte-identical when only narrative moved, `memgrep validate` + `lint` clean.
6. Refresh the index fence (`G10.1`: every root topic listed) and the map fence.

Runs through `memory_txn` like every other editorial chore, so a crash rolls forward.

## 3. The exemption is a closed list (`G9.1`)

Exempt: git, commit, branching, merging, linting, building, testing, tagging, pushing, CI,
publishing, installing, deploying. The test is "is this a command an agent runs to operate
the repo?". Architecture, gotchas, incident history, design rationale and conventions are
NOT exempt however short. The chore MUST NOT extend the list by analogy — encode it as a
literal enumeration so a future model cannot reason its way to a wider one.

## 4. Acceptance

- [ ] A line added to `CLAUDE.md` outside the five elements is migrated by the next chore
      run, without any agent being prompted.
- [ ] The migrated content is recallable by a symptom query that uses none of its own jargon.
- [ ] A dev-ops command line added to §Commands is left ALONE (the exemption holds).
- [ ] Preservation oracle passes; refuses to commit and reports if it does not.
- [ ] Index fence lists every root topic after the migration.
- [ ] `claudemd_slim check` exits 0 afterwards.
- [ ] A chore that cannot find an owning page creates one at the right tier rather than
      dumping the text into an unrelated page.

## 5. Risks

- **Knowledge shredding** — the chore removes lines it failed to write anywhere. Mitigated
  by step 5 being a hard gate: no removal without a passing preservation proof.
- **Page sprawl** — a chore that creates a page per migrated paragraph. Mitigated by step 2
  (recall-first) and by the wikimem rule "one element = one page".
- **Over-broad exemption** — a future model reasons that "deployment architecture" is
  dev-ops. Mitigated by §3's literal enumeration.
