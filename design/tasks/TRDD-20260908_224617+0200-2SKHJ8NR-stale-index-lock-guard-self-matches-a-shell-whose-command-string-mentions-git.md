---
trdd-id: 2SKHJ8NR
title: The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper
column: todo
created: 2026-09-08T22:46:17+0200
updated: 2026-09-08T22:46:17+0200
current-owner: janitor-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
labels: [git-utils, stale-index-lock, false-positive, self-match]
relevant-rules: [6]
npt: []
eht: []
---

# The stale-index-lock guard self-matches a shell whose command string mentions git, so it refuses forever when invoked from any sh -c wrapper

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-08

- **Symptom:** `git_utils.clear_stale_index_lock(repo, min_age_s=1800)` returned `live-git`
  on seven consecutive calls over two minutes (five of them 15 s apart) for a 0-byte
  `.git/index.lock` aged 36–40 min with no `lsof` holder, while an unfiltered `ps` grep
  showed no `git` process on the host. The heartbeat detector `stale-index-lock.py` run by
  hand (rc=0) also left it in place.
- **Cause (measured, not inferred):** a probe printed what `_live_git_pids(_gather_ps_snapshot())`
  matched: exactly one pid, `75589`, `cwd=<this repo>`, alive, not a zombie — and its ps line
  was `/bin/zsh -c source …snapshot-zsh… && eval '…'`: the shell running the probe itself,
  whose `-c` string contained `git -C "$R" add …` for the commit chained after the check.
  `_live_git_pids` (scripts/lib/git_utils.py, `def` at line 400) matches "basename of ANY
  argv token equal to `git`", by design to avoid substring hits — but a `sh -c` string is
  whitespace-split into argv tokens by `ps`, so the word `git` anywhere in the wrapped
  command matches. The shell's cwd is the repo, so `_live_git_holds` fails closed on it.
- **Why it matters:** every caller that reaches the guard through a wrapper whose command
  text mentions git — Claude Code's Bash tool, a CI `run:` step executed via `sh -c`, a
  Makefile recipe — is refused deterministically, not transiently. The production path
  (dispatch.py → detector) has no `git` in its own argv, so heartbeat fires may pass; a
  human or agent trying to recover by hand cannot. This is lesson [1] of
  `git-index-lock-orphan-recovery` in a fourth dress: liveness of a process that is not a
  git writer read as holding.
- **Fix shape (option, not decided):** match the EXECUTABLE token only — the first argv
  token after the `pid ppid etime` columns (basename `git`) — instead of any token; keep the
  exact-basename rule. Add a regression test whose snapshot line is
  `<pid> <ppid> 00:00 /bin/zsh -c git status` and asserts it is NOT matched, and one with
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
- [ ] From a shell whose command string contains `git`, with a 0-byte lock older than
      `min_age_s` and no holder, `clear_stale_index_lock` returns `removed`, not `live-git`.
- [ ] `git-index-lock-orphan-recovery` gains a dated lesson naming this fourth self-match
      form (via the memgrep verb, not by hand).

## Approval log

- 2026-09-08T22:46:17+0200 — Authored at `todo` by the janitor session, from a live
  refusal on this repo during the TWF7DXXR commit. Tier 0 (in-scope bugfix; PRRD S6.1).
