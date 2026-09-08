---
trdd-id: M4HVFU2A
title: The model-fallback detector keeps typing /model opus into every session after a rotation onto an account whose Fable window is not enforced
column: testing
created: 2026-09-06T06:04:24+0200
updated: 2026-09-08T15:22:00+0200
implementation-commits: [772e46a1]
current-owner: janitor-main-session
task-type: bugfix
priority: critical
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
relevant-rules: []
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

Reported 2026-09-06 06:05 by the ai-maestro hub session (peer message) and confirmed by the
USER ("i see the command to switch to opus still sent to all claude instances"; "fix and update
those damn blind scripts that does not realize that we have already switched to an account with
fable headroom"). Measured first-hand with the detector's own gather
(`rotator_usage.accounts_usage()`): live account fresh (172 s), 5h 18 % / 7d 69 %, Fable
**97 %** with `is_active: true` and `severity: critical`. (The 06:04 version of this block
said `is_active: false`; that was wrong — read from the raw probe the same hour. The flag flips
BELOW 100 %, so it is NOT an enforcement signal.) The detector's bar was `_SCOPED_HIGH = 90`,
so 97 % read as "spent": it was not reading a stale or wrong account. Defects:

1. **Wrong bar.** 90 % used is the rotator's EARLY-rotation trigger; the only reading that
   means "actually spent" is 100 %. `is_active` cannot serve (measured above).
2. **No rotation-first check.** USER ruling: rotation comes BEFORE any model change, because a
   model change invalidates the prompt cache of every agent on the pane.
3. **No backoff after a human cancel.** An unconfirmed switch is retryable by design, so a
   cancelled dialog was re-typed every 5-minute heartbeat, in every session. This is the loop.
4. Doc drift: `dispatch.py:487` said the detector ships dark; `model_fallback.enabled()`
   defaults ON.

Landed in 772e46a1 (on disk 2026-09-06 06:14 by the worker; re-verified first-hand 2026-09-08:
ruff, mypy, pyright clean, test_model_fallback + test_window_burn_rate 81 passed, worker gate
incl. test_oauth_rotator 212 passed). `require_active=True` on the detector's verdict call =
`util_pct >= 100` only (the rotator's `cmd_auto` keeps the 90 % early trigger, default False).
`_sibling_has_headroom` scans `accounts_usage()` for a non-live slot whose same-model window is
`< 100` and, when one exists, prints `rotate first: /janitor-rotate-account-to <label>` and
touches no pane. A SENT-but-unconfirmed keystroke writes `model-fallback-declined.ts` in the
PROJECT state dir (same scope as the switch cooldown — each armed project backs off on its own
first cancel, so up to N first keystrokes across N projects before every one is quiet) and the
detector backs off 3600 s. Comment fixed.

Said plainly: (a) 90 → 100 on the detector path is a POLICY change, not a bug fix — the
detector now lets a session reach a true wall before typing, on the owner's cost model that a
cache reset across every agent costs more than a short wall the rotator / rotate-first clears.
(b) The detector stays DEFAULT ON — my decision, not a ruling; opt out per session with
`CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED=false`. (c) NOT done: the interim cooldown stamp
into the 4 armed projects — dropped together with the settings.json idea after the USER
objected to patching settings; running sessions keep the cached 3.4.14 behaviour until the
plugin is updated. (d) Cost: the verdict path now gathers `accounts_usage()` twice per fire
(live read, then sibling scan); `usage_probe` caches per account (TRDD-WEBA1RMF), so the second
gather is a local cache read inside its window — reusing the first gather is a cleanup, not a
fix. NEXT ACTION: `publish.py --patch`, `claude plugin update`, reply to the peer with the
shipped version, then the peer confirms the retyping stopped.

## Acceptance

- [x] a 97 % Fable window (even with `is_active: true`) produces NO verdict on the detector
      path; only a true 100 % does (772e46a1)
- [x] with any non-live slot holding Fable headroom the detector types nothing and names it
- [x] a cancelled/unconfirmed switch is not re-typed for 3600 s (per project)
- [x] existing rotator early-trigger behaviour (90 %) unchanged and its tests green
- [ ] published and installed on this host; the peer session confirms the retyping stopped
