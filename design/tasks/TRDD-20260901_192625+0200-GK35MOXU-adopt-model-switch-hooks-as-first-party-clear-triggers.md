---
trdd-id: GK35MOXU
title: Adopt the PreModelSwitch/PostModelSwitch hooks as the first-party model-change trigger for the external clear
column: blocked
created: 2026-09-01T19:26:25+0200
updated: 2026-09-16T22:26:35+0200
review-after: 2026-09-23
implementation-commits: [df26fa12, 73b242a8, 83e7242d]
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: [VT332PJG]
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-2F3I2P18]
pre-block-column: testing
unblock-when: []
blocker-probe: [trddgrep, --porcelain, show, VT332PJG]
blocker-holds-if: not-match:\t(complete|completed|cancelled|superseded)\t
assignee: janitor-main-session
---

# The harness now EMITS the model-change event — stop polling for it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:20+0200

- **2026-09-03 11:20 — `dev → testing` (soak).** `.cpv-version` bumped v5.4.0 → v5.16.2 with the
  two workflow literals (`tests/test_cpv_pin_ssot.py` 11/11; `cpv-remote-validate plugin .
  --strict` at v5.16.2 → `CRITICAL=0 MAJOR=0 MINOR=0 NIT=0`, exit 0 — v5.4.0 had rejected
  `PostModelSwitch` as `[CRITICAL] Unknown hook event`). The advisor's pre-existing hole in
  `on-session-start-cold-cache-clear.py::_payload` (a non-object JSON body raised outside the
  guard) is closed (`return data if isinstance(data, dict) else {}`; probed with `[]` and
  `"x"` → exit 0). All code work is done; the two open boxes (live `/model`, `/effort`) can only
  be observed in a session running the NEXT published version — this session's 3.4.13
  `hooks.json` carries no `PostModelSwitch` entry. **NEXT ACTION:** after the publish installs,
  run `/model opus` then `/model fable` in one session and grep
  `.janitor/state/` for the stamp the hook advances; then `/effort` and record whether it fires.
- **Box 1 (hooks.json registration)**: `PostModelSwitch` entry ADDED to `hooks/hooks.json`
  (upstream `claude-plugins-validation#222` closed 2026-09-02). CPV's own repo now accepts
  the event (`scripts/cpv_validation_common.py:334-335` in `claude-plugins-validation` main,
  released as v5.15.0+). **NOT done: bumping this repo's `.cpv-version` pin** (currently
  `v5.4.0`, 70+ releases behind) — that is a repo-wide publish-pipeline change spanning every
  CPV delta since 5.4.0, not something to rush inside this card's scope. Orchestrator: bump
  `.cpv-version` (own TRDD or chore) before the next publish, or the gate still won't see this
  hook. **Still NOT done: a real `/model` switch verification on this machine** — a subagent
  worker cannot safely switch its own session's model mid-task; needs a human/interactive run.
- **Box 3 (/effort measurement)**: NOT measured live this pass (same reason — needs an
  interactive session running `/effort`). CPV's spec-sync report for 2.1.251
  (`claude-plugins-validation/reports/spec-sync-2.1.257/20260901_222622+0200-w2-issue-222-model-switch-hooks.md`)
  documents the event registration but says nothing about whether an effort-only change fires
  it. Fallback poll (`prefix_invalidated`) stays in place until this is measured.
- **Box 4 (SessionStart staleness) — DONE this pass.** A live 2.1.251+ resume payload was
  found on disk (`.janitor/state/session-staleness.json`, 3 projects) and named the real
  fields: `prompt_cache_likely_expired` (bool) + `estimated_cache_write_usd` (float).
  Bound `prompt_cache_likely_expired` in `external_clear.cache_expired_from_harness_payload`
  (new, pure) and wired it into `on-session-start-cold-cache-clear.py`: the harness signal, read
  straight from the hook's own stdin payload (NOT the sibling file — that hook fires in
  parallel and reading its file here would race the writer), outranks and skips the
  agentlensPro probe subprocess when present. `estimated_cache_write_usd` is bound/observed
  but not consumed — no consumer needs it yet; leaving it in the persisted file is enough.
- **Box 5 (gates)**: ruff + mypy clean repo-wide. pytest: 16139 passed, 1 pre-existing
  UNRELATED failure (`test_rules_installer.py::test_shipped_rules_stay_under_the_context_floor_cap`
  — shipped `rules/*.md` corpus 829 B over its byte cap; touches none of this card's files,
  confirmed pre-existing via `git log` on that test/rules — not fixed here, out of scope).
- (superseded 11:20 — the `.cpv-version` bump landed; see the top entry for the live-check
  NEXT ACTION.)

**2026-09-08 — vs owner ruling TRDD-7MGJYLY5:** CONSISTENT WITH R1's preferred path (first-party
PreModelSwitch/PostModelSwitch hooks as an earlier, non-polled trigger for the external clear);
does NOT itself deliver R1's fire-before-autocompact on context fill (no such trigger here).
R2/R4: outside this card's scope; R3: one mention (grep count), not assessed against the ruling.

## Why (USER directive, 2026-09-01: "you said there is no model change event? wrong")

TRDD-2F3I2P18 detects a model/effort switch by POLLING `agentlenspro statusline-history raw`
and diffing the two newest rows. That was correct for the CC version it was written against.
**Claude Code 2.1.251 (installed: 2.1.252) added `PreModelSwitch` and `PostModelSwitch` hook
events** — the harness now tells us, at the instant of the switch, with no subprocess, no
agentlens dependency, no 2-row parse, and no per-session ambiguity.

## The design (mirror the reload-acked pattern exactly)

1. Add a `PostModelSwitch` hook to the plugin's `hooks/hooks.json` that appends/advances a
   `.janitor/state/model-switch-acked.ts` stamp (a generation int, exactly like
   `reload-acked.ts`) — cheap, no model turn.
2. Extend `external_clear.reload_invalidated`'s family with the same stamp (or fold it into
   `_read_reload_state` as a third name): unprocessed fresh ack ⇒ dead prefix ⇒ fire; the
   fire path's `consume_reload_events` consumes it. All the 2F3I2P18 semantics (tri-state,
   probe-does-not-consume, 10-min freshness) carry over verbatim.
3. Keep `prefix_invalidated` (statusline poll) as the FALLBACK for sessions on CC < 2.1.251
   and for effort-only switches IF the hook does not fire on effort change — VERIFY whether
   `/effort` fires PostModelSwitch before assuming either way; 2.1.251 also notes `/effort`
   now saves per-model defaults, so a model switch may imply an effort switch.
4. `PreModelSwitch` (can block/confirm) is deliberately NOT used to block — the janitor never
   vetoes the user's switch; it only reacts.

## Also from the same release — use in the resume gate

`SessionStart` resume hooks now receive **session staleness and the estimated re-cache cost**.
`should_clear_on_resume` currently infers coldness from transcript mtime + agentlens; the
hook payload is first-party ground truth. Wire it: on-session-start persists the two fields to
`.janitor/state/`, the resume gate prefers them when present.

## Acceptance

- [x] PostModelSwitch hook ships in hooks/hooks.json and stamps the ack file (verified by a
      real `/model` switch on this machine, not just a unit test) — hooks.json entry ADDED
      2026-09-03 (CPV upstream issue 222 closed, CPV main now knows the event); `.cpv-version`
      pin bumped to v5.16.2 (STATE 2026-09-03); the live `/model`-switch verification is DONE
      2026-09-16 — six real PostModelSwitch stamp advances in .janitor/logs/external-clear.log (Notes)
- [x] the external-clear gate fires on the stamp with the consume-on-fire semantics
      (`df26fa12`: third stamp name in `_read_reload_state`; probe/consume tests)
- [ ] measured whether `/effort` fires the hook; fallback poll retained or retired accordingly,
      with the finding written into the card — STILL OUTSTANDING, needs an interactive
      session; fallback poll (`prefix_invalidated`) stays in place
- [x] SessionStart staleness + re-cache cost persisted and preferred by the resume gate —
      the real field names (`prompt_cache_likely_expired`, `estimated_cache_write_usd`) were
      bound from a live payload found on disk; `external_clear.cache_expired_from_harness_payload`
      (new) is wired into `on-session-start-cold-cache-clear.py` and outranks + skips the
      agentlensPro probe when the harness already answered (2026-09-03, 4 new unit tests)
- [x] pytest + ruff + mypy green — RE-TICKED 2026-09-04 against the NAMED commit the
      box below demanded: **`72725c03`**, working tree clean (`git status --porcelain`
      empty, so HEAD and the tree are identical).
      `uv run ruff check scripts tests` → All checks passed.
      `uv run mypy scripts/ --ignore-missing-imports` → no issues in 504 source files.
      `uv run --extra dev pytest tests/ -x -q -n auto --dist loadgroup --timeout=300
      --timeout-method=thread` → 16370 passed, 1 skipped, 8 subtests passed.
      The specific regression this box was re-opened for was re-run on its own first:
      `tests/test_git_index_lock_e2e.py` → 5 passed, including
      `test_stale_orphaned_lock_is_removed_and_renamed_aside`.
      SHA CONVENTION, so a reader need not infer it: the gates ran on `72725c03`;
      this tick lands in the NEXT commit, which touches only card files
      (`git show --stat` confirms). A commit cannot be tested before it exists, so
      naming the tested tree plus what changed after it is the honest form.
      This box was reachable without a release all along — an adversarial re-audit of the
      `testing` column found it mis-bucketed as release-gated by PROXIMITY to the two
      genuine live-`/model`-switch boxes on the same card. A "re-run the gates" box is not
      a runtime-event box, and grouping it with its neighbours hid that for a day.
      (Precisely: the audit's contribution was flagging it still OPEN. That it was
      gate-runnable was already known — I un-ticked it myself earlier this session
      for citing the wrong tree.)
      HISTORY, kept because it is the reason for the named-sha discipline:
      the 3.4.14 publish gate ran on commit `4326519d` (ruff clean, mypy clean over 504
      source files, 16351 passed / 1 skipped / 0 failed), three doc commits behind HEAD.
      Re-running the three on HEAD `9d0a5a86` was NOT a formality — it surfaced a real
      failure the gate had not:
      `test_git_index_lock_e2e.py::test_stale_orphaned_lock_is_removed_and_renamed_aside`
      returned `live-git` for a scratch worktree, because `git_utils`' probes never used
      the `state.timeout_scale()` seam and `lsof` timed out under xdist load. Fixed in
      `git_utils.py` (all four probes scaled) with three regression tests. Re-tick only
      against a NAMED commit, once the full suite is green on it.
      The 2026-09-03 rules-floor-cap carve-out is separately gone.

## Notes and lessons learned

- The lesson that produced this card: a trigger design claim ("no event exists, we must poll")
  has a shelf life of one harness release. Re-read the changelog BEFORE building a poller.
- **The paid-detector (`83e7242d`)**: the invariant that makes a clear free is "no turn ran
  since the prefix died", not "the prefix died recently" — a mid-conversation `/model` switch
  is re-paid by the very next turn (heartbeats included), so a fresh-but-paid event is
  consumed silently, exactly like a stale one. Firing on it would clear a WARM session.
- **Bounded residual of the 10s paid-slack (`f05ab464`, review-fork, no action)**: an idle
  switch followed by a trivial turn completing within 10s leaves the event armed on a warm
  session; if every veto passes, the cost is ONE spurious handoff-and-clear at idle (capped
  by consume-on-fire + the fired cooldown, and llm-ext costs zero Claude-side tokens). The
  10s value is an unmeasured knob — recalibrate when the live verify observes a real
  switch's append timing. Boundary proven at exactly the constant (9s fires, 11s paid).
- **Pre-existing cross-session ceiling (review-fork, no action)**: the ack stamps are
  per-PROJECT and the watcher clears the one RECORDED pane, so with two sessions in one
  project, session B's switch can trigger a clear aimed at session A. Same holds for the
  reload stamps since birth; a per-session stamp keyed on session id is the upgrade if it
  ever bites.
- 2026-09-16 — box 1 ticked: six `model switch acked (gen N)` lines in .janitor/logs/external-clear.log (gen 1 2026-09-09 15:10 … gen 6 2026-09-16 20:08) prove the hook stamps on real PostModelSwitch fires on this machine; the harness payload carried none of previous_model/new_model/model on any of them. Box 3 (/effort) needs one interactive /effort in a live session — asked of the owner 2026-09-16; parked as blocked on that decision. This session's 21:45 Opus→Fable change was a --resume, not /model; no fire expected. Report: reports/board-drain/20260916_215500+0200-GK35MOXU-model-switch-stamp.md

## Approval log

- 2026-09-03T09:25:00+0200 — UNBLOCK (blocked → dev) by janitor-main-session acting for USER
  (delegation 2026-09-03 09:58). `blocked-by: claude-plugins-validation#222` is CLOSED
  (COMPLETED) — verified `gh issue view 222 --repo Emasoft/claude-plugins-validation --json state`
  → `CLOSED`. Restored to `pre-block-column: dev` per
  `reports/board-drain/20260903_091543+0200-blocked-cards-audit.md`.
- 2026-09-16T22:18:12+0200 — column → blocked. waits on one interactive /effort by the owner (box 3); review-after 2026-09-23 is the park form
