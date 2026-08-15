---
trdd-id: CEWVQ8DG
title: The cold-resume shrink refuses when agentlensPro cannot answer and degrades to a template because llm-ext is not on the hook PATH
column: testing
created: 2026-08-15T22:14:54+0200
updated: 2026-08-15T22:41:00+0200
current-owner: janitor-main-session
task-type: bugfix
implementation-commits: [904ddef4]
scope: project
approval-tier: 0
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-YOZ9TS3W, TRDD-B07VPT2G]
---

# The cold-resume shrink refuses when agentlensPro cannot answer, and degrades to a template because llm-ext is not on the hook PATH

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-15

**The incident.** The owner restarted dozens of Claude Code sessions on expired caches. Not one
used the externalized compaction. Every session's FIRST turn was the heartbeat re-arm, which on a
cold cache re-writes the whole window as cache-creation (~600k weighted at a ~500k context). The
owner's `/clear` queued BEHIND that turn, so the cost was paid first and the work was lost anyway:
*"i was left with dozens of claude code sessions empty, cleared, without memory, loosing everything
they were working on."*

**Two defects, both MEASURED in this project's own logs — not inferred.**

* **D1 — the gate refuses on an unknown cache state.** `external_clear.should_clear_on_resume`
  requires `cache_expired is True`; the only source is `cache_certainly_expired()`, a probe of the
  OPTIONAL agentlensPro CLI. When it cannot answer the verdict is `None` → refuse. Proof, from
  `.janitor/logs/cold-cache-clear.log`:
  `[2026-08-13T22:20:18+0200] source=resume fire=False trigger=- why=cache state unknown — not clearing`
  A fleet-wide lever whose reachability depends on a third-party tool being installed is the exact
  shape `cold_cache_compact`'s own docstring warns about twice: *"a threshold high enough to never
  be met is a feature that does not exist."*
* **D2 — when it DOES fire, the handoff has no summary.** `attempt_llm_ext_summary` resolves the
  CLI with `shutil.which("llm-ext")` only. The binary lives at
  `~/.claude/plugins/cache/<marketplace>/llm-externalizer/<version>/bin/llm-ext` — a plugin-cache
  dir that is on the INTERACTIVE shell's PATH (via the profile snapshot) but NOT in the
  environment of a hook-spawned detached child. `which` returns None → `OUTCOME_PERMANENT` → no
  retry → template. Proof, from `.janitor/logs/external-clear.log`, the same fire that produced
  this session's own handoff:
  `[2026-08-15T21:29:58+0200] summary: permanent — llm-ext is not on PATH; not retrying`
  `[2026-08-15T21:29:58+0200] handoff degraded to template: permanent — llm-ext is not on PATH`
  This is the owner's *"even the compaction failed"*: the clear ran, the summary did not, so the
  cleared session inherited links and a message tail instead of its working state.

**What is NOT wrong, verified before changing anything** — do not re-diagnose these:

* The feature is not dark on this machine: `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED=true`
  is set, `ec.enabled()` is True, and the 21:29:58 fire proves the whole chain runs.
* The CLI invocation is correct: `llm-ext --help` lists `session compact -> session-summary`, and
  `session compact --help` documents both `--stdout` and `--transcript`. The flat form the code
  calls exists in 13.5.1. Only RESOLUTION is broken, not the contract.
* The hook blocks rather than detaching (2800 s vs the 2600 s deadline), so a fire really does
  land before the first turn. The ordering is sound; the gate was the problem.

**SHIPPED 2026-08-15 in `904ddef4`; column `dev → testing`.** Both fixes are in, with 16 tests, a
green full suite (15462 passed / 0 failed) and clean ruff+mypy. Two field checks were run on this
machine rather than only in fixtures: `resolve_llm_ext()` under `env -i PATH=/usr/bin:/bin` (the
exact hook-child condition that failed) resolves the real 13.5.1 binary AND its correct data dir;
and the gate against this project's live state returns `None` for an active session (16 s idle),
still honours a warm probe over an ancient mtime, and returns `True` for a simulated 3 h idle —
the refusal that burned the fleet. What remains is only the FIELD proof below, which needs a real
cold resume to occur.

**NEXT ACTION.** Verify on the next real cold resume that
`cold-cache-clear.log` shows `fire=True` with `trigger=resumed-cold` and `external-clear.log` shows
`summary: ok`, not `permanent`.

## Design

### D1 — answer the cache question with arithmetic, not an optional tool

Add a PURE predicate to `lib/external_clear.py` and consult it only when the probe abstains:

* `cache_expired_by_age(last_turn_age_s, *, ttl_minutes) -> bool | None` — returns `True` when the
  elapsed time alone makes expiry CERTAIN, otherwise `None`. **It never returns `False`**: absence
  of certainty is not warmth, and a `False` here would override a probe that said `True`.
* The certainty floor is `max(ttl_minutes, CERTAIN_EXPIRY_FLOOR_MINUTES=60)`. 60 minutes is the
  LONGEST prompt-cache TTL the platform offers, so past it no cache survives under ANY regime.
  Using the longest (not `DEFAULT_TTL_MINUTES=5`) is the load-bearing asymmetry: the short TTL is
  correct for `next_fire_misses_cache`, which predicts a COST and may err toward acting, but this
  gate authorizes an UNRECOVERABLE `/clear` and must only fire where certainty is real.
* `resolve_cache_expired(probe, ...)` composes them: a probe that answered wins verbatim; only
  `None` falls through to the age. So the change is strictly ADDITIVE — it can turn "unknown" into
  "certainly expired", and can never flip a "warm" into a clear.

The hook already holds everything needed: it computes `newest_transcript(root)` for the context
size, and the age is that file's mtime. No new I/O, no new dependency.

### D2 — resolve llm-ext by its own install convention, not by PATH luck

Add `resolve_llm_ext() -> str` to `lib/external_clear.py`: try `shutil.which` first, then scan
`~/.claude/plugins/cache/*/llm-externalizer/*/bin/llm-ext` and pick the NEWEST version by parsed
numeric tuple (never lexicographic — `"9.0.0" > "13.5.1"` as strings, which would pin the oldest
install forever). Route all three call sites (`llm_ext_progress_fn`, `run_llm_ext_summary`,
`attempt_llm_ext_summary`) through it. `llm_ext_data_dir` already derives the data dir FROM the
binary path, so an absolute plugin-cache path keeps working unchanged.

## Acceptance

- [x] `cache_expired_by_age` returns True past the floor, None below it, None on unknown age, and
      NEVER False.
- [x] `resolve_cache_expired` prefers a probe verdict (True AND False) and only falls back on None.
- [x] The floor uses the LONG TTL even when the configured/regime TTL is short.
- [x] `resolve_llm_ext` finds the binary with an empty PATH, picks the newest version numerically,
      and returns "" when genuinely absent.
- [x] The hook passes the age-derived verdict into the gate.
- [x] ruff + mypy clean; full pytest suite green.
- [ ] Field proof on the next real cold resume: `fire=True trigger=resumed-cold` AND
      `summary: ok` (not `permanent`) in the logs.

## Notes

The arm-preemption the owner named is NOT fixed by a separate gate, and deliberately so. With D1
fixed, the expensive case — cold cache + large context — is exactly the case that now gets cleared
BEFORE the first turn, and a cleared session's re-arm is a cheap small-context turn. The residual
"unknown" band (idle under an hour) is precisely where the cache is most likely still warm, and a
warm arm is a cache read. Adding a second suppression gate on top would risk leaving a session with
no heartbeat at all — the failure this project has shipped twice — to save a cost D1 already removes.
