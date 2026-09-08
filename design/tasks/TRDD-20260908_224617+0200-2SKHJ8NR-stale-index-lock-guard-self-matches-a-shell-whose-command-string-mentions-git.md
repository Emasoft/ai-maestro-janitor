---
trdd-id: 2SKHJ8NR
title: The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper
column: todo
created: 2026-09-08T22:46:17+0200
updated: 2026-09-08T22:55:44+0200
current-owner: janitor-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
labels: [git-utils, stale-index-lock, false-positive, self-match]
relevant-rules: []
npt: []
eht: []
---

# The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

- **Symptom:** `git_utils.clear_stale_index_lock(repo, min_age_s=1800)` returned `live-git`
  on seven consecutive calls over two minutes (five of them 15 s apart) for a 0-byte
  `.git/index.lock` aged 36–40 min with no `lsof` holder, while an unfiltered `ps` grep
  showed no `git` process on the host. The heartbeat detector `stale-index-lock.py` run by
  hand (rc=0) also left it in place — from a Bash-tool zsh in the repo cwd. If its command
  text carried a bare `git` token it is the same self-match; the lock was already past
  1800 s, so `too-young` is excluded, but `no-probe` is not — and the detector is fail-soft,
  so rc=0 with the lock left cannot distinguish these. It is no evidence about a heartbeat
  fire either way.
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
- **NEXT ACTION:** grep `design/requirements/PRRD.md` for `lock|guard|fail-closed` (the
  PRRD was not swept when this card was filed — `relevant-rules: []` means none cited, not
  none applies); implement the executable-token match + the two tests; run
  `uv run pytest tests -k "index_lock or live_git" -q`; re-run the probe from a Bash-tool
  shell whose command mentions git and confirm `matched pids: []`. Control for the
  production-path claim: run `stale-index-lock.py` from a wrapper whose command text has no
  bare `git` token against a synthetic stale lock (`min_age_s=0`) and expect `removed`.

## Acceptance

- [ ] `_live_git_pids` matches only when the executable token's basename is `git`; a
      `sh -c "… git …"` wrapper line is not matched (test present and passing).
- [ ] Runnable without a 30-minute wait, and unable to pass for the wrong reason:
      `_live_git_holds(snapshot, repo_root)` with `repo_root` = the test's OWN cwd
      (`monkeypatch.chdir(tmp_repo)` — with the cwd outside `repo_root` the old code also
      returns False and proves nothing) is False for a snapshot whose only git-mentioning
      line is `<own pid> <ppid> 00:00 /bin/zsh -c git status` and True for `<own pid> <ppid>
      00:00 /opt/homebrew/bin/git status`; end to end, in that tmp repo with a 0-byte
      `.git/index.lock`, `clear_stale_index_lock(repo, min_age_s=0)` returns `removed` while
      a child `sh -c 'sleep 60 # git'` (killed in `finally`, so it cannot exit before the
      snapshot under load) runs with cwd inside the repo. On any other value the test prints
      it: `held`/`no-probe`/`no-snapshot` is the probe, not the matcher, and not this card.
- [ ] `git-index-lock-orphan-recovery` gains a dated lesson naming this fourth self-match
      form (via the memgrep verb, not by hand), then committed.

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
