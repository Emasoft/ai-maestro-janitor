---
trdd-id: QM8YRCZ5
title: Secret vault keeps every redacted secret stored in plain text with an id in the redaction marker
column: backburner
status: tasked
created: 2026-11-16T19:10:47+0100
updated: 2026-11-17T23:34:19+0100
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

# Secret vault keeps every redacted secret stored in plain text with an id in the redaction marker

Owner 2026-11-16 (verbatim): For the secrets we can adopt a strong "nothing is ever lost policy", with the adoption of a sqlite db where each secret is stored when redacted, along with the datetime of redaction, secret type  and the file path, and associated with an unique random uuid that will be placed in the correspondent redaction string. for example [REDACTED-BY-SECRET-SHIELD. Type: <type of secret>. ID: <UUID>]. repeated secrets will point to the same entry in the db and will have the same uuid (but only for same files.. secrets redacted in different files will have a different uuid). all secrets will be stored indefinitely in the sqlite db (or better-sqlite, used by other plugins) and new ccommands of secrets-shield will allow the agent to delete the secrets by time  interval, secret type, file containing it or uuid, but never to read the secret. the reports-sanitizer will use the secrets-shield internally so it will be the same.

The owner ordered the vault (quote above) and told the agent to decide the open points on verified facts; the decisions are listed under Decisions. Related: TRDD-L1I0FP5T.

## Approval log

- 2026-11-16T19:10:47+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T19:52:56+0100 main-agent: owner asked "what are you waiting for?"; proceeding on the recommended defaults: (b) transcript:<session-id>; (c) human-only restore behind a passphrase the agent cannot answer (replaces the Keychain-only design, works on every platform). Owner 2026-11-16 (verbatim): "i told you to decide yourself. just base your decisions of verified facts." (d) owner 2026-11-16 (verbatim): "make sure the sqlite db is unique and saved into ~/.secrets_shield/" - one vault file for every tool at ~/.secrets_shield/vault.db, no environment override (tests pass a temporary path as a function argument, never the real file).
- 2026-11-16T19:59:03+0100 main-agent: correction to the 19:52:56 line: tests do not pass a path as a function argument (it cannot cross from Python through the bun bridge to the helper); they run with HOME set to a temporary folder. owner 2026-11-16 (verbatim): "do not use passphrases. if a mod can read the passphrase, any malicious actor can." Private key: macOS Keychain item with an empty trusted-app list (-T ""), every read prompts the human (per man security, not run here).
- 2026-11-16T20:00:42+0100 main-agent: supersedes the 19:52:56 restore design, which is withdrawn. The restore design now: the private key is the macOS Keychain item described in Columns, reads need the human to allow them (per man security, not run here), and no secret is typed by anyone (owner 2026-11-16, quoted on the 19:59:03 line).
- 2026-11-16T20:04:07+0100 main-agent: owner 2026-11-16 (verbatim): "no, you misunderstood: no protection or encryption at all. the sqlite db is open annd readable by all. why? because there is no way to protect those secrets if the mod must access to it in my absence. it should work without my presence, so any password or key should be saved somewhere, and any process can use it emulating the mod." Encryption, keys and the Keychain design are dropped; the 19:52:56, 19:59:03 and 20:00:42 lines are superseded.
- 2026-11-16T20:12:45+0100 main-agent: owner 2026-11-16 (verbatim): "those secrets where redacted to avoid them being exfiltrated (by git push with tracked files or by llm api requests with the transcripts jsonl). but to protect them inside the computer locally it's impossible." and (verbatim): "so no keychain or any other method. just a plain sqlite db open to all." The restricted file mode (0700 folder, 0600 file) is dropped as well. The 20:04:07 line superseded only the encryption, passphrase and Keychain parts: (b) transcript:<session-id> and (d) the single vault path stand. The 19:59:03 test design (HOME set to a temporary folder) is withdrawn, because the helper reads the home folder from the account database. Restore is human-only (agent decision). The mod passes values in a request file because the mods docs show no stdin for $.process.run.
- 2026-11-16T20:14:14+0100 main-agent: correction to the previous line: no mods doc chapter shows a stdin option for $.process.run or $.process.spawn (searched 2026-11-16), which does not prove there is none; the request-file route and the account-database home lookup are both still to be verified in the probe.
- 2026-11-16T20:28:08+0100 main-agent: the "no environment override" of the 19:52:56 line means nothing can point the vault at another path; the one exception is the test-only setting described under Decisions (d), which refuses any path outside the system temp folder.

## Design

- Marker: [REDACTED-BY-SECRET-SHIELD. Type: <kind>. ID: <uuid>]. The same secret in the same file gets the same uuid, a different file gets a new one, and re-redacting a file gives identical text. The old marker [JANITOR-REDACTED:<kind>] stays recognised and protected. redact() stays pure and synchronous and takes an ID provider; the callers do the vault I/O, one batched helper call per text.
- The mod hooks module has no SQLite access of its own: the mods API gives $.fs (text files, 4 MiB cap) and $.process.run (30 s timeout); $.store is dropped after cleanupPeriodDays without use, so it cannot hold the vault.
- Storage: a bun helper using bun:sqlite (WAL, busy_timeout). The report-sanitizer bun bridge passes the values over stdin. The mod probably cannot: no mods doc chapter shows a stdin option for $.process.run or $.process.spawn (searched 2026-11-16; the call signature of spawn is not documented there), so the planned route is a request file in ~/.secrets_shield/ whose name alone goes on argv; the helper reads the file and removes it. The probe verifies both points. Values never go on argv (ps shows argv). One INSERT ... ON CONFLICT(origin, value) ... RETURNING id per value, batched per text.
- Columns: uuid, type, origin (the file path), first and last redaction time, count, value (plain text). No encryption, key, passphrase, Keychain or restricted file mode (owner 2026-11-16): the vault must work unattended, and any key the mod could read, any process could read too. One row per (origin, value); the same secret in the same file reuses its uuid.
- Commands: list (metadata only) and delete by time interval, type, file or uuid (permanent, logged in an audit table without values). No command prints a value. Exposed as a mod tool and as /secret-shield vault.
- Failure: if the vault write fails, report-sanitizer exits with an error and leaves the file untouched; the live mod withholds the tool result.
- Security limit (owner 2026-11-16: local protection is impossible): the vault is a plain SQLite file open to every process, created with the default file mode; backups copy it. Its job is to keep secrets out of git and out of model requests: it lives in ~/.secrets_shield/, outside every repo, and a janitor PreToolUse guard keeps agents from reading the vault, the request files or the helper output into context, because every transcript row is sent to the model. Agent commands list metadata and delete; none prints or writes back a value. Planned, verified by the probe: the helper reads the home folder from the account database (dscl on macOS, getent on Linux), because bun os.homedir() and os.userInfo().homedir both follow HOME (checked 2026-11-16); tests use a test-only setting accepted only for a path under the system temp folder.
- Order: a probe (two processes writing bun:sqlite in WAL; $.process.run latency; whether the mod's $.fs can write, and the helper remove, a request file in ~/.secrets_shield/; the account-database home lookup), the helper, the core marker change, the report-sanitizer bridge and re-pin, the commands and the guard, then mod wiring (blocked by TRDD-2V7OAUPE).
- Only a run that rewrites a file or a tool result stores values; report-sanitizer --dry-run, --scan and CI runs store nothing.

## Decisions

- (b) Origin for text that is not a file (Bash output, transcript rows): transcript:<session-id> (agent decision, on the owner's order to decide).
- (c) Restore (writing a stored value back into its file) is a human-only command: the agent guard refuses it from an agent, because a restored secret in a tracked file can leave by git push (agent decision, on the owner's order to decide).
- (d) Decided by the owner 2026-11-16: one vault file for every tool at ~/.secrets_shield/vault.db (the owner's explicit order overrides the standing rule against new dot folders); nothing can point the vault at another path. The one exception is a test-only setting that refuses any path outside the system temp folder; tests use it and never HOME (the helper ignores HOME, see Security limit), and one test checks that the real vault is untouched.
- Schema change, 2026-11-17T23:29:50+0100, by main-agent, from the increment 3 spec (design/specs/TRDD-BAQB9SYO-increment-3-redact.md, R4 and R9): the row key becomes (origin, value, encoding), with a new encoding column (raw or json-string), because a value found inside a JSON string must be restored re-escaped or its line stops parsing; restore looks a row up by its uuid alone and reports a moved origin, because uuid v4 already identifies the row and projects get moved after redaction.
- Restore by origin, 2026-11-17T23:34:19+0100, by main-agent (supersedes the restore part of the Schema change line of 2026-11-17T23:29:50+0100; spec v4 R9): restore.ts restores a row whose origin is the file's current path; a row from another origin is restored only with --any-origin and is otherwise reported as moved and left as a marker, because without the flag a marker copied into another file would write the secret there.

## Acceptance checklist

- [ ] a redacted secret gets the owner marker with a uuid: the same uuid for the same file, a new one for another file, with tests
- [ ] tests prove the resolved vault path is outside every git work tree and the agent guard refuses an agent Read, Grep or Bash of the vault and of the request files
- [ ] list and delete by time interval, type, file and uuid work, and no command prints a value
- [ ] report-sanitizer and the shield emit the same marker through the same vault
- [ ] report-sanitizer --dry-run and --scan store nothing in the vault
