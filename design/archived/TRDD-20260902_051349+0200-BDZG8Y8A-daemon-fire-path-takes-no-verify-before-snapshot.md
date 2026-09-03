---
trdd-id: BDZG8Y8A
title: the daemon fire path takes no handoff_clear_verify before-snapshot, so an automated clear can never produce the PASS table
column: complete
created: 2026-09-02T05:13:49+0200
updated: 2026-09-03T10:05:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-QZVAEWQH, TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-Z582IKIR]
implementation-commits: [8ee015de]
---

# An automated clear leaves no `--phase before` snapshot to verify against

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02

Code landed in `8ee015de` (repo only): `external_handoff_clear._snapshot_before` runs the harness's
`--phase before` as a subprocess with the chain's child-only `CLAUDE_PROJECT_DIR`, agentlensPro
probe off, 10 s bound, fail-open, immediately BEFORE `_spawn_chain`. Two unit tests cover the
ordering and the fail-open. Boxes 1–2 closed on that; box 3 needs the fix INSTALLED (the daemon
runs the cached 3.4.7) and then one automated fire — so it is gated on the next `publish.py`
release + daemon restage. Not publishing for this alone: the next fire still cannot summarize
until TRDD-QZVAEWQH is ruled on, so batch this into that release.

**Daemon-shaped probe PASSED (2026-09-02 05:56, review-fork settling command)** — the unit test
alone could not tell CLAUDE_PROJECT_DIR from a conftest override, so the harness was run the way
the daemon will run it: `env -i` (bare launchd-like env), the framework `python3.12` the plist
names, cwd inside THIS git repo, `CLAUDE_PROJECT_DIR` pointing at a throwaway dir, the context
probe option set to `""`. Both the repo harness and the cached 3.4.7 copy wrote the json under
the throwaway dir with the probe's cron id and `context_source=unknown` (no agentlensPro call),
and this repo's own `handoff-clear-verify.json` was untouched. Root precedence is
`state._resolve_project_root`: `CLAUDE_PROJECT_DIR` first, then override, git toplevel, cwd. The
daemon beat runs `sys.executable <latest cache scripts>/external_handoff_clear.py --project-root`
(`cold_cache_clear_task.py:111-186`), so `_SCRIPTS` resolves to the cache tree, which ships the
harness and `lib/state.py` alongside — the fix cannot ship dark for a root/path reason.

**The context-measurement branch is proven too, separately (05:59)** — the second review fork
pointed out that `context_source=unknown` on a transcript-less throwaway dir leaves the
harness's transcript branch UNEXERCISED, and its `except Exception: pass` would print the same
`unknown` on an ImportError under the bare env. So the harness's own `_context_tokens()` was run
under the daemon's env + interpreter (`env -i`, framework python, probe option `""`), imported
in-process with `scripts/` and `scripts/lib` on the path — the same two dirs the script entry
has (its own dir by the sys.path[0] rule, plus `_HERE/lib`) — against a REAL project root, zero
writes: it returned `(353811, 'transcript')` — the same `cold_cache_compact.context_tokens_for`
reader the gate uses, on the newest transcript of that root. **Box 3 therefore also requires
`before.context_tokens` to be non-null** on the observed automated fire: a `None` there means the
branch went dark silently (the 2026-08-15 shape), not that the session was small.

**NEXT ACTION:** after the next publish installs, read the `after` table the resumed session's
cue produces and check its `before.ts` sits seconds before the matching `fired:` line in
`global-state/external-clear.log`.

Found on the first live automated clear (AgentlensPro, 2026-09-02 04:23:48, TRDD-QZVAEWQH). The
cross-`/clear` harness `scripts/handoff_clear_verify.py` proves five assumptions by comparing a
`--phase before` snapshot (cron id, context size, handoff links, resume flag) against a
`--phase after` re-read. The in-session skill `/janitor-handoff-and-clear` runs `--phase before`
right before typing `/clear`. The DAEMON path — `external_handoff_clear._fire` — does not: it
captures the transcript, types `/clear`, and leaves `.janitor/state/handoff-clear-verify.json`
whatever the last hand-run drill wrote (on AgentlensPro: a snapshot from 21:10 the day before).

Consequence: running `--phase after` on a session the daemon cleared compares against a stale
snapshot and reports a table that proves nothing about THAT clear. TRDD-PXP08ZQC's last box ("one
observed end-to-end unattended cycle … with the verify harness PASS table") and TRDD-1QJIZFFW's
box 5 ("cross-/clear verification via the existing harness") are therefore unsatisfiable by the
automated path as shipped — the path they exist to prove.

## What to do

Before `_fire` types `/clear`, take the same `--phase before` snapshot the skill takes (call the
harness's `snapshot_before` in-process — no subprocess, no network, milliseconds, fail-open like
the rest of the harness). The resumed session's post-clear resume cue already instructs it to run
`--phase after` FIRST, so nothing else changes: the table simply becomes true for automated
clears too.

## Acceptance

- [x] `_fire` writes a fresh `before` snapshot to `handoff-clear-verify.json` immediately before
      the clear is typed; a harness fault cannot block the fire (fail-open, logged) — `8ee015de`
- [x] a unit test drives `_fire` with a fake terminal and asserts the snapshot's `ts` is within
      the fire and its `cron_id` matches the pre-clear stamp — `8ee015de`,
      `test_fire_takes_a_verify_before_snapshot_before_spawning_the_chain` +
      `test_fire_still_spawns_when_the_verify_snapshot_fails`
- [x] the next automated clear's `--phase after` run (from the resume cue) reports a table whose
      `before.ts` is seconds before the `fired:` line in `external-clear.log` AND whose
      `before.context_tokens` is non-null (a null there is the transcript branch gone dark under
      the daemon, not a small session — see STATE) — proven on 4 independent live projects:
      llm-externalizer (`ts=1788405929` matches `external-clear.log:618 fired:` at the same
      second), AgentlensPro (`context_tokens=635706`), ai-maestro-janitor (`context_tokens=369314`),
      CLAUDE-PLUGIN-VALIDATION (`context_tokens=308764`)

## Notes and lessons learned

## Approval log

- 2026-09-03T10:05:00+0200 — CLOSE (testing → complete) by janitor-main-session acting for USER
  (delegation 2026-09-03 09:58). Audit `reports/board-drain/20260903_092000+0200-testing-cards-evidence-audit.md`
  verdict CLOSE: box 3 proven on 4 live projects, all `ts` matching `external-clear.log fired:` lines.
