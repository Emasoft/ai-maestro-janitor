---
trdd-id: 2SKHJ8NR
title: The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper
column: todo
created: 2026-09-08T22:46:17+0200
updated: 2026-09-08T22:50:20+0200
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
  hand (rc=0) also left it in place — but that run was launched from the same Bash-tool
  script, whose text also contained `git -C "$R" add`, so it is the same self-match and
  says nothing about the detector under a heartbeat fire.
- **Cause — measured part:** a probe printed what `_live_git_pids(_gather_ps_snapshot())`
  matched: exactly one pid, `75589`, `cwd=<this repo>`, alive, not a zombie, ps line
  `/bin/zsh -c source …snapshot-zsh… && eval '…` (printed truncated at 200 chars): the zsh
  running the probe itself. **Inferred part (high confidence, not displayed):** the `git`
  token. The probe's own command, written by this session, chained `git -C "$R" add …`
  after the check; the truncated line does not SHOW that token. Mechanism from source:
  `_live_git_pids` (scripts/lib/git_utils.py, `def` at line 400) matches "basename of ANY
  argv token equal to `git`", by design to avoid substring hits — but `ps` prints a `sh -c`
  string whitespace-split, so the word `git` anywhere in the wrapped command matches. The
  shell's cwd is the repo, so `_live_git_holds` fails closed on it. The regression test in
  box 1 is what turns this inference into a measurement.
- **Why it matters:** every caller that reaches the guard through a wrapper whose command
  text mentions git — Claude Code's Bash tool, a CI `run:` step executed via `sh -c`, a
  Makefile recipe — is refused deterministically, not transiently. Whether the production
  path (dispatch.py → detector under a heartbeat fire) carries `git` in any argv is
  UNVERIFIED — nobody printed the detector's argv from a fire; confirm before claiming that
  heartbeat fires pass. A human or agent recovering by hand cannot. This is lesson [1] of
  `git-index-lock-orphan-recovery` in a fourth dress: liveness of a process that is not a
  git writer read as holding.
- **Fix shape (option, not decided):** match the EXECUTABLE token only — the first token of
  the COMMAND column, however `_gather_ps_snapshot` lays the columns out (read it first) —
  instead of any token; keep the exact-basename rule. `/usr/bin/env git …` and `xcrun git …`
  are missed by an executable-token match, and that does not matter for a HOLDER check:
  both exec the real `git` binary, so the process that actually holds `index.lock` shows as
  `git` in ps anyway — do not add a wrapper list. Add a regression test whose snapshot line
  is `<pid> <ppid> 00:00 /bin/zsh -c git status` and asserts it is NOT matched, and one with
  `/opt/homebrew/bin/git status` that IS.
- **Resolution this time:** the lock was removed by hand at 22:44:59 after the page's own
  conditions held inline (age 2390 s > 1800, `lsof` 0 lines, no git process with this repo's
  path in a fresh snapshot, 0 bytes). Commit `49c09951` then landed.
- **NEXT ACTION:** implement the executable-token match + the two tests; run
  `uv run pytest tests -k "index_lock or live_git" -q`; re-run the probe from a Bash-tool
  shell whose command mentions git and confirm `matched pids: []`.

## Acceptance

- [ ] `_live_git_pids` matches only when the executable token's basename is `git`; a
      `sh -c "… git …"` wrapper line is not matched (test present and passing).
- [ ] Runnable without a 30-minute wait: `_live_git_holds(snapshot, repo_root)` is False for
      a snapshot whose only git-mentioning line is `<own pid> <ppid> 00:00 /bin/zsh -c git
      status` (own cwd inside the repo) and True for `<own pid> <ppid> 00:00
      /opt/homebrew/bin/git status`; and end to end, in a tmp repo with a 0-byte
      `.git/index.lock`, `clear_stale_index_lock(repo, min_age_s=0)` returns `removed` while
      a child `sh -c 'sleep 5 # git'` started by the test runs with cwd inside that repo.
- [ ] `git-index-lock-orphan-recovery` gains a dated lesson naming this fourth self-match
      form (via the memgrep verb, not by hand).

## Approval log

- 2026-09-08T22:46:17+0200 — Authored at `todo` by the janitor session, from a live
  refusal on this repo during the TWF7DXXR commit. Tier 0 (in-scope bugfix in the janitor's
  own lib).
- 2026-09-08T22:50:20+0200 — Revised after review: "measured" split from "inferred" (the
  `git` token was never displayed — the probe line was truncated at 200 chars), the by-hand
  detector run marked as the same self-match, the production-path claim marked unverified,
  box 2 rewritten to run with `min_age_s=0`, the PRRD S6.1 citation dropped (S6.1 governs a
  detector's fail-soft, not a guard that refuses).
