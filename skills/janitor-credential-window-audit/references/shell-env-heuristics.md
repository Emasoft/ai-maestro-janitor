# Shell-environment heuristics

How the credential-window auditor enumerates environment variables and which NAMES it flags. The auditor reads NAMES only. It NEVER reads, captures, echoes, or logs a value.

## Table of contents

- [Enumeration recipe](#enumeration-recipe) — the only safe way to list env-var NAMES.
- [Pattern matching](#pattern-matching) — regex tables, stale-NAME heuristics, allow-list.
- [Reporting format](#reporting-format) — what each finding looks like in the report.

## Enumeration recipe

```bash
env | cut -d= -f1 | sort -u
```

`env | cut -d= -f1` strips every value at source. The pipe never sees a value, the auditor's process never reads one, and a `set -x` trace would only print the NAME. Do NOT use:

- `env` alone — emits NAME=VALUE pairs.
- `printenv VAR` — emits the value.
- `set` — emits shell-function bodies and exported values.
- `echo $SUSPECT_VAR` / `echo "$SUSPECT_VAR"` — same problem; never appears anywhere in the auditor's code.

If the auditor runs in a context where stdout is captured to a file (transcript, log, report), the cut at source still holds: there is no value to leak because the pipeline never received one.

## Pattern matching

### Secret-NAME regex table

Each pattern is anchored loosely (matches the NAME with `*` on either side). Severity reflects the typical sensitivity of the NAME, NOT the value (which the auditor never sees).

| Pattern | Severity | Typical NAMES it catches | Notes |
|---|---|---|---|
| `.*_TOKEN$` | HIGH | `GITHUB_TOKEN`, `NPM_TOKEN`, `SLACK_TOKEN`, `OPENAI_TOKEN` | Long-lived API tokens |
| `.*_PAT$` | HIGH | `GH_PAT`, `AZURE_PAT` | Personal access tokens |
| `.*_API_KEY$` | HIGH | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `STRIPE_API_KEY` | API keys |
| `.*_SECRET$` | HIGH | `JWT_SECRET`, `SESSION_SECRET`, `OAUTH_SECRET` | Symmetric secrets |
| `.*_PASSWORD$` | HIGH | `DB_PASSWORD`, `REDIS_PASSWORD` | Passwords |
| `.*_PWD$` | HIGH | `DB_PWD`, `MYSQL_PWD` | Password aliases |
| `.*_KEY$` (excludes `*_PUBLIC_KEY`, `*_PUB_KEY`) | MEDIUM | `PRIVATE_KEY`, `SIGNING_KEY` | Generic; many false positives |
| `.*_CREDENTIALS$` | HIGH | `AWS_CREDENTIALS`, `GCP_CREDENTIALS` | Credential bundles |
| `.*_AUTH$` | MEDIUM | `BASIC_AUTH`, `BEARER_AUTH` | Auth headers |
| `.*_BEARER$` | HIGH | `GITHUB_BEARER` | Bearer tokens |
| `AWS_SECRET_ACCESS_KEY` (exact) | HIGH | `AWS_SECRET_ACCESS_KEY` | AWS-canonical secret |
| `AWS_SESSION_TOKEN` (exact) | HIGH | `AWS_SESSION_TOKEN` | Short-lived but powerful |
| `KUBECONFIG` (exact) | MEDIUM | `KUBECONFIG` | Path to a file holding tokens |
| `DOCKER_AUTH_CONFIG` (exact) | HIGH | `DOCKER_AUTH_CONFIG` | Inline Docker registry auth |
| `.*_OAUTH.*$` | HIGH | `GITHUB_OAUTH_TOKEN`, `OAUTH_REFRESH` | OAuth credentials |
| `.*_WEBHOOK.*SECRET.*$` | HIGH | `STRIPE_WEBHOOK_SECRET` | Webhook signing secrets |

The pattern set is conservative: it accepts a higher false-positive rate (e.g. `LDFLAGS_KEY` matches `.*_KEY$`) over missing a real credential NAME.

### Stale-NAME heuristics

A NAME matching one of the secret patterns above AND ALSO matching any of these is upgraded by one severity step (LOW → MEDIUM, MEDIUM → HIGH, HIGH → CRITICAL):

| Suffix / pattern | Meaning |
|---|---|
| `.*_OLD$` | Probable previous-value backup the user forgot to unexport |
| `.*_BAK$` | Same as `_OLD` |
| `.*_TMP$` / `.*_TEMP$` | Scratch credential left in the environment |
| `.*_PREV$` / `.*_PREVIOUS$` | Same as `_OLD` |
| `.*_2$` / `.*_3$` / `.*_NEW$` | Rotation in progress; old NAME still around |
| `.*_DEPRECATED$` | Self-documenting "should not be here" |
| `OLD_.*` / `BAK_.*` / `TMP_.*` (prefix variants) | Same idea on the prefix side |

Rationale: a stale-NAMED credential almost certainly persists past its useful window, which is the exact thing this audit measures. Surface NAME + recommended action: `unset <NAME> && rotate <upstream>`.

### Allow-list / known-safe NAMES

Even if they match a secret-pattern regex, the auditor SUPPRESSES (does not report) these well-known false positives:

- `MAKEFLAGS`, `LDFLAGS`, `CFLAGS`, `CXXFLAGS`, `CPPFLAGS` — build flag NAMES.
- `XDG_*_KEY` (none currently standard).
- `SSH_AUTH_SOCK` — points to an agent socket, not a key value.
- `GPG_TTY` — TTY pointer for gpg-agent.
- `PASSWORD_STORE_DIR`, `PASSWORD_STORE_KEY` — directory + GPG key id for `pass`; both are NAMES of locations, not credentials.
- `KEYCHAIN_*` macOS keychain identifiers.
- `KUBECONFIG` is MEDIUM (file path, value is a path not a token; downgrade does NOT apply if combined with a stale-NAME suffix).

The allow-list is a small fixed table. Edits require updating this reference file, not the SKILL.md.

### Cross-reference with shell history

Optional surface check (LOW severity), surfaced as a hint:

```bash
grep -lE '(export|set) [A-Z_]+_(TOKEN|API_KEY|SECRET|PASSWORD|PAT)=' \
  ~/.bash_history ~/.zsh_history 2>/dev/null
```

Reports `~/.bash_history references secret-NAME assignments`. The auditor does NOT capture the matched line — only the file path and the NAME side of the assignment (`export NAME=`). Remediation hint: `history -d` for the specific line, or rotate.

## Reporting format

Each finding in the report is rendered as a single line:

```
HIGH  | env:GITHUB_TOKEN  | unset GITHUB_TOKEN; rotate at https://github.com/settings/tokens; only export when needed
HIGH  | env:NPM_TOKEN_OLD | stale NAME; unset NPM_TOKEN_OLD and revoke at npm registry
MEDIUM| env:PRIVATE_KEY   | unset PRIVATE_KEY; load on demand via ssh-agent / keychain
```

Layout: severity (6 chars left-aligned) | `env:NAME` | terse remediation. No values, no context lines, no surrounding env. The user is the one with full shell access and can investigate; the auditor's job is to point.
