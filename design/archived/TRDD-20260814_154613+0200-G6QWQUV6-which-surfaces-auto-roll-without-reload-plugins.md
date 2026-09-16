---
trdd-id: G6QWQUV6
title: Which janitor surfaces can auto-roll to a new version without reload-plugins
column: complete
created: 2026-08-14T15:46:13+0200
updated: 2026-08-14T15:46:13+0200
current-owner: janitor-session
task-type: audit
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: []
---

# Which janitor surfaces can auto-roll without `/reload-plugins`

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

This card is a **decision record**, not open work. It exists so the next session does
not re-derive this analysis a third time (it has now cost two full derivations).

**DECIDED: do NOT ship a hook shim.** Reasons in "The rejected design" below.
**DECIDED: overwriting the in-use version-stamped cache dir is off the table.** Reasons
in "Why not just overwrite the cache".

If a future session is tempted by either, read those two sections before re-opening.

## The question

`/reload-plugins` swaps plugin code in place but breaks the prompt-cache prefix, so the
next turn re-caches the whole conversation at ~1.25× instead of reading it at 0.1×
(`scripts/lib/token_meter.py`). At a large context that is a real, avoidable cost. Hence:
how much of the janitor can pick up a new version **mid-session**, without that command?

## The law that decides every row

A surface auto-rolls if and only if **both** hold:

1. **resolution happens at use-time, in a fresh process**, and
2. **the janitor authors the string that names the entry point.**

The heartbeat cron satisfies both — the janitor wrote the cron prompt, and it names an
absolute path to `dispatcher-stub.py` in the DATA dir, outside the version-stamped cache;
the stub re-resolves the newest verified version on every fire
(`dispatcher-stub.py:215-251`, with the C2/C3/quarantine fail-open ladder).

`hooks.json`, and every listing the harness caches at session start, fail (2): Claude Code
owns those strings, not the janitor. No amount of indirection changes that.

## Surface table (measured 2026-08-14)

| Surface | Verdict |
|---|---|
| heartbeat dispatcher | **already auto-rolls** — the stub pattern |
| detector scripts | **already auto-rolls** — launched by the version the stub chose |
| global daemon | **already auto-rolls** — recency gate restarts an older daemon |
| `scripts/lib/**` | follows its entry script — correct as-is; do NOT mix versions in one process |
| script-backed skills / commands | **largely already there** — 46 of 56 skills delegate to a script |
| hook script bodies | *could*, via policy-as-data — judged not worth it, see below |
| `hooks.json` wiring (matchers, timeouts, which hooks exist) | **structurally cannot** |
| skill / agent prose, and ALL listings + descriptions | **structurally cannot** |
| `~/.claude/rules/*.md` | path is stable, but content is injected at session start → current at the NEXT session, not this one |

**A new session already resolves the newest installed version at start.** So the entire gap
this card is about is *long-running sessions started before the update*. That framing keeps
the value of any fix in proportion.

## The rejected design — a hook shim

Point every `hooks.json` entry at a stable path outside the versioned cache, which resolves
newest-version and execs the real hook. Rejected on four grounds:

1. **Partial by construction.** The wiring is still read at session start, so new, removed,
   or re-timed hooks need a restart anyway.
2. **Latency inside fail-open budgets.** Timeout distribution is 10 entries at 3s, 8 at 5s,
   **3 at 2s**. A shim adds a process spawn + readdir + integrity check. A hook that times
   out fails *open* — so the cost of getting this wrong is silent.
3. **No usable anchor.** `${CLAUDE_PLUGIN_DATA}` points at whichever plugin owns the running
   turn. The janitor's OWN SessionStart hook already refuses to trust it without a substring
   guard and falls back to a hard-coded path (`scripts/hooks/on-session-start.py:437`). It is
   used 0 times in `hooks.json` today.
4. **A shim without the stub's C2/C3 ladder would exec an unverified newest version on every
   tool call** — strictly worse than the pinned status quo.

## Why not just overwrite the cache dir

Writing new content over the in-use `…/cache/…/<version>/` would not crash Claude Code — hooks
re-exec from disk per fire, so new bodies would take effect. It is still wrong:

- `cp -r` is **not atomic**, and hooks fire on nearly every tool call → torn reads and
  mixed-version trees (a new hook importing an old lib), both silent.
- The dir name and its `plugin.json` version would disagree, lying to Claude Code's own
  installed-version bookkeeping in `~/.claude/plugins/known_marketplaces.json`.
- It invalidates the `manifest_hmac` integrity pin — which is precisely the tamper signal
  that pin exists to raise. The overwrite trick and the integrity check are mutually
  exclusive by construction.
- It does not even help the sessions that need it most: a session pinned to an OLDER version
  dir is untouched by overwriting the newest one.

## Residual risks worth a future detector

- **Version skew is already live and by design:** stub-launched detectors run the newest
  version while that session's hooks run the pinned one. Any change to `state.py` or the
  global-state schema must therefore be one-version compatible, or an old session's hooks
  silently misread state the newest version wrote.
- **Cache GC:** if Claude Code ever prunes old version dirs, a long-running session's pinned
  hooks break — fail-open, hence silently. Not under janitor control.

## Notes

Derived twice (this card exists to stop a third time). The advisor consulted on the shim
concurred with the rejection. One of its four citations did not survive verification
(`scripts/rotator.py` does not exist; the real path is `scripts/oauth_rotator/rotator.py`) —
recorded here as a reminder that advisor citations get checked, not assumed.

Surfaced `TRDD-ZM5LZ24Y` (stale C3 pin) as a side effect of this audit.
