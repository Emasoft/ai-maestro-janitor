# Owner requirement 2026-11-18: jss add writes a secret straight into the vault (TRDD-DSXC9MP9)

Owner order, verbatim, received 2026-11-18 (copied from the session transcript; the two bracketed lines replace the chat's paste-marker lines, and the blank lines next to them were adjusted; every other byte is the owner's):

```text
jss (or jsscli) must also support adding secrets directly to the sqlite db, with `jsscli add SECRET_NAME SECRET_VALUE "<CONTEXT_STRING>"`. For example in case of .env files you can do the following without ever see the secret:



[pasted text follows, as the owner sent it]
Yes. For the unquoted, single-line entries produced by our earlier command, you can read the value literally and pass it directly to jss add.

The helper below has two forms:

Invocation    Action
envget API_KEY    Prints the value of API_KEY from .env.
envget API_KEY SECRET_NAME    Calls jss add SECRET_NAME with that value as its final argument.

Each command below defines and executes the function on one physical line, and works with Bash 3.2.

Read the value

Replace the final API_KEY with the name you want to read:

envget() ( set +xu; shopt -u nocasematch; LC_ALL=C; key=${1-}; [[ $# -ge 1 && $# -le 2 && $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ && ( $# -eq 1 || -n ${2-} ) ]] || { printf 'Usage: envget KEY [JSS_SECRET_NAME]\n' >&2; exit 2; }; [[ -f .env && -r .env ]] || { printf 'Cannot read .env\n' >&2; exit 1; }; found=0; pattern="^[[:blank:]]*(export[[:blank:]]+)?$key[[:blank:]]*=(.*)$"; while IFS= read -r line || [[ -n $line ]]; do line=${line%$'\r'}; if [[ $line =~ $pattern ]]; then (( found == 0 )) || { printf '%s appears more than once\n' "$key" >&2; exit 3; }; value=${BASH_REMATCH[2]}; found=1; fi; done < .env || exit; (( found )) || { printf '%s was not found\n' "$key" >&2; exit 1; }; if [[ $# -eq 2 ]]; then jss add "$2" "$value"; else printf '%s\n' "$value"; fi ); envget API_KEY

Read the value and add it to jss

Replace the final API_KEY with the variable name in .env, and SECRET_NAME with the destination name in jss:

envget() ( set +xu; shopt -u nocasematch; LC_ALL=C; key=${1-}; [[ $# -ge 1 && $# -le 2 && $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ && ( $# -eq 1 || -n ${2-} ) ]] || { printf 'Usage: envget KEY [JSS_SECRET_NAME]\n' >&2; exit 2; }; [[ -f .env && -r .env ]] || { printf 'Cannot read .env\n' >&2; exit 1; }; found=0; pattern="^[[:blank:]]*(export[[:blank:]]+)?$key[[:blank:]]*=(.*)$"; while IFS= read -r line || [[ -n $line ]]; do line=${line%$'\r'}; if [[ $line =~ $pattern ]]; then (( found == 0 )) || { printf '%s appears more than once\n' "$key" >&2; exit 3; }; value=${BASH_REMATCH[2]}; found=1; fi; done < .env || exit; (( found )) || { printf '%s was not found\n' "$key" >&2; exit 1; }; if [[ $# -eq 2 ]]; then jss add "$2" "$value"; else printf '%s\n' "$value"; fi ); envget API_KEY SECRET_NAME

Behavior

* It matches the exact, case-sensitive variable name, including entries with an optional export prefix or whitespace before =.
* It preserves the value, including embedded = characters, dollar signs, backslashes, and spaces. The complete value becomes one argument to jss add.
* If the key is missing or appears more than once, it reports an error without calling jss.
* It accepts an explicitly empty value such as API_KEY=, handles CRLF endings and a missing final newline, and leaves .env unchanged.
* It reads the file as text; it does not execute its contents. A failure from jss add is returned to the calling script.

Format limitation: this retrieves the literal text after =. It does not remove surrounding quotes, strip inline comments, expand ${VARIABLE}, or decode multiline values. For example, API_KEY="abc" returns "abc" including the quotes. Files using those features need the parser used by your application; dotenv syntax is not a single formally specified format. 

The helper disables shell tracing before handling the secret. However, the interface you supplied—jss add NAME VALUE—necessarily passes the value in jss’s command-line arguments. Handling an existing destination name is governed by jss add itself.

Tested under Bash 3.2.0 and 5.2.37, including strict-mode scripts, missing and duplicate keys, literal special characters, and a mock jss that verified the exact arguments received.
[end of pasted text]
```

## Derived requirements (main-agent reading, not the owner's words)

- R5. `jss add <name> <value> "<context>"` (alias `jsscli add`) writes a secret straight into the vault together with its context string. It is the write path for envget and for every other harvester.
- R6. The owner's envget helper above (Bash 3.2 and 5.2) is the reference consumer: `envget KEY NAME` reads one unquoted single-line value literally from .env and passes it to `jss add` as one argument, so the agent never sees the value. `envget KEY` alone prints the value, so the shield's output redaction (R4 in TRDD-DSXC9MP9-owner-jss-envkey.md) must hide it.
- R7. The context string is stored redacted: when it contains the value, `jss add` replaces the value with the vault marker before storing it (same rule as R3).

## Open questions for the owner

1. R1 says the name passed to jss is the secret's UUID. Does `jss add` take a caller-chosen name, a caller-chosen UUID, or a name for which jss creates a UUID and prints it?
2. The pasted text notes that the value travels in jss's command-line arguments. While `jss add` runs, other processes and users on the machine can read it from the process list; the shield hides it from the agent (R4) but not from them. Should `jss add` also take the value on stdin (for example `jss add NAME - "<context>"`), with envget piping it?
3. What does `jss add` do when the name already exists: refuse, overwrite, or overwrite only with a flag?
4. The ordered form `jss add NAME VALUE "CONTEXT"` has three arguments, but the envget example calls `jss add "$2" "$value"` with two and no context. Is the context optional, or should envget pass the matched .env line with the value redacted as the context?
