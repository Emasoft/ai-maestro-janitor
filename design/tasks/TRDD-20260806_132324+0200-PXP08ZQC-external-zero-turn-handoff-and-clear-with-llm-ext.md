---
trdd-id: PXP08ZQC
title: Cache-expiry-aware EXTERNAL handoff-and-clear — zero model turns, terminal-driven, handoff composed by llm-externalizer for free
column: blocked
pre-block-column: testing
blocked-by: [QZVAEWQH, BDZG8Y8A]
created: 2026-08-06T13:23:24+0200
updated: 2026-09-02T05:16:16+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
relevant-rules: []
implementation-commits: [def783f5, 95a5beda, 73a426c4, 07e8d986]
---

# External zero-turn handoff-and-clear (owner failure report 2026-08-06, item 3)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02

### ⛔ 2026-09-02 05:15 — ONE AUTOMATED CYCLE OBSERVED, minus its external handoff. Blocked on TRDD-QZVAEWQH + TRDD-BDZG8Y8A

> **The first LIVE automated clear on the 3.4.7 lane fired at 04:23:48 on AgentlensPro**
> (trigger `next-fire-misses`; context 418,505 tokens measured from the captured transcript;
> human_idle 1100 s — that trigger needs no idle floor, the next heartbeat would have missed the
> 5-min cache anyway). `external-clear.log`: `fired:` at 04:23:51, then three llm-ext attempts at
> 04:24:02 / 04:24:16 / 04:24:28 — the TRDD-2F3I2P18 clear-first ordering is observed live. The
> session re-armed at 04:24:45 and emitted its post-clear resume cue at 04:25:03 (a new session
> id; heartbeat fires continue). **But every llm-ext attempt failed identically:**
> `Remote api 'openrouter-remote' requires 'api_key' (env var $OPENROUTER_API_KEY is not set)` —
> the launchd daemon carries no such variable (the twin of TRDD-XCJFCJUX, for a credential instead
> of an option), so the chain logged `NO_SUMMARY_POST_CLEAR`, held the session on the 15-minute
> summary hold (dispatch.log 04:29/04:34/04:39) and left the resumed session to ground itself on
> the only handoff there was: the link-only `agent-handoff.md` of 22:59 (the resumed session Read
> it at 04:25:33), written BEFORE the cleared session was born (23:08) — so that session's five
> hours of work (23:08 → 04:19, 418k tokens) are covered by NO handoff; `precompact-handoff.md`
> is older still (18:48) and llm-ext wrote nothing. Filed as **TRDD-QZVAEWQH** (`design/proposals/`, USER ruling — every fix
> places a credential). Also exposed: the daemon fire path takes no `handoff_clear_verify.py
> --phase before` snapshot, so no PASS table can exist for an automated clear — **TRDD-BDZG8Y8A**
> (`todo`).

Of the last box's five elements — big idle session → external handoff → clear → re-arm → resume —
four are now observed on the automated path; the external handoff (the llm-ext summary) is the
one that failed, and the PASS table cannot be produced for an automated clear until BDZG8Y8A. Not
ticked.

### ⛔ 2026-09-02 — publish+install DONE (3.4.3), lever ON, and the daemon still cannot see it

`next-publish-install` is discharged: 3.4.3 is installed, the daemon restaged and respawned
(23:43:56), and TRDD-NDAARSXT closed on its live VERDICT lines. The lever has read `"true"`
since 2026-09-01 21:30. The daemon STILL runs every evaluation as `[SHADOW — dry-run]`,
because under launchd it carries ZERO `CLAUDE_PLUGIN_OPTION_*` variables (measured: `ps -E`
snapshot of the daemon pid, no plist `EnvironmentVariables`, `launchctl getenv` empty) —
`external_clear.enabled()` reads `os.environ`, never the file. Re-blocked on
**TRDD-XCJFCJUX** (the settings-env loader); when its publish is installed and the shadow
tag disappears from `cold-cache-clear.log`, the drill below runs unchanged.

### ⏵ 2026-09-01 — column re-honest-ed; ONE post-publish drill closes three cards

The frontmatter had drifted back to `todo` (the 2026-08-26 correction below set it to
`blocked` — the same claim-vs-reality failure this card documents, third occurrence). Reset
to `blocked` on `next-publish-install`: the remaining box (one observed end-to-end cycle WITH
the verify PASS table) must run on the post-2F3I2P18 clear-first ordering, which exists only
in the repo until the next `scripts/publish.py` release installs. The SAME drill then closes
the measurement boxes of TRDD-2F3I2P18, TRDD-1QJIZFFW (its STATE carries the lever-flip
step), and this card — run it once, harvest three.

### ⚠ 2026-08-26 — the opt-in below was REVERSED, and the card's column was wrong

Two corrections, both measured:

1. **The lever is `false` again.** `~/.claude/settings.json:22` now reads
   `"CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED": "false"`. The 2026-08-15 entry below
   says it was set to `true`; that is no longer true. It was turned OFF during the 2026-08-26
   resume-storm, in which the installed 3.3.26 template-`/clear`ed on a FAILED summary and
   froze 16 sessions. The fix (`e789506c`) is in **3.4.0**, blocked on push protection — so
   this card is blocked on that publish, exactly like TRDD-1QJIZFFW.
2. **The frontmatter said `testing` while this block said "Column `todo` since 2026-08-12,
   nobody is working this".** The STATE block was right and the frontmatter was stale — per
   the TRDD rules the STATE block wins on disagreement, and the frontmatter is now corrected
   to `blocked` rather than to either of the two columns that were arguing.

The irony is worth keeping, because it is the card's own subject: this is a card about a
feature that shipped DARK and cost ~7M tokens because a silent refusal left no trace. Its
column had been silently wrong for two weeks for the same reason — nothing forced the claim
to be re-checked against reality.

### ⏵ STATE (2026-08-15 — retained below)

### ⏵ INCIDENT 2026-08-15 — the feature shipped DARK and cost the owner ~7M tokens

v3.3.0 shipped the wired SessionStart hook (`on-session-start-cold-cache-clear.py`, registered
in hooks.json), but `external_clear.DEFAULT_ENABLED` is `False` BY THIS CARD'S OWN DESIGN
("opt-in until one observed end-to-end unattended cycle"). Nothing on the owner's machine set
`CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED`, and the `enabled()` refusal was SILENT (no
log line), so when the owner updated the plugin and restarted the whole fleet onto expired
caches expecting the feature, every session refused invisibly and paid the full cold re-read —
~7M tokens. The defect was not the gate; it was (a) announcing the feature without stating the
opt-in, and (b) a refusal that left no trace anywhere.

Done in response, 2026-08-15:
- `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED=true` added to `~/.claude/settings.json`
  `env` — every NEW session on this machine is opted in (already-running sessions are not).
- The `enabled()` refusal in the hook now logs one line naming the env var (repo edit, this
  commit) — a dark feature is now distinguishable from a broken one.
- Chain verified live with the switch on: enabled=True → transcript found → 325k ≥ 150k floor
  → agentlens probe answered `False` (warm — correct for an active session) → verdict
  `fire=False why='cache warm'`. Every stage answers; the only refusals left are legitimate.

NEXT: the first genuine cold restart on this machine is the "one observed end-to-end unattended
cycle" acceptance box. When it is observed, flipping `DEFAULT_ENABLED` to `True` is that box's
payoff (per the constant's own comment). Do NOT flip it before then.

### ⏵ 2026-08-19 00:30 — llm-ext 13.5.7 CONTRACT FIX confirmed live; the CODE blocker is CLEARED. Remaining = transient free-pool 429 only.

Probed 13.5.7 directly this session (`llm-ext session-summary --stdout --transcript <13.4MB prior
transcript>`, `CLAUDE_PLUGIN_DATA` unset per the janitor's own contract). Result: **rc=1**,
empty stdout, and a CLASSIFIABLE stderr message — no longer the silent empty-on-zero:
`FAILED: session-summary: chunk 6 hit a rate limit on 'google/gemma-4-31b-it:free' … Checkpoint
saved … re-run to resume once the limit clears (free daily quotas reset at 00:00 UTC)`. So
llm-ext's TRDD-P4ULUV1R fix (empty/failed summary → NON-ZERO exit with a one-line reason) is
**live on this host**, and the janitor side is already correct: `run_llm_ext_summary` returns
None on `returncode != 0` → degrades to template. The 14×-empty-on-ZERO loop that defined this
blocker on 3.3.16 cannot recur under 13.5.7 — a failed attempt now exits non-zero and is
classified, not retried-into-a-template silently.

What actually failed in the probe is a genuine **free-pool 429** (OpenRouter free models
rate-limited upstream right now) — TRANSIENT/environmental, NOT a code defect, and exactly the
"machine-wide free-pool contention" the 21:50 note already suspected. This maps into the
janitor's existing bounded-UNKNOWN/transient classification with no janitor change (per the
21:50 close-condition note). A checkpoint was saved (`…/session-summary-checkpoints/
b928b4e23333f543.json`); a resume after the 00:00-UTC quota reset would produce the real summary
and directly evidence the summary half succeeding on this host with 13.5.7.

**Status change: this card is no longer blocked on llm-ext CODE.** The CLOSE CONDITION (an
unattended cycle whose SUMMARY half succeeds) is now gated ONLY on catching a genuine idle
window while the free pool has quota — a timing/environmental matter, not a fix. DEFAULT_ENABLED
still stays False until such a cycle is observed (the bar is unchanged); but the risk that the
bar could never be met because of a CLI contract gap is retired.

### ⏵ 2026-08-18 21:00 — a REAL unattended cycle fired, but it only proved the FAIL-SAFE half.
### DEFAULT_ENABLED stays False; the summary half is 100% degraded on this host.

Measured in `global-state/external-clear.log` (session 98b5f8c0): at 17:56:14 the trigger
genuinely fired unattended (`trigger=long-idle`, 304954s ≥ 3600s) and a handoff WAS produced —
but only after **14/14 summary attempts** returned `transient — empty summary on a zero exit`,
so the handoff `degraded to template` and the cycle repeated the same shape at 18:01. The
"never produces no handoff" safety property is now proven live; the llm-ext summary half has a
**0% success rate** on this host. Note this is NOT the rc!=0 `(nonconforming)` class —
`f5c0543f`/`5e1d7fab` are in the running v3.3.16 (verified by tag ancestry) — it is rc=0 with
EMPTY output, i.e. llm-ext succeeding with no content. Reported to the llm-externalizer peer
session this evening. **Decision under the USER's delegation: the flip's bar is an observed
cycle whose SUMMARY half worked, not one that only exercised the template fallback — a default
rollout on a 0%-summary host would ship the degraded experience as the product.** Card stays
`testing`, box stays open, blocker is llm-ext's empty-summary-on-zero-exit.

### ⏵ 2026-08-18 ~21:50 — peer diagnosis landed; blocker OWNED with an ETA; janitor half done

The llm-externalizer session confirmed the CONTRACT GAP in their code (session-summary's
--stdout path returns the assembled summary with no final gate — empty at exit 0), will make
empty-final-summary a NON-ZERO exit with a classifiable one-line stderr message in
**llm-ext ≥ 13.5.7** (their TRDD-P4ULUV1R), and could NOT reproduce the 17:23-17:56 window on
the current build (same transcript → 5743-byte real summary; the window coincided with
machine-wide free-pool contention). Two janitor-side facts settled in the same pass:
- the 14× window ran the PRE-3.3.16 plugin — the per-attempt forensic evidence line
  (`attempt N [outcome] detail | …stdout/stderr excerpts`) shipped in 3.3.16 (`617e3fcd`),
  which is why the window's log had no evidence lines; the next failure will carry them;
- their request (persist the CLI's stderr tail on failed/empty attempts) is DONE: the
  evidence line's stderr excerpt tail widened 400 → 2000 chars (~20 lines) on the failure
  paths — stdout is the summary alone by contract, so stderr is where every diagnostic lives.
CLOSE CONDITION unchanged: an unattended cycle whose SUMMARY half succeeds, expected after
llm-ext ≥ 13.5.7 + the next genuine idle window; their fixed rc!=0 maps into our existing
bounded-UNKNOWN/transient classification with no janitor change needed.

**Column `todo` since 2026-08-12.** Nobody is working this — 0/5 acceptance, and the NEXT ACTION
(wire the watcher) is known and concrete, so it is pullable rather than in progress.
*(2026-08-15 correction: the watcher/hook IS wired and shipped in v3.3.0 — the remaining work is
the observed-cycle acceptance + default flip above, not the wiring.)*

*History, kept because the reasoning was sound and only the state moved:* this block opened with
**"Column `dev` since 2026-08-06 … `todo → dev` skipped `design`/`dispatch` (mono-agent
self-assignment)"** — true when written. The card was RE-COLUMNED `dev → todo` on
2026-08-12T15:39:16+0200 (see `## Approval log`) because a WORK column asserts active work and
nobody was working it after 6 idle days. A 2026-08-13 readiness audit was then appended BELOW
without anyone revisiting this opening sentence, so the line a reader is told to read FIRST
claimed `dev` while the frontmatter and the card's own audit trail said `todo`. Corrected
2026-08-13 after a full STATE-vs-column sweep of all 60 non-terminal cards found it — the only
such contradiction on the board.

### ⏵ READINESS AUDIT 2026-08-13 — everything is built EXCEPT the invocation

Audited end-to-end because the owner is about to re-attempt free compaction on a fixed
llm-externalizer. Verified from the tree, not from this card:

- **llm-ext IS live**, not rejected — see the corrected row 2b. `llm-ext` resolves on PATH at
  **13.1.0**; `use_llm_ext()` defaults True; the composer falls back to the template on failure.
- **The watcher has NO CALLER.** Exhaustive search (`*.py`/`*.json`/`*.md`/`*.sh`, whole repo):
  every hit is this card, TRDD-1QJIZFFW, two test files, the auto-generated CLAUDE.md map, a
  memory page, or its own docstring. **No `dispatch.py` roster entry and no `daemon.py` task** —
  `dispatch.py:943` still calls it "the future external-clear watcher".
- **Feature flag is DEFAULT OFF** (`DEFAULT_ENABLED = False`, `external_clear.py:64`).

**Consequence, and it is the whole point of this audit: flipping the knob ON changes NOTHING.**
Two independent gates stand between built and running — the flag AND a caller — and only the
flag is discoverable from the config. That is this project's recurring shipped-dark shape
(G4BCRUP7), here in its most expensive form: a fully-tested feature (43 tests across parts 1+1b)
that cannot execute.

**So the remaining work is exactly two steps, in this order:** (1) wire the invocation as a
**HOOK** per the owner's 2026-08-12 correction below — NOT the daemon task this card originally
specified; (2) flip the default. Step 1 is gated on the `user-decision-run-the-clear` that blocks
TRDD-1QJIZFFW, because it is the first change that can `/clear` OTHER projects' sessions and a
clear is unrecoverable. Nothing here is blocked on llm-externalizer.

### Component state

| Part | State |
|---|---|
| 1. Watcher — pure gate | **DONE** `scripts/lib/external_clear.py` (`def783f5`), 29 tests |
| 1b. Watcher — gather + fire CLI | **DONE** `scripts/external_handoff_clear.py` (`95a5beda`), 14 tests |
| 2. Handoff writer — template | **DONE** `compose_template_handoff`, passes `check_handoff_concise` by construction |
| 2b. Handoff writer — llm-ext upgrade | **STALE ROW — it was re-attempted and SHIPPED.** `73a426c4` built it, `07e8d986` removed it, then `df7d4cb3` (TRDD-1QJIZFFW) wired it for good: `external_handoff_clear.py:260` calls `ec.run_llm_ext_summary(transcript)` when `use_llm_ext()` (default **True**) and a transcript exists, degrading to the template on any failure — "both branches produce a handoff; neither can produce none". Verified 2026-08-13. Do NOT read the old "REJECTED" wording as current: it would send the next pass to rebuild a live feature, or to refuse a re-attempt the owner has since asked for |
| 3. Typist | **DONE, ZERO CHANGES** — `clear_trigger._spawn_chain` reused verbatim |
| 4. Daemon wiring | **NOT STARTED** — the only thing between this and unattended operation |

Shipped **DEFAULT OFF** (`CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED`, default false).

### NEXT ACTION (one step, runnable)

**Correction (USER, 2026-08-12): the "wire into `scripts/daemon.py`" shape below is WRONG.** The
handoff is invoked by a HOOK, not a skill/command/daemon task. The hook layer already exists and
runs: `PreCompact → pre-compact-handoff.py`, `PostCompact → post-compact-resume.py`,
`Stop → on-stop-proactive-compact.py`. See TRDD-1QJIZFFW for the USER's payload spec (llm-ext
summary file + scriptable TRDD facts + a TRUNCATED message tail, budgeted so the injection never
refills the context it was built to empty). The daemon-wiring text below is SUPERSEDED — do not
carry it forward.

Wire the watcher into `scripts/daemon.py`: add `_INTERVAL_EXTERNAL_CLEAR` (600 s — an idle
session stays idle; this need not be responsive) + `task_external_handoff_clear()` that walks
`fleet_scan.gather_fleet()` and runs `external_handoff_clear.py --project-root <inst.project_root>`
per instance, then register it in `_build_tasks()`.

**Two filters that gate must carry, and neither is optional:**
- **skip `server_owned` instances** — inside an ai-maestro harness the actuation belongs to the
  server (the janitor#100 split), so typing into those panes is a boundary violation;
- **skip any instance whose `diagnosis` is not healthy** — a `frozen` / `cron_dead` session needs
  RECOVERY, not a clear. Clearing a frozen session destroys its cron while it cannot re-arm.

### Why phase 3 was NOT done in the same pass

It is the first change that can act on OTHER projects' sessions, and `/clear` is unrecoverable.
Phases 1–2 are inert without it (nothing calls the CLI), so stopping here leaves a fully-tested,
independently-runnable artifact and no live blast radius. Verify the two filters above against
`fleet_scan.Instance` before wiring.

### The llm-ext composer: built, measured, removed (do NOT re-attempt blind)

One real call, 2026-08-06, no mocks. `llm-ext` itself works fine (exit 0, report path on
stdout, ~$0 on the free pool). It is the wrong SHAPE for this consumer:

- it returns an **ensemble report**, not a handoff — a metadata header plus one
  `## Model: <name>` section per model in the profile's ensemble (3 here), each restating the
  same summary differently; **3250 bytes for ONE input file**;
- **one** file took **>90 s** (the first end-to-end run returned `None` purely because the
  180 s cap could not cover 4 files — a correct fallback, but a silent one);
- using it would mean parsing three competing answers and picking one — a fresh judgement
  call, on generated text, in a directive position, guarding an unrecoverable `/clear`. The
  safety gate it needed (marker-mimicry + fence + concision) was evidence of the problem.

**The card already contains the argument against needing it**, in the owner's own words about
the fallback: *"a template handoff from the STATE blocks alone (they are the durable payload
anyway)"*. The STATE block is authoritative and the next session reads it directly; the
handoff's job is to POINT at it. An LLM summary of an authoritative document is lossy where a
pointer is not. The acceptance box is met by its stated alternative — zero main-model tokens,
via the template.

Re-open this only if the goal changes from *pointing at* the payload to *summarising* it, and
only with a single-model (non-ensemble) profile.

### Verified so far (do not re-verify)

- `--dry-run` on this live session → `VERDICT HOLD trigger=- why=user-present`. The presence
  veto works against a REAL breadcrumb, not a fixture.
- `clear_trigger.py` needed **no** modification — its `--__chain` child already takes pane +
  state dir + directive as DATA. The one requirement is setting `CLAUDE_PROJECT_DIR` for the
  child (its fallbacks resolve to the DAEMON's cwd, which would strand the cleared session).
- 43 tests green, `ruff` + `mypy` clean.

### Load-bearing findings (measured on THIS machine 2026-08-06 — do not re-derive)

- **The card's stated trigger is DEAD as written here.** `.janitor/state/ttl-regime.json` says
  `minutes: 60` (probed) and `armed-cadence.cron` is `*/5 * * * *`. A fire every 5 min against a
  60-min TTL means the prompt cache **never** expires while armed, so a literal `cache-expired`
  predicate is never true — the "threshold high enough to never be met is a feature that does not
  exist" failure `cold_cache_compact` already burned on twice.
  **DEVIATION (owner may veto):** the gate ORs two triggers and names which one fired —
  (a) *next-fire-misses* — `age_since_last_turn + seconds_until_next_fire >= ttl` (the card's
  intent, correctly expressed: the point is that the NEXT fire pays the miss, not that the cache
  is already cold); and (b) *long-idle* — nothing but beats for ≥1 h (owner directive 2026-08-04),
  which is what actually bites here: the handoff records ~10 M cache-**read** per warm fire and
  177.7 M of the 7 d weighted spent on janitor fires alone. Trigger (b) alone justifies the card.
- **Terminal identity is already solved out-of-session.** `.janitor/state/terminal-identity.json`
  exists (`iterm_session_id` = `w0t1p0:<uuid>`); `fleet_restart.recorded_terminal()` reads it. It
  returns the FLEET shape (`iterm_session_id`/`tmux_pane`); `clear_trigger._this_terminal()` and
  `terminal_trigger` use the OTHER shape (`kind`+`pane`/`session_id`). An adapter is required —
  and `ITERM_SESSION_ID` is `<tty>:<UUID>`, so the UUID must be split off exactly as
  `_this_terminal()` does, or `_UUID_RE` rejects it.
- **Unknown-context must NOT veto** (repeat of the 2026-08-04 correction on
  `should_clear_when_long_idle`): an unmeasurable transcript silently disabled the lever. Unknown
  **idle**, however, still vetoes — an unknown idle age may never authorize a destructive act.
- The existing in-model lever (`dispatch._phase_idle_clear_nudge`, TRDD-5C42VCUX) shares the
  `idle-clear-fired.ts` cooldown stamp, so whichever fires first stands the other down. Keep that
  sharing — it is the coexistence contract while both exist.

### SUPERSEDED — do NOT carry forward

- "watcher fires only on idle + **cache-expired** + over-threshold" — replaced by the two-trigger
  OR above. The acceptance box is rewritten accordingly.

### Artifacts to read first

`scripts/clear_trigger.py` (the typist + `check_handoff_concise`) ·
`scripts/lib/cold_cache_compact.py` (the CLEAR section + why size was dropped) ·
`scripts/dispatch.py::_phase_idle_clear_nudge` (the in-model sibling).

## WHY

Today's shape: session idle, prompt cache expired (>5-min TTL), the NEXT heartbeat fire
pays a full ~400–460k cache-miss write just to say "nothing to do" — and the current
handoff flow makes it WORSE, because authoring the handoff is itself a model turn on the
huge context. The owner's requirement, verbatim intent: when the cache is expired and
the session is idle, the janitor must handoff-and-clear WITHOUT triggering a model run —
monitor the terminal from OUTSIDE, compose the handoff for free, and type `/clear` at
the right moment (before the next turn executes).

## Design shape (three parts, all OUTSIDE the model)

1. **Watcher** (daemon task or detached per-session child): detects
   idle + cache-expired + context-above-threshold. Inputs it already has: the
   context snapshot / token meter, transcript mtime, `user_intent.user_is_present`,
   the cadence state. Timing contract: act in the idle gap BEFORE the next cron fire
   would enqueue a turn (it knows the armed cron's schedule).
2. **Handoff writer, zero tokens**: `llm-ext` CLI (chat/scan over the transcript
   JSONL + the TRDD STATE blocks ON DISK — pass paths, never content) composes the
   link-only handoff into `.janitor/state/agent-handoff.md`, honoring the existing
   concision contract (`clear_trigger.check_handoff_concise`). Free mode / auto-free
   makes this ~$0; the model never wakes. Fallback when llm-ext is absent: a
   template handoff from the STATE blocks alone (they are the durable payload anyway).
3. **Typist**: the ALREADY-RATIFIED injection chain (`terminal_trigger.run_chained_inject`
   — pane-free wait, 8s retry, stop-on-keystroke, verified submit) types `/clear` then
   the arm+resume bootstrap. iTerm via python/osascript, tmux via send-keys; inside the
   ai-maestro harness the actuation is the server's per the janitor#100 split — file the
   ask upstream if a harness variant is wanted (see also ai-maestro#110).

## Acceptance

- [x] watcher fires only on user-absent-per-rules AND (next-fire-misses OR long-idle), never on
      unknown idle; over-threshold applies only when the context is measurable (see STATE)
- [x] handoff written by llm-ext with ZERO main-model tokens (or template fallback), passes
      check_handoff_concise
- [x] /clear + bootstrap land via run_chained_inject with no model turn before them
- [ ] one observed end-to-end unattended cycle: big idle session → external handoff →
      clear → re-arm → resume, with the verify harness PASS table
      — the CYCLE was observed 2026-08-15 (below); the `handoff_clear_verify.py` PASS table was NOT
      captured, so this stays open on that half alone
- [x] cost note: measured per-cycle cost vs today's per-fire cache-miss write — see
      `reports/trdd-verify/20260829_224254+0200-79LXF6PJ-token-saving.md` for the NEW-path
      cost, cross-referenced against this TRDD's own baseline below.

### Cost note (2026-08-29)

- **Baseline (today, no fix)**: this TRDD's own WHY (line 281) states the next-fire
  cache-miss write is **~400,000–460,000 tokens**; sibling TRDD-5C42VCUX (line 86, 120)
  independently states the same range for the same trigger ("EVERY fire re-paid a
  ~400–460k cache-miss WRITE"). Not re-measured here — cited from the existing corpus.
- **NEW path (external handoff+clear, this TRDD)**: **0 Claude-side tokens, $0** —
  verified by reading source in `reports/trdd-verify/20260829_224254+0200-79LXF6PJ-token-saving.md`
  §1: `external_handoff_clear.py::_compose()` calls `run_llm_ext_summary()`, which shells
  out to the `llm-ext` CLI (a $0 external OpenRouter model); grep of both modules for
  `anthropic|claude.*api|messages.create` returns nothing, so no Anthropic API call exists
  on the handoff-composition path this TRDD ships. The `/clear` + bootstrap step (typist,
  box 3) is a terminal keystroke injection, not a model turn — also 0 tokens.
- **Arithmetic**: saving per avoided cycle = baseline − new = (400,000–460,000) − 0 =
  **400,000–460,000 tokens (100% of the cache-miss write), per fire this mechanism heads off**.
  In dollars this is model-rate-dependent (not separately measured): at Sonnet's
  $2.50/MTok input × 1.25 cache-write multiplier ($3.125/MTok) ≈ **$1.25–$1.44**; at
  Opus's $6.25/MTok × 1.25 ($7.8125/MTok) ≈ **$3.13–$3.59**. Both dollar figures are
  LABELLED derivations from the token range above, not independent measurements.
- **What the cited report does NOT cover directly**: report 79LXF6PJ measured the
  Claude-side cost of a full *compaction* turn over a 12MB/9,216-line transcript
  (693k–3.0M tokens, bytes÷4 approximation) — a different, larger event than the
  ~400–460k "next-fire cache-miss write" this box asks about. The two are compatible
  (both show the NEW path's Claude-side cost is 0 either way) but are not the same
  denominator; the 400–460k figure used above comes from this TRDD's own WHY section
  and TRDD-5C42VCUX, not from 79LXF6PJ.

## ⏵ 2026-08-15/16 — OBSERVED IN PRODUCTION, and it found two real defects

The watcher fired for real at **21:29:58** on this project: `trigger=resumed-cold`,
`context=431357`, handoff composed and written, `/clear` typed, and the fresh session bootstrapped
and resumed from `.janitor/state/agent-handoff.md` — the cycle this card is about, with zero model
turns in front of it. That is boxes 1 and 3 satisfied by observation rather than by argument.

It also surfaced two defects that the toy fixtures could not, both now fixed:

1. **The handoff had no summary.** `summary: permanent — llm-ext is not on PATH; not retrying` —
   the CLI lives in a plugin-cache bin dir that an interactive profile puts on PATH and a
   hook-spawned child never inherits. Fixed in TRDD-CEWVQ8DG (`resolve_llm_ext`, shipped v3.3.6).
2. **The handoff VIOLATED the contract it is gated by.** The same fire logged
   `handoff violates the concision contract: ['too-large']` and injected it anyway. Cause:
   `compose_handoff` defaulted to **8192** while `clear_trigger.check_handoff_concise` enforces
   **4096**, and the caller passed neither — a producer and its checker tuned independently, which
   is the second time this file has paid for that (see `_FLEET_LEASE_TTL_MARGIN_S`). Both composers
   now default to one `HANDOFF_MAX_BYTES` constant.

**Why no test caught #2, which is the more useful half.** The existing guard
(`test_composed_handoff_satisfies_the_concision_contract`) composes ONE card and no transcript, so
its handoff is far too small to reach either budget and passes under both — green while production
violated the contract. The new `test_a_REALISTIC_handoff_passes_the_contract_with_defaults` uses a
handoff the size a real project produces, and the fix is proven by measurement rather than
assertion: the same input at the old default yields **8184 bytes, `['too-large']`** — the exact
reason string from the production log — and **3883 bytes, passing** at the new one. A constant-
equality test now pins producer and checker together so they cannot drift apart again.

## Pointers

- Sibling/prereq relationship: TRDD-5C42VCUX (make the EXISTING in-model idle-clear
  engage — the stopgap while this lands).
- Reuse: `handoff_clear_verify.py` (proof harness), `clear_trigger._run_chain_payload`
  (the chain child), `lib/token_meter.resolve_context`, `lib/user_intent`.
- llm-ext rule: ~/.claude/rules/use-llm-externalizer.md (paths not content; --estimate
  on paid profiles; auto-free on low balance).

## Approval log

- 2026-08-12T15:39:16+0200 — RE-COLUMNED dev → todo by janitor-main-session. A WORK column
  asserts active work; nobody was working this (idle 6d). 0/5 acceptance; NEXT ACTION is known
  and concrete (wire the watcher). No scope or acceptance changed.
- 2026-08-29T22:30:00+0200 — UNBLOCKED. The blocker (TRDD-X4LJFTB4, GitHub push protection on the
  3.4.0 publish) was resolved and v3.4.0/v3.4.1 shipped; restored to the pre-block column.
- 2026-09-02T05:16:16+0200 — testing → blocked by janitor-main-session (delegated review authority, USER 2026-09-01). Blocked on TRDD-QZVAEWQH (daemon llm-ext has no OpenRouter key under launchd) and TRDD-BDZG8Y8A (no before-snapshot on the daemon fire path); four of the five cycle elements observed live 04:23.
