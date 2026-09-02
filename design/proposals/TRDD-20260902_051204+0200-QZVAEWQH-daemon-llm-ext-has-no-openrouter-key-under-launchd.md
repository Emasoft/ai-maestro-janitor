---
trdd-id: QZVAEWQH
title: the daemon-spawned llm-ext cannot see the OpenRouter key under launchd — every automated clear degrades to the mechanical handoff
column: proposal
created: 2026-09-02T05:12:04+0200
updated: 2026-09-02T05:12:04+0200
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
implementation-commits: []
---

# The clear lane fires, clears, re-arms and resumes — and then cannot summarize, because the daemon has no OpenRouter key

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
at 04:29, 04:34, 04:39) and then continued from the mechanical `precompact-handoff.md` — whose
mtime was 18:48 the previous day. The model-authored `agent-handoff.md` (22:59) was untouched.

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

Where the interactive sessions get it (verified, names only, values never read): NOT from any
shell file — `~/.zshenv`, `~/.zprofile`, `~/.zshrc`, `~/.zautovenv` (the protected loader) and
the usual `.env` candidates define nothing; `launchctl getenv` is empty; `~/.claude/settings.json`
`env` has no such key; the keychain has no item under that account name. The variable is present
in a live session's Bash, so it is injected by the desktop harness that launches Claude Code from
its own secure store. A launchd daemon can never inherit that.

## Why it matters more now than before 2F3I2P18

Before the clear-first reorder, "no summary" meant "no clear" (the 79LXF6PJ gate). After it, the
clear happens FIRST, so a missing key now produces the worst of both: the session is cleared, held
15 minutes, and resumed from the cheap mechanical handoff the USER retired on 2026-08-23 as
"useless". Every automated clear on this machine will take that path until the daemon has a key.

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

- [ ] USER rules on A / B / C (or names another placement)
- [ ] the daemon's llm-ext child env carries the key under launchd — proven by the next
      automated fire's `external-clear.log` showing a `SUMMARY_READY <N>B` line instead of
      `NO_SUMMARY_POST_CLEAR`
- [ ] the cleared session resumes from the llm-ext summary (a keyed
      `agent-handoff-<key>-<ts>-<pid>.md` written by `handoff_files.write`), not from
      `precompact-handoff.md`
- [ ] the five drill cards blocked on this (2F3I2P18, 1QJIZFFW, PXP08ZQC, 79LXF6PJ, 5RXBI65T's
      successor observation) re-measure against that fire

## Approval log

- 2026-09-02T05:12:04+0200 — PROPOSED by janitor-main-session (min-approval-requirement: user —
  every option places a credential). Filed from the first live automated clear on the 3.4.7 lane.
