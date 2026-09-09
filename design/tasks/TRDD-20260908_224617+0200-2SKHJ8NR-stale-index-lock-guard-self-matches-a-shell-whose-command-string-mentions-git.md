---
trdd-id: 2SKHJ8NR
title: The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper
column: testing
created: 2026-09-08T22:46:17+0200
updated: 2026-09-09T11:52:53+0200
current-owner: janitor-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
labels: [git-utils, stale-index-lock, false-positive, self-match]
relevant-rules: []
implementation-commits: [9c3af0f2]
npt: []
eht: []
---

# The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-09

- **Symptom:** `git_utils.clear_stale_index_lock(repo, min_age_s=1800)` returned `live-git`
  on seven consecutive calls over two minutes (five of them 15 s apart) for a 0-byte
  `.git/index.lock` aged 36–40 min with no `lsof` holder, while an unfiltered `ps` grep
  showed no `git` process on the host. The heartbeat detector `stale-index-lock.py` run by
  hand (rc=0) also left it in place — from a Bash-tool zsh (cwd presumed the repo). Its
  timestamp is not in evidence: before 22:35:09 the lock was under 1800 s, so `too-young`,
  `no-probe` and the self-match all remain, and the detector is fail-soft, so rc=0 with the
  lock left distinguishes none of them. It is no evidence about a heartbeat fire either way.
- **Cause — measured part:** a probe printed what `_live_git_pids(_gather_ps_snapshot())`
  matched: exactly one pid, `75589`, `cwd=<this repo>`, alive, not a zombie, etime `00:00`,
  ps line `/bin/zsh -c source …/shell-snapshots/snapshot-zsh-<this session>.sh … && eval '…`
  (printed truncated at 200 chars): a Bash-tool zsh of this session, under a second old when
  `ps` ran — consistent with the probe's own wrapper, which had just started; another
  same-second zsh from this session cannot be excluded from the snapshot alone. **Inferred
  part (high confidence, not displayed):** the `git` token. The probe's own command, written
  by this session, chained `git -C "$R" add …` after the check; the truncated line does not
  SHOW that token. Mechanism from source: `ps` prints the `-c` string verbatim, and
  `_live_git_pids` (scripts/lib/git_utils.py, `def` at line 400) splits the whole line on
  whitespace (`fields = line.split()`, line 410) and matches "basename of ANY token equal to
  `git`" — by design to avoid substring hits — so the word `git` anywhere in the wrapped
  command matches. The shell's cwd is the repo, so `_live_git_holds` fails closed on it. The
  regression test in box 1 is what turns this inference into a measurement.
- **Why it matters:** every caller that reaches the guard through a wrapper whose command
  text mentions git — Claude Code's Bash tool, a CI `run:` step executed via `sh -c`, a
  Makefile recipe — is refused deterministically, not transiently. Whether the production
  path (dispatch.py → detector under a heartbeat fire) carries `git` in any argv is
  UNVERIFIED — nobody printed the detector's argv from a fire; confirm before claiming that
  heartbeat fires pass. A human or agent recovering by hand cannot, unless the command text
  avoids a bare `git` token. This is lesson [1] of
  `git-index-lock-orphan-recovery` in a fourth dress: liveness of a process that is not a
  git writer read as holding.
- **Fix shape (decided by this session; two reviews found no writer it drops):** match the
  EXECUTABLE token only — the first token of the COMMAND column, however
  `_gather_ps_snapshot` lays the columns out (read it first) — instead of any token; keep the
  exact-basename rule. Alternative worth one look: add `comm` as a snapshot column and match
  that (basename only, no args) — only if the snapshot's other consumers do not need the
  args. `/usr/bin/env git …`, `xcrun git …` and a single-command `sh -c 'git …'` all exec the
  real `git` binary, so the process that actually holds `index.lock` shows as `git` in ps
  anyway — do not add a wrapper list. Non-git holders (libgit2/gitoxide apps) were never
  caught by argv under either shape; `_lock_is_held` is the guard for those, not this
  matcher. Add a regression test whose snapshot line is `<pid> <ppid> 00:00 /bin/zsh -c git
  status` and asserts it is NOT matched, and one with `/opt/homebrew/bin/git status` that IS.
- **Resolution this time:** the lock was removed by hand at 22:44:59 after the page's own
  conditions held inline (age 2390 s > 1800, `lsof` 0 lines, no git process with this repo's
  path in a fresh snapshot, 0 bytes). Commit `49c09951` then landed. Audit (rule 0.5): no
  user text authorized it; a 0-byte `index.lock` is a regeneratable artifact (RULE 0
  exempt); removed after the janitor's own guard refused seven times, for the cause above.
- **DONE 2026-09-09 (commit `9c3af0f2`; column: testing):** the PRRD grep
  (`lock|guard|fail-closed`, per the previous NEXT ACTION) returned S3.1 (atomic file
  writes) and S6.1 (detector fail-soft) only; judged not to constrain this change (S3.1: no
  file write changed; S6.1: the matcher's no-raise `len(fields) > 3` guard is consistent
  with it, not required by it) — a reading, so `relevant-rules: []` stands as none cited.
  Executable-token match landed with three tests. Mutation check: under the OLD matcher
  exactly the two tests that encode the new rule fail (by name:
  `test_a_shell_whose_command_string_mentions_git_is_not_a_git_process`,
  `test_stale_lock_is_removed_despite_a_git_mentioning_shell`; 2 failed / 38 passed, same
  40-test file) and `test_a_git_invoked_by_full_path_is_still_a_git_process` passes under
  both; new code 77 passed over `tests/test_git_index_lock_recovery.py`,
  `tests/test_git_index_lock_e2e.py`, `tests/test_stale_index_lock_detector.py` plus three
  of the guard's caller test files (the invocation lives in the session's task output, not
  in the repo). ruff, mypy, pyright artefacts from 2026-09-08 23:13 are clean (mypy: `1
  source file`, so scoped to `git_utils.py`; comment-only edits followed; the publish gate
  re-runs all three tree-wide). Live probe at the lib level from a Bash-tool shell whose
  command text mentioned git printed `matched pids: []` in the background run launched by
  the 2026-09-08 session (exited 0; its output carries no clock line).
- **Detector-level controls (2026-09-09; throwaway repos under the session scratchpad, a
  fresh 0-byte `.git/index.lock` each, `CLAUDE_PLUGIN_OPTION_STALE_INDEX_LOCK_MIN_AGE=0`,
  fresh `<repo>/.janitor/state` — there is no separate state-dir knob, the state dir derives
  from `CLAUDE_PROJECT_DIR`):** (a) git-free wrapper → the detector printed its `Removed a
  stale .git/index.lock` line, lock gone (shows the detector removes at all; dispatch's
  actual argv is still unread from a fire, so the production-path claim stays a stand-in).
  (b) wrapper whose text carried a bare `git` token but whose cwd was OUTSIDE the repo →
  same outcome, NOT discriminating: `_live_git_holds` excludes a matched pid whose cwd
  resolves outside `repo_root` (this card's own box 2 said so; a review round forgot it).
  (c) child `sh -c 'sleep 60 # git'` with cwd INSIDE → same outcome, NOT discriminating
  either: sh tail-execs into `sleep 60`, so no `git` token reaches the ps table — the design
  this card's box 2 originally proposed has that hole. (d) child `/bin/sh -c 'sleep 60; :
  git'` with cwd INSIDE (two commands keep sh alive; ps line `/bin/sh -c sleep 60; : git`,
  the only git-bearing line in the saved snapshot): the OLD `_live_git_pids` (from
  `01637fba`) replayed on that snapshot returned `[60722]` (the child), the NEW returned
  `[]`, and the new-code detector printed its Removed line and the lock was gone. The old
  DETECTOR was not run end to end; the old rule's refusal is measured at unit level (2 failed
  by name) and at matcher level on this live snapshot. Reports:
  `reports/colony/20260909_113921+0200-unit{3,4,5,6}-*.md` (gitignored, this machine).
- **NEXT ACTION:** none open on this card; closure (`testing` → `complete`) is the owner's
  call.

## Acceptance

- [x] `_live_git_pids` matches only when the executable token's basename is `git`; a
      `sh -c "… git …"` wrapper line is not matched (test present and passing).
- [x] With the only git-mentioning line being a shell wrapper, `_live_git_pids` returns `[]`
      and `clear_stale_index_lock` returns `removed`, not `live-git` — tested with an
      injected `ps_snapshot` (the parameter the card's first draft did not know existed) and
      the three probes patched (`_pid_cwd` None, `_pid_is_alive` True, `_pid_is_zombie`
      False): one of the two fail-closed combinations; the cwd-in-repo one is equally
      unreachable because the pid is never matched; `removed` also relies on
      `_lock_is_held` finding no lsof holder on the tmp lock. The OLD matcher fails this test
      and its unit-level sibling (the two names in the 2-failed run). (Rewritten 2026-09-09,
      see approval log.)
- [x] `git-index-lock-orphan-recovery` gains a dated lesson naming this fourth self-match
      form (via the memgrep verb, not by hand), then committed — done 2026-09-09: `[^4]` /
      `ATOM-XMY7-ZFNS` via `memgrep update-mem-atom --lesson`, validate NONE, lint 0
      findings, page commit `442e3794`.

## Approval log

- 2026-09-08T22:46:17+0200 — Authored at `todo` by the janitor session, from a live
  refusal on this repo during the TWF7DXXR commit. Tier 0 (in-scope bugfix in the janitor's
  own lib).
- 2026-09-08T22:50:20+0200 — Revised after review: "measured" split from "inferred" (the
  `git` token was never displayed — the probe line was truncated at 200 chars), the by-hand
  detector run marked as the same self-match, the production-path claim marked unverified,
  box 2 rewritten to run with `min_age_s=0`, the PRRD S6.1 citation dropped (S6.1 governs a
  detector's fail-soft, not a guard that refuses).
- 2026-09-08T22:55:44+0200 — Second and final review round: "same self-match" for the
  by-hand detector run downgraded to a conditional (its command text is not in evidence;
  rc=0 cannot distinguish self-match from `no-probe`); "the probe itself" downgraded to
  "consistent with, not excluded" with the etime `00:00` evidence added; the whitespace split
  attributed to `_live_git_pids` (line 410), not to `ps`; fix shape decided, with the `comm`
  column named as the alternative and libgit2 holders assigned to `_lock_is_held`; box 2 made
  unable to pass for the wrong reason (`repo_root` = own cwd, `sleep 60` killed in `finally`,
  non-`removed` values printed); rule 0.5 audit line added; NEXT ACTION gains the PRRD sweep
  and the no-git-wrapper control. Further wording changes go to the owner, not a third round.
- 2026-09-08T23:00:40+0200 — Correction of round 2's own over-claim (fork-identified, not a
  third round): the by-hand detector run's timestamp is not in evidence, so `too-young` is not
  excluded; the control names the detector's real knob
  (`CLAUDE_PLUGIN_OPTION_STALE_INDEX_LOCK_MIN_AGE`, fresh state dir) instead of the lib
  parameter; box 2 names the `live-git`-from-another-pid outcome.
- 2026-09-09T11:52:53+0200 — Fix landed (`9c3af0f2`); column → testing (code and tests
  landed; four detector-level controls run the same morning, results in STATE). Box 2
  rewritten after the fact: the card predates knowing `ps_snapshot=` is injectable, and the
  test does what the box meant (a git-mentioning shell as the only candidate, no 30-minute
  wait) without `monkeypatch.chdir` or a sleeping `sh -c 'sleep 60 # git'` child — a child
  that, run live, turned out not to carry the `git` token at all (control c). Box 3 ticked on
  page commit `442e3794`. Two review rounds on this text plus one on the controls; the
  control results and the correction of the "discriminating run" wording were added after
  round 2 from measured output, not re-reviewed before the write (disclosed in the session
  reply). Tier 0, no publish.
