---
trdd-id: GZXTSJSR
title: Proactive all-accounts OAuth login nudge — prompt EARLY and via a real notification, capture every account before any expires
column: dev
created: 2026-07-23T18:11:48+0200
updated: 2026-09-03T10:05:00+0200
current-owner: janitor-main-session
task-type: feature
scope: project
implementation-commits: [cf9fb7a1]
relevant-rules: []
parent-trdd:
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

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
2. NOT DONE — `/janitor-capture-all-logins` does not exist yet (P3, out of this session's scope).
3. ✓ PROVEN — the nudge resolves `rotator.open_login_script()` per-host, no hard-coded stale
   path; the script exists at `scripts/oauth_rotator/open-login.sh`.
4. ✓ PROVEN (commit cf9fb7a1) — bucket-aware escalation signature re-notifies same-day on a
   worsening state — `tests/test_oauth_login_needed.py::test_escalation_sig_re_notifies_same_day_when_bucket_worsens`.
5. UNVERIFIED — whether the cardinal LATE+fail-open invariant applies to this standalone
   roster detector (vs. only to in-process `dispatch.py` phases) was not investigated this
   session.
6. ✓ PROVEN this session — `uv run ruff check scripts/detectors/oauth-login-needed.py
   tests/test_oauth_login_needed.py`: all checks passed. `uv run mypy scripts/
   --ignore-missing-imports`: Success, no issues found in 498 source files. `uv run pytest
   tests/test_oauth_login_needed.py -q -p no:randomly`: 31 passed. (Full-suite `pytest
   tests/` and the `~/.claude` untouched proof were not re-run this session — no code
   changed, prior gate results for those stand.)

## Approval log

- 2026-07-23T18:11:48+0200 — Authored as `planned`: the USER explicitly and forcefully requested
  this feature in direct response to a costly incident (a live scenario killed by a preventable
  rate-limit). Standalone project → the user is the approver. Implementation plan presented for
  the HOW before the multi-file build begins.
