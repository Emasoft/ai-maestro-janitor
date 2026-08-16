---
trdd-id: CEWVQ8DG
title: The cold-resume shrink refuses when agentlensPro cannot answer and degrades to a template because llm-ext is not on the hook PATH
column: testing
created: 2026-08-15T22:14:54+0200
updated: 2026-08-16T16:36:40+0200
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

### FIELD CHECK 2026-08-16 06:28 — half PASSED, half **FAILED**. Do not close this card.

| half of the NEXT ACTION | result |
|---|---|
| `cold-cache-clear.log`: `fire=True trigger=resumed-cold` | **PASS** — `2026-08-15T21:29:58 [s:f6b2ee4a] source=resume fire=True trigger=resumed-cold why=resumed on a dead cache (context=431357)` |
| `external-clear.log`: `summary: ok` | **FAIL** — three refusals today, session `e88bb088`, at `00:53:34`, `05:11:29`, `05:16:44`: `summary: permanent — llm-ext data dir unresolvable; not retrying` |

**The failure string CHANGED, and that is the informative part.** Pre-fix it read `llm-ext is not
on PATH` (still in this log at `2026-08-15T21:29:58`). Today it reads **`data dir unresolvable`** —
so `resolve_llm_ext` is answering (the half this card fixed) and `llm_ext_data_dir` is the half
now refusing. The fix moved the failure; it did not remove it.

**NOT reproducible from the current tree + host state — measured, both environments:** interactive
PATH → `shutil.which` returns the cache binary; `env -i PATH=/usr/bin:/bin` → `which` returns
`None`, the glob fallback finds `…/cache/emasoft-plugins/llm-externalizer/13.5.1/bin/llm-ext`, and
`llm_ext_data_dir` returns the real `…/data/llm-externalizer-emasoft-plugins` in BOTH. So the
refusal cannot be re-derived by rerunning it here, which is exactly why the next step is
instrumentation and not another observation.

**The reachable path that produces this exact string while the binary resolves** (stated as a
hypothesis, not a diagnosis): `resolve_llm_ext` lets `shutil.which` **win first** — deliberately,
"so an operator who put a specific build there keeps control" — while `llm_ext_data_dir` refuses
ANY binary whose resolved path is not `…/cache/<marketplace>/<plugin>/…`. A PATH-provided
`llm-ext` outside the plugin layout therefore yields *resolved binary + empty data dir* → permanent
refusal. The docstring's escape hatch and the derivation are in tension; nothing today reconciles
them.

**NEXT ACTION (replaces the above).** One line of instrumentation settles it and no further waiting
will: log the RESOLVED BINARY PATH alongside the `data dir unresolvable` refusal. The refusal
currently names the failure without naming the input that caused it, so a reader cannot tell an
outside-the-layout PATH hit from a missing data dir — the same "unreachable vs silent" distinction
TRDD-ZM5LZ24Y had to add instrumentation for. Then decide whether `which` should still win when its
answer defeats data-dir derivation.

### SUPERSEDED 2026-08-16 11:23 — the refusal is REMOVED, not instrumented

The user directed contacting the llm-externalizer project; its session replied with the decisive
fact, **verified first-hand on the installed 13.5.1 build before acting** (decide-on-facts):
`launcher.mjs:274` reads `process.env.CLAUDE_PLUGIN_DATA || deriveDataDirFromLayout()` — the
launcher performs the SAME cache-layout derivation this codebase was doing, from its own resolved
path, where it is authoritative and every caller can only guess. Live test:
`env -u CLAUDE_PLUGIN_DATA llm-ext --help` → rc 0.

So `attempt_llm_ext_summary` no longer derives, no longer refuses, and **REMOVES**
`CLAUDE_PLUGIN_DATA` from the child env rather than merely not setting it — in a janitor
hook/daemon child that variable names the JANITOR's data dir, the env var WINS over the launcher's
derivation, and inheriting it would self-install llm-ext's native module into the wrong plugin's
store. The `data dir unresolvable` outcome no longer exists; the launcher's own named error
(stderr) now covers the one genuine remaining gap (a PATH build outside the cache layout), and the
existing rc/stderr classification handles it.

The instrumentation ask above is therefore moot — the input that needed naming is now named by the
component that owns it. The remaining exit gate for this card is unchanged: one real cold resume
whose `external-clear.log` shows `summary: ok`.

### QUEUED FOLLOW-UP — llm-ext's NEXT release moves the ground again (peer notice 2026-08-16)

The llm-externalizer session's second reply supersedes its first: as of their commit `f338112`
(on their `main`, **NOT yet published** — the cached 13.5.1 we exec still has the old launcher),
native deps pin to `~/.llm-externalizer/native` (`LLM_EXT_CONFIG_DIR` override) and
**`CLAUDE_PLUGIN_DATA` is no longer read at all**.

Our env-strip stays CORRECT under both builds (13.5.1 self-derives; the new build ignores the
var). But TWO things break or become dead the release lands, and nothing will announce it:

1. **`llm_ext_progress_fn` will silently watch a DEAD directory.** It fingerprints the data-dir
   mtime as the retry loop's progress signal; the new build's checkpoints land under
   `~/.llm-externalizer`, so the gate would read "no progress" forever on a working summarize.
   Repoint it at `LLM_EXT_CONFIG_DIR` / `~/.llm-externalizer` when the release ships.
2. **`llm_ext_data_dir` becomes fully dead code** (its last consumer is #1) — delete it then,
   per the peer's explicit ask, not before (the installed 13.5.1 still writes checkpoints to the
   plugin data dir, so deleting early breaks the progress gate TODAY).

Also flagged by the peer, filed as their issue rather than worked here: first-run self-install
(`npm ci` into the shared deps dir) is unguarded against concurrency, and the janitor can
genuinely race it — the daemon's long-idle compose and an interactive handoff can exec llm-ext in
the same minute after an upgrade.

### REGRESSION FOUND AND FIXED 2026-08-16 — the warm-cancel probe made the idle lever unreachable

Earlier the same day, per an owner directive, the `/clear` injection chain gained a
`still_wanted` hook: while the pane is busy it re-asks agentlensPro every 8 s whether the cache
is still expired and CANCELS the `/clear` the moment the cache reads WARM (the user's own turn
rebuilt it, so clearing would destroy a live context). The 30 s inject give-up was raised to a
3600 s ceiling at the same time.

**DEFECT.** That probe was wired to EVERY trigger. Measured result — six consecutive
`long-idle` fires cancelled, e.g.
`[2026-08-16T15:55:05+0200] fired: trigger=long-idle — nothing but heartbeats for 9000s`
immediately followed by `inject cancelled: cache is WARM again`. 100% veto rate; the lever was
unreachable.

**CAUSE.** `long-idle` fires BECAUSE heartbeats are the only activity, and a ~5-minute heartbeat
cadence against a 1 h TTL keeps the prompt cache warm by construction. A warm cache is that
trigger's NORMAL, HEALTHY state, not a reason to stand down. The same is true of
`next-fire-misses`, which is predictive and fires while the cache is deliberately still warm.
This is the exact failure the docstring of `external_clear.next_fire_misses_cache` already
warned about: asking whether the cache is *already* cold makes the lever unreachable whenever
the cadence is faster than the TTL.

**FIX.** The chain payload now carries `cache_gated`, set by `external_handoff_clear._fire` to
`trigger in {resumed-cold, cache-certain-expired}`; `clear_trigger._run_chain_payload` arms the
`still_wanted` probe only when that key is true. An absent key means no gate, so the two
in-model/CLI `_spawn_chain` sites are unaffected and keep their pre-existing behaviour plus the
longer patience ceiling.

**Deliberately NOT added:** a second predicate asking "has a real non-heartbeat turn happened
since the verdict?", which is the semantically correct cancel for an idleness trigger. The
3600 s ceiling and the busy-pane deferral bound the case; add the predicate only if a long-idle
clear is ever observed landing on a user who had just returned. This is an explicit open risk,
not a closed question.

Two regression tests pin both directions in `tests/test_external_handoff_clear.py`.

**Separate finding — test-isolation leak, also fixed.** `tests/test_inject_still_wanted.py` was
writing its fixture strings into the REAL `.janitor/logs/terminal_trigger.log`, because the
repo's autouse test isolation covers HOME and the global-state dirs but NOT
`CLAUDE_PROJECT_DIR`, which is what `state.log_line` resolves the project log from. The string
`inject cancelled: cache went warm` had landed in the live log three times and read there as
production evidence. Fixed with a module-scoped autouse fixture redirecting
`CLAUDE_PROJECT_DIR`; proven by the log staying at 504 lines across a run that previously grew
it by 2.

**QUEUED FOLLOW-UP above — both items now resolved, not just tracked.** Item 1 (repoint the
progress fingerprint away from the plugin data dir) is DONE — `llm_ext_state_dir()` reads
`LLM_EXT_CONFIG_DIR` / `~/.llm-externalizer` plus `/session-summary-checkpoints`, and
`llm_ext_progress_fn()` uses it. Item 2 (delete `llm_ext_data_dir` once its last consumer goes)
is being executed by another worker in this same pass.

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

* [x] `cache_expired_by_age` returns True past the floor, None below it, None on unknown age, and
      NEVER False.
* [x] `resolve_cache_expired` prefers a probe verdict (True AND False) and only falls back on None.
* [x] The floor uses the LONG TTL even when the configured/regime TTL is short.
* [x] `resolve_llm_ext` finds the binary with an empty PATH, picks the newest version numerically,
      and returns "" when genuinely absent.
* [x] The hook passes the age-derived verdict into the gate.
* [x] ruff + mypy clean; full pytest suite green.
* [ ] Field proof on the next real cold resume: `fire=True trigger=resumed-cold` AND
      `summary: ok` (not `permanent`) in the logs.

## Notes

The arm-preemption the owner named is NOT fixed by a separate gate, and deliberately so. With D1
fixed, the expensive case — cold cache + large context — is exactly the case that now gets cleared
BEFORE the first turn, and a cleared session's re-arm is a cheap small-context turn. The residual
"unknown" band (idle under an hour) is precisely where the cache is most likely still warm, and a
warm arm is a cache read. Adding a second suppression gate on top would risk leaving a session with
no heartbeat at all — the failure this project has shipped twice — to save a cost D1 already removes.
