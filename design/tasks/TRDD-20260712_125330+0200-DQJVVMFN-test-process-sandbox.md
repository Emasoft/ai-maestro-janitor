---
trdd-id: DQJVVMFN
title: Make the test suite structurally incapable of touching real machine state
column: complete
created: 2026-07-12T12:53:30+0200
updated: 2026-07-12T13:05:00+0200
current-owner: ai-maestro-janitor
task-type: infra
scope: project
release-via: publish
relevant-rules: [1]
implementation-commits: [dc102a0, 84fe8da, fd0b482, 12633c8, 2863a51]
last-test-result: pass
---

# Make the test suite structurally incapable of touching real machine state

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-12

**DONE. Shipped on `main`, unpushed.** Full suite: **12657 passed, 1 skipped**, ruff clean.

- `tests/sandbox_guard.py` — the process/signal guard (S1h). ALLOW-LIST, deny by default.
- `tests/conftest.py` — the `real_subprocess` marker + the non-file witnesses (S1i).
- `tests/test_sandbox_guard_process.py` — 35 tests, falsified.

**NEXT ACTION:** nothing here. This TRDD is complete. (Publishing v0.42.0, which carries
this, is NON-EXEMPT and awaits the user.)

**SUPERSEDED — do NOT carry forward:** an early claim that the suite's 31 `gh` POST/DELETE
calls and its 18 `claude plugin update` calls were real escapes "saved only by the fake repo
slug `o/r`". **FALSE.** Those tests already stub `gh` and `claude` into a tmp `bin/` and
prepend it to PATH. The denial log (below) is the authority on what actually escaped.

## The demand

> *"your test suite last time almost erased/overwrote the whole project. now it corrupted the
> oauth token. what else is going to happen next time we run the tests? please fix the tests."*

The OAuth accusation was **wrong** — see `[[debugging-methodology]]#debug-a-timestamp-says-when-never-who`
and TRDD-RYZCVVKA. But the underlying complaint was **right**, and it is what this TRDD acts on.

## The hole

The suite had five isolation layers and every one of them compared **file content**. Yet every
genuinely dangerous janitor capability is a **subprocess** or a **signal**, and was therefore
invisible to all of them:

| capability | mechanism | previously guarded by |
|---|---|---|
| kill a real process | `os.kill` — `memory_guard.select_victim()` reads the REAL `ps` table, so it returns a REAL pid | each test remembering to monkeypatch the killer |
| type into a real terminal | `osascript` / `tmux send-keys` | nothing |
| write the real keychain | `security add/delete-generic-password` | *convention* — remember `keychain_scope_args()` |
| register a real OS service | `launchctl` | nothing |
| mutate the real plugin tree | `claude plugin update` | nothing |
| mutate a real repo / GitHub | `git push`, `gh api --method POST` | nothing |

Guarded-by-convention is exactly the design that is always one incident behind.

## The design: an ALLOW-LIST, built from a measured audit

A block-list can only forbid the binaries someone already thought of; the failure mode is the
binary **nobody** thought of. So: anything not on the table is DENIED, and the denial names the
fix (stub it on PATH, or `@pytest.mark.real_subprocess`).

The table was built from a **Phase-0 audit** of the real suite (2631 spawns, 68 binaries), not
from a guess. Measuring paid for itself immediately — four findings no guess would have produced:

1. **Identity must come from what was INVOKED, never from the realpath.** Following symlinks
   RENAMES a binary: Homebrew's coreutils makes `echo` resolve to `…/bin/gecho`, which turned
   three allow-listed tools into unknown binaries. Containment still uses the realpath, so a tmp
   symlink pointing at the real `gh` cannot pose as a test's own stub.
2. **Classification must use the spawn's EFFECTIVE cwd** (Popen's `cwd=` kwarg). pytest's cwd IS
   this repo, so reading `os.getcwd()` reported all ~400 tmp-repo `git commit`/`git init` calls
   as mutating the real repo — and would have missed a real one that passed `cwd=` explicitly.
3. **Prefix launchers must be unwrapped** or they are a one-token bypass: the daemon really does
   spawn `taskpolicy -b claude plugin marketplace update`.
4. **Signal permission must follow ANCESTRY**, not the pid Popen returned. The process a test
   means to kill is routinely its GRANDCHILD — the daemon is launched through `uv`, and
   multiprocessing's workers come from `fork_exec`, which never passes through Popen at all.

**A denied child Python was the wrong answer.** The first cut denied a child whose explicit
`env=` dropped the sandbox. That broke 47 legitimate tests whose curated env IS their isolation,
and "protected" them by refusing to run rather than by making them safe. `_harden_child_env`
injects the two sandbox vars instead — those 47 children are now **sandboxed** rather than merely
permitted. Strictly better, and free.

## What actually escaped (the denial log — evidence, not assumption)

A green suite does not prove the guard fired: `state.run_subprocess` swallows every exception by
design, so a `SandboxViolation` inside it vanishes and the test still passes. Hence the denial
log. It caught exactly **9 spawns**, all real:

| binary | n | what it was doing |
|---|---|---|
| `gh` | 4 | real network reads of the GitHub releases API |
| `tmux` + `osascript` | 2 | the **REAL fleet scan** — enumerating the user's live iTerm sessions and tmux panes |
| `aimaestro-agent.sh` | 1 | the real ai-maestro CLI |
| `lean-ctx` | 2 | `lean-ctx allow …` **MUTATING the user's real lean-ctx config**, on every run |

None of the nine is what its test asserts — they are incidental side effects of running real
code — so the suite is green with them blocked and **no test became vacuous**.

## S1i — the two states that are not files

Every prior guard compared file content, so the keychain and launchd were invisible. Now
witnessed at session start/finish:

- **launchd → FAILS the suite.** Nothing but a test registers/tears down a janitor OS service.
- **the credential → REPORTED, never fails.** Claude Code rewrites that item on every ordinary
  token refresh, so failing would cry wolf on most runs — and conftest already says why that is
  fatal ("a guard that cries wolf is a guard people learn to ignore"). Since S1h makes a
  test-caused change structurally impossible, this is EVIDENCE, not an alarm: the evidence whose
  absence cost a day. Reads **attributes only, never `-w`** (the `-w` secret read is what raises
  the ACL prompt flood).

Verified on a full run: the real credential's `mdat` was **unchanged end to end**.

## Falsification

Per `[[feedback-falsify-each-layer-separately]]`: the process patches were disabled and the
suite re-run — exactly the 5 enforcement tests FAILED (install self-test, three live spawn
denials, the foreign-pid signal denial), while the pure `classify_argv` policy tests kept
passing, which is correct: those test the decision, not the installation.

Negative tests are written to be **harmless if the guard breaks** (`launchctl list`,
`gh --version`, SIGTERM to pid 1, which a non-root process cannot deliver). A test that proves
"we never touch the machine" must not become the thing that touches the machine the day it
regresses. **No env-var kill switch ships** — an env var that turns the guard off is a hole in
the guard.

## Known limits (honest)

- **A shell is the one child the sandbox cannot follow into.** `sitecustomize` reaches every
  child *Python*, but a shell's own children (the `launchctl` inside `keepalive_install.sh`) are
  invisible. Shells are therefore denied unless `-n` (parse-only) or tmp-resident;
  `test_launchd_keepalive` carries an explicit `real_subprocess("bash")` marker, and its safety
  comes from `KEEPALIVE_SKIP_ACTIVATION=1`, not from the sandbox.
- **`secret-tool` on Linux.** It is absent on macOS, so it resolves to nothing and is allowed
  through (a non-existent binary cannot touch anything). On a Linux box with libsecret installed
  it would resolve and be DENIED — correctly, since two of the audited calls look up the REAL
  `Claude Code-credentials` service. Those tests would then need a PATH stub. Not a regression;
  a latent finding this guard now surfaces instead of hiding.
