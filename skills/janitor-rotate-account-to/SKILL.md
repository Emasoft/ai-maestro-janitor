---
name: janitor-rotate-account-to
description: Rotate the live OAuth account in ONE call — an optional email argument switches to that account directly, or with no argument picks the best alternate by remaining 5h/7d/Fable headroom (typing /model opus first when every candidate's Fable window is spent). Trigger on "rotate account", "switch account", "Fable window is ending", "rate limit / out of headroom, move to another account".
---

# Janitor rotate-account-to

## Overview

The manual rotation path (recall a memory, list slots, read usage, find the switch verb,
run it) takes ~15 tool calls before the keychain write actually happens — the write itself
is one call. This skill IS that one call: it runs `rotate_to.py`, which reuses the
rotator's own slot reads, usage probe and switch primitive and adds only the target
ranking (owner directive, TRDD-S2RZHXU7).

## When to use

- An account/window is ending or already spent and the live credential needs to move.
- The user names a specific account to switch to.

## Instructions

Run the script with whatever argument you were given (may be empty), then **relay its
first stdout line verbatim** — that line IS the report (`ROTATED …`, `ALREADY_LIVE …`,
`UNKNOWN_ACCOUNT …`, `NO_TARGET …`). Never sleep, retry, or add your own commentary.

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/oauth_rotator/rotate_to.py" [<account_email>]
```

## Exit codes

- `0` — rotated (or already live on the requested account).
- `2` — the named email is not a known slot.
- `3` — no non-live slot has both a usable usage snapshot and account headroom.

## Scope

Writes the live OAuth keychain entry only when a target was actually found — a running
`claude` picks it up on its next turn, no restart required.
