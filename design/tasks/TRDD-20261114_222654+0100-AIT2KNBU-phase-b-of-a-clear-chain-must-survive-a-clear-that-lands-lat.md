---
trdd-id: AIT2KNBU
title: Phase B of a clear chain must survive a clear that lands late and the hooks must still hand over the handoff (issues 355 and 356 F2 and F3)
column: todo
status: tasked
created: 2026-11-14T22:26:54+0100
updated: 2026-11-15T04:43:12+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T22:26:54+0100
---

# Phase B of a clear chain must survive a clear that lands late and the hooks must still hand over the handoff (issues 355 and 356 F2 and F3)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: CONSULT THE FABLE ADVISOR (fable-advisor:advisor; run agentlenspro model-headroom fable -q first) BEFORE building: this touches 3+ files and a hook-versus-chain ownership decision. Then build F3 first (or together with F2), one bounded change, tests written but run only before the push.
- Status: not started. Parent work: TRDD-V8GWJVFN (F1+F4, already committed); GitHub issues 355 and 356.
2026-11-15 04:10 EVIDENCE (this repo, installed 3.8.13, .janitor/logs/clear-trigger.log, session-start.log, jev-post-clear-hook.log): (a) session 1603e47a: clear landing 2026-11-14 23:25:46 at 400517 tokens, chain FAILED 23:28:48 (no fresh session within 180s, resume state KEPT); the clear landed at 23:30:07 (SessionStart source=clear in c94c7168, about 261 s late), the template handoff was injected at 23:30:58 (inside the 300 s sidecar window), but the chain typed no phase B. (b) session c94c7168: clear landing 2026-11-15 01:31:17 at 431778 tokens, chain FAILED 01:34:19; at 01:34:48 SessionStart reports source=compact in the SAME session: the native auto-compact ran before the queued /clear landed, which the Corrections paragraph already calls harmless to state; the post-clear hook returns on any source other than clear or startup before it consumes the sidecar (scripts/hooks/on-session-start-post-clear-compact.py:255), so a compaction does not eat the sidecar and F3 stands. The queued /clear then landed at 01:42:28 (f40b3073, source=clear) and jev-post-clear-hook.log says "sidecar ... is 672s old — ignoring": a LIVE instance of the F3 bug (no handoff injected), real numbers for T4. Each landing line is followed within 9-150 s by 'another clear chain is already pending — skipping'. f40b3073: landing 03:32:14 at 441654, next session 909e5562 got the handoff at 03:34:39 and resumed.
2026-11-15 04:25 ADVISOR VERDICT (built-in advisor, Fable headroom 44%): build F3 first as its own change, then F2 separately. F3 DISPATCHED 04:25 to one sonnet-worker: files scripts/hooks/on-session-start-post-clear-compact.py, scripts/hooks/on-session-start.py, tests/test_on_session_start_post_clear_compact.py (T4); report in reports_dev/sonnet-worker/*-ait2knbu-f3.md; do NOT send a second writer to these files before that report is read. Disclosed limit (main-agent decision): nothing tells the janitor's late /clear from one the user types within the hour after a give-up while the flag and the matching resume-after-clear.ts remain, so such a user /clear also receives the handoff. F2 later: read TRDD-N954KWUC STATE first (it owns the screen reader the probe uses); the probe must count a compacting pane as busy (case b) and T3 must cover it; check tldr impact run_chained_inject so callers without gate_extend keep 180 s.

## Problem

Even with F1 (TRDD-V8GWJVFN) a /clear can still land late: the chain child may be killed, the host may reboot, or the 180 s gate may expire while the pane is busy for another reason. Then phase B (the commands after the clear: /janitor-arm plus /goal or /janitor-resume) is never typed and no handoff reaches the new session. Evidence from issue 355: the clear was submitted at 16:08:16, landed at about 16:27:35 (19 minutes), the chain had given up at 180 s ("/clear submitted but no fresh session within 180s", resume state KEPT, no phase B, lock released), and no code path dequeues the queued /clear.

## F2 and F3 (design, verified by reading code; labels V verified, U unverified)

F3 (late-landing guard for the hooks). scripts/hooks/on-session-start-post-clear-compact.py _consume_sidecar (about L102, L296-300) renames the per-pane sidecar, then ignores it when age exceeds _SIDECAR_FRESH_MAX_AGE_S (300 s) and returns 0. scripts/hooks/on-session-start.py (about L381) returns silently when any resume-after-clear.<pane>.transcript* file exists, and that check is unbounded; the rename left a .consumed-<epoch> file that matches it. Net effect (V): a clear that lands more than 300 s late injects NOTHING from either hook. The same trap is already documented for the startup lane in on-session-start.py _startup_chain_clear_service; the clear lane has it unfixed. Fix: ignore only if NOT (flag present AND resume-after-clear.ts equals the sidecar written_at AND age at most external_clear._UNARMED_CLEAR_FLAG_MAX_AGE_S = 3600). Do not depend on the clear-observed.ts stamp (two parallel SessionStart hooks race on it). Never end silent: move the age decision BEFORE the rename (keep the rename before the compose, it is deliberate for crash durability) so on-session-start.py's fallback pointer path runs when the hook still ignores. Residual accepted cost (already documented near on-session-start.py L475-480): a manual /clear after a failed chain within one hour gets this chain's handoff, which is benign.

F2 (phase B must outlive a queued /clear). run_chained_inject (scripts/lib/terminal_trigger.py, _await_fresh_session about L1813, gate_timeout_s=180): add a gate_extend callable. When the 180 s gate expires, call gate_extend(); True keeps polling clear-observed.ts up to _CLEAR_CHAIN_GIVEUP_S (3600 s), False gives up as today. clear_trigger passes a probe based on pane_state: True while the main turn is busy or the input field shows a QUEUED message (our /clear is still ahead of the turn), False when the pane is idle and the field empty (the clear really went nowhere); unreadable probe counts as True, bounded by the 3600 s. Effect: lock clear-chain.lock stays held, which also blocks a second chain from typing a second /clear (in issue 355 only coincident recovery_pending and a compaction flag stopped two more queued clears; nothing else did).

Rejected alternative, rated worse: a hook-spawned phase-B-only sender. Both SessionStart hooks do resolve the pane (terminal_trigger.self_terminal(os.environ)) so a hook COULD type, but there is no reliable "no chain alive" signal (external_clear.py near L1265-1272 warns that probing clear-chain.lock with LOCK_EX|LOCK_NB can make a NEW chain fail to acquire) and two senders could type phase B twice. F2 keeps one owner of phase B.

Corrections binding on the builder: F1, F2 and F3 are ALL needed for 355 (without F3 a 19-minute landing still injects nothing); the claim "only the chain child can type" is wrong as stated (see above); a compaction between submit and landing is harmless to state because the handoff comes from the OLD transcript and the goal is re-set from clear_bootstrap computed at spawn (low risk: the goal text may be stale if it changed in between).

## Tests to write (real, no mocks; run only before the push)

T3 tests/test_clear_chain_queued_landing.py: real tmux pane showing a busy frame; run_chained_inject(gate_timeout_s=1, gate_extend=real probe) with a background thread writing clear-observed.ts after 3 s and flipping the frame to idle: asserts ok and the then-commands typed. Negative: idle plus empty frame and no stamp returns False after gate_timeout (converts the old behaviour into the asserted give-up). T4 tests/test_on_session_start_post_clear_compact.py: real files, sidecar written 1200 s ago plus flag plus equal ts: hook subprocess with source clear prints the injection (template path acceptable when Jev is unreachable); and sidecar 1200 s old WITHOUT flag: still ignored AND on-session-start's fallback emits the pointer. State in the docstrings that the tmux pane is a scripted printout of a captured frame (a simulated TUI), not a live Claude Code; end-to-end needs the owner to run a live session with /goal.

Files: scripts/lib/terminal_trigger.py, scripts/clear_trigger.py, scripts/hooks/on-session-start-post-clear-compact.py, scripts/hooks/on-session-start.py (only if the pointer path needs it).

## Approval log

- 2026-11-14T22:26:54+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
