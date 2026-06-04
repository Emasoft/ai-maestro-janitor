---
name: janitor-auto-manage-oauth-off
description: Deactivates the janitor's unattended multi-account OAuth rotator on this machine. Clears the opt-in flag so the daemon's oauth-rotator-tick Task stops rotating — no more credential backups or account swaps. Also tears down any legacy launchd agent left by a pre-fold install. Leaves your captured account slots untouched (re-enable any time with /janitor-auto-manage-oauth-on). Idempotent. Trigger with /janitor-auto-manage-oauth-off, "turn off oauth rotation", "disable the account rotator", "stop rotating my accounts".
---

# Janitor auto-manage OAuth off

## Overview

Deactivates the OAuth account rotator (TRDD-32acd15f) on this machine by
clearing the opt-in flag under `${CLAUDE_PLUGIN_DATA}/oauth-rotator/`. The
janitor daemon's 60s `oauth-rotator-tick` Task gates on that flag, so once it is
gone the tick is a total no-op — no more credential backups, no rotation.

**The flag is the authoritative off switch.** Since TRDD-f892e109 there is no
launchd agent to unload — the daemon owns the tick. For machines that were
opted-in BEFORE the daemon-fold, this command also does a best-effort one-time
teardown of the legacy launchd agent (`launchctl bootout` + remove the old
plist), so an upgraded install is left fully clean.

**Your captured account slots are left untouched** — `slots/`, `state.json`,
and the live keychain credential are not modified. Re-enable any time with
`/janitor-auto-manage-oauth-on`; nothing needs re-capturing.

## Prerequisites

- `${CLAUDE_PLUGIN_DATA}` resolves at invocation (Claude Code v2.1+).

## Instructions

1. **Clear the opt-in flag** (the authoritative off switch — the daemon tick
   then no-ops):

   ```bash
   ROT_DATA="${CLAUDE_PLUGIN_DATA}/oauth-rotator"
   rm -f "$ROT_DATA/opt-in.flag"
   ```

2. **Best-effort legacy teardown** (one-time migration cleanup for installs
   that pre-date the daemon-fold; a no-op on a clean install and off macOS):

   ```bash
   if [ "$(uname -s)" = "Darwin" ]; then
     UID_N="$(id -u)"
     launchctl bootout "gui/$UID_N/com.emasoft.claude-account-rotator" 2>/dev/null || true
     rm -f "$HOME/Library/LaunchAgents/com.emasoft.claude-account-rotator.plist"
   fi
   ```

3. **Report one line:**

   ```bash
   echo "Janitor OAuth rotator: OFF (opt-in flag cleared; the daemon's oauth-rotator-tick now no-ops). Any legacy launchd agent was torn down. Your captured account slots are untouched. Re-enable with /janitor-auto-manage-oauth-on."
   ```

## Output

One line confirming OFF. Files removed: the `opt-in.flag` and (if a pre-fold
install left one) the legacy launch-agent plist under the user's per-user
agents directory. The slots and state.json are deliberately left in place so
re-enabling is instant.

## Error Handling

- Flag already absent → `rm -f` is a no-op (idempotent).
- No legacy agent / off macOS → step 2 is a best-effort no-op (`|| true`).
- `${CLAUDE_PLUGIN_DATA}` unset → abort "Claude Code v2.1+ required" before
  touching anything.
- Re-run while already off → idempotent; same one-line confirmation.

## Examples

```text
User: /janitor-auto-manage-oauth-off
User: turn off oauth rotation
User: disable the account rotator
User: stop rotating my accounts for now
```

## Scope

ONLY clears the opt-in flag and tears down any legacy launchd agent. Does NOT
delete captured account slots, does NOT touch the live keychain credential,
does NOT disarm the heartbeat cron (that is `/janitor-disarm`). To re-activate,
run `/janitor-auto-manage-oauth-on`.

## Resources

- `${CLAUDE_PLUGIN_DATA}/oauth-rotator/opt-in.flag` — the flag cleared here (the authoritative off switch).
- `${CLAUDE_PLUGIN_DATA}/oauth-rotator/slots/` — captured accounts (left intact).
- `${CLAUDE_PLUGIN_ROOT}/scripts/daemon.py` — the daemon whose `oauth-rotator-tick` Task gates on the flag.
- `design/tasks/TRDD-20260528_131132+0200-32acd15f-account-rotator.md` — full design.
- `design/tasks/TRDD-20260531_091048+0200-f892e109-scanner-trust-and-rotator-fold.md` — the daemon-fold (removed the launchd agent).

## Checklist

Copy this checklist and track your progress:

- [ ] Clear the `opt-in.flag` (authoritative off switch)
- [ ] Best-effort legacy launchd teardown (pre-fold installs, macOS only)
- [ ] Report one line (slots left untouched)
