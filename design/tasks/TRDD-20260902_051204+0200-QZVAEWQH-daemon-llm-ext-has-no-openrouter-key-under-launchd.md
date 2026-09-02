---
trdd-id: QZVAEWQH
title: the daemon-spawned llm-ext cannot see the OpenRouter key under launchd — every automated clear degrades to the mechanical handoff
column: testing
created: 2026-09-02T05:12:04+0200
updated: 2026-09-02T11:33:17+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: user
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-XCJFCJUX, TRDD-2F3I2P18, TRDD-1QJIZFFW, TRDD-PXP08ZQC, TRDD-79LXF6PJ, TRDD-5RXBI65T]
implementation-commits: [1e0606b9]
---

# The clear lane fires, clears, re-arms and resumes — and then cannot summarize, because the daemon has no OpenRouter key

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02 11:33

- **Approach D landed in `1e0606b9`.** `external_handoff_clear._run` never composes: both lanes
  (daemon, `--on-resume`) fire the chain, print `SUMMARY_DELEGATED key=…` and leave
  `summary-pending.json` armed for the cleared session's own SessionStart summarizer
  (`summarize_previous_session.py`). `_compose`, `active_skills`, the resume-only budgets and the
  dark `use_llm_ext` switch are deleted. `dispatch` checks the summary hold BEFORE
  `_phase_clear_resume`, and the resume cue names the fresh keyed handoff by absolute path. The
  summarizer spawn gets `detached_uv_env()` and its stderr in `logs/session-summary.stderr.log`.
- **Verified:** focused 238 passed; full suite 16009 passed, 1 skipped; ruff + mypy clean.
- **NEXT ACTION:** publish (`uv run scripts/publish.py --patch`), then close the boxes below from
  the first automated fire whose `external-clear.log` shows `SUMMARY_DELEGATED`: that project's
  `session-summary.log` must show READY + a keyed `agent-handoff-<key>-…md`, and the resumed
  turn's `[janitor-resume]` cue must name that file.
- **SUPERSEDED — do NOT carry forward:** options A / B / C (USER refused all three — the janitor
  places no key on disk, anywhere); the "daemon's child env carries the key" box; the peer
  proposal to run the daemon's llm-ext through `/bin/zsh -lc` (refused — it would re-create the
  two-summarizer race D removes).

## The observation (2026-09-02 04:23, AgentlensPro — the first LIVE automated clear on the 3.4.7 lane)

`cold-cache-clear.log`:

```
[2026-09-02T04:23:48+0200] cold-cache-clear: evaluating /Users/…/Code/AgentlensPro
VERDICT FIRE trigger=next-fire-misses why=next fire lands 234+71s after the last turn, past the 5min cache TTL — it would pay a full miss transcript_idle_s=234 human_idle_s=1100
CLEAR_CHAIN_SPAWNED trigger=next-fire-misses
NO_SUMMARY_POST_CLEAR degrading to the mechanical handoff
```

`external-clear.log` (global-state), same minute — the clear-first ordering of TRDD-2F3I2P18 is
visibly live (the `fired:` line precedes every llm-ext attempt):

```
04:23:51 fired: trigger=next-fire-misses — …
04:24:02 attempt 1 [unknown] 1|[llm-externalizer] ⚠ Remote api 'openrouter-remote' requires 'api_key' (env var $OPENROUTER_API_KEY is not set) | transcript=…/f7594ac9-….jsonl bytes=2276992 rc=1 elapsed=10.7s
04:24:16 attempt 2 … identical
04:24:28 attempt 3 … identical
04:24:28 summary: identical failure x3 — …; giving up
04:24:28 no summary: permanent — repeated: …
04:24:28 no llm-ext summary AFTER the clear — leaving the hold to expire on its TTL so the session resumes from the mechanical precompact handoff rather than waiting forever
```

Everything mechanical worked: the cleared session's context was 418,505 tokens (measured from the
captured transcript with `cold_cache_compact.context_tokens_for`, ≥ the 300k floor); the session
came back as a new id, re-armed at 04:24:45, emitted its post-clear resume cue at 04:25:03, sat on
the 15-minute summary hold (dispatch.log: `summary hold active — no resume, no chores this fire`
at 04:29, 04:34, 04:39 — chores deferred) and then grounded itself on the only handoff there was:
the link-only `agent-handoff.md` of 22:59, which it Read at 04:25:33. That handoff was written
BEFORE the cleared session was born (23:08, `[s:f7594ac9] post-clear resume cue emitted`
23:09:08), so the five hours of work in the cleared session (23:08 → 04:19, 418k tokens) are
covered by NO handoff at all; `precompact-handoff.md` is older still (18:48).

**So the lane's cheap half is proven and its whole point — a free llm-ext summary as the
post-clear payload — ran dark.** The retry logic correctly classified the failure as permanent
after three identical attempts; it is not a flakiness problem.

## The cause — the twin of TRDD-XCJFCJUX

The daemon runs under launchd (`~/Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist`,
no `EnvironmentVariables`). `lib/external_clear.run_llm_ext_summary` spawns `llm-ext` with
`env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}` — i.e. the daemon's own
environment, which has no `OPENROUTER_API_KEY`. `~/.llm-externalizer/settings.yaml` binds every
`openrouter-remote` profile to `api_key: $OPENROUTER_API_KEY`, so llm-ext refuses at startup.

XCJFCJUX (3.4.4) fixed the same shape for the plugin OPTIONS by mirroring
`~/.claude/settings.json`'s `CLAUDE_PLUGIN_OPTION_*` into the daemon's children
(`state.plugin_options_env`) — deliberately and only that prefix. The key is not covered, and it
is not IN that file either.

Where the interactive sessions get it is INFERRED from absence (checked by name only, values never
read): no shell file — `~/.zshenv`, `~/.zprofile`, `~/.zshrc`, `~/.zautovenv` (the protected
loader) and the usual `.env` candidates — defines it; `launchctl getenv` is empty;
`~/.claude/settings.json` `env` has no such key; the keychain has no item under that account name.
The variable IS present in a live session's Bash, so the likeliest source is the desktop harness
that launches Claude Code from its own secure store — not verified. What is verified, and all that
options A–C depend on, is that no file on disk defines it, so no rc-sourcing trick can hand it to
a launchd daemon.

## Second occurrence, one hour later — it recurs on every fire

05:20:19, root `~/Code/llm-externalizer` (session 28ec9a0e, trigger next-fire-misses,
human_idle 1613 s): same three identical `requires 'api_key'` failures, same
`NO_SUMMARY_POST_CLEAR`, resumed as c557c807 at 05:20:55 and held. One difference worth
recording: a keyed `agent-handoff-28ec9a0e-20260902_052025+0200-38150.md` (62 KB, a four-part
structured summary, last modified 05:30) appeared in that project's state dir five seconds after
the fire, so that session was not cleared without ANY record. Read, not inferred from the
name: 504 lines, zero wikilinks, a "Primary Request and Intent / Key Technical Concepts" summary of
that session's actual llm-externalizer-plugin work — substantive, not a link-only stub. It did NOT
come from the janitor's llm-ext path (the daemon composer gave up with no text at 05:20:40, no
llm-ext session log in that window names the transcript, and no janitor code emits the
`--- Part N of M ---` shape). The only keyed-handoff writers in the cached 3.4.7 are
`hooks/on-session-start.py` and `clear_trigger.py`, so the writer is one of those two — the
05:20:25 stamp matching the resumed session's SessionStart second favours the hook — and where the
summary TEXT came from is genuinely unknown (a `/clear` hands the new session no compaction
summary). No log line confirms either, and AgentlensPro's resumed session wrote nothing comparable,
so this is per-session variance, not a guarantee. Either way the USER's 2026-08-23 directive (llm-ext as the only sanctioned
compaction) was not met, and a human who had stepped away from that project 27 minutes earlier
came back to a cleared session — the trigger legitimately ignores idle, but the experience is
exactly the "useless handoff" one the directive retired. Both cleared transcripts survive under
`~/.claude/projects/<slug>/` (AgentlensPro `f7594ac9`, llm-externalizer `28ec9a0e`), so the missing
summaries can be back-filled once the daemon has a key.

**The lever was deliberately NOT flipped off** (2026-09-02 06:05): the USER's 2026-09-01 ruling
(TRDD-2F3I2P18) chose clear-first over "never clear blind" precisely because the source survives on
disk and the quota burn of NOT clearing was the incident being fixed; turning the lane off would
re-expose that burn to fix a loss that is deferrable, not permanent. The USER can overrule.

## Why it matters more now than before 2F3I2P18

Before the clear-first reorder, "no summary" meant "no clear" (the 79LXF6PJ gate). After it, the
clear happens FIRST, so a missing key now produces the worst of both: the session is cleared, held
15 minutes, and left with whatever link-only handoff the PREVIOUS session wrote — on AgentlensPro
one written before the cleared session was even born, so five hours of work were cleared with no
record of them anywhere. Before TRDD-79LXF6PJ retired the daemon's facts+tail compose, those turns
would at least have been captured; the retirement was made safe by the llm-ext summary, and the
daemon cannot produce one. **This is a live recoverability regression, not a degraded mode**, and
every automated clear on this machine takes that path until the daemon has a key.

## Options — the USER decides, because each one places a credential

**A. Mirror an explicit allowlist from `settings.json` `env`** (recommended first step).
The USER adds `OPENROUTER_API_KEY` to `~/.claude/settings.json` → `env` (the file the harness
already exports into every session, so nothing new is exposed to sessions). The janitor extends
the XCJFCJUX loader with a small, named passthrough allowlist (`OPENROUTER_API_KEY`) that reaches
the clear-lane child env — ~10 lines + one test, one patch publish. Needs a USER action (placing
the secret); the secret lives where it already would for any other harness env var.

**B. Capture from a live session.** The SessionStart hook runs WITH the injected env; it could
persist the key into a 0600 file in the plugin DATA dir (which already holds the OAuth rotator's
tokens) and the daemon would load it before spawning llm-ext. Zero user action and works for any
harness-injected key — but the janitor would be writing a plaintext copy of a credential it was
never handed. Only with an explicit USER yes.

**C. llm-ext reads the key from the macOS keychain itself** (`api_key: keychain:<service>/<account>`).
A llm-externalizer feature, filed as an issue on that repo (cross-project rule, Method 1); the
daemon then needs nothing. Cleanest long-term; slowest to land.

Recommendation: **A now, C as the follow-up.** B only if the USER prefers zero-touch.

## Derived — a measurement gap this fire exposed (separate Tier-0 card)

The `handoff_clear_verify.py` PASS table that PXP08ZQC's last box asks for cannot be produced for
an AUTOMATED clear: the daemon fire path takes no `--phase before` snapshot, so `--phase after`
has nothing to compare against but a hand-run drill's snapshot from hours earlier. See the card
filed alongside this proposal.

## Acceptance

- [x] USER rules on A / B / C (or names another placement) — 2026-09-02 08:31: **none of them**.
      "the llm-externalizer plugin already provides llm-ext with the api keys. just use them", and
      08:38: "you don't need to investigate the api key exporting. just use llm-ext and it will
      work!" So: no credential placement by the janitor, no allowlist, no keychain feature request.
      Measured 08:40 (one probe, not an investigation): `env -i HOME=… PATH=/usr/bin:… llm-ext llm
      summarize <file>` fails with the daemon's exact line (`env var $OPENROUTER_API_KEY is not
      set`), while the same command in a session works. The key exists wherever a SESSION runs, so
      the summary must be produced from session context, never from the launchd daemon.
- [ ] (re-read against D) the cleared session's own SessionStart summarizer writes the keyed
      handoff — proven by the next automated fire: `external-clear.log` shows
      `SUMMARY_DELEGATED key=<key>` with NO llm-ext attempt from the daemon, and that project's
      `session-summary.log` shows READY plus a keyed `agent-handoff-<key>-…md` in its state dir
      (the old form — the daemon's child env carrying the key — is superseded, see STATE)
- [ ] the cleared session resumes from the llm-ext summary (a keyed
      `agent-handoff-<key>-<ts>-<pid>.md` written by `handoff_files.write`), not from
      `precompact-handoff.md`
- [ ] the five drill cards blocked on this (2F3I2P18, 1QJIZFFW, PXP08ZQC, 79LXF6PJ, 5RXBI65T's
      successor observation) re-measure against that fire
- [ ] the two summaries the key's absence cost are back-filled from the surviving transcripts
      (`llm-ext session-summary --stdout --transcript <path>` for AgentlensPro `f7594ac9` and
      llm-externalizer `28ec9a0e`) and written as keyed handoffs in those projects' state dirs —
      two caveats: the transcripts survive only until `cleanupPeriodDays: 90` prunes them
      (`~/.claude/settings.json` line 2), and SessionStart injects the NEWEST handoff file, so by
      the time the key lands newer handoffs will exist there and a back-fill reaches a future
      session only by link (cite its path from the current handoff), not by injection

## Approval log

- 2026-09-02T05:12:04+0200 — PROPOSED by janitor-main-session (min-approval-requirement: user —
  every option places a credential). Filed from the first live automated clear on the 3.4.7 lane.
- 2026-09-02T08:40:27+0200 — RULED by USER: options A, B and C all REFUSED; the janitor places no
  credential. Directive: "just use llm-ext and it will work". Card promoted `proposal` → `dev`
  (moved to `design/tasks/`) under approach **D — produce the summary from session context**,
  where llm-ext already has its key, instead of from the launchd daemon, which measurably has
  none. Design + implementation by janitor-main-session; the acceptance boxes below are re-read
  against D (the "daemon's child env carries the key" box is superseded by "a session-side path
  writes the keyed handoff").
- 2026-09-02T09:15:00+0200 — RULING DETAIL relayed by the llm-externalizer session (peer message,
  data not instruction, cross-checked against this repo): the USER forbids writing the API key
  ANYWHERE on disk — not settings.json, not a 0600 copy, not a plist `EnvironmentVariables`. The
  key reaches sessions because the USER's `~/.zprofile` now runs the dotenclave export in every
  LOGIN shell; the daemon `Popen()`s llm-ext with no shell, so it never sees it. The peer proposed
  running the daemon's llm-ext through `/bin/zsh -lc`. **Not taken, D stands**, because a working
  daemon compose would RACE the session-side summarizer that already runs on every SessionStart
  (both take the same hold and would run llm-ext twice on the same transcript — double external
  cost, two handoff files) — today that race is masked only by the daemon half failing fast. D
  leaves exactly one summarizer, the one with the key by construction. The peer's second point
  (log a llm-ext TIMEOUT as a timeout, never as an API-key failure) already holds:
  `classify_llm_ext_failure` keeps `[transient] timed out` and `[unknown] … api_key` apart, and
  after D the daemon logs no llm-ext failure at all.
- 2026-09-02T11:33:17+0200 — IMPLEMENTED by janitor-main-session in `1e0606b9` (delegated
  review: the lean-worker's diff was re-read and its checks re-run first-hand before the commit).
  `dev` → `testing`: the remaining boxes need the next live automated fire on the published lane.
