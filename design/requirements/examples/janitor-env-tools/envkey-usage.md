# envkey v2: write a JSS secret's value under an env-file variable name

`envkey` retrieves a secret with `jss JSS_SOURCE_SECRET_NAME` and writes it to a named environment-variable assignment. An existing key is left unchanged unless you pass `--force`, even if the stored value differs from the current secret.

The function supports Bash 3.2+ and zsh, at an interactive prompt or inside a script. It uses standard `awk`, `mktemp`, `chmod`, `mv`, and `rm` commands. Python is needed only for the optional test runner.

## 1. The four files

| File | Purpose |
| --- | --- |
| `envkey.sh` | Complete reusable implementation: execute it to write a key, or source it to declare the function. |
| `envkey-one-liner.md` | Complete independent function definition followed by one invocation, on one physical line. |
| `envkey-usage.md` | This guide, including both complete forms and installation instructions. |
| `test_envkey.py` | Optional tests using synthetic values and a mock `jss`. |

This is the writing companion to `envget.sh`. The files are `envkey.sh`, `envkey-one-liner.md`, `envkey-usage.md` and `test_envkey.py`; the functions are named `envkey` and `envget`. `envkey` copies a value **from `jss` into an env file**. `envget` reads a value **from an env file**, then either prints it or passes it to `jss add` under a destination secret name.

## 2. Names, values, and the exact interface

**Both positional arguments are names. Neither argument is the secret's actual value.**

```text
envkey [-f FILE | --file FILE | --file=FILE] [--force] [--] ENV_VAR_NAME JSS_SOURCE_SECRET_NAME
```

| Argument | What you supply | Example |
| --- | --- | --- |
| `ENV_VAR_NAME` | The destination variable **name** to write in the env file. | `API_KEY` |
| `JSS_SOURCE_SECRET_NAME` | The existing secret **name** to retrieve from `jss`. | `MY_SERVICE_API_KEY` |
| Secret value | You do **not** supply this as either positional argument. The helper retrieves it internally. | `example-secret-123`, returned by `jss` |

`API_KEY` and `MY_SERVICE_API_KEY` are concrete example names, not secret values. Replace them with your own env-file variable name and your own existing JSS entry name. The earlier examples `SERVICE_API_KEY` and `SERVICE_PASSWORD` also meant **JSS secret names**, never the stored values; v2 uses explicit role names to remove that ambiguity.

### Add a key: a complete example

```bash
envkey API_KEY MY_SERVICE_API_KEY
```

The function retrieves the value with:

```bash
jss MY_SERVICE_API_KEY
```

If that command returns the synthetic example value `example-secret-123`, the helper writes:

```dotenv
API_KEY=example-secret-123
```

The lookup is performed only when a write is needed. If `API_KEY` is already present and `--force` was not supplied, the function skips the assignment without calling `jss`.

### A name is different from `$NAME`

| Form | Meaning for this helper |
| --- | --- |
| `envkey API_KEY MY_SERVICE_API_KEY` | Correct: pass the literal destination name `API_KEY` and literal JSS source name `MY_SERVICE_API_KEY`. |
| `envkey "$API_KEY" MY_SERVICE_API_KEY` | The shell expands `$API_KEY` first. If it holds a secret, that secret is incorrectly supplied where a destination variable name is expected. |
| `envkey ACTUAL_SECRET_VALUE MY_SERVICE_API_KEY` | Incorrect when `ACTUAL_SECRET_VALUE` stands for the password/token itself. The first argument is treated as a variable name, not a value to store. |
| `envkey API_KEY "$(jss MY_SERVICE_API_KEY)"` | Incorrect for this interface: the retrieved value would be supplied as a name for another JSS lookup. |

The literal text `API_KEY` names a variable. `$API_KEY` expands to that variable's current value. Exporting a variable does not change this distinction: `export` makes its value available to child processes; it does not make `$API_KEY` expand to the name `API_KEY`.

The destination variable does not need to be defined or exported in your current shell. **Writing an env file does not export or change that variable in your current shell.** If you already have an exported `API_KEY`, its current shell value is not the input to `envkey`.

Do not type angle brackets such as `<API_KEY_VALUE>` as literal arguments: `<` and `>` are shell redirection operators. This guide uses uppercase placeholders without angle brackets and labels every placeholder's role explicitly.

### When quoted variable expansion is appropriate

Quoted expansion is valid when your shell variables deliberately contain the two **names**:

```bash
env_var_name='API_KEY'
jss_source_secret_name='MY_SERVICE_API_KEY'
envkey "$env_var_name" "$jss_source_secret_name"
```

Here `env_var_name` contains the name `API_KEY`, not its secret value. Likewise, `jss_source_secret_name` contains the name of the JSS entry. The helper still retrieves the actual value internally. This version has no direct-secret-value mode.

### Source and destination: envkey versus envget

| Command | Source of the actual value | Destination |
| --- | --- | --- |
| `envkey API_KEY MY_SERVICE_API_KEY` | `jss MY_SERVICE_API_KEY` | Variable named `API_KEY` in `.env`. |
| `envget API_KEY` | Variable named `API_KEY` in `.env`. | Standard output. |
| `envget API_KEY MY_IMPORTED_API_KEY` | Variable named `API_KEY` in `.env`. | JSS entry named `MY_IMPORTED_API_KEY`, using `jss add`. |

Thus the writer's second name is a **JSS source secret name**. The reader's optional second name is a **JSS destination secret name**. Neither function accepts the actual secret value as a positional argument. See `envget-usage.md` for the reader's complete instructions.

### Options and examples

| Command | Result |
| --- | --- |
| `envkey API_KEY MY_SERVICE_API_KEY` | Retrieve `jss MY_SERVICE_API_KEY` and add variable `API_KEY` to `.env` if absent. |
| `envkey -f .env.local API_KEY MY_SERVICE_API_KEY` | Use `.env.local`. |
| `envkey --file .env.backup API_KEY MY_SERVICE_API_KEY` | Use `.env.backup`. |
| `envkey --file=.env.local API_KEY MY_SERVICE_API_KEY` | Equivalent long-option form. |
| `envkey --force API_KEY MY_SERVICE_API_KEY` | Add or replace variable `API_KEY` in `.env`. |
| `envkey -f .env.local --force API_KEY MY_SERVICE_API_KEY` | Add or replace it in `.env.local`. |
| `envkey API_KEY MY_SERVICE_API_KEY --force` | Equivalent trailing-force form. |
| `envkey --help` | Print usage and the name/value explanation without calling `jss`. |

Put options before `ENV_VAR_NAME`, apart from the explicitly supported trailing `--force`. Env-file variable names must be ASCII identifiers: a letter or underscore followed by letters, digits, or underscores. Matching is case-sensitive. JSS source names must be nonempty and are passed as one argument exactly as supplied; `jss` decides which entry names it accepts.

### Paths and the default file

The default is `.env` in the **current working directory**, not beside the installed helper. Relative paths are also relative to the current directory. The filename has no extension restriction.

```bash
envkey -f "/Users/User/Project Secrets/.env.backup" API_KEY MY_SERVICE_API_KEY
envkey -f "/Users/User/Project Secrets/.env.backup" --force API_KEY MY_SERVICE_API_KEY
```

Quote paths and JSS names containing spaces. Leading-dash filenames and filenames containing `=` are supported when passed with the file option:

```bash
envkey -f "--settings.env" API_KEY MY_SERVICE_API_KEY
envkey -f "settings=local.env" API_KEY MY_SERVICE_API_KEY
```

If the file is missing, a successful write creates it. Its parent directory must already exist. Existing symlinks, dangling symlinks, directories, and other nonregular targets are rejected.

## 3. Existing keys, duplicates, and --force

Without `--force`, any active assignment for the exact key causes a successful skip. The original bytes, permissions, and modification time are retained. `jss` is not called and no temporary file is created. A message goes to standard error; the exit status is `0`, so this expected skip does not stop a script using `set -e`.

This is based on the **key's presence**, not a comparison of secret values. An existing empty assignment also counts as present. If multiple assignments already exist, the default action leaves all of them unchanged.

With `--force`, the function retrieves the new secret and:

1. Replaces the first matching assignment in its existing position.
2. Preserves that assignment's indentation, optional `export`, and spacing before and including `=`.
3. Removes additional active assignments of the same key.
4. Keeps unrelated records in their original order.

If no assignment exists, `--force` appends a new one just like a normal write.

For example, suppose `.env` contains:

```dotenv
OTHER=keep
  export API_KEY =old-first
API_KEY_SUFFIX=unrelated
API_KEY=old-second
```

If `jss MY_SERVICE_API_KEY` returns `new-value`, this command:

```bash
envkey --force API_KEY MY_SERVICE_API_KEY
```

produces:

```dotenv
OTHER=keep
  export API_KEY =new-value
API_KEY_SUFFIX=unrelated
```

Comment-only records, differently cased names, and longer names such as `API_KEY_SUFFIX` do not match `API_KEY`.

## 4. Password symbols and the literal file format

The retrieved value is data. Dollar signs, exclamation marks, both quotation marks, backticks, backslashes, equals signs, glob characters, brackets, parentheses, semicolons, ampersands, pipes, leading/trailing spaces, tabs, and UTF-8 text are preserved. Shell-looking text such as `$(command)` is not executed.

The writer uses a fixed `printf` format. The secret is passed to `awk` through standard input, never as an `awk -v` argument, a regular expression, or replacement text. It never sources or evaluates the env file.

The format is deliberately **literal, unquoted, single-line `KEY=value`**. The supplied `envget` reads the same format. Examples of the exact line written for different retrieved values:

| Value returned by jss | Line written for `PASSWORD` |
| --- | --- |
| `abc#def` | `PASSWORD=abc#def` |
| `abc=def==` | `PASSWORD=abc=def==` |
| `"abc"` with literal quote characters | `PASSWORD="abc"` |
| `abc # note` | `PASSWORD=abc # note` |
| `${OTHER}` | `PASSWORD=${OTHER}` |
| `abc\nxyz` with a backslash and the letter `n` | `PASSWORD=abc\nxyz` |

This is not a universal dotenv serializer. Applications differ in how they interpret quotes, comments, escapes, interpolation, and whitespace. For example, a loader may remove the quote characters from `PASSWORD="abc"`, although this helper and its companion `envget` treat those characters as part of the password. Use an application-specific serializer/parser when those interpretations are required. Do not source an env file written in this literal format as shell code.

Values must fit on one physical line. A successful empty `jss` result is allowed and writes `KEY=`. Embedded line feeds and carriage returns are rejected before modifying the target. Shell command substitution removes trailing line feeds from `jss` output, including its customary output newline; a secret that intentionally ends in a newline therefore cannot be represented. NUL bytes and binary secrets are unsupported and are not reliably detectable after shell command substitution.

### Existing line endings

On a successful write, existing LF and CRLF record endings are retained. A replaced assignment keeps the ending of its original first matching record. An appended assignment uses the ending of the file's last record; new or empty files use LF. A missing final newline is normalized to a newline when the file is rewritten. A skipped operation leaves the original bytes unchanged, including a missing final newline.

## 5. Independent one-liner

The following is a complete independent command: it defines the function, includes an explicit explanation of the arguments, and invokes `envkey`. **Before running it, replace the two quoted placeholders in the final invocation with names**: `'ENV_VAR_NAME'` is the destination variable name in the env file; `'JSS_SOURCE_SECRET_NAME'` is the existing secret name in `jss`. Neither placeholder is a secret value. It does not depend on an installed `envkey.sh` file.

Paste it at a Bash or zsh prompt, or put it in a Bash or zsh script. The display may wrap, but the command is **one physical line**.

```bash
envkey() ( set +eux; set -o pipefail; LC_ALL=C; export LC_ALL; envkey_file=.env; envkey_force=0; while [ "$#" -gt 0 ]; do case "$1" in -f|--file) if [ "$#" -lt 2 ] || [ -z "$2" ]; then printf '%s\n' 'envkey: --file requires a nonempty path' >&2; exit 2; fi; envkey_file=$2; shift 2; ;; --file=*) envkey_file=${1#*=}; if [ -z "$envkey_file" ]; then printf '%s\n' 'envkey: --file requires a nonempty path' >&2; exit 2; fi; shift; ;; --force) envkey_force=1; shift; ;; -h|--help) printf '%s\n' 'Usage: envkey [-f FILE | --file FILE] [--force] [--] ENV_VAR_NAME JSS_SOURCE_SECRET_NAME' 'Both positional arguments are names; neither is the secret value.' 'ENV_VAR_NAME: destination variable name in the env file, for example API_KEY.' 'JSS_SOURCE_SECRET_NAME: name of an existing secret in jss, for example MY_SERVICE_API_KEY.' 'Retrieve the value internally with: jss JSS_SOURCE_SECRET_NAME' 'Use the literal name API_KEY, not "$API_KEY" when that variable contains a secret value.' 'A trailing --force after JSS_SOURCE_SECRET_NAME is also accepted.' 'Default file: .env in the current working directory.' 'Existing keys are skipped successfully unless --force is supplied.' 'Values are written literally, without quoting, interpolation, or evaluation.' 'Writing the env file does not export the value into the calling shell.'; exit 0; ;; --) shift; break; ;; -*) printf 'envkey: unknown option: %s\n' "$1" >&2; exit 2; ;; *) break; ;; esac; done; if [ "$#" -eq 3 ] && [ "$3" = --force ]; then envkey_force=1; set -- "$1" "$2"; fi; if [ "$#" -ne 2 ] || [ -z "$2" ]; then printf '%s\n' 'Usage: envkey [-f FILE | --file FILE] [--force] [--] ENV_VAR_NAME JSS_SOURCE_SECRET_NAME' 'Both positional arguments are names; the secret value is retrieved from jss internally.' >&2; exit 2; fi; envkey_key=$1; envkey_name=$2; case "$envkey_key" in ''|[0-9]*|*[^A-Za-z0-9_]*) printf 'envkey: invalid variable name: %s\n' "$envkey_key" >&2; exit 2; ;; esac; case "$envkey_file" in /*) ;; *) envkey_file=./$envkey_file; ;; esac; if [ -L "$envkey_file" ] || { [ -e "$envkey_file" ] && [ ! -f "$envkey_file" ]; }; then printf 'envkey: target must be a regular file, not a symlink: %s\n' "$envkey_file" >&2; exit 1; fi; envkey_source=/dev/null; if [ -e "$envkey_file" ]; then if [ ! -r "$envkey_file" ]; then printf 'envkey: cannot read file: %s\n' "$envkey_file" >&2; exit 1; fi; envkey_source=$envkey_file; fi; if envkey_count=$(command awk -v envkey_key="$envkey_key" ' BEGIN { pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envkey_key "[[:blank:]]*="; count = 0; while ((rc = getline line) > 0) { if (line ~ pattern) count++; } if (rc < 0) exit 5; printf "%d", count; } ' < "$envkey_source"); then :; else printf 'envkey: failed to inspect %s\n' "$envkey_file" >&2; exit 1; fi; if [ "$envkey_count" != 0 ] && [ "$envkey_force" -eq 0 ]; then printf 'envkey: %s already exists in %s; unchanged (use --force to update)\n' "$envkey_key" "$envkey_file" >&2; exit 0; fi; envkey_value="$(jss "$envkey_name")" || exit; case "$envkey_value" in *$'\n'*|*$'\r'*) printf '%s\n' 'envkey: jss must return a single-line value without CR or embedded LF' >&2; exit 3; ;; esac; if [ -L "$envkey_file" ] || { [ -e "$envkey_file" ] && [ ! -f "$envkey_file" ]; }; then printf 'envkey: target changed or is not a regular file: %s\n' "$envkey_file" >&2; exit 1; fi; envkey_source=/dev/null; if [ -e "$envkey_file" ]; then if [ ! -r "$envkey_file" ]; then printf 'envkey: cannot read file: %s\n' "$envkey_file" >&2; exit 1; fi; envkey_source=$envkey_file; fi; umask 077; envkey_tmp=$(command mktemp "${envkey_file}.envkey.XXXXXX") || exit 1; trap 'command rm -f "$envkey_tmp"' 0; trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM; if builtin printf '%s\n' "$envkey_value" | command awk -v envkey_key="$envkey_key" -v envkey_force="$envkey_force" ' BEGIN { if ((getline secret) != 1) exit 5; pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envkey_key "[[:blank:]]*="; found = 0; ending = ""; while ((rc = getline line < "/dev/fd/3") > 0) { ending = (line ~ /\r$/) ? "\r" : ""; if (match(line, pattern)) { if (envkey_force == 0) exit 10; if (found == 0) printf "%s%s%s\n", substr(line, 1, RLENGTH), secret, ending; found = 1; } else { printf "%s\n", line; } } if (rc < 0) exit 5; if (found == 0) printf "%s=%s%s\n", envkey_key, secret, ending; } ' 3< "$envkey_source" > "$envkey_tmp"; then :; else envkey_rc=$?; if [ "$envkey_rc" -eq 10 ]; then printf 'envkey: %s now exists in %s; unchanged (use --force to update)\n' "$envkey_key" "$envkey_file" >&2; exit 0; fi; printf 'envkey: failed to prepare update for %s\n' "$envkey_file" >&2; exit 1; fi; if [ -L "$envkey_file" ] || { [ -e "$envkey_file" ] && [ ! -f "$envkey_file" ]; }; then printf 'envkey: target changed or is not a regular file: %s\n' "$envkey_file" >&2; exit 1; fi; if command chmod 600 "$envkey_tmp" && command mv -f "$envkey_tmp" "$envkey_file"; then :; else printf 'envkey: failed to install update for %s\n' "$envkey_file" >&2; exit 1; fi; ); : 'Replace both quoted placeholders with names: ENV_VAR_NAME is the env-file variable name; JSS_SOURCE_SECRET_NAME is the existing jss secret name; the secret value is retrieved internally.'; envkey -f .env 'ENV_VAR_NAME' 'JSS_SOURCE_SECRET_NAME'
```

The `: 'Replace both quoted placeholders ...'` statement is a shell no-op containing the explanation. It is placed before the final call so the command returns `envkey`'s status. It works at a default interactive zsh prompt without requiring interactive comments to be enabled.

Change only the final invocation to choose your file, destination variable name, JSS source secret name, and force behavior. For example, replace the end of that same line with one of these complete invocations:

```bash
envkey -f .env.local API_KEY MY_SERVICE_API_KEY
```

```bash
envkey -f .env.local --force API_KEY MY_SERVICE_API_KEY
```

```bash
envkey -f .env.backup API_KEY MY_SERVICE_API_KEY --force
```

These examples are alternatives for the final call; the full one-liner already includes the function definition. After running the complete line at an interactive prompt, `envkey` stays declared in that shell for subsequent calls.

The text file contains that complete line unchanged. After replacing the two placeholder names in its final invocation, it can also be executed directly through an interpreter:

```bash
bash ./envkey-one-liner.md
```

The placeholder words are literal names when executed; they do not automatically read shell environment variables or substitute values. Replace them with the names you actually use before running the command. Running the file as a child process does not declare a function in the parent shell.

## 6. Complete reusable script: envkey.sh

Save the following complete source as `envkey.sh`, or use the supplied file. Executing it performs the requested operation. Sourcing it only declares the function; sourcing does not retrieve a secret or modify an env file.

```bash
#!/usr/bin/env bash
# envkey v2: retrieve a secret from jss and write a literal env-file assignment.
# Execute this file, or source it in Bash 3.2+ / zsh to declare envkey.
# Usage: envkey [-f FILE] [--force] ENV_VAR_NAME JSS_SOURCE_SECRET_NAME
# Both positional arguments are NAMES. Neither argument is the secret value.
# ENV_VAR_NAME is the destination name in the env file, such as API_KEY.
# JSS_SOURCE_SECRET_NAME names an existing jss entry; its value is fetched inside.
# API_KEY is a literal name; "$API_KEY" expands to that shell variable's value.
# This helper writes the file; it does not export a value into the calling shell.

# BEGIN_ENVKEY_FUNCTION
envkey() (
    # Check failures explicitly; isolate options, variables, and cleanup traps.
    set +eux;
    set -o pipefail;
    LC_ALL=C;
    export LC_ALL;
    envkey_file=.env;
    envkey_force=0;

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -f|--file)
                if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                    printf '%s\n' 'envkey: --file requires a nonempty path' >&2;
                    exit 2;
                fi;
                envkey_file=$2;
                shift 2;
                ;;
            --file=*)
                envkey_file=${1#*=};
                if [ -z "$envkey_file" ]; then
                    printf '%s\n' 'envkey: --file requires a nonempty path' >&2;
                    exit 2;
                fi;
                shift;
                ;;
            --force)
                envkey_force=1;
                shift;
                ;;
            -h|--help)
                # The $ in the help text is literal on purpose: it names the $API_KEY shell-expansion pitfall as text; it must not expand.
                # shellcheck disable=SC2016
                printf '%s\n' 'Usage: envkey [-f FILE | --file FILE] [--force] [--] ENV_VAR_NAME JSS_SOURCE_SECRET_NAME' 'Both positional arguments are names; neither is the secret value.' 'ENV_VAR_NAME: destination variable name in the env file, for example API_KEY.' 'JSS_SOURCE_SECRET_NAME: name of an existing secret in jss, for example MY_SERVICE_API_KEY.' 'Retrieve the value internally with: jss JSS_SOURCE_SECRET_NAME' 'Use the literal name API_KEY, not "$API_KEY" when that variable contains a secret value.' 'A trailing --force after JSS_SOURCE_SECRET_NAME is also accepted.' 'Default file: .env in the current working directory.' 'Existing keys are skipped successfully unless --force is supplied.' 'Values are written literally, without quoting, interpolation, or evaluation.' 'Writing the env file does not export the value into the calling shell.';
                exit 0;
                ;;
            --)
                shift;
                break;
                ;;
            -*)
                printf 'envkey: unknown option: %s\n' "$1" >&2;
                exit 2;
                ;;
            *)
                break;
                ;;
        esac;
    done;

    # Preserve the convenient "ENV_VAR_NAME JSS_SOURCE_SECRET_NAME --force" form.
    if [ "$#" -eq 3 ] && [ "$3" = --force ]; then
        envkey_force=1;
        set -- "$1" "$2";
    fi;
    if [ "$#" -ne 2 ] || [ -z "$2" ]; then
        printf '%s\n' 'Usage: envkey [-f FILE | --file FILE] [--force] [--] ENV_VAR_NAME JSS_SOURCE_SECRET_NAME' 'Both positional arguments are names; the secret value is retrieved from jss internally.' >&2;
        exit 2;
    fi;
    envkey_key=$1;
    # The second argument is a jss SOURCE NAME, not a supplied secret value.
    envkey_name=$2;
    case "$envkey_key" in
        ''|[0-9]*|*[^A-Za-z0-9_]*)
            printf 'envkey: invalid variable name: %s\n' "$envkey_key" >&2;
            exit 2;
            ;;
    esac;

    # A ./ prefix prevents leading-dash paths from becoming utility options.
    case "$envkey_file" in /*) ;; *) envkey_file=./$envkey_file; ;; esac;
    if [ -L "$envkey_file" ] || { [ -e "$envkey_file" ] && [ ! -f "$envkey_file" ]; }; then
        printf 'envkey: target must be a regular file, not a symlink: %s\n' "$envkey_file" >&2;
        exit 1;
    fi;
    envkey_source=/dev/null;
    if [ -e "$envkey_file" ]; then
        if [ ! -r "$envkey_file" ]; then
            printf 'envkey: cannot read file: %s\n' "$envkey_file" >&2;
            exit 1;
        fi;
        envkey_source=$envkey_file;
    fi;

    # Read errors must remain errors; no END block overrides getline's result.
    if envkey_count=$(command awk -v envkey_key="$envkey_key" '
        BEGIN {
            pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envkey_key "[[:blank:]]*=";
            count = 0;
            while ((rc = getline line) > 0) { if (line ~ pattern) count++; }
            if (rc < 0) exit 5;
            printf "%d", count;
        }
    ' < "$envkey_source"); then
        :;
    else
        printf 'envkey: failed to inspect %s\n' "$envkey_file" >&2;
        exit 1;
    fi;
    if [ "$envkey_count" != 0 ] && [ "$envkey_force" -eq 0 ]; then
        printf 'envkey: %s already exists in %s; unchanged (use --force to update)\n' "$envkey_key" "$envkey_file" >&2;
        exit 0;
    fi;

    # This assignment preserves jss's exit status and keeps its output off argv.
    envkey_value="$(jss "$envkey_name")" || exit;
    case "$envkey_value" in
        *$'\n'*|*$'\r'*)
            printf '%s\n' 'envkey: jss must return a single-line value without CR or embedded LF' >&2;
            exit 3;
            ;;
    esac;

    # Recheck after the lookup in case the path changed while jss was running.
    if [ -L "$envkey_file" ] || { [ -e "$envkey_file" ] && [ ! -f "$envkey_file" ]; }; then
        printf 'envkey: target changed or is not a regular file: %s\n' "$envkey_file" >&2;
        exit 1;
    fi;
    envkey_source=/dev/null;
    if [ -e "$envkey_file" ]; then
        if [ ! -r "$envkey_file" ]; then
            printf 'envkey: cannot read file: %s\n' "$envkey_file" >&2;
            exit 1;
        fi;
        envkey_source=$envkey_file;
    fi;

    umask 077;
    envkey_tmp=$(command mktemp "${envkey_file}.envkey.XXXXXX") || exit 1;
    trap 'command rm -f "$envkey_tmp"' 0;
    trap 'exit 129' HUP;
    trap 'exit 130' INT;
    trap 'exit 143' TERM;

    # The secret travels through stdin, never through awk -v or a replacement.
    # fd 3 supplies the original file; filenames never become awk arguments.
    if builtin printf '%s\n' "$envkey_value" | command awk -v envkey_key="$envkey_key" -v envkey_force="$envkey_force" '
        BEGIN {
            if ((getline secret) != 1) exit 5;
            pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envkey_key "[[:blank:]]*=";
            found = 0;
            ending = "";
            while ((rc = getline line < "/dev/fd/3") > 0) {
                ending = (line ~ /\r$/) ? "\r" : "";
                if (match(line, pattern)) {
                    if (envkey_force == 0) exit 10;
                    if (found == 0) printf "%s%s%s\n", substr(line, 1, RLENGTH), secret, ending;
                    found = 1;
                } else {
                    printf "%s\n", line;
                }
            }
            if (rc < 0) exit 5;
            if (found == 0) printf "%s=%s%s\n", envkey_key, secret, ending;
        }
    ' 3< "$envkey_source" > "$envkey_tmp"; then
        :;
    else
        envkey_rc=$?;
        if [ "$envkey_rc" -eq 10 ]; then
            printf 'envkey: %s now exists in %s; unchanged (use --force to update)\n' "$envkey_key" "$envkey_file" >&2;
            exit 0;
        fi;
        printf 'envkey: failed to prepare update for %s\n' "$envkey_file" >&2;
        exit 1;
    fi;

    if [ -L "$envkey_file" ] || { [ -e "$envkey_file" ] && [ ! -f "$envkey_file" ]; }; then
        printf 'envkey: target changed or is not a regular file: %s\n' "$envkey_file" >&2;
        exit 1;
    fi;
    if command chmod 600 "$envkey_tmp" && command mv -f "$envkey_tmp" "$envkey_file"; then
        :;
    else
        printf 'envkey: failed to install update for %s\n' "$envkey_file" >&2;
        exit 1;
    fi;
)
# END_ENVKEY_FUNCTION

# Sourcing declares the function; executing calls it with the script arguments.
if [ -n "${ZSH_VERSION-}" ]; then
    case "${ZSH_EVAL_CONTEXT-}" in
        toplevel) envkey "$@" ;;
        *) ;;
    esac
elif [ -n "${BASH_VERSION-}" ]; then
    if [ "${BASH_SOURCE[0]-}" = "$0" ]; then
        envkey "$@"
    fi
else
    printf '%s\n' 'envkey.sh: use Bash or zsh to run or source this file' >&2
    # shellcheck disable=SC2317
    return 2 2>/dev/null || exit 2
fi
```

The shebang selects Bash when you execute the file directly. Sourcing it in zsh uses the shared implementation in the current zsh session. Loading its text with `eval "$(cat envkey.sh)"` or `-c "$(cat envkey.sh)"` only declares the function and ignores any arguments; run the file itself to execute it. Run or source it with Bash or zsh, not with `sh`.

## 7. Install and load the function

From the directory containing the downloaded or saved `envkey.sh`:

```bash
mkdir -p "$HOME/.config/env-tools"
cp ./envkey.sh "$HOME/.config/env-tools/envkey.sh"
chmod 700 "$HOME/.config/env-tools/envkey.sh"
```

### Execute without declaring a function

```bash
"$HOME/.config/env-tools/envkey.sh" -f .env.local API_KEY MY_SERVICE_API_KEY
"$HOME/.config/env-tools/envkey.sh" -f .env.local --force API_KEY MY_SERVICE_API_KEY
"$HOME/.config/env-tools/envkey.sh" --help
```

To choose macOS's system Bash explicitly:

```bash
/bin/bash "$HOME/.config/env-tools/envkey.sh" -f .env.backup API_KEY MY_SERVICE_API_KEY
```

Executing the script runs a child process and does not declare a function in your current terminal. Source it when you want the short `envkey` command in that session.

### Declare the function immediately

Both Bash and zsh support:

```bash
source "$HOME/.config/env-tools/envkey.sh"
```

The dot spelling is equivalent:

```bash
. "$HOME/.config/env-tools/envkey.sh"
```

Then use the function:

```bash
envkey -f .env.local API_KEY MY_SERVICE_API_KEY
envkey -f .env.local --force API_KEY MY_SERVICE_API_KEY
```

## 8. Load automatically when your shell starts

These are shell-startup settings, not machine-boot hooks. No reboot is needed. Source the file once to use the function now; the configuration loads it in future shell sessions.

### zsh: ~/.zshrc

Add this block to `~/.zshrc`:

```bash
if [ -r "$HOME/.config/env-tools/envkey.sh" ]; then
    source "$HOME/.config/env-tools/envkey.sh"
fi
```

If you have set `ZDOTDIR`, use `$ZDOTDIR/.zshrc` instead. `.zshrc` is read by interactive zsh sessions. `.zprofile` is read by login shells only; put the block there when you specifically want login-shell-only loading. [zsh startup-file reference](https://zsh.sourceforge.io/Doc/Release/Files.html)

### Bash: ~/.bashrc and your login profile

Add the same block to `~/.bashrc`:

```bash
if [ -r "$HOME/.config/env-tools/envkey.sh" ]; then
    source "$HOME/.config/env-tools/envkey.sh"
fi
```

For interactive login Bash sessions, make sure the login profile you already use loads `.bashrc`:

```bash
if [ -r "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi
```

Bash checks `~/.bash_profile`, `~/.bash_login`, and `~/.profile` in that order and reads the first readable file. Add the block to the profile you already use: creating a higher-priority profile can change which existing configuration is loaded. [Bash startup-file reference](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files)

You do not need `export -f envkey`. That is Bash-specific and is not a shared Bash/zsh setup mechanism. Sourcing declares the function in either shell.

## 9. Use inside scripts

Noninteractive scripts should source the helper explicitly or execute its installed path. Do not depend on interactive startup files being loaded.

### Bash script

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$HOME/.config/env-tools/envkey.sh"
envkey -f "/absolute/path/to/.env.local" API_KEY MY_SERVICE_API_KEY
```

### zsh script

```zsh
#!/usr/bin/env zsh
set -euo pipefail

source "$HOME/.config/env-tools/envkey.sh"
envkey -f "/absolute/path/to/.env.local" API_KEY MY_SERVICE_API_KEY
```

The full one-liner in section 5 can also be used directly in either script. It already defines and invokes the function, so no separate `source` step is needed for that form.

Variables, option changes, locale changes, `umask`, and cleanup traps inside `envkey` are scoped to a subshell, leaving the caller's corresponding settings unchanged. An existing-key skip returns `0`; actual failures return nonzero. With `set -e`, an unhandled failure stops the calling script according to its normal shell rules.

## 10. How jss is called, and command substitution

This implementation calls the interface you provided:

```text
jss JSS_SOURCE_SECRET_NAME
```

It expects the command's standard output to contain only the secret and an optional trailing newline. Diagnostic or authentication messages should go to standard error. `envkey` does not infer a failure from text: `jss` must return nonzero on failure. A successful empty result is an intentionally empty value.

For standalone execution, make `jss` available as an executable command in `PATH`. When sourcing the helper or using the one-liner, an existing shell function named `jss` can also work. Do not rely on aliases as the shared Bash/zsh interface.

The writer intentionally takes a **JSS name**, so call it like this:

```bash
envkey API_KEY MY_SERVICE_API_KEY
```

Do not replace that second argument with `"$(jss MY_SERVICE_API_KEY)"`: in this version, that would supply the retrieved secret as the name for another `jss` lookup. Looking up the value internally also lets `envkey` check for an existing key before retrieving any secret, and preserve a failed lookup's exit status before doing any write.

For shell syntax generally, double quotes allow command substitution while retaining its output as one argument; single quotes keep the text literal. For example, `"$(jss MY_SERVICE_API_KEY)"` performs a lookup, whereas `'$(jss MY_SERVICE_API_KEY)'` is literal text. Substitution output is not parsed again as shell source. Command substitution removes trailing newlines. [Bash command-substitution reference](https://www.gnu.org/software/bash/manual/html_node/Command-Substitution.html)

Within this writer, the secret does not appear in an external command's argument list. Shell tracing is disabled inside the function before lookup. The writer does not print the secret, although `jss`'s standard error is passed through unchanged. The implementation does not call `jss add`; it only retrieves existing secrets.

## 11. File replacement and errors

Successful writes are prepared in a temporary file beside the destination, set to mode `600` (read/write for the owner), and installed with a same-directory rename. An existing-key skip leaves the old permissions untouched. The temporary file is removed on normal exit and handled HUP, INT, and TERM signals.

Lookup failures, rejected values, read failures, and detected preparation/install failures return nonzero without installing the temporary output. The tests exercise these failure paths using mock commands. As with ordinary cleanup traps, an uncatchable termination or machine failure can leave a temporary file behind.

Replacement creates a new file inode. A successful update does not preserve the original inode, hard-link relationships, or arbitrary file metadata such as extended attributes and ACLs. It intentionally sets the result's mode to `600`.

The rename prevents exposing a partially written replacement during an ordinary update. It is **not a lock or a transaction across concurrent writers**: another process editing the same target can still race with this helper. Use it when you control writes to the env file; serialize multiple writers if your workflow has them.

| Status | Meaning |
| --- | --- |
| `0` | Successful add/update, existing-key skip, or help. |
| `1` | File/type/read error or temporary-file, processing, permission, or install failure. |
| `2` | Invalid options/arguments, invalid variable name, or empty JSS name. |
| `3` | The retrieved value contains a carriage return or an embedded line feed. |
| Nonzero status from `jss` | Lookup failed; its exit status is propagated and no update is installed. |

A `jss` failure can use a numeric status that also appears in this table. Its original status is deliberately preserved; use the accompanying diagnostic to identify the source. If `jss` is unavailable, the shell's command-not-found failure propagates as well.

## 12. Verification and optional test runner

The exact delivered v2 script and one-liner passed **804 checks with zero failures** on Linux using actual GNU Bash 3.2.0, GNU Bash 5.2.37, and zsh 5.9. Each shell ran 88 cases across three invocation forms plus four startup/name-handling checks: 268 checks per shell.

The checks cover creation/appending, exact-key matching, default skipping before lookup, forced replacement and duplicate removal, symbols, command-looking text, Unicode, whitespace, empty values, custom paths, CRLF and missing final newlines, strict scripts, exit statuses, file mode, unchanged bytes/permissions/mtime on skipped or failed operations, temporary-file cleanup, and absence of secret values from `awk` arguments or shell tracing. Mocked failures exercise lookup, inspection, rewriting, temporary-file creation, permission-setting, and installation.

The v2 checks verify the explicit names-versus-values help, shell variables that deliberately hold the two names, and preservation of an existing exported `API_KEY` in the calling shell. They execute the entire delivered one-liner with its explanation and final placeholder invocation in interactive Bash and zsh with history expansion enabled. The line uses a quoted no-op annotation, so it does not depend on zsh's interactive-comment option. Source-only and source-inside-a-function checks verify that loading the helper declares it without retrieving or writing a secret.

Only synthetic values and a mock `jss` were used. The included `test_envkey.py` is the runner from that final passing run.

Native macOS execution was not available for these checks. The implementation uses shared Bash/zsh syntax, standard `awk` operations, `/dev/fd/3`, and no GNU-only command-line options. The tests used an actual Bash 3.2 executable, rather than only a compatibility mode in a newer Bash.

The optional `test_envkey.py` uses Python 3.7+ and only the standard library. It creates disposable files under the current working directory and uses its own mock `jss`; it does not retrieve or modify real secrets. Keep it beside `envkey.sh` and `envkey-one-liner.md`, then run:

```bash
python3 test_envkey.py
```

To choose specific installed shells, including macOS's system interpreters:

```bash
python3 test_envkey.py --shell /bin/bash --shell /bin/zsh
```

Python is optional and is not required to run the writer itself.

## References

- [Bash startup files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files)
- [zsh startup files](https://zsh.sourceforge.io/Doc/Release/Files.html)
- [Bash command substitution](https://www.gnu.org/software/bash/manual/html_node/Command-Substitution.html)
- [Bash simple-command expansion and assignment exit status](https://www.gnu.org/software/bash/manual/html_node/Simple-Command-Expansion.html)
- [python-dotenv's description of dotenv file syntax](https://github.com/theskumar/python-dotenv/blob/main/README.md#file-format)
