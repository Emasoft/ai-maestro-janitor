---
name: janitor-refresh-cc-logins
description: Re-stock the rotator with a long-lived OAuth key per account — the human REAUTHENTICATE step no automation can do (the claude.ai login needs an OS-level passkey / Google-2FA prompt, and the consent page sits behind a Cloudflare challenge). Walks the user through /login then `claude setup-token` per account, has them paste each key into the keys CSV, then imports the whole file with /janitor-import-oauth-tokens. The login and the mint are HUMAN steps (an OS-level passkey prompt and a Cloudflare challenge), so this skill PAUSES for the user and cannot complete unattended; do not select it in a cron or headless context. Use on an oauth-login-needed / oauth-cookie-reminder nudge, when a slot's refresh is dead, or when "had to rotate manually / accounts won't switch / cookie expired". Trigger with /janitor-refresh-cc-logins, "reauth my accounts". (Named cc-logins, not claude-logins — a skill name may not contain the reserved word "claude".)
---

# Janitor refresh-cc-logins

## Overview

The interactive multi-account credential re-stocker — the **REAUTHENTICATE** leg of the OAuth
rotator. **TWO** of its steps need a human, for two different reasons: the claude.ai login uses
a **passkey / Google-2FA** prompt that is **OS-level — outside any browser**, and the
`setup-token` consent page sits behind a **Cloudflare challenge** a driven browser does not
clear. The user logs in and mints; you orchestrate, then import. **Never enter credentials or
log in for the user — only open the browser and check results.**

**Filing is no longer a human step.** The user writes each key as one `email,token` line in
`~/.claude/oauth_keys/claude_code_oauth_long_lived_keys.csv`, and `/janitor-import-oauth-tokens`
imports the whole file in one unattended command. The old per-account paste is gone: it needed
a terminal, so in a tool call the hidden prompt never opened, stdin was empty, and the script
fell through to the macOS clipboard — one value for three accounts, silently filing the wrong
key.

So this skill still **pauses**, but only for the login and the mint. Once the CSV has the keys,
everything after it is mechanical.

What the rotator ends up holding is a **1-year, no-refresh** key per account. That is the whole
design: once the three keys are filed, the rotator's only remaining job is to rotate between
them, for about a year, with nothing to renew or re-capture in between.

This skill + its helper scripts live IN the plugin (TRDD-3T4DZWXA, completing the
TRDD-f892e109 fold — they were previously a user-scope `/refresh-claude-logins` command). The
rotator ENGINE and these helpers are now always the same plugin version. The architecture is
the `oauth-rotation-renew-reauth` PROJECT memory page (the ROTATE → RENEW → REAUTHENTICATE
3-layer model); this skill is layer 3.

Scripts (in the plugin, beside the rotator engine):

```bash
ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
#   $ROT/rotator.py            — the engine (read-only subcommands + the RENEW tick)
#   $ROT/open-login.sh <email> — open a clean REAL Chrome on the account's profile (blocks until Cmd+Q)
#   $ROT/check-login.sh <email>— verify the profile saved a LIVE session (exit 0 = saved)
#   $ROT/lifetime-status.sh    — cookie-vs-OAuth lifetime table + what's due
```

> Run every rotator invocation with `env -u CLAUDE_PLUGIN_DATA` so the engine resolves the
> JANITOR's data dir via its own guard (a foreign `CLAUDE_PLUGIN_DATA` from another plugin's
> context would otherwise mis-route the state — TRDD-7100178d / TRDD-5EUYV08H). Invoke the engine
> with `python3` (NOT `uv run`) — rotator.py is stdlib-only, so `uv run` would only sync the
> caller's cwd uv-project for no gain; the helper `.sh` drive it the same way (TRDD-3T4DZWXA).

## When to use

- An `oauth-login-needed` or `oauth-cookie-reminder` heartbeat nudge fired (a cookie is
  expiring, or an account needs a fresh human login).
- The user says "refresh my claude logins" / "reauth my accounts" / "I had to log in manually".
- ~Monthly proactive refresh, to stagger cookie-vs-OAuth lifetimes so they never coincide.

## Instructions

1. **Preflight.** Confirm the engine + 3 helpers exist and the rotator resolves a roster. If
   anything is missing, tell the user exactly what and stop.

   ```bash
   ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
   for f in rotator.py open-login.sh check-login.sh lifetime-status.sh; do
     [ -f "$ROT/$f" ] || { echo "missing: $ROT/$f"; exit 1; }
   done
   env -u CLAUDE_PLUGIN_DATA python3 "$ROT/rotator.py" known-emails   # the roster, one email/line
   ```

2. **Show current status first.** Surface `lifetime-status.sh`'s table so the user sees which
   accounts need a refresh and that OAuth is healthy enough to do it safely. (If it says all
   healthy and nothing is due, ask whether they still want to refresh everything anyway.)

   ```bash
   env -u CLAUDE_PLUGIN_DATA bash "$ROT/lifetime-status.sh"
   ```

3. **For EACH account that needs a refresh, in turn:**
   a. Tell the user, as your own message BEFORE launching:
      `▶ Account k/N — a Chrome window will open. Log in as <email>, tick "stay signed in",
       then QUIT Chrome with Cmd+Q (closing just the window is not enough).`
   b. `env -u CLAUDE_PLUGIN_DATA bash "$ROT/open-login.sh" <email>` with a generous Bash
      timeout (it blocks while the user logs in, returns when they Cmd+Q).
   c. `env -u CLAUDE_PLUGIN_DATA bash "$ROT/check-login.sh" <email>` and report ✓/✗. If ✗,
      offer to retry that account (back to 3a) before moving on.

4. **Mint a long-lived token per account — MANUAL, and tell the user so.** The reauth above
   only saved COOKIES; a usable credential still has to be minted, and minting is a HUMAN
   step. There is no automated path and you must not write one: the consent page is behind a
   Cloudflare challenge that a driven browser does not clear (owner ruling 2026-09-09 — no
   minting automation ships, and none is to be added). Give the user these steps verbatim, one
   account at a time:

   > **For each of your Pro/Max accounts, in turn:**
   > 1. Open Claude Code in a terminal.
   > 2. Run `/login`.
   > 3. Choose the subscription OAuth option.
   > 4. A browser window opens. Log in as the account you picked.
   > 5. If the browser was already signed in as somebody else, sign out and sign back in as
   >    the account you picked. Getting this wrong is the one mistake nothing downstream can
   >    detect.
   > 6. Click **Authenticate**. The page confirms you are authenticated.
   > 7. Go back to Claude Code and press Enter to confirm.
   > 8. Open a new terminal window (or exit Claude Code first).
   > 9. Run:
   >    ```bash
   >    claude setup-token
   >    ```
   > 10. The browser opens again. Click **Authenticate**.
   > 11. Back in the terminal, the command finishes and prints a **1-year** OAuth key. It
   >     prints ONCE — copy it now.
   > 12. Open `~/.claude/oauth_keys/claude_code_oauth_long_lived_keys.csv` and add or update
   >     one line: the account's email, a comma, then the key. No spaces, no quotes.
   > 13. Repeat from step 1 for the next account.

   `/login` is what decides which account `setup-token` mints for, so it is always
   login-then-mint, one account at a time. Do NOT echo a key back into the conversation, a
   log, or a command line — treat it exactly like a password.

   Step 5 of that procedure is the load-bearing one. An inference-scoped key returns 403 on
   every identity endpoint, so **nothing can verify that a key belongs to the email on its
   line** — the login-then-mint ordering is the only thing binding them. Mint while the wrong
   account is signed in and the rotator will believe it has N accounts while spending one
   subscription under two names.

5. **Import the whole file.** Invoke `/janitor-import-oauth-tokens`. It runs unattended — no
   prompt, no TTY, no browser — and that skill owns everything downstream: what each output
   line means, which failures need a re-mint, and how to report them. Follow it rather than
   duplicating its rules here, or the two copies drift and nothing cross-checks them.

5. **Finish.** The pause is at step 4, not 4b: until the user says they have written the keys
   into the CSV, an account missing from that file is indistinguishable from one they have not
   got to yet, so do not read it as a failure. Once they confirm, 4b runs and reports per
   account. Then run `lifetime-status.sh` once more to confirm. Success is every account
   holding
   a filed slot with ~1 year of runway — **do NOT check for a refresh-bearing token**: a
   `setup-token` slot has `refreshToken: None` by construction, so that check would report
   failure on a perfectly good run. Confirm instead with
   `env -u CLAUDE_PLUGIN_DATA python3 "$ROT/rotator.py" list` that each account has a slot and
   an expiry far out. Then tell the user plainly: nothing needs renewing until those keys
   expire; the daemon's remaining job is rotation alone. List any account whose slot stayed
   empty and what to retry.

## Notes

- Each account has its OWN Chrome profile (separate cookie jar) — you never log out, you just
  log into each account's profile once. Re-run only when a session nears expiry (the monitor /
  the `oauth-cookie-reminder` heartbeat tells you when).
- The opener is a clean, normal Chrome (no automation flags) so Cloudflare + Google-2FA treat
  it as a human browser; it never logs in itself. The passkey / 2FA prompt is OS-level — that
  is WHY the login needs a human and cannot be automated.
- A filed key is **inference-scoped**: measured 2026-09-09, it returns HTTP 403 on
  `/api/oauth/usage` and on every identity endpoint, while the SAME key is accepted by
  `/v1/messages`. So a 403 from those endpoints says nothing about the key's health — only a
  401 does. Do not read one as a dead credential.

## Scope

ONLY orchestrates the human claude.ai login refresh, the human `setup-token` mint, and the
import of the resulting keys file. Does NOT change rotator config, does NOT rotate to a
DIFFERENT account, does NOT enter credentials for the user, and does NOT automate the mint.
The import step may refresh the live credential in place for the account already live — same
account, new key — which is what lets a running session keep going. Rotate deliberately with
`/janitor-rotate-account-to`; toggle daemon-managed rotation with
`/janitor-auto-manage-oauth-on` / `-off`.

## Resources

- `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/` — the engine (`rotator.py`, `reauth.py`,
  `slot_capture_browser.py`, …) + the helpers (`open-login.sh`, `check-login.sh`,
  `lifetime-status.sh`).
- `/janitor-auto-manage-oauth-on` / `-off` — toggle daemon-managed rotation.
- The `oauth-rotation-renew-reauth` PROJECT memory page — the ROTATE → RENEW → REAUTHENTICATE
  architecture this skill's layer 3 belongs to.
