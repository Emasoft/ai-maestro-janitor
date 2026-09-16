---
trdd-id: S2RZHXU7
title: A one-call account rotation — the janitor-rotate-account-to skill and the rotate_to.py script it wraps, with headroom-driven target selection when no account is named
column: complete
created: 2026-09-06T05:44:34+0200
updated: 2026-09-16T22:18:11+0200
implementation-commits: [ae96dd12, 9d88e2db, 8342337b, 6a5199cd]
current-owner: janitor-main-session
task-type: feature
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
relevant-rules: []
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-06

USER directive 2026-09-06 05:40, verbatim intent: *"all this to rotate? too slow. we will end
breaking continuity! next time create a janitor skill `/janitor-rotate-account-to
<account_email>` that calls a single script `rotate_to.py <account_email>`. if no account is
specified in the skill argument, it picks the one with still 5h and 6d window headroom but with
more headroom left for Fable, if no headroom is left for Fable, picks the one with more 5h and
7d headroom, but switch model to opus first."* ("6d" read as the 7-day window — the only
second window the rotator tracks.) Context: the Fable window on the live account hit 100 % and
the manual path took ~15 tool calls (recall, slot list, usage, verb lookup, switch) before
`rotator.py switch emanuele.sabetta@…` ran. The switch itself is one keychain write and a
running `claude` adopts it on its next turn — the cost was entirely in FINDING it.

Landed in ae96dd12 (verified first-hand: ruff, mypy, pyright clean; 204 tests incl. 10 new).
Two review fixes folded in before commit: the pane resolver reuses
`terminal_trigger.self_terminal` instead of a local copy, and `cmd_switch`'s WARNING lines
are forwarded to stderr on the explicit-email path. NEXT ACTION: none — waits on the
full-suite publish gate (shared box); reaches sessions with the next `publish.py`.

## Spec

**Skill** `skills/janitor-rotate-account-to/SKILL.md` — one command, no reasoning: run
`uv run --script --quiet "<plugin-root>/scripts/oauth_rotator/rotate_to.py" [<email>]` with
the skill's argument (may be empty), then relay the script's FIRST stdout line verbatim. The
description must trigger on "rotate account", "switch account", "Fable window is ending",
"rate limit / out of headroom, move to another account".

**Script** `scripts/oauth_rotator/rotate_to.py [email]` — reuses `rotator.py` (no second
implementation of anything the rotator already has):

1. `email` given → must be a known slot (`rotator.cmd_known_emails` set); unknown ⇒
   `UNKNOWN_ACCOUNT <email>` on stdout, exit 2. Known ⇒ `rotator.cmd_switch(email)`; on
   success print `ROTATED <email>` and exit 0; a non-zero `cmd_switch` prints
   `SWITCH_FAILED <email>` and returns that code. `cmd_switch`'s own WARNING lines (an
   expired token) are forwarded to stderr, never swallowed.
2. no `email` → rank every NON-live slot that has a usage snapshot (each slot's usage dict is
   what `cmd_usage` already reads per slot through `usage_probe`). **Both rotator knobs are
   percent-USED thresholds, not headroom** (verified 2026-09-06 in `token_burn.model_fallback_verdict`:
   `if account_max > account_headroom: no verdict`; `util_pct >= scoped_high ⇒ spent`; both
   default 90). So, per slot: `account_used = max(5h%, 7d%)`; `fable_used` = `util_pct` of the
   entry labelled `7d/Fable` in `token_burn.model_windows_from_usage(usage, now)` (verified
   2026-09-06: it builds `<base>/<model>` labels from the probe's `limits[]` entries — the Fable
   one is `kind: weekly_scoped`, `scope.model.display_name: Fable`, utilization key `percent`).
   A slot with NO Fable entry is never in the has-Fable-headroom set but stays a candidate for
   the no-Fable fallback below. Two exclusions apply to BOTH sets: (a) an EMPTY probe — the
   window builders skip any entry whose `resets_at` does not parse, so a never-probed slot has
   no windows at all, and its flat `five_hour`/`seven_day` blocks read `0.0` with
   `resets_at: None` (seen on disk 2026-09-06); such a slot is UNKNOWN, never "0 % used", and
   is excluded (`NO_TARGET` names it if nothing else remains); (b) a slot whose token
   `_blob_locally_expired(blob)` says is within `EXPIRY_GRACE_H` (0.5 h,
   `ROTATOR_EXPIRY_GRACE_H`) of its local expiry, or past it, is excluded from automatic
   selection — an explicit `<email>` keeps `cmd_switch`'s existing behaviour (WARNING line, then
   switch), because the operator named it. Candidates = the rest with
   `account_used <= SCOPED_ACCOUNT_HEADROOM` (`ROTATOR_SCOPED_ACCOUNT_HEADROOM`, the rotator's
   own knob — reuse the constant).
   - some candidate has `fable_used < SCOPED_SWITCH_AT` ⇒ pick the LOWEST `fable_used`.
   - none does ⇒ pick the LOWEST `account_used` candidate, and BEFORE switching type
     `/model opus` into THIS session's pane through the existing
     `model_fallback` / `terminal_trigger.send_verified` + `confirm_model_switch` path
     (the same keystroke the model-fallback detector types); if the pane is not automatable
     (`NO_ITERM`), still switch and say so.
   - no candidate ⇒ `NO_TARGET <one-line reason>` exit 3, switch nothing.
   Print `ROTATED <email> fable=<n>% 5h=<n>% 7d=<n>% [model-fallback: typed|not-automatable]`.
3. Never prompts, never sleeps, never retries; every failure is one stdout token + non-zero
   exit. Idempotent: naming the already-live account prints `ALREADY_LIVE <email>` exit 0.
4. **NEVER gated on chore ownership or on the harness.** The script must not consult
   `harness_backend.server_runs_chores()` / claimed chores / any chore-coordination yield, must
   not require an ai-maestro server, a running daemon, or a liveness file, and must not defer
   to the daemon's `cmd_auto`. USER, 2026-09-06 (verbatim): *"when the rotator chore is owned
   by the ai-maestro, the janitor (even outside of the ai-maestro harness) must still have a way
   to do the rotation manually. that is the reason of the new skill."* It is the operator's
   manual verb; the only preconditions are a known slot and a readable keychain.

**Tests** `tests/test_rotate_to.py` — real code against a temp profiles root (reuse the
fixture shape of the existing rotator tests): unknown email exit 2; explicit email switches;
Fable-headroom ranking picks the max-Fable slot; no-Fable path picks max-account-headroom AND
requests the model fallback; no candidate exits 3; already-live exit 0.

## Acceptance

- [x] `/janitor-rotate-account-to <email>` is one tool call from the skill to a switched
      credential
- [x] the no-argument path selects per the spec and is pinned by tests
- [x] the no-Fable path types `/model opus` first (or reports not-automatable) and is pinned
- [x] ruff, mypy, pyright, skill-frontmatter test, rotator tests green
- [x] full-suite publish gate green (shared box)

## Notes

`cmd_auto` already contains the scoped-wall ranking for the DAEMON's automatic rotation
(f185e521, ATOM-PH7Z-4FY8); this card is the OPERATOR's one-call verb for the same decision.
The reason it exists (USER, 2026-09-06): when the rotator chore is owned by the ai-maestro
server, the janitor's daemon yields it and nothing on the janitor side rotates — and outside the
ai-maestro harness there is no server at all. The janitor must still be able to rotate manually
in both cases, which is why Spec §4 forbids any ownership/harness gate. On 2026-09-06 the chore
was server-owned and no rotation fired at a Fable wall; the manual switch worked, but finding
it took ~15 tool calls. A test MUST pin that the script runs to completion with no liveness
file, no daemon and the chore claimed by a (fake) server.

## Approval log

- 2026-09-16T12:50:00+0200 — boxes 1, 2, 4, 5 ticked on the evidence in reports/board-drain/20260916_123637+0200-S2RZHXU7-box-evidence.md (skill is one call into rotate_to.py; _pick_target ranking pinned by six tests; ruff/mypy/pyright/frontmatter/rotator tests green first-hand; 3.5.5 gate green with ae96dd12 included). Box 3 stays open: the no-Fable path's /model opus typing has only its dispatch pinned (the test mocks _request_model_opus); the real keystroke path via terminal_trigger has zero coverage. Column todo until that test exists — testing was claiming work nobody was doing.
- 2026-09-16T12:37:56+0200 — column → todo. one open box with a concrete missing test; no session on it (triage 2026-09-16)
- 2026-09-16T22:18:11+0200 — box 3 ticked: the keystroke half is pinned by three tests in tests/test_rotate_to.py that drive the REAL _request_model_opus through terminal_trigger with only the pane boundary injected (command '/model opus', esc_first, bypass_interrupt_cooldown; no-pane → not-automatable; a raising send → not-automatable with a WARNING line on stderr), mutation-checked (9d88e2db, 8342337b, 6a5199cd); the ORDERING half ('first', before the credential switch) stays pinned by the pre-existing test_no_fable_path_… test that mocks _request_model_opus. A swallowed keystroke failure is no longer silent. COMPLETE by the session under the 2026-09-03 standing permission.
- 2026-09-16T22:18:11+0200 — COMPLETE by session. all 5 boxes ticked; keystroke path pinned and published-ready.
