---
trdd-id: HMLS5WE8
title: Self-injection was blind on iTerm and typed compact four times into one field
column: dev
created: 2026-09-05T12:07:40+0200
updated: 2026-09-05T12:30:00+0200
current-owner: main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
labels: [terminal-injection, compaction, continuity]
implementation-commits: []
---

# Self-injection was blind on iTerm and typed `/compact` four times into one field

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

**Owner report (verbatim, 2026-09-05 11:45):** *"you made a mess.. the compaction script of the
janitor injected 4 times the compact command, and the api gave error"* — the pane showed
`❯ /compact/compact/compact/compact` submitted as ONE prompt, which the model rejected with
`prompt is too long: 1002563 tokens > 1000000 maximum`. Then: *"clearly you didn't check the
terminal screen to verify that in the queue there was already another /compact. i told you to
make the script that gives commands smarter and aware of what there is on the screen terminal."*

**Root cause — read from source, not inferred:**
- The typer is `scripts/compact_trigger.py`. Its only `--hard` caller is
  `scripts/hooks/pre-tool-context-usage.py::_run_compact_trigger` (≥85% context), which re-fires
  once per `_AUTOCOMPACT_DEDUPE_S = 180` s while the session stays over the wall. **Per-fire
  attribution is NOT logged** — none of the three callers (that hook, `on-stop-proactive-compact`,
  `dispatch.py:1523`) records a fire — so "the hook fired all four during the 22-minute turn" is
  the only caller consistent with `--hard`, not a measurement.
- `terminal_trigger.send_self_command` returned `USE_ITERM_PATH` for `kind == "iterm"`
  (`_DELEGATE_KINDS = {"tmux"}`), so `compact_trigger.main` fell to its OWN `_build_osascript`
  — a blind `write text "/compact"` with no read-back. The owner's three ratified injection
  rules (`inject_until_sent`, 2026-08-02: empty field first, stop on any keystroke, re-read
  before Enter) exist in the same module and ARE iTerm-capable (`read_pane_text`,
  `build_type_only_steps`, `build_submit_steps`, `build_clear_field_steps` all have an iTerm
  branch) — but only `clear_trigger`'s chain, `model-fallback`, and `dispatch`'s idle-clear
  used them. The self-sender's tmux branch was blind too (`build_tmux_steps` + Enter); the tmux
  path the clear chain and the daemon use was already verified.
- `tests/test_idle_clear_injection.py` already said it: *"sibling trigger scripts' osascript
  branches become dead code worth deleting, which is a change someone should make deliberately
  rather than discover."*
- NOT established: why the first `/compact`'s Enter never submitted (candidates: the
  slash-command completion menu absorbing the first Enter; the TUI's API-retry state). The fix
  does not depend on which — it reads the field back and confirms the submit either way.

**Fix (phase 1, this card — `scripts/lib/terminal_trigger.py`, `tests/sandbox_guard.py`, tests):**
1. `_DELEGATE_KINDS = {"tmux", "iterm"}`; `self_terminal(env, kind)` builds the pane dict from
   `$TMUX_PANE` / `$ITERM_SESSION_ID` (id only when it matches the detected kind, or when
   detection is `unknown`); `send_self_command` fires `_fire_detached_verified` — a detached
   child (`--__send-verified`) that runs `send_verified` per command under a project-wide
   exclusive lock (`.janitor/state/self-send.lock`) with a same-command dedupe stamp
   (`self-send.stamps.json`, `_SELF_SEND_DEDUPE_S = 300`), the stamp read AFTER the lock.
   Returns `FIRED:iterm` / `FIRED:tmux`. `USE_ITERM_PATH` is no longer returned for iTerm.
   **Residual (pre-existing, closed by phase 2):** a kind detected as some OTHER terminal
   (vscode, apple-terminal) with an inherited `ITERM_SESSION_ID` still reaches the callers'
   blind osascript — the branches become unreachable only when the ancestry walk says iTerm or
   unknown, not "on any host with the id".
2. `inject_until_sent` rule-1 exception: a field that already shows EXACTLY our command is an
   earlier injection whose Enter never took → submit it, never retype (rule 2, the typing probe,
   still wins). **DEVIATION FROM THE LETTER OF RULE 1 ("inject only into an EMPTY field"), for
   the owner to ratify:** a human who typed exactly `/compact` themselves and paused ≥8 s gets
   it submitted for them. The field is verified to show exactly the command and nobody is
   typing, so the "never Enter into an unverified pane" lesson holds.
3. Post-submit confirm: read FIRST; only while the field still shows ONLY our command (and the
   user is not typing) settle, re-read, and press Enter again, at most
   `_SUBMIT_CONFIRM_ATTEMPTS = 2`. Never a retype.
4. One ceiling for the child (`_SELF_SEND_GIVEUP_S = 900`, overridable per payload): it caps
   the wait for the lock AND the field wait inside `send_verified`, and once it has passed the
   child REFUSES to type at all (a remaining budget of a fraction of a second would otherwise
   still land one whole injection 900 s late — the stale-`/compact` case). So a child deferring
   on a busy field cannot hold the lock for the injector's default hour and starve a DIFFERENT
   later command. **This is a second deviation** from the injector's own 3600 s default — a
   self-triggered slash command that could not land in 15 minutes is stale for every caller.
5. Test hermeticity: `_force`/`_force_kind` clear `ITERM_SESSION_ID`/`TMUX_PANE`. A spawn-level
   deny of the `--__send*`/`--__chain` children was tried and REVERTED: the trigger tests drive
   those children on purpose against `tmux`/`osascript` stubs written into tmp (the suite's
   "stub it on PATH" pattern), and the guard's default-deny of the REAL binaries inside the
   child is what actually protects the developer's pane.

**What the first test run did (claim softened after review):** three forced-kind tests fired a
real `--__send-verified` child each, because they inherited this session's real
`ITERM_SESSION_ID`. **Established:** no `self-send.lock`/stamps exist anywhere searched (the
repo's `.janitor/state`, every `pytest-of-*` tmp dir), no `verified send` line was logged, and
this session did not compact afterwards. **NOT established:** which mechanism stopped them —
the guard's default-deny of `osascript` inside the child, or something earlier. "Nothing was
typed" is supported by the absence of a compaction, not by a pane read.

**Untested claims (acceptance below marks them):** the `flock` serialisation under two real
concurrent children; `_run_verified_payload`'s `abort_unless_any`.

**Phase 2 (own commit, after phase 1 is green):** delete the now-dead blind osascript branches —
`compact_trigger._build_osascript/_fire/_UUID_RE`, `clear_trigger._build_osascript/_fire_phase`'s
iTerm tail, `reload_trigger`, `reload_skills_trigger`, `resume_trigger` equivalents — and the
tests that pin them (`test_compact_trigger.py::test_build_osascript_*`,
`test_idle_clear_injection.py::test_every_remaining_caller_handles_the_iterm_sentinel`);
`clear_trigger._this_terminal` → `terminal_trigger.self_terminal`; the four inline
`[0-9a-fA-F-]{8,64}` sites → `valid_iterm_session_id`.

**NEXT ACTION:** phase-1 tests + gates green → commit → review fork → wikimem lesson on
`claude-code-esc-input-semantics` (the blind-sender lesson) → phase 2.

## Acceptance

- [ ] On iTerm, `send_self_command("/compact", dry_run=True)` reports `DRY_RUN:iterm:<uuid>:…`,
      never `USE_ITERM_PATH`; a real fire launches ONE `--__send-verified` child.
- [ ] `inject_until_sent` with a field already showing `/compact` presses Enter once and types
      nothing; with `xx/compact` it clears and retypes (unchanged); with `hello` it defers.
- [ ] After a submit whose Enter did not take, the injector presses Enter again (bounded) and
      never types a second copy.
- [ ] Two verified children for the same command within 300 s: the second skips with a log line
      (unit-tested with a fake sender; the real `flock` under two concurrent children is NOT
      tested).
- [ ] `_run_verified_payload` honours `abort_unless_any` (NOT tested).
- [ ] A test that reaches a `--__send*` / `--__chain` spawn fails at the sandbox guard.
- [ ] `uv run ruff check`, `mypy`, `uvx --with pyright pyright` clean; the trigger test files pass.
- [ ] Phase 2 removes every dead osascript branch and its tests (separate commit).
- [ ] The two rule deviations (items 2 and 4 above) are ratified or reverted by the owner.

## Notes and lessons learned

- A sender that cannot read the screen cannot be made safe by timers or dedupe windows: the
  180 s hook dedupe was working exactly as written and still produced four copies, because the
  question "is my command already there?" can only be answered by looking.
