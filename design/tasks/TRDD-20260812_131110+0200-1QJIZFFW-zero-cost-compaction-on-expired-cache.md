---
trdd-id: 1QJIZFFW
title: Zero-cost compaction whenever the prompt cache is expired — wire the llm-externalizer CLI into the existing external-clear scaffold
column: dev
blocked-by: []
created: 2026-08-12T13:11:10+0200
updated: 2026-09-02T03:56:00+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
severity: high
implementation-commits: [df7d4cb3, 169d967d, 295c1243]
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-PXP08ZQC, TRDD-31095269, TRDD-D3PROACT, TRDD-WUUR2DFX]
---

# Zero-cost compaction on an expired cache

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02

### ⛔ 2026-09-02 — THE LEVER IS ON AND CANNOT REACH THE DAEMON; blocked on TRDD-XCJFCJUX

The 2026-09-01 NEXT ACTION below WAS executed (`~/.claude/settings.json` line 20 reads
`"true"`, file mtime 21:30) and 3.4.3 is installed + restaged (TRDD-NDAARSXT closed on the
daemon's live VERDICT lines). Yet the daemon still evaluates in SHADOW: under launchd it has
ZERO `CLAUDE_PLUGIN_OPTION_*` variables (measured 2026-09-02 — `ps -E` snapshot of the daemon
pid, no `EnvironmentVariables` in the plist, `launchctl getenv` empty), so
`external_clear.enabled()` is False regardless of the file. Boxes 4/5 wait on XCJFCJUX's
settings loader shipping in the next publish + restage; the drill then needs NO further action
— the lever is already set. Do not flip anything else, and do not re-run the flip.

**NEXT ACTION:** after the XCJFCJUX publish is installed and `cold-cache-clear.log` shows
`evaluating <root>` WITHOUT `[SHADOW — dry-run]`, let one automated clear happen and measure
boxes 4 and 5 against it.

### ✅ 2026-08-29 — THE BLOCKER BELOW IS DISCHARGED. Box 2 is now reachable.

The 2026-08-26 section says box 2 waits on "3.4.0 publishes → installs → the lever is
re-enabled". Two of those three are done, verified first-hand tonight rather than recalled:

- **3.4.1 is published AND installed** — `~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.4.1/`.
- **The freeze cause is gone in the INSTALLED copy**, which is the only copy that matters:
  `3.4.1/scripts/external_handoff_clear.py:250` — *"No template to fall back to any more. The
  caller reads `""` as 'do not clear'."* A failed summary no longer template-clears. The
  singleflight lock is there too (same file, ~line 369).
- **In-flight agents cannot be cleared out from under.** Read the GATE, not its inputs:
  `lib/external_clear.py:1566` — `if active_waiting: return ClearVerdict(False, why="active-waiting")`.
  A hard refusal branch, third in the chain after `cooldown` and ahead of `awaiting-user`.
  That line is inside `should_clear_externally` — `def` at `:1503`, and no `def` between, so the
  ownership is not assumed:
  `awk '/^def /{last=NR": "$0} NR==1566{print last; exit}' <that file>` → `1503: def should_clear_externally(`.
  Worth stating because the same file holds SIBLING decision functions (`should_clear_on_resume`
  at `:1355`, and the docstring right above `:1566` discusses `should_clear_when_long_idle`), so a
  line window alone cannot tell you which one you are reading. The caller side needs no such
  check: `external_handoff_clear.py:172` splats `ec.should_clear_externally(**gate)`, and a
  mismatched key would raise `TypeError` at call time rather than bind silently. The
  term is fed by `external_handoff_clear.py`'s `active_waiting = dispatch._cadence_active_waiting(sd, now)`,
  which counts `pending_agents.pending_external(...)`.

  **The two-source form is the point, and the first source alone was not enough.** This was
  originally written citing only `_cadence_active_waiting` — a function whose NAME and docstring
  are about picking a cheap-vs-expensive CADENCE tier, i.e. how OFTEN the watcher acts, not
  WHETHER it clears. Every line of that reading is satisfied by a watcher that merely runs
  slower and still clears a session with four agents mid-flight. The refusal branch is what makes
  the claim true; the input binding only makes it reachable. Do not re-derive this from the
  caller side alone.

  So the USER's 2026-08-29 "gate every compact on `pending-agents.json == []`" requirement is met
  by `:1566` — **verify that line still says `return ClearVerdict(False, …)` before relying on
  this**, because a sentence in a STATE block claiming a user directive is already discharged is
  exactly the sentence that stops the next session from checking.

### ⛔ 2026-09-01 — DO NOT FLIP THE LEVER YET; the flip now waits on the NEXT PUBLISH, deliberately

The 2026-08-29 NEXT ACTION below is SUPERSEDED in timing, not in substance. TRDD-2F3I2P18
landed the clear-first reorder tonight (capture transcript → fire /clear → summarize; commits
`59e31dcb`…`f05ab464`) — but only in the REPO. The installed 3.4.1 still runs the OLD
compose-then-clear ordering, the exact shape the USER's 2026-09-01 quota incident indicts.
Enabling `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED` now would arm the known-bad flow
machine-wide. Flip it only AFTER the next `scripts/publish.py` release is installed locally;
then run the drill and measure boxes 4/5 against the NEW ordering (which is also what
2F3I2P18's own "measured" box needs). One drill can close both cards' measurement boxes.

**NEXT ACTION (one step, runnable as written — AFTER the publish+install):** flip the lever,
then run the drill.

```
~/.claude/settings.json:22  "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED": "false"  →  "true"
```

then let one automated external clear happen and measure boxes 4 and 5 against it.

**Do NOT flip it while background agents are in flight or mid-edit-batch.** Not because the
gate would misfire — it vetoes correctly — but because the drill needs the clear to actually
FIRE to be measurable, and a vetoed fire measures nothing. Pick a seam.

**SUPERSEDED — do NOT carry forward:** "this card moves to `blocked` on that publish" (the
publish landed); "the lever was pulled because 3.3.26 template-clears on a failed summary"
(true of 3.3.26, false of the installed 3.4.1).

### ⚠ 2026-08-26 — BOX 2 IS UNREACHABLE RIGHT NOW, and it is not a scheduling problem (SUPERSEDED — see above)

Box 2 needs a run through the AUTOMATED path. That path cannot run on this machine: the lever
is OFF, verified rather than recalled —

```
~/.claude/settings.json:22
  "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED": "false"
```

It was turned off deliberately: the installed 3.3.26 still template-CLEARS on a FAILED summary,
which is the resume-storm that froze 16 sessions. The fix (`e789506c` — resume-aware budgets,
a per-root singleflight lock, and no `/clear` when the summary fails) ships in **3.4.0**, which
is blocked on the GitHub push-protection decision.

So the sequence is fixed and none of it is optional: **3.4.0 publishes → installs → the lever
is re-enabled → box 2 can be attempted.** Re-enabling BEFORE 3.4.0 installs would re-arm the
exact freeze the lever was pulled to stop. This card therefore moves to `blocked` on that
publish; it is not idle work anyone can pick up.

(Unchanged and still true: box 1 is discharged only as literally written, and the idle-resume
defect the drill exposed remains the more valuable output of that run.)

## ⏵ STATE (2026-08-22 — retained below)

**~~PARKED ON THE OWNER'S GO-AHEAD~~ — GO-AHEAD GIVEN 2026-08-12, and the core is BUILT
(`df7d4cb3`).** The owner's words were "before publishing you must implement the zero tokens
compacting via llm-externalizer", which also makes this a gate on the pending release.

**DONE:** `use_llm_ext()` has a caller at last — `external_handoff_clear._compose` runs
`llm-ext session-summary` and composes the owner's three-part payload (scriptable facts +
summary + TRUNCATED tail) under ONE budget. Verified end-to-end on a real 464 KB transcript
(~1 s warm), payload inside budget at 8192/6000/4000/2500 with all three parts present, 10
tests.

**Four defects found by measuring, each of which would have shipped silently:** `facts` had no
`transcript` key (the summary branch would have degraded to template-only forever — dark code
in the commit meant to un-dark it); the unbounded summary ate the tail's room, producing a
handoff with no recent turns; a constant +38-byte overrun from appending the truncation notice
outside the accounting; and a test of mine that could not fail (`"m0" in "m100"`).

**THE REACTIVE TRIGGER IS NOW WIRED** (`169d967d`, `295c1243`). `agentlenspro cache-expired`
is the measurement; it is OR'd in AHEAD of the prediction so a fire is attributed to the
measurement when both agree. Two things it cost, both of which the code would have hidden:

  - **The watcher had been crashing on every run since `df7d4cb3`** —`_decide` passed a
    composer-only `transcript` key into the pure gate, which raised `unexpected keyword
    argument`, and the `# type: ignore[arg-type]` on that call is what kept mypy quiet. The
    feature was dead on arrival for the whole window in which it looked shipped.
  - **The probe's first timeout made the new trigger dead too.** At the burn probes' shared
    5 s it returned `None` on 2 of 3 real calls (measured CLI latency: 0.15 s, 11.5 s, 19.7 s)
    — and `None` fails open, so a too-short bound is INDISTINGUISHABLE from "agentlensPro is
    not installed". Its own 30 s constant now, pinned by a test that carries the measurement.

**BOX 1 IS DISCHARGED ONLY AS WRITTEN — "a cross-`/clear` run through the harness" happened,
2026-08-22. The HARNESS crossed a clear; the FEATURE this card is about did not.** Read the box
strictly or it becomes the same overclaim box 2 warns against one paragraph down. Report:
`reports/continuity-build/20260822_223959+0200-handoff-clear-verify.md` — **4 PASS · 0 FAIL · 1
SKIP**. Timeline: `--phase before` 22:29:50 → `/clear` observed 22:31:20 → re-arm 22:35:35 →
`--phase after` 22:39:59.

| check | verdict | evidence |
|---|---|---|
| cron_recreated | PASS | `b549cb16` → `368ce188`; the targeted `CronDelete` of the old id returned *not found*, i.e. `/clear` had already destroyed it |
| context_collapsed | PASS | 657 959 → 199 020 tok (install floor ~229 542) |
| handoff_links_resolve | PASS | 4/4 `[[links]]` resolve via memgrep in the virgin session |
| session_restarted | PASS | armed 1787430935 > snapshot 1787430590, `source=clear` |
| resume_flag_consumed | **SKIP** | no `resume-after-clear.flag` existed to consume |

**BOX 2 IS *NOT* DISCHARGED — do not read the 4 PASSes as closing it.** The run measured the
*model-turn* half of the claim (zero model turns between the clear and the resumed session's
first turn — verifiable in the transcript) but NOT the *$0-summary* half: this was a **hand-typed
`/clear` with a MODEL-AUTHORED handoff**, so `external_handoff_clear._compose` / `llm-ext
session-summary` — the whole thing box 2 is about — never ran. Box 2 needs a run through the
AUTOMATED path (`clear_trigger.py` / the skill), not another manual one.

**AND THE RUN EXPOSED A REAL DEFECT, which is the more valuable output.** Zero model turns was
satisfied *because nothing happened*: the resumed session sat idle 4m15s until the human
complained. Root cause, verified in code —
`resume-after-clear.flag` has ONE writer — `clear_trigger.py:236`, the automated chain — verified
by literal-string grep across `scripts/ hooks/ skills/`, which holds only because every module
names the file as a string literal rather than composing the name.
This drill was staged by running `--phase before` STANDALONE and asking the human to type
`/clear` — the shape `skills/janitor-handoff-and-clear/SKILL.md` explicitly warns against. So no
flag ⇒ `on-session-start.py:258 _inject_post_clear_handoff` returned early (it is *deliberately*
gated on the flag: "a MANUAL `/clear` … the user meant that as a discard") ⇒ no
`[janitor-resume]` ⇒ and the heartbeat cron was dead anyway. `resume-directive.txt` sat on disk
with the exact next command; its only consumer is `post-compact-resume.py`, which cannot run on a
clear path. It then re-fired `[janitor-resume]` on every heartbeat until trashed by hand.

**The harness is complicit:** `--phase before` already records `resume_flag_present: false` and
prints NOTHING about it — its stdout reports cron id, context and link count only. It certified a
staging that could not resume. And the one check that would have caught it degrades to SKIP
(fail-open), so the drill reports **green on a cycle whose resume path failed completely**.

**NEXT ACTION:** (a) make `--phase before` WARN on stderr when no `resume-after-clear.flag` is
present — a hand-typed `/clear` will not auto-resume, so the caller must use `clear_trigger.py`/
the skill or hand the user the `--phase after` command; (b) then re-run the drill through the
AUTOMATED path to discharge box 2. Deliberately NOT chosen: making `--phase before` write the
flag itself — it would flip the documented "manual clear = discard" semantics for 24 h and make
check #4 self-fulfilling.

**SUPERSEDED — do NOT carry forward:**
  - *"STARTS WHEN: the owner says go"* / *"NEXT ACTION when unblocked: give
    `external_clear.use_llm_ext()` an actual caller"* — both discharged. The go-ahead came
    2026-08-12 and the caller landed in `df7d4cb3`.
  - *"the only remaining question is whether the owner considers v12.0.0 settled enough"* —
    answered by building against it with a hard timeout + degrade-to-template, so a young CLI
    cannot break the clear path.
  - the table row marking `use_llm_ext` **DARK** — it has a caller now
    (`external_handoff_clear._compose`).

### 2026-08-14 — the SessionStart hook was NOT bounded; two "open" gaps were already closed

**FIXED: the hook's declared timeout was 600s.** I had recorded "the probe costs 25-30 s
inside a SessionStart hook — confirm that is bounded" as a question for the owner. Checked
it, and the answer was no. The probe's own bound is 90 s (`_CACHE_EXPIRED_TIMEOUT_S`), but
`hooks/hooks.json` declared **600 s** for the hook — 6.7x its own worst case, and **120x**
every sibling SessionStart hook (all 5 s). So a hang anywhere in the hook blocked session
start for TEN MINUTES before Claude Code killed it. Now 120 s: the probe can still take its
full 90 s, and a hang costs 2 min instead of 10. `DEFAULT_ENABLED = False` means this was
never live, which is exactly why it survived — an opt-in path's costs are only paid by the
person who opts in, and nobody had.

**NOT a gap after all — verified, do NOT "fix" these:**
- *`mark_clear_fired` stamped after spawn.* `dispatch.py:2136` stamps only AFTER a verified
  send (`if not ok: return False` precedes it); the SessionStart hook latches with
  `dedupe.emit_once` BEFORE its `Popen`; `external_handoff_clear.py:340` stamps after the
  spawn call deliberately, with the reasoning written inline, and the window is microseconds
  against daemon beats minutes apart, serialized by `clear-chain.lock`.
- *Floor staleness — "nothing consults `measured_after_compact_ts`".* That note was WRONG.
  `refresh_floor` reads it: `if last_compact <= floor_ts: return floor` — a compaction newer
  than the measurement re-measures. The residue is install-change (a new plugin raises the
  real floor while the stored one stays low, over-stating gain), and it self-heals at the
  next compaction. Not worth code.

### 2026-08-14 — advisor verdict on the RE-FIRE policy, and a floor-staleness gap

The owner asked whether `already_fired_this_session` is too blunt: a long session whose cache
expires AGAIN, with a big context, should be allowed to clear again. His proposed simplification
was to drop the latch and gate on `cache_expired AND context > 300_000`, reasoning that context
cannot be that large right after a clear — so the threshold IS the loop guard.

**REJECTED on a measured fact.** This install's post-compaction floor is **305,119** (live
`read_floor`, and the code comment records 308,644 on 2026-07-17). A 300k threshold sits BELOW the
floor, so every clear would land above it and re-fire forever: the threshold would be a loop
TRIGGER, not a loop guard. Worse, `external_clear.DEFAULT_MIN_CONTEXT_TOKENS` is **150_000** — less
than half the floor — so today the latch is the ONLY thing preventing that loop.

Advisor's shipping predicate (drop the latch, keep everything else):

```
source in RESUME_SOURCES
and cache_expired is True
and not in_cooldown                       # stamped by the HOOK, pre-spawn
and context_tokens is not None
and context_tokens >= max(min_context, (floor + min_gain) if floor else 350_000)
```

Why each survivor is load-bearing, not belt-and-braces:
  - **RESUME_SOURCES** — returns before the ~20s probe on 41 of 48 measured fires, AND
    `source=compact` is a mid-session re-entry where the docstring's whole safety argument ("no
    turn has run, nothing in-flight") is FALSE. With floor > 300k, dropping it would `/clear` a
    live session after every harness compaction.
  - **cooldown** — the ONLY guard for a FAILED clear (context stays high, cache stays dead, so the
    threshold passes again). A threshold guards the success case only.
  - `cache_expired` does NOT break the loop either: only a paid TURN warms a cache.

**BUG found in the current code:** `mark_clear_fired` is stamped AFTER spawn, so two SessionStart
deliveries can both pass `clear_in_cooldown` and interleave — the second `/clear` destroying the
first's injected handoff. Stamp it in the hook, before `Popen`.

**GAP found while verifying (this is the open one).** `read_floor` returns
`(tokens, measured_after_compact_ts)` — the staleness signal is already carried — but NOTHING
consults it. There is no age or install-change invalidation anywhere. A floor measured before N
plugins were installed under-reports, so `floor + min_gain` computes a threshold too low and the
gate fires where there is less to reclaim than it believes; a floor measured on a fat install
over-reports and the gate never fires. Fail-safe: treat a floor older than the last plugin/rules
change as UNKNOWN and fall back to the conservative default rather than trust it. The plumbing is
already in place — the second return value is simply unused.

**VERIFY FIRST, before any of this ships:** if a resume mints a NEW session_id per launch, the
latch never blocked the owner's scenario at all and the change is moot. One logged resume answers
it (`cold-cache-clear` log line, `session_id`).

### 2026-08-12 13:49 — the CLI has LANDED; the block is now only the owner's go-ahead

`llm-ext session-summary` ships in **llm-externalizer v12.0.0** (janitor#251). VERIFIED by
invoking it, not by reading the issue:

- Self-describes as **"$0 by construction"** — always the biggest free, text-emitting
  OpenRouter model, falling down a ranked list if one is delisted / stops being free /
  exhausts its daily cap mid-run.
- **Streams** the JSONL via map-reduce (never loads the transcript into memory) and
  **checkpoints after every chunk**, so an interrupted run RESUMES on re-invocation rather
  than restarting — re-running the same command is safe, which is what makes it usable from
  a hook that may itself be interrupted.
- `--stdout` prints the text; otherwise stdout is the report PATH, with banner/progress/errors
  on stderr — so `SUMMARY=$(llm-ext session-summary …)` is hook-safe by design.
- Relevant knobs: `--transcript` / `--session_id` (defaults to the project's most recent
  transcript), `--output`, `--prune`, `--max_chunk_tokens`, `--checkpoint`, `--resume`.

**THE INTEGRATION TRAP, measured — `CLAUDE_PLUGIN_DATA` MUST be set explicitly.** With it
unset the binary dies before doing any work:

```
[llm-externalizer] FATAL: native module 'better-sqlite3' is missing AND CLAUDE_PLUGIN_DATA
is unset. The launcher cannot self-install without a persistent data directory.
```

A janitor hook / detached child is EXACTLY that context. Worse, the value is **another
plugin's** data dir, and there are two candidates on this host
(`llm-externalizer-emasoft-plugins` and `llm-externalizer-inline`) — so it cannot be guessed
at call time and must be resolved and passed deliberately. With it set, the launcher
self-installs its native dep and runs.

Two further cautions for the wiring:

- **Do not read the exit code through a pipe.** `llm-ext … | head` reports `head`'s status;
  the launcher's own failure is invisible. Capture to a file, then inspect.
- The v12.0.0 issue thread is a FIX to this very command (an unbounded body-read hang: the
  abort was disarmed when headers arrived, so the timeout bounded time-to-first-byte only and
  a stalled generation hung forever). Treat the version as young: wrap the call in a real
  timeout of our own and degrade to `compose_template_handoff` on any non-zero exit.

## The injected payload — USER spec, 2026-08-12

**It is a HOOK that injects the handoff, not a skill or a command** (USER correction, 2026-08-12).
The hook layer already exists and runs: `PreCompact -> pre-compact-handoff.py`,
`PostCompact -> post-compact-resume.py`, `Stop -> on-stop-proactive-compact.py`. Build on those.
PXP08ZQC's "wire a task into `daemon.py`" NEXT ACTION is therefore NOT the shape to copy.

The new handoff injects THREE parts:

1. **The `llm-ext session-summary` output** — the CLI writes it to a file; inject that file.
2. **Scriptable facts about the pending TRDD(s)** — id, title, column, and the STATE block's NEXT
   ACTION. All of it is greppable from frontmatter, so it costs ZERO model tokens to assemble and
   is exactly the part that must never be paraphrased.
3. **The latest messages — TRUNCATED.** The tail of the conversation, capped.

**THE HARD CONSTRAINT: the injection must not refill the context it was built to empty.** A
handoff that restores a large payload at session start defeats the entire feature — we would pay
the cache-write we just avoided, one turn later. So the payload carries a byte/token BUDGET, and
the message tail is the part that gets cut (parts 1 and 2 are small and load-bearing; part 3 is
the elastic one). Truncate from the OLDEST end — the most recent exchanges are what a resuming
session needs.

Design notes for when this is built:
- Budget the whole injection, not each part separately, or three "small" parts add up.
- Say WHEN truncation happened ("N earlier messages dropped") — a silently clipped tail reads as
  a complete record, which is worse than an explicitly short one.
- Parts 2 and 3 must survive an llm-ext failure: if the CLI errors, inject 2 + 3 alone rather than
  nothing (degrade, never lose the handoff).

## Why (the USER's framing)

Two costs this removes, both paid today for nothing:

1. **The restart-after-a-long-pause cache miss.** Claude Code resumes with a cold prompt cache,
   so the FIRST turn re-writes the whole conversation at the cache-WRITE rate (~1.25x) instead
   of riding the 0.1x cache-read. On a large session that single turn is the most expensive of
   the day. Compacting *before* that first turn removes the thing being re-written.
2. **Every other cache expiry** — an API error, a blocking AskUser prompt nobody answered, a
   long network malfunction. Same waste, and today nothing reacts to it.

The USER's design, in intent: use the **agentlensPro CLI** to know *for certain* whether the
cache is expired; if it is, run the **llm-externalizer CLI** to compact at zero cost; then
`/clear`; then **inject the saved summary file back via a hook**.

## The socket already exists — do NOT rebuild it (VERIFIED at HEAD 2026-08-12)

The janitor already shipped this pipeline in TEMPLATE form under TRDD-PXP08ZQC. Verified
first-hand, not assumed:

| piece | where | state |
|---|---|---|
| the decision | `external_clear.should_clear_externally` | shipped — returns a named-rule verdict |
| the cache-miss predicate | `external_clear.next_fire_misses_cache` | shipped — "will the NEXT fire land on an EXPIRED cache?" |
| the TTL input | `external_clear.read_ttl_minutes` | shipped — reads the dispatcher's probed TTL |
| the handoff text | `external_clear.compose_template_handoff` | shipped — from ON-DISK facts, zero model tokens |
| the watcher/actuator | `scripts/external_handoff_clear.py` | shipped — the ZERO-model-turn clear |
| **the llm-ext switch** | **`external_clear.use_llm_ext`** | **DARK — exported, defaults True, ZERO callers** |
| the agentlens probe | `scripts/lib/agentlens_probe.py` | shipped — config-gated, bounded, fail-open |

So the work is **not** "build zero-cost compaction". It is: replace the template composer with
the llm-externalizer CLI behind the switch already written for it, and add the agentlensPro
expiry signal as a second trigger alongside the predictive one.

A switch defaulting to **True** with no callers is the exact defect shape audited all through
the 2026-08-12 session — code that exists, is exported, reads as a shipped feature, and never
runs. Its default is a promise the code does not keep; at wire-up time, re-decide the default
deliberately, because today it means nothing either way.

## What (sketch — decisions deferred until the CLI is real)

- **Trigger.** Keep `next_fire_misses_cache` (predictive) AND add the agentlensPro CERTAIN
  expiry read (reactive — API error, blocked AskUser, network gap). Predictive alone cannot see
  an unplanned expiry; reactive alone cannot pre-empt the restart case. Both, or it is partial.
- **Compose.** Behind `use_llm_ext()`: call the CLI, which writes the summary to a file and
  returns its path. Template composition stays the FALLBACK — a subprocess can fail, and a
  failed summarize must degrade to the existing zero-token template, never to a lost context.
- **Clear + re-inject.** `/clear`, then a hook injects the saved summary file. The existing
  `handoff_clear_verify.py` harness already measures a cross-`/clear` before/after — reuse it
  as the acceptance oracle rather than writing a second one.
- **Cost floor.** The whole point is ZERO Claude tokens. Any step costing a model turn defeats
  it; measure, do not assume (`llm-ext --estimate` on a paid profile).

## Acceptance (to be firmed up when unblocked)

- [x] The llm-ext compact verb exists and is invoked ONLY through `use_llm_ext()` — `df7d4cb3`
- [x] A CLI or probe failure degrades to `compose_template_handoff`, never to a lost handoff
- [x] agentlensPro-certain expiry triggers the same path as the predictive miss — `169d967d`,
      `295c1243`. Live: `cache_certainly_expired` returns a real `False` on this project.
- [ ] Measured: the whole cycle costs zero Claude tokens (no model turn on the clear path)
- [ ] Cross-`/clear` verification via the existing `handoff_clear_verify.py` harness

## Approval log

- 2026-08-12T13:11:10+0200 — QUEUED by janitor-main-session (tier 0, own scope). Filed at
  `backburner` rather than `todo` because it is blocked on an external deliverable, not on
  capacity — a WORK column would assert activity that cannot happen. The USER said "just wait";
  this card is the wait, made visible.
- 2026-08-12T18:58:36+0200 — `backburner` → `dev` by janitor-main-session (tier 0). The USER
  gave the go-ahead ("before publishing you must implement the zero tokens compacting via
  llm-externalizer"), which both unblocks the card and makes it a gate on the pending release.
  The core landed in `df7d4cb3`; three acceptance boxes remain, so the column asserts WORK
  rather than `complete`.
- 2026-08-29T22:30:00+0200 — UNBLOCKED. The blocker (TRDD-X4LJFTB4, GitHub push protection on the
  3.4.0 publish) was resolved and v3.4.0/v3.4.1 shipped; restored to the pre-block column.
