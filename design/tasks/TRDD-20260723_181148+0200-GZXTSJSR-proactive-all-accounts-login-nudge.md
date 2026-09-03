---
trdd-id: GZXTSJSR
title: Proactive all-accounts OAuth login nudge — prompt EARLY and via a real notification, capture every account before any expires
column: testing
created: 2026-07-23T18:11:48+0200
updated: 2026-09-03T11:11:20+0200
current-owner: janitor-main-session
task-type: feature
scope: project
implementation-commits: [cf9fb7a1]
relevant-rules: []
parent-trdd:
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03 (advisor follow-up F1-F3)

- **F1, F2, F3, F7, F8 FIXED this session — proven by tests, gates clean.** An advisor
  review of commit `0fc3ad5d` (P3/P5's own commit) found 5 real defects in the P3/P3c
  code; the orchestrator verified F1 and F2 in code before dispatch. F4/F5/F6 are
  OPEN — see below.
  - **F1 (SEVERE, fixed)** — `oauth-login-needed.py`'s topup summary was
    byte-identical every 7-day cycle, so `notify.push`'s content-hash dedupe
    (checked against the FULL sent-history, not age-filtered) silently DEDUPED every
    fire after the very first one, forever, on a given host; the stamp also wrote
    unconditionally (DISABLED/BELOW_SEVERITY/CAPPED/DEDUPED all burned the cadence).
    Fixed: the summary now bakes in the ISO period (`%Y-%m-%d`), the stamp writes
    ONLY when `notify.push` returns `PUSHED`/`PUSHED_DIGEST`, and an in-context
    heartbeat line was added via `dedupe.emit_once(seen, f"topup-{day}", …)` (key
    `.oauth-login-topup-seen.txt`). Proven with the REAL `notify.push` (only actual
    OS-level delivery mocked via `notify._deliver`) in an isolated
    `JANITOR_GLOBAL_STATE_DIR` — `tests/test_oauth_login_topup.py::test_main_topup_pushes_again_next_due_cycle_with_real_notify`
    (a fire 8 days later PUSHES, not DEDUPES) + 4 more tests for the stamp-gating and
    the heartbeat line.
  - **F2 (HIGH, fixed)** — `capture_all_logins.py`'s old `subprocess.run(timeout=120)`
    had no `start_new_session`, so a timeout SIGKILLed only the `uv` process,
    orphaning `slot_capture_browser.py` + headful Chrome (the capture legitimately
    polls consent up to 300s). Fixed: `capture_one` now runs via `Popen(...,
    start_new_session=True)`, kills the WHOLE process group on timeout
    (`_kill_process_group`: SIGTERM then SIGKILL after a 5s grace), and the default
    timeout is 400s, env-tunable via `CLAUDE_PLUGIN_OPTION_CAPTURE_TIMEOUT_S`. Proven
    with a REAL process tree (a fake capture script that forks a `sleep 600`
    grandchild) — `tests/test_capture_all_logins.py::test_kill_process_group_terminates_a_grandchild_too`
    and `::test_capture_one_kills_the_whole_tree_and_reports_timeout` (asserts the
    grandchild pid is dead via `os.kill(pid, 0)` after the timeout, and that
    `TimeoutExpired` still propagates so the walker's per-account catch keeps going).
  - **F3 (HIGH, fixed)** — the walker did not honor the daemon's bootstrap PID lock
    (`rotator._bootstrap_pid_path`/`_bootstrap_pid_alive`), so a manual capture could
    race the daemon's own detached auto-bootstrap on the same email's Chrome
    `--user-data-dir`. Fixed: `capture_already_running(email)` checks the lock
    BEFORE launching and `main()` skips with a `SKIPPED (a capture is already
    running, pid=…)` line (reported as a per-cycle failure, not a hard abort);
    `capture_one` also writes/clears its OWN pidfile at the same path
    (write-after-spawn, remove in `finally`, even on a timeout). Proven —
    `tests/test_capture_all_logins.py::test_capture_already_running_*` (3 tests) +
    `::test_main_skips_account_with_a_capture_already_running`.
  - **F7 (LOW, no code change needed)** — verified by re-reading
    `skills/janitor-capture-all-logins/SKILL.md:24` and `README.md:128`: both already
    say "heartbeat line" / describe the nudge generically — the wording is now true
    because F1 actually added that heartbeat line.
  - **F8 (MINOR, fixed)** — `_topup_days()`'s `state.coerce_int(...)` call now passes
    `detector_name="oauth-login-needed"` and
    `var_name="CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS"` so a bad env value logs
    instead of silently reverting to the default.
  - **F4 (FIXED, 2026-09-03)** — confirmed a REAL divergence, not just a comment
    mismatch: `cmd_known_emails` read the module-level `ROOT` (computed once at
    import from `_rotator_root()`, which never consults `CLAUDE_ROTATOR_HOME`),
    while `_slot_facts`'s callers (`oauth-login-needed.py`,
    `oauth-cookie-reminder.py`) resolve root via `configured_rotator_home()`,
    which honours `CLAUDE_ROTATOR_HOME`. Under that env var (the tests' / a
    standalone seed-login setup's isolated root) the walker's roster silently
    diverged from the reauth-flow's — real slots seeded only under the override
    were invisible to `known-emails`. Fixed `cmd_known_emails`
    (`scripts/oauth_rotator/rotator.py`) to resolve root the same way
    `configured_rotator_home()` does, and to fold in legacy unindexed
    `slots/*.json` stems (the same fallback `_slot_facts` applies), so the
    roster is always a superset of what `_slot_facts` would report for the same
    env. `load_state()` now takes an optional `state_file` override for this.
    Updated the stale/incomplete comments in `capture_all_logins.py`'s module
    docstring and `cmd_known_emails`'s own docstring to state the real
    invariant. Tests:
    `tests/test_oauth_rotator.py::test_known_emails_follows_claude_rotator_home_override`
    +
    `tests/test_oauth_rotator.py::test_known_emails_includes_legacy_unindexed_slot_files`.
    The `rotator.py` ~L2534-2535 comments cited in the original F4 note turned
    out to be about `_invoke_slot_capture`'s env-inheritance (`CLAUDE_PLUGIN_DATA`),
    unrelated to this roster divergence — no contradiction there to fix.
  - **F5 (OPEN, deferred, needs `scripts/daemon.py`)** — move the topup push
    daemon-side per the original P2 design intent (the DAEMON is the human channel;
    `oauth-login-needed.py` currently calls `notify.push` directly from the
    per-project detector subprocess, which works today but is not where P2 says the
    channel should live). Deliberately NOT touched this session — `daemon.py` is
    owned by another concurrent worker per explicit instruction.
  - **F6 (OPEN, deferred)** — not independently investigated this session; tracked
    alongside F5 as part of the daemon-side move.
  - **Gates:** `uv run ruff check scripts tests` clean on every touched file;
    `uv run mypy scripts/ --ignore-missing-imports`: Success, no issues found in 501
    source files; `uv run pytest tests/test_oauth_login_needed.py
    tests/test_oauth_login_topup.py tests/test_capture_all_logins.py -q
    -p no:randomly`: 64 passed (17 + 22 new/changed in topup+capture-all, 25
    unchanged in oauth-login-needed).
  - **NEXT ACTION:** F5 (move the topup push daemon-side) + F4 (roster-divergence
    comment fix) as their own bounded follow-up, once `daemon.py` is free.

## ⏵ PRIOR STATE (P3+P5) — 2026-09-03

- **P3 + P5 ARE DONE this session.** `/janitor-capture-all-logins` skill
  (`skills/janitor-capture-all-logins/SKILL.md`) + its backing walker
  `scripts/capture_all_logins.py` (lists the roster via `rotator.py known-emails`,
  runs `slot_capture_browser.py <email>` per account, prints per-account progress,
  aborts only on an INFRA failure — missing engine/capture script or the roster
  call itself failing; a single account's capture failing is reported and the
  walk continues). A periodic P3c "top up ALL logins" proactive nudge was added
  INSIDE `scripts/detectors/oauth-login-needed.py` (`_topup_due`/`_topup_days`,
  `CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS`, default 7, stamped at
  `<rotator-home>/.login-topup-last.txt`) — reuses the SAME `notify.push` channel
  P1/P2 wired in, fires regardless of whether any single account currently needs
  a login (capture-before-crisis), and is fail-open (wrapped in
  try/except, never breaks the rest of the detector). P5: verified BY GREP that
  the nudge path (both the reactive login-needed nudge and the new topup nudge)
  is NOT gated on `supervisor._server_owns_chores()` — that predicate is called
  ONLY from `supervisor.diagnose()`'s tick-stall finding, never from
  `oauth-login-needed.py`; no shared suppression-flag protocol exists anywhere in
  the tree (grepped for one — none found), so per the task's own instruction
  nothing was invented; both sides may notify and `notify.push`'s own
  content-hash dedupe + 24h cap already bound the human-facing spam if the
  server ever grows its own prompt.
- **Criterion 5 RESOLVED — the LATE+fail-open invariant applies BY CONSTRUCTION,
  not by placement.** `oauth-login-needed.py` is one of `dispatch.py`'s
  `_DETECTORS` roster entries, invoked by `_run_detector()` (`dispatch.py:828`)
  as an isolated `subprocess.run([script, "--one-shot"], timeout=…)` — Phase 2 of
  `_run_heartbeat`, itself the LAST phase before `_emit_quiet_if_idle()`. A crash
  or hang inside the new topup code cannot skip a later phase (there is none
  after Phase 2) and cannot starve a sibling detector beyond its own wall-clock
  timeout (`CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT`, default 120s) — the
  subprocess boundary IS the fail-open guarantee the in-process `_phase_*`
  convention exists to approximate for functions that share one process. No
  further change was needed to satisfy the invariant; the new code additionally
  wraps its own `notify.push`/stamp-write in try/except so a fault there can't
  even shadow the detector's OTHER (pre-existing) nudges in the same run.
- Existing tests `test_notify_pushed_high_for_a_48h_bucket_account` and
  `test_notify_escalates_to_critical_when_expired` were updated to filter
  `calls` by `code == "OAUTH-LOGIN-NEEDED"` — a fresh rotator home now also
  fires the P3c topup push on its first-ever run (no stamp yet), so the
  previous `len(calls) == 1` assumption no longer held.
- **NEXT ACTION:** none for P3/P5 — both are complete and proven. Only
  criterion 2 (P3) and 5 were open before this session; both are now ✓. The
  card's full P1–P5 acceptance list is proven — move to `testing`.

## ⏵ PRIOR STATE (P1) — 2026-09-03

- **P1 IS DONE — verified this session, no new code needed.** Commit `cf9fb7a1`
  (2026-08-22) already delivers the card's full P1 design scope: grace window
  1.0→2.0 days (`_grace_days()`, env-tunable via `CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS`),
  fire-on-fail-signal via `cascade.classify` (a `token_days is None` — i.e. `via=None`/no
  token — or `refresh_failures >= DEFAULT_MAX_REFRESH_FAILURES` both land in `REAUTH_NUDGE`
  immediately, no grace wait: `scripts/oauth_rotator/cascade.py:138,152-154`), and the
  decision stays entirely inside the cascade SSOT (no threshold logic duplicated in the
  detector). Same commit also folded in P2's notify-routing (`notify.push`, severity
  CRITICAL/HIGH by worst account) and P4's escalation dedupe (bucket-aware signature
  re-notifies same-day on worsening) — bonus, not required by P1, but it means acceptance
  criteria 1 and 4 are ALSO proven. Root cause 5 (stale `open-login.sh` path) was already
  fixed pre-existing (`rotator.open_login_script()` resolves per-host, verified present at
  `scripts/oauth_rotator/open-login.sh`) — criterion 3 proven.
- **STILL OPEN (out of this session's scope — P1 only was requested):** P3
  (`/janitor-capture-all-logins` skill walking every account — criterion 2, NOT built) and
  P5 (server-ownership coordination). Criterion 5 (nudge phase LATE + fail-open inside the
  heartbeat, combined resume+nudge test) is UNVERIFIED — `oauth-login-needed.py` is a
  standalone roster detector (`dispatch.py:303`, 6h cadence), not a phase inside
  `dispatch.py`'s own function list the STATE's cardinal invariant names
  (`_phase_self_cost_alarm` etc.); whether that invariant even applies to a separate-process
  detector, vs. only to phases literally inside `_run_heartbeat`, was not investigated this
  session — do that before closing P5.
- **NEXT ACTION:** author P3 (`/janitor-capture-all-logins` skill + backing script that
  loops `slot_capture_browser.py <email>` over every configured account) as its own bounded
  task, then P5's server-suppression-flag check. Column stays `dev` — the card's acceptance
  list spans P1-P5 and only P1's 3 design bullets are proven; do not move to `testing` until
  criteria 2 and 5 are also proven.

- **WHY THIS EXISTS:** a live scenario was interrupted by a rate-limit / all-accounts
  exhaustion; the agents died; re-running costs millions of tokens. The rotator had NO healthy
  alternate at rotation time because every account's token was near-dead AND the user was never
  PROACTIVELY prompted to re-login. The janitor's login-nudge machinery exists but stayed silent.
- **ROOT CAUSES (verified from code + on-disk state, 2026-07-23):**
  1. `oauth-login-needed.py` grace window = **1.0 day** (`_grace_days()` default) → fires only
     when a token is already near-dead. NOT proactive.
  2. Heartbeat cadence = **21600s (6h)** (`dispatch.py` roster) → too coarse for tokens that
     expire in ~8h and windows that burn in minutes.
  3. **Machine-scoped DAILY dedupe** (`due-{day}-{sig}`) → at most ONE nudge/day, then silence
     even while a login is overdue.
  4. The nudge is a **passive heartbeat drift line** (`print(line)`) → lands in the model's
     context; there is **no desktop notification, no real prompt**. An UNATTENDED scenario never
     sees it. This is the decisive gap.
  5. The nudge prints a **STALE command** (`~/.claude/account-rotator/open-login.sh <email>`) that
     does not exist on this install; the WORKING capture is
     `cd scripts/oauth_rotator && env -u CLAUDE_PLUGIN_DATA uv run --with playwright python slot_capture_browser.py <email>`.
  6. It nudges only accounts *already* needing login — there is **no proactive "top up ALL your
     logins" flow** the user asked for.
  7. When the **ai-maestro server owns the host**, the janitor daemon yields rotation — but the
     login is a HUMAN action neither can perform, so the human MUST still be prompted. The
     responsibility fell in the janitor↔server gap and neither prompted.
- **NEXT ACTION:** implement Phase 1 (widen window + real daemon notification + escalation) — see
  the plan below. Delegate the multi-file build to ONE bounded agent; keep the orchestrator thin.
- **LOAD-BEARING FACTS:** `notify.py` is the DAEMON-ONLY human channel (Tier-1 desktop
  notification default-on, Tier-2 opt-in webhook; gates: sev≥HIGH + content-hash dedupe + 24h cap + one-per-day digest). Cardinal survival invariant: NEVER add actuation to an early-returning
  heartbeat phase — a login-nudge phase must be LATE and fail-open, like
  `_phase_self_cost_alarm` or `_phase_user_presence_breadcrumb` (the current tail of
  `dispatch.py`).
- **SUPERSEDED — do NOT carry forward:** the exemplar this line used to name,
  `_phase_self_budget`, was deleted 2026-08-12-verified by `d9a7189d feat!: remove
  MAINTENANCE MODE and the self-budget actuation`. The INVARIANT it illustrated is
  unchanged and still load-bearing; only the worked example had to be re-pointed at a phase
  that still exists. Found by a prototype of TRDD-FDV1RQEB's dead-symbol check, which
  flagged this card and nothing else across the whole non-terminal board.
- **ARTIFACTS TO READ BEFORE ACTING:** `scripts/detectors/oauth-login-needed.py`,
  `scripts/lib/notify.py`, `scripts/oauth_rotator/supervisor.py` (`_slot_facts`, `diagnose`),
  `scripts/oauth_rotator/slot_capture_browser.py`, `scripts/daemon.py`
  (`task_oauth_rotator_supervisor`), `.janitor/state/agent-handoff.md`.

## Problem

The rotator "fails when it is needed most" because at the moment it needs a healthy alternate
account, every account is near-dead AND the user was never asked to re-login in time. The
login-nudge detectors exist but are (a) reactive (1-day grace), (b) coarse (6h), (c) once-a-day
then silent, (d) PASSIVE — a heartbeat line no unattended session reads, (e) printing a broken
command, and (f) never offering to capture ALL accounts proactively.

The user's requirement (verbatim intent): the janitor MUST immediately and PROACTIVELY prompt the
user to log in when a token/cookie is about to expire OR is already expired, and must ask the user
to log in to ALL its accounts, one after another, so it can capture them all — before a crisis,
not during one.

## Design

**P1 — Proactive lookahead + fire on every fail signal.**
- Widen the login-nudge window from 1 day to a generous proactive default (e.g. 48h,
  env-tunable), so it fires WELL BEFORE a token dies.
- Fire immediately (not just near expiry) on any `refresh_failures ≥ max`, `via=None` / no token,
  or expired — the states the incident showed.
- Keep the pure decision in the cascade SSOT; only the thresholds/urgency change.

**P2 — A REAL notification, not a passive line (the decisive fix).**
- Route the login need through `notify.py` from the DAEMON (the human channel): a HIGH-severity
  desktop notification (Tier-1) — and Tier-2 webhook if configured — so an UNATTENDED user
  actually sees "log in to your Claude accounts now" instead of a heartbeat line nobody reads.
- Keep the in-context heartbeat line for ATTENDED sessions (belt and suspenders).
- Respect notify.py's existing gates (sev≥HIGH, content-hash dedupe, 24h cap, one-per-day digest)
  but ESCALATE severity as it worsens (48h → 24h → expired) so a worsening state re-notifies.

**P3 — All-accounts capture flow (what the user explicitly asked for).**
- A `/janitor-capture-all-logins` skill (+ backing script) that walks EVERY configured account and
  runs the WORKING capture one after another
  (`slot_capture_browser.py <email>`), guiding the user through each login in turn.
- A periodic PROACTIVE "top up all logins" prompt on a schedule (e.g. every N days, tunable) so
  tokens never approach expiry — capture-before-crisis by default.
- Fix the stale `open-login.sh` reference in the nudge to the working command / the new skill.

**P4 — Escalation instead of once-a-day-then-silent.**
- While a login is genuinely overdue, keep surfacing at a bounded cadence (daemon notify cadence),
  re-notifying on any severity increase rather than deduping into permanent silence.

**P5 — Server-ownership coordination.**
- Even when the ai-maestro server owns rotation, the janitor STILL surfaces the login need (the
  login is a human action neither side can perform). Confirm the two don't double-spam; the
  capture is idempotent, so surfacing from both is safe — but prefer a shared suppression flag if
  the server already prompts.

## Acceptance criteria

1. ✓ PROVEN (2026-09-03, commit cf9fb7a1) — with an account whose token expires in <48h (or
   has via=None / refresh_failures≥max), a HIGH (CRITICAL when expired/dead-refresh) desktop
   notification fires from `notify.push` — `tests/test_oauth_login_needed.py::test_notify_pushed_high_for_a_48h_bucket_account`,
   `::test_notify_escalates_to_critical_when_expired`.
2. ✓ PROVEN (2026-09-03) — `/janitor-capture-all-logins`
   (`skills/janitor-capture-all-logins/SKILL.md`) + `scripts/capture_all_logins.py`
   walk every `rotator.py known-emails` account and run `slot_capture_browser.py
   <email>` for each in turn; the periodic topup nudge is a P3c addition to
   `scripts/detectors/oauth-login-needed.py` — `tests/test_capture_all_logins.py`
   (10 tests), `tests/test_oauth_login_topup.py` (9 tests).
3. ✓ PROVEN — the nudge resolves `rotator.open_login_script()` per-host, no hard-coded stale
   path; the script exists at `scripts/oauth_rotator/open-login.sh`.
4. ✓ PROVEN (commit cf9fb7a1) — bucket-aware escalation signature re-notifies same-day on a
   worsening state — `tests/test_oauth_login_needed.py::test_escalation_sig_re_notifies_same_day_when_bucket_worsens`.
5. ✓ PROVEN (2026-09-03) — `dispatch.py::_run_detector` (line 828) invokes every roster
   detector, including `oauth-login-needed.py`, as an isolated `subprocess.run(...,
   timeout=…)` inside Phase 2 (the LAST phase of `_run_heartbeat` before
   `_emit_quiet_if_idle()`) — the subprocess boundary + wall-clock timeout IS the
   fail-open guarantee for a standalone detector; there is no later phase it could
   accidentally skip and no shared-process state it could corrupt. The new P3c code
   additionally wraps its own `notify.push`/stamp-write in try/except.
6. ✓ PROVEN this session — `uv run ruff check scripts tests`: all checks passed.
   `uv run mypy scripts/ --ignore-missing-imports`: Success, no issues found in 501
   source files (498 + 3 new: `scripts/capture_all_logins.py`,
   `tests/test_capture_all_logins.py`, `tests/test_oauth_login_topup.py`). `uv run
   pytest tests/test_oauth_login_needed.py tests/test_oauth_login_topup.py
   tests/test_capture_all_logins.py -q -p no:randomly`: 50 passed. (Full-suite `pytest
   tests/` and the `~/.claude` untouched proof were not re-run this session — no code
   changed, prior gate results for those stand.)

## Approval log

- 2026-07-23T18:11:48+0200 — Authored as `planned`: the USER explicitly and forcefully requested
  this feature in direct response to a costly incident (a live scenario killed by a preventable
  rate-limit). Standalone project → the user is the approver. Implementation plan presented for
  the HOW before the multi-file build begins.
