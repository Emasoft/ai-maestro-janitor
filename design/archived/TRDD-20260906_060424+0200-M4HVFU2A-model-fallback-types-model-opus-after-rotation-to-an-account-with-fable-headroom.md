---
trdd-id: M4HVFU2A
title: The model-fallback detector keeps typing /model opus into every session after a rotation onto an account whose Fable window is not enforced
column: complete
created: 2026-09-06T06:04:24+0200
updated: 2026-09-17T05:43:45+0200
implementation-commits: [772e46a1, 2d8cf86e]
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
`_sibling_has_headroom` scans `accounts_usage()` for a non-live slot with same-model headroom
and, when one exists, prints `rotate first: /janitor-rotate-account-to` and touches no pane.
Review 2026-09-08 → 2d8cf86e: the 772e46a1 line named the slot's LABEL (a local part the
explicit `rotate_to.py <email>` path rejects as UNKNOWN_ACCOUNT) and judged it on `< 100`
with no account check, while rotate_to's auto-select uses 90/90 — so for a sibling at
90–99 % it pointed at a rotation that would itself type `/model opus` first. Now ONE
predicate, `token_burn.model_headroom_candidate`, decides both rotate_to's has-Fable-headroom
membership and the detector's stand-down (bars pinned equal by test); the line names the
sibling with its util % and the verb with no argument. Accepted mismatch: a sibling whose
token is about to expire qualifies here while rotate_to's auto-select skips it
(`_blob_locally_expired`) → the verb answers NO_TARGET and the detector keeps standing down.
Rotate-first is ADVICE only: the detector types the skill name and never rotates. While the
server's rotator fix (below) is on HOLD, or no alternate is server-safe, an unattended session
therefore sits at a true Fable wall until a human runs the verb, where 3.4.14 at least switched
models; once the server's fix is live the wall is not reached while a server-safe alternate
(Fable under its SAFE_SCOPED 95) exists. The advisory line
repeats every fire until someone rotates (no backoff on the stand-down path) — the same loop as
3.4.14's, as text instead of a keystroke. A SENT-but-unconfirmed keystroke writes `model-fallback-declined.ts` in the
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
gather is a local cache read inside its window (`usage_probe._TTL_DEFAULT = 600`, verified) —
reusing the first gather is a cleanup, not a fix.

Peer (ai-maestro hub, 2026-09-08 ~15:50, its card TRDD-271764MC): RETRACTS its 09-06 "stale or
wrong-account read" — one account read live, Fable 94→97→98 over 17 min; the server's own bars
were the cause: `tick.ts SAFE_SCOPED = 90` vetoes every alternate at/above 90 while the
rotate-away trip is 97, so in the 90–100 band no alternate is ever "safe" and the fleet gets
the model switch. Its fix (not live, on HOLD): SAFE_SCOPED 95, SCOPED_SWITCH_AT_PCT 97.
FOLLOW-UP, not done here: the janitor's `rotator.SCOPED_SWITCH_AT` (rotate_to's has-Fable-headroom
bar AND, since 2d8cf86e, the detector's rotate-first bar) is 90 — with the live window at
100 % and the only sibling at 92 %, the server would rotate onto it but the DETECTOR sees no
headroom sibling and types `/model opus`, and rotate_to (no other sibling under 90) types it
first too; aligning 90→95 is an owner call (S2RZHXU7 settled 90). Peer's open premise for the
owner: a rotation onto another subscription is a different org, and caches are org-isolated —
VERIFIED 2026-09-08 in the prompt-caching doc ("Caches are isolated between organizations.
Different organizations never share caches, even if they use identical prompts") — so
rotate-first buys Fable minutes but NOT the cache the ruling was made to protect; the burst
itself is NOT measured by the janitor (its rotation log records swaps, not cache-hit rates).
Verified for the fork's other questions: `is_live` and rotate_to's `live_email` come from the
same rotator state; `_fable_used` and the predicate read the same `*/Fable` windows; no heartbeat or daemon
path calls rotate_to.py (grep over scripts/ + hooks/: only the detector's advisory text and a
token_burn docstring name it). NEXT ACTION: `publish.py --patch`,
`claude plugin update`, reply to the peer with the shipped version, then the peer confirms
the retyping stopped.

## Acceptance

- [x] a 97 % Fable window (even with `is_active: true`) produces NO verdict on the detector
      path; only a true 100 % does (772e46a1)
- [x] with any non-live slot `/janitor-rotate-account-to` would pick as a Fable-headroom target
      (shared predicate) the detector types nothing, names the slot and the no-arg verb (2d8cf86e)
- [x] a cancelled/unconfirmed switch is not re-typed for 3600 s (per project)
- [x] existing rotator early-trigger behaviour (90 %) unchanged and its tests green
- [x] published and installed on this host; the peer session confirms the retyping stopped

## Approval log

- 2026-09-17T05:43:35+0200 — COMPLETE by main session (owner standing permission 2026-09-03). Model-fallback fix landed (772e46a1) plus review-round fix unifying on token_burn.model_headroom_candidate (2d8cf86e); test_model_fallback.py 28 passed.
2026-09-17 — box 5 ticked: review-round fix 2d8cf86e unifying rotate_to's auto-select on token_burn.model_headroom_candidate; test_model_fallback.py 28 passed
