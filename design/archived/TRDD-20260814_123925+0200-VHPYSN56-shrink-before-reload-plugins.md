---
trdd-id: VHPYSN56
title: Reloading plugins shrinks context first so the cache-prefix break lands near the floor
column: complete
created: 2026-08-14T12:39:25+0200
updated: 2026-08-14T12:39:25+0200
current-owner: janitor-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
implementation-commits: [f96cb584, 9a26d147]
---

# Reloading plugins shrinks context first

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

**Shipped and green** (15274 passed, ruff + pyright clean). `/janitor-reload-plugins` now
clears before reloading whenever context is at/above the reload-guard threshold.

- `reload_trigger.py` — `--shrink {auto,never,force}`, default `auto`; `should_shrink` is
  a pure, exhaustively-tested predicate; `RELOAD_SETTLE_S = 4.0`.
- `clear_trigger.py` — new public `spawn_shrink_chain(then=…, settle_between_s=…)` +
  `BOOTSTRAP_CMDS` alias, so the verified chain is REUSED, never re-implemented.
- `terminal_trigger.run_chained_inject` — new `settle_between_s` (default 0.0, additive).
- `dispatch._phase_plugin_reload` — the high-context deferral now EMITS instead of
  returning.
- `skills/janitor-reload-plugins/SKILL.md` — step 0 (author the handoff) + the new
  `RELOAD_SHRINK_CHAIN_SPAWNED` outcome; the stale "shrink manually" prose is gone.

**NEXT ACTION:** none for this card. The open sibling is the twin defect in
`/janitor-reload-skills` (`reload_skills_trigger.py`), which still types `/reload-skills`
at whatever context is live — its own SKILL.md still carries the manual-shrink prose, which
remains ACCURATE until that trigger gains `--shrink`. That is its own TRDD, not a body edit
here.

## Why

`/reload-plugins` breaks the prompt-cache prefix, so the next turn re-caches the WHOLE
conversation at ~1.25× instead of reading it at ~0.1×. Measured on this session while the
work was underway: a warm heartbeat turn ran `cache_read 444,258 / cache_write 225`. One
reload at that size converts ~444k of cheap cache-reads into full-price writes — roughly
$0.22 → $2.80 for a single turn.

Owner directive (2026-08-14, verbatim): *"if the janitor reload-plugins is called, it
should first run the janitor compacting (clear+summary injection), only then reloading the
plugins with /reload-plugins . in this way the /reload-plugins will not have a 600k context
to burn, but only a 350k at best"*, and: *"you must compact before running the command, so
the invalidation will burn as few tokens of context as possible"*.

## The load-bearing decisions

**1. The reload is the FIRST post-clear step, ahead of `/janitor-arm`.** Between `/clear`
and the first API turn no prompt cache has been written yet, so the reload there invalidates
*nothing* — it is free, not merely cheap. Running it after `/janitor-arm` (which IS an API
turn) would re-bill the freshly-written ~305k base at 1.25× on the very next turn. The order
is asserted by a dedicated test because a reorder would keep every other test green while
silently deleting the entire saving.

**2. Shrink only above the threshold.** Below it, clearing a 320k session to reach the
~305,119 floor destroys the conversation to save nothing — negative value on the owner's own
metric. `reload_trigger` reads the SAME `CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD`
env var and default (`token_meter.RELOAD_GUARD_DEFAULT_THRESHOLD = 350_000`) that dispatch's
guard reads, so the two cannot silently disagree; a test pins that.

**3. Every refusal fails toward the RECOVERABLE outcome.** `/clear` is unrecoverable; an
expensive reload is merely expensive. So: `--hard` never shrinks (urgent means urgent); an
unreadable context never shrinks in `auto` (never clear on a guess); an unreadable pane
falls back to a direct reload rather than clearing blind.

**4. Missing handoff WARNS, never blocks.** Refusing would leave the session running stale
plugin code — trading a recoverable loss for an invisible one. The obligation to author the
handoff belongs to the SKILL (step 0), which knows what the session was doing.

## The latent bug this fixed on the way

`dispatch._phase_plugin_reload` deferred `[janitor-reload]` above the threshold and
documented the reason as *"the context shrinks on its own and the reload lands cheaply
then"*. That is false for exactly the sessions this plugin serves: an unattended session
above the threshold never shrinks by itself, so the reload deferred **forever** and the
session kept running stale plugin code — silently, since the ack is deliberately left
unadvanced and nothing else reports it. A cost guard that never terminates is an
availability bug; a plugin update carrying a security fix could sit unapplied indefinitely.

## Facts worth not rediscovering

- **`/reload-plugins` fires NO hook of any kind** (measured; `token_meter.py` §reload-guard,
  wikimem `claude-code-hook-types` `^no-plugin-reload-hook`). So its completion is
  unobservable and nothing can gate on it — `RELOAD_SETTLE_S` is a mitigation, not a gate.
- **`/clear` does NOT pick up new plugin code.** `on-session-start.py:351` seeds
  `reload-acked.ts` only for `source in ("startup", "resume")` — `clear` is deliberately
  excluded, because a clear does not restart the PROCESS that loaded the plugins. This is
  why the reload step after a clear is necessary rather than redundant.
- **The post-clear floor here is ~305,119** (live `read_floor`).

## Rejected

- **Arm before reload** — safer-sounding, but costs ~381k weighted tokens per shrink for
  almost no gain: the chain already stops and logs if arm's inject fails.
- **`/compact` instead of `/clear`** — raises the floor and costs a summary turn; the owner
  specified clear + summary injection.
- **Measuring whether the reload really breaks the prefix first** — the repo had ALREADY
  recorded it as measured, in the very file being modified. See the lesson below.

## Notes and lessons learned

[^1]: {id: LESSON-VHPY-01, status: active, keywords: "already measured, re-run an experiment
the repo already answered, propose a test for a documented fact, recall before acting",
ocd: 2026-08-14, lmd: 2026-08-14}
DO NOT design an experiment to establish a fact before grepping the code you are about to
change, BECAUSE `token_meter.py` already documented — as MEASURED — that `/reload-plugins`
breaks the prompt-cache prefix and costs ~1.25× the whole window, and a test was proposed to
the owner to re-establish exactly that. DO grep the module you are about to modify for the
claim first; the answer was 3 lines above the constant being read.

[^2]: {id: LESSON-VHPY-02, status: active, keywords: "cost guard never terminates, defer
forever, waits for a condition that never comes, unattended session never shrinks",
ocd: 2026-08-14, lmd: 2026-08-14}
DO NOT write a guard that defers an action until a condition improves without asking who
makes it improve, BECAUSE the reload guard deferred on "the context shrinks on its own" and
on an unattended session nothing ever shrinks it — so the reload never happened and the
session ran stale code silently. DO give every deferral a terminating path, or make the
deferring party responsible for causing the condition it waits on.
