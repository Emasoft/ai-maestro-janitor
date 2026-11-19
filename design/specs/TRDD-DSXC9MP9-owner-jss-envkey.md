# Owner requirements 2026-11-18: jss CLI, autonomous .env editing, context field (TRDD-DSXC9MP9)

Owner order, verbatim, received 2026-11-18 (copied from the session transcript, not retyped):

```text
another thing that the secrets-shield can do is to edit .env files autonomously without waiting for the user. it can read a secret from somewhere, and the secret will be added automatically to the sqlite db and it will only see its uuid. then just by using the janitor secrets shield cli (name it jss or jsscli), you can do this (write all i'm saying in requirements):
Yes. Double quotes allow command substitution. In your existing version, this is valid:

ENVKEY_VALUE="$(jss SECRET_NAME)"

Bash executes jss SECRET_NAME and captures its standard output. Single quotes, as in '$(jss SECRET_NAME)', would keep that text literal instead. Double quotes also prevent word splitting and filename expansion of the captured output. 

For your use case, here is the complete one-liner with the jss lookup inside the function. It checks for an existing key before retrieving the secret, and it stops without writing if jss fails:

envkey() ( set +xu; shopt -u nocasematch; LC_ALL=C; key=${1-}; secret_name=${2-}; [[ $# -ge 2 && $# -le 3 && $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -n $secret_name && ( $# -eq 2 || ${3-} == --force ) ]] || { printf 'Usage: envkey KEY SECRET_NAME [--force]\n' >&2; exit 2; }; [[ ! -L .env && ( ! -e .env || -f .env ) ]] || { printf '.env must be a regular file\n' >&2; exit 2; }; rows=(); pos=-1; prefix="$key="; pattern="^[[:blank:]]*(export[[:blank:]]+)?$key[[:blank:]]*="; if [[ -e .env ]]; then while IFS= read -r line || [[ -n $line ]]; do if [[ $line =~ $pattern ]]; then if (( pos < 0 )); then pos=${#rows[@]}; prefix=${BASH_REMATCH[0]}; fi; else rows+=("$line"); fi; done < .env || exit; fi; if (( pos >= 0 )) && [[ ${3-} != --force ]]; then printf '%s already exists; unchanged (use --force to update)\n' "$key" >&2; exit 0; fi; secret="$(jss "$secret_name")" || exit; [[ $secret != *$'\n'* && $secret != *$'\r'* ]] || { printf 'Value must be a single line\n' >&2; exit 2; }; (( pos >= 0 )) || pos=${#rows[@]}; umask 077; tmp=$(mktemp .env.XXXXXX) || exit; trap 'rm -f "$tmp"' EXIT; printf '%s\n' "${rows[@]:0:pos}" "$prefix$secret" "${rows[@]:pos}" > "$tmp" && mv -f "$tmp" .env ); envkey API_KEY SECRET_NAME

At the end of that line:

* Replace API_KEY with the variable name to store in .env.
* Replace SECRET_NAME with the name you pass to jss.
* Append --force to allow updating an existing key.

The function now takes KEY SECRET_NAME [--force]. Without --force, an existing key is skipped successfully and jss is not called. With --force, existing copies are consolidated into one updated assignment.

The critical statement is secret="$(jss "$secret_name")" || exit: the assignment preserves the command substitution’s exit status, so a failed lookup exits the function before any file changes. 

Bash strips trailing newline characters from command substitution, which handles the usual newline printed after a secret. Embedded newlines remain and are rejected by this function. It still writes unquoted, single-line tokens. 

Tested with a mock jss under Bash 3.2.0 and 5.2.37, including strict scripts, lookup failures, duplicate skipping, forced updates, and returned text containing literal $() and backticks. 

Of course the SECRET_NAME passed to jss or jsscli is simply the UUID of the secret. When harvestig secrets the janitor secrets shield must sabe to the sqlite db not only the secret but also the full line of code where it was used (with the value already redacted) so that the agent can read the context field of the secret and understand if it was asigned to a variable, a env var, exported, passed to a funcion, etc. and understand better what that secret is without ever see it)
```

## Derived requirements (main-agent reading, not the owner's words)
- R1. The janitor secrets shield CLI is named `jss`, with `jsscli` as an alias. `jss <uuid>` prints the vaulted value to stdout, so `"$(jss <uuid>)"` works inside double quotes. The argument the owner calls SECRET_NAME is the secret's UUID. This replaces the name `shield get` in the mods-expert design.
- R2. The shield edits .env files on its own, without waiting for the user: it takes a secret from a source, stores it in the vault, and the agent sees only its UUID. The owner's `envkey KEY SECRET_NAME [--force]` function is the reference implementation (Bash 3.2 and 5.2): it checks for an existing key before the lookup, stops before writing when jss fails, rejects multi-line values, and writes through a temp file with umask 077.
- R3. Every vault row stores a context field: the full line of code where the secret was found, with the value already redacted. The agent reads that field to tell whether the secret was assigned to a variable or an env var, exported, or passed to a function, without ever seeing the value.
- R4. Unchanged from the earlier vault directive: jss output and every command line that holds a resolved value stay redacted for the agent (the known-value index).
- Open, for the owner: whether jss lookups need a permission prompt or a host or command allow-list (exfiltration through a resolved value).

## Reference implementation (owner, 2026-11-18)

The owner's tested helpers are in scripts/janitor-env-tools/ (envkey.sh, envget.sh, their usage guides, one-liners and tests), copied to design/requirements/examples/janitor-env-tools/. PRRD G30.1, G31.1, G32.1 and G33.1 hold the owner's words.
