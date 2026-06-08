---
name: janitor-auto-manage-oauth-on
description: Opts THIS machine into the janitor's unattended multi-account OAuth rotator. Sets an opt-in flag the always-on janitor daemon's 60s oauth-rotator-tick Task reads to rotate the live Claude Code credential to an alternate paid account before a rate-limit 429 stalls an overnight session. Default OFF, macOS only, idempotent; refuses if a pinning env var would defeat rotation. Trigger with /janitor-auto-manage-oauth-on, "turn on oauth rotation", or "enable account rotator".
---

# Janitor auto-manage OAuth on

## Overview

Activates the **OAuth account rotator** (TRDD-32acd15f) on this machine.
The rotator swaps the live Claude Code credential between two-or-more of
**your own paid** Max subscriptions so an unattended overnight session keeps
working past a single account's 5h/7-day rate-limit window, instead of sitting
idle in the rate-limit UI.

Turning it on is a single action: **set the opt-in flag.** The janitor's
always-on global **daemon** owns the rotation — its 60s `oauth-rotator-tick`
Task (TRDD-f892e109) runs the rotator's `tick --only-if-claude-running`:

- no-ops instantly unless the real Claude Code binary is running;
- when it is, backs up the live keychain credential to a 0600 slot and reads
  `/api/oauth/usage` (zero inference cost) to decide whether the LIVE account
  has crossed the switch threshold (**97%** of its tightest window) — if so it
  swaps in the *drain-first* alternate (the usable account closest to its own
  limit, so fresh accounts stay in reserve).

There is **no launchd agent** — the rotation rides the same always-on daemon
that already refreshes marketplaces and self-updates the janitor. That daemon
is lazy-spawned and kept alive by the heartbeat, so the rotator works whenever
the janitor heartbeat is armed (`/janitor-arm`) and a session fires it.

**Scope: machine-wide and global.** The opt-in flag lives under
`${CLAUDE_PLUGIN_DATA}/oauth-rotator/` (persistent, survives updates), NOT in a
per-project `.janitor/state/`. Rotation is a user/global-scope mutation (a
keychain swap), which is why the daemon owns it and this is a deliberate opt-in
command, not a default-on detector.

**ToS note (per TRDD Decision #3).** This rotates ONLY your own paid accounts
doing your own work; the keepalive itself is the standard OAuth refresh Claude
Code performs anyway. Rotating accounts to extend past a rate limit may still
conflict with Max usage terms — by running this you accept the account-flagging
risk. Nothing here touches any account that is not yours.

### Self-healing logins — log in once, the rotator manages the rest

Some accounts can't self-renew on their own: a `setup-token` has no refresh
token, or a refresh chain is revoked. The rotator closes that gap with two
heartbeat-driven pieces (TRDD-32acd15f P4c/P4d), so you only ever do the one
thing a machine can't: the human sign-in.

- **Ask-to-login** — the opt-in `oauth-login-needed` detector surfaces, on the
  janitor heartbeat, *exactly* the accounts that need a one-time human login —
  the ones that can neither self-renew (no refresh token) nor auto-bootstrap (no
  live claude.ai session). The nudge names
  `~/.claude/account-rotator/open-login.sh <email>` and is explicit that it
  opens a **dedicated Chrome window**: your default browser (e.g. Safari) stays
  untouched, and you do **not** need to make Chrome your default — Chrome only
  needs to be installed. Accounts that already self-renew are never nudged.
- **Auto-bootstrap** — once you've signed in (a live session now exists in that
  account's Chrome profile), the daemon's next `oauth-rotator-tick` runs
  `slot_capture_browser.py` (via `uv run --with playwright`) to mint a
  refresh-bearing slot from the seeded session, with **no further human action**.
  It runs **visible** (a real Chrome window appears briefly — Cloudflare blocks
  headless on the consent page; opt into headless with
  `CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS=1` only if your environment allows it) and
  **detached** so it never blocks or starves the keep-alive rotation. From then
  on the account self-renews like any other. If the capture keeps failing, a
  secondary `[oauth-capture-stalled]` nudge points you at the bootstrap log and
  an `open-login.sh` re-seed.

Maturity: both pieces are implemented and unit-tested; full unattended
end-to-end verification (a live headful capture clearing Cloudflare on the
consent page) is tracked as TRDD-32acd15f #142 — until that lands, treat the
auto-bootstrap as best-effort (a failed capture is logged and re-attempted next
tick, and the stalled nudge tells you when to step in).

## Prerequisites

- **macOS** — the credential swap uses the macOS `security` keychain CLI. On
  Linux/Windows this command aborts; the rotator core is portable but the
  keychain glue here is macOS-only.
- `${CLAUDE_PLUGIN_DATA}` resolves at invocation (Claude Code v2.1+).
- **The janitor heartbeat is armed** (`/janitor-arm`). The daemon that runs the
  rotation is kept alive by the heartbeat; without it the flag is set but
  nothing ticks. This command sets the flag regardless and just reminds you.
- **No pinning env var.** If `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or
  `CLAUDE_CODE_OAUTH_TOKEN` is set, the binary reads auth from the env (pinned
  at process start) and ignores the keychain — rotation would be silently
  defeated. This command REFUSES in that case rather than setting a no-op flag.

## Instructions

1. **Refuse on a pinning env var** (hard precondition):

   ```bash
   for v in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN; do
     if [ -n "${!v:-}" ]; then
       echo "Janitor auto-manage-oauth ABORTED: \$$v is set — it overrides the keychain and defeats rotation. Unset it first, then re-run." >&2
       exit 3
     fi
   done
   ```

2. **Refuse off macOS:**

   ```bash
   [ "$(uname -s)" = "Darwin" ] || { echo "Janitor auto-manage-oauth: macOS only (keychain swap). The rotator core is portable but the keychain glue here is not." >&2; exit 4; }
   ```

3. **Set the opt-in flag atomically** (the daemon's `oauth-rotator-tick` reads
   it every 60s):

   ```bash
   ROT_DATA="${CLAUDE_PLUGIN_DATA}/oauth-rotator"
   mkdir -p "$ROT_DATA"
   printf 'on' > "$ROT_DATA/opt-in.flag.tmp.$$" && mv -f "$ROT_DATA/opt-in.flag.tmp.$$" "$ROT_DATA/opt-in.flag"
   ```

4. **Report one line**, noting slot readiness:

   ```bash
   # Count known accounts from the KEYCHAIN via the rotator (known-emails), NOT the
   # plaintext slots/*.json the keychain migration deletes — those read 0 on every
   # migrated machine (audit C2 class).
   VER="$(ls -d "$HOME"/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/*/scripts/oauth_rotator/rotator.py 2>/dev/null | sort -V | tail -1 || true)"
   N=$( [ -n "$VER" ] && uv run "$VER" known-emails 2>/dev/null | grep -c . || echo 0 )
   echo "Janitor OAuth rotator: ON (daemon oauth-rotator-tick every 60s, threshold 97%, drain-first). Known accounts: ${N:-0}. ${N:-0} < 2 ⇒ capture a 2nd account before rotation can fire (run /refresh-claude-logins — it seeds via open-login.sh then auto-bootstraps a refresh-bearing slot). Ensure /janitor-arm has armed the heartbeat so the daemon stays alive. Disable with /janitor-auto-manage-oauth-off."
   ```

## Output

One line: ON, the 60s daemon-tick cadence, threshold, and how many account
slots exist (rotation needs ≥ 2). Only ONE file is written: the `opt-in.flag`
under `${CLAUDE_PLUGIN_DATA}/oauth-rotator/`. No launchd agent, no plist.

## Error Handling

- Pinning env var set → abort (exit 3) with which var; do NOT set the flag.
- Non-macOS → abort (exit 4); the keychain swap is macOS-only.
- `${CLAUDE_PLUGIN_DATA}` unset → abort "Claude Code v2.1+ required".
- Re-run while already on → idempotent: the flag is re-written; same one-line
  confirmation.

## Examples

```text
User: /janitor-auto-manage-oauth-on
User: turn on oauth rotation
User: enable the account rotator
User: keep my overnight session alive across both my accounts
```

## Scope

ONLY sets the opt-in flag. Does NOT capture accounts (that needs a human login —
see `/refresh-claude-logins`, which seeds via `open-login.sh` then auto-bootstraps
a refresh-bearing slot), does NOT arm the
heartbeat cron (that is `/janitor-arm`, which the daemon needs to stay alive),
and does NOT touch per-project state. To deactivate, run
`/janitor-auto-manage-oauth-off`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/oauth_rotator/rotator.py` — the rotator engine (`tick`/`auto`/`capture`/`usage`); the daemon's `oauth-rotator-tick` Task runs its `tick`. `tick` also runs the post-login auto-bootstrap (`_bootstrap_seeded_slots`).
- `${CLAUDE_PLUGIN_ROOT}/scripts/oauth_rotator/slot_capture_browser.py` — mints a refresh-bearing slot from a human-seeded Chrome session (the auto-bootstrap subprocess).
- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/oauth-login-needed.py` — the heartbeat detector that nudges you to run `open-login.sh` for accounts that need a one-time login (opens a dedicated Chrome window; default browser untouched).
- `~/.claude/account-rotator/open-login.sh <email>` — opens the dedicated Chrome for the one-time human sign-in (no default-browser change needed).
- `${CLAUDE_PLUGIN_ROOT}/scripts/daemon.py` — the always-on daemon that owns the 60s `oauth-rotator-tick`.
- `${CLAUDE_PLUGIN_DATA}/oauth-rotator/` — persistent state: `opt-in.flag`, `slots/`, `state.json`, `rotator.log`.
- `design/tasks/TRDD-20260528_131132+0200-32acd15f-account-rotator.md` — full design.
- `design/tasks/TRDD-20260531_091048+0200-f892e109-scanner-trust-and-rotator-fold.md` — the daemon-fold (removed the launchd agent).

## Checklist

Copy this checklist and track your progress:

- [ ] Refuse if a pinning env var (ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN/CLAUDE_CODE_OAUTH_TOKEN) is set
- [ ] Refuse off macOS
- [ ] Set the `opt-in.flag` atomically under `${CLAUDE_PLUGIN_DATA}/oauth-rotator/`
- [ ] Report one line with the captured-account count and the ≥2 reminder
