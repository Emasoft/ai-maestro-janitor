---
name: janitor-import-oauth-tokens
description: Import the owner's long-lived Claude Code OAuth keys from ~/.claude/oauth_keys/claude_code_oauth_long_lived_keys.csv into the rotator's encrypted slots, and adopt the new key for the account that is live right now (no session restart). Runs unattended — no TTY, no prompt, no browser. Use after the user has minted keys with /login then `claude setup-token` and pasted them into that file, or whenever they say "import my oauth tokens", "I added a new token", "load the keys csv", "the rotator does not know my new key". Trigger with /janitor-import-oauth-tokens.
---

# Janitor import-oauth-tokens

## Overview

Reads ONE file — `~/.claude/oauth_keys/claude_code_oauth_long_lived_keys.csv`, one
`email,token` line per account — validates each key, files it into that account's encrypted
rotator slot, and swaps the live credential when the currently-live account's own key
changed. A running `claude` re-reads the keychain on its next turn, so nothing has to close.

**This is the whole import path, and it needs no human.** It replaces the old per-account
paste-at-a-prompt step, which an agent structurally could not run: a tool call has no
terminal, so the hidden prompt never opened, stdin was empty, and the script fell through to
reading the macOS clipboard — one value for three accounts, silently filing the wrong key.

The human part is upstream and is the sibling skill's job
(`/janitor-refresh-cc-logins`): mint one key per account, write it into the file. Once the
file exists, everything from here is mechanical.

## When to use

- The user added or replaced a line in the keys file and wants the rotator to know.
- After `/janitor-refresh-cc-logins` walked them through minting.
- The rotator reports a slot missing or expired for an account the user has a key for.
- The user says "import my oauth tokens" / "load the csv" / "I generated a new token".

## Instructions

1. **Run it.** One command, no arguments, no prompts:

   ```bash
   env -u CLAUDE_PLUGIN_DATA python3 \
     "$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/import_oauth_tokens.py"
   ```

   Add `--csv <path>` only if the user keeps the file somewhere else.

   > `env -u CLAUDE_PLUGIN_DATA` is required: a foreign `CLAUDE_PLUGIN_DATA` inherited from
   > another plugin's context would mis-route the rotator's state (TRDD-7100178d /
   > TRDD-5EUYV08H). Invoke with `python3`, not `uv run` — the rotator is stdlib-only, so
   > `uv run` would sync the caller's project for no gain.

2. **Report its lines verbatim.** Every line is already safe to show: the script prints
   emails and 8-character fingerprint prefixes, never a token. Read them as follows.

   | line | meaning |
   |---|---|
   | `OK   <email> (fp …)` | filed, and the server confirmed the key works |
   | `OK?  <email> (fp …)` | filed, but nobody answered — the key is unproven |
   | `SKIP <email> — …` | refused by the server, or the rotator lock was busy |
   | `IGNORED line N` | that line did not parse; the user should fix it |
   | `WARNING: … SAME credential …` | two accounts appear to share one subscription |
   | `tightened … to mode 600` | the file was readable by others; it no longer is |

3. **Act on what it found.**
   - A `SKIP` means that one account needs re-minting. Tell the user which, and point them
     at `/janitor-refresh-cc-logins`. Do not re-run the import for the others — they are
     already filed.
   - An `IGNORED` line means the file has a typo. Tell the user the line number. Never print
     the line's contents, since field 2 is a secret.
   - A `WARNING` about a shared credential means `/login` was on one account while
     `claude setup-token` ran for another. That account's key must be re-minted in
     login-then-mint order, or the rotator will spend one subscription under two names.

4. **Confirm the roster.** `env -u CLAUDE_PLUGIN_DATA python3
   "$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/rotator.py" list` shows every slot and its
   expiry. Success is one slot per account with roughly a year of runway. **Do not check for
   a refresh token**: these keys have none by construction, so that check reports failure on
   a perfectly good import.

## Exit codes

| code | meaning |
|---|---|
| 0 | at least one slot was filed. Any failures are named on stdout |
| 1 | nothing was filed. Stdout says which of four: an ai-maestro rotation tick held its lock (the key file was never read), no usable rows parsed, two rows carried the same token, or every row was rejected |
| 2 | no key file, or a bad argument |

A partial import exits 0 on purpose. The accounts that landed are usable immediately, and
re-running the whole import to chase one bad row would redo keychain writes that were already
correct.

Exit 1 deliberately does not separate *"your input was examined and rejected"* from *"your
input was never examined"* — the lock case is the second, and the fix for it is to re-run
unchanged rather than to edit the file. A human reads which one from stdout. If something ever
scripts this command, that is the distinction worth adding a code for.

## Notes

- **The live swap only happens on a verified key.** If the network was down while the
  currently-live account's key was validated, the slot is still filed but the live credential
  is left alone, and the script says so. Installing an unproven token as the one in use right
  now is how a hand-mangled key takes down the running session.
- **Nothing can prove a token belongs to the email on its line.** These keys are
  inference-scoped and return 403 on every identity endpoint, so the login-then-mint ordering
  is the only thing binding a token to an account. That is why the shared-credential warning
  exists, and why it is worth reading.
- **The key file is a long-lived secret store.** It holds bearer tokens valid for about a
  year. The script forces it to mode 600, but it is still a plaintext file: it belongs in
  backup and cloud-sync exclusions. The script never deletes or truncates it — the user
  maintains it by hand and edits single lines.
- A filed key returns 403 on `/api/oauth/usage` and on identity endpoints while `/v1/messages`
  accepts it. Only a 401 indicates a dead key; do not read a 403 as one.

## Scope

ONLY reads the key file, files slots, and refreshes the live credential in place for the
account that is already live. Does NOT rotate to a DIFFERENT account, does NOT mint keys,
does NOT open a browser, does NOT change rotator config, and does NOT modify or delete the
key file's contents. Rotate deliberately with `/janitor-rotate-account-to`; toggle
daemon-managed rotation with `/janitor-auto-manage-oauth-on` / `-off`.

## Resources

- `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/import_oauth_tokens.py` — this skill's script.
- `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/slot_capture_token.py` — the single-account
  path, and the shared validator and slot-blob definition this script reuses.
- `/janitor-refresh-cc-logins` — the upstream human step that produces the keys.
- The `oauth-rotation-renew-reauth` PROJECT memory page — the ROTATE → RENEW →
  REAUTHENTICATE architecture these skills belong to.
