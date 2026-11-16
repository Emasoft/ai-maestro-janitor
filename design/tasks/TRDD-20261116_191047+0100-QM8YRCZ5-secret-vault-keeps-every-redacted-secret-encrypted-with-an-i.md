---
trdd-id: QM8YRCZ5
title: Secret vault keeps every redacted secret encrypted with an id in the redaction marker
column: backburner
status: tasked
created: 2026-11-16T19:10:47+0100
updated: 2026-11-16T19:25:39+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T19:10:47+0100
---

# Secret vault keeps every redacted secret encrypted with an id in the redaction marker

Owner 2026-11-16 (verbatim): For the secrets we can adopt a strong "nothing is ever lost policy", with the adoption of a sqlite db where each secret is stored when redacted, along with the datetime of redaction, secret type  and the file path, and associated with an unique random uuid that will be placed in the correspondent redaction string. for example [REDACTED-BY-SECRET-SHIELD. Type: <type of secret>. ID: <UUID>]. repeated secrets will point to the same entry in the db and will have the same uuid (but only for same files.. secrets redacted in different files will have a different uuid). all secrets will be stored indefinitely in the sqlite db (or better-sqlite, used by other plugins) and new ccommands of secrets-shield will allow the agent to delete the secrets by time  interval, secret type, file containing it or uuid, but never to read the secret. the reports-sanitizer will use the secrets-shield internally so it will be the same.

The owner ordered the vault (quote above); only the decisions under "Pending owner decisions" are open. Related: TRDD-L1I0FP5T.

## Approval log

- 2026-11-16T19:10:47+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Design

- Marker: [REDACTED-BY-SECRET-SHIELD. Type: <kind>. ID: <uuid>]. The same secret in the same file gets the same uuid, a different file gets a new one, and re-redacting a file gives identical text.
- The mod hooks module has no file or SQLite access of its own: the mods API gives $.fs (text files, 4 MiB cap), $.process.run (30 s timeout) and crypto.subtle; $.store is dropped after cleanupPeriodDays without use, so it cannot hold the vault.
- Storage: a bun helper using bun:sqlite (WAL, busy_timeout, secure_delete). The mod, or the report-sanitizer bun bridge, encrypts each value in memory with a public key and hands over only the ciphertext and a keyed hash; one INSERT ON CONFLICT(origin, hash) RETURNING id.
- Columns: uuid, type, origin (the file path), first and last redaction time, count, ciphertext, keyed hash. The private key sits in the macOS Keychain behind a per-use prompt; writing never needs it.
- Commands: list (metadata only) and delete by time interval, type, file or uuid (permanent, logged in an audit table without values). No command prints a value. Exposed as a mod tool and as /secret-shield vault.
- Failure: if the vault write fails, report-sanitizer exits with an error and leaves the file untouched; the live mod withholds the tool result.
- Security limit: the agent can still read the encrypted file, and a password-like secret can be guessed offline from its keyed hash; a janitor PreToolUse guard refuses tool calls naming the vault file or the key.
- Order: a probe (crypto.subtle RSA-OAEP, AES-GCM and HMAC inside the mod; $.process.run latency; two processes writing bun:sqlite in WAL), the helper and key setup, the core marker change, the report-sanitizer bridge and re-pin, the commands and the guard, then mod wiring (blocked by TRDD-2V7OAUPE).

## Pending owner decisions

- (b) Origin recorded for text that is not a file (Bash output, transcript rows); proposed: transcript:<session-id>.
- (c) Whether a human-only restore exists, behind the Keychain prompt, that writes the secret back into its file and prints only a count.
- (d) Vault location; proposed: the platform application-data folder (Application Support on macOS, XDG_DATA_HOME on Linux), overridable with SECRET_SHIELD_VAULT.

## Acceptance checklist

- [ ] a redacted secret gets the owner marker with a uuid: the same uuid for the same file, a new one for another file, with tests
- [ ] a test proves the vault file never holds a fixture secret in plaintext
- [ ] list and delete by time interval, type, file and uuid work, and no command prints a value
- [ ] report-sanitizer and the shield emit the same marker through the same vault
