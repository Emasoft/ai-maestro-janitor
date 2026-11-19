# envget v2: read an env-file value by its variable name

`envget` reads a value from an env file and either prints it or saves it with `jss add`. **Its arguments are names, never the secret value itself.** It supports Bash 3.2+ and zsh, including prompts and scripts. The helper uses standard `awk`; Python is only needed for the optional tests.

## The four reader files

| File | Purpose |
| --- | --- |
| `envget.sh` | Execute a read/import operation, or source it to declare `envget`. |
| `envget-one-liner.md` | Complete independent function, explicit argument explanation, and immediate read invocation on one physical line. |
| `envget-usage.md` | This complete guide, including the exact script and one-liner. |
| `test_envget.py` | Tests using synthetic values and a mock `jss`. |

The files are `envget.sh`, `envget-one-liner.md`, `envget-usage.md` and `test_envget.py`. The shell function is named **`envget`**.

## 1. Variable name, JSS destination name, and secret value

```text
envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]
```

| Term | Meaning | Example |
| --- | --- | --- |
| `ENV_VAR_NAME` | The variable **name** before `=` in the env file. | `API_KEY` |
| `JSS_DESTINATION_SECRET_NAME` | Optional destination **name** to add in `jss`. | `MY_SERVICE_API_KEY` |
| Secret value | The actual password, token, key, or other value, read internally from the file. It is not an argument to `envget`. | `example-secret-123` |

These uppercase terms are descriptive placeholders. Replace them with your own names. Do not paste angle brackets around them: `<` and `>` are shell redirection operators.

### Read a value

Suppose `.env` contains this assignment:

```dotenv
API_KEY=example-secret-123
```

Run:

```bash
envget API_KEY
```

Here `API_KEY` is the literal variable **name**, not the value. The command prints:

```text
example-secret-123
```

No `jss` operation occurs when you supply only the variable name.

### Read and add the value to jss

```bash
envget API_KEY MY_SERVICE_API_KEY
```

In this example, `API_KEY` is the source variable **name in `.env`**, and `MY_SERVICE_API_KEY` is the destination secret **name in `jss`**. The function reads `example-secret-123` from the file and internally makes the equivalent call:

```bash
jss add MY_SERVICE_API_KEY 'example-secret-123'
```

The value in that lower-level `jss add` call is filled in by `envget`. You do not supply it as an `envget` argument. `envget` does not retrieve `jss MY_SERVICE_API_KEY`; it uses that name as the destination for `jss add`.

### API_KEY is a name; $API_KEY expands to a value

| Form | Meaning |
| --- | --- |
| `envget API_KEY` | Correct: read the env-file variable named `API_KEY`. |
| `envget API_KEY MY_SERVICE_API_KEY` | Correct: read `API_KEY` from the file and add its value under the JSS destination name `MY_SERVICE_API_KEY`. |
| `envget "$API_KEY"` | The shell expands `$API_KEY` first and uses its current value as the variable name to look up. This is normally incorrect when `API_KEY` contains a secret value. |
| `envget <API_KEY_VALUE>` | Not the interface: actual secret values are not accepted in that position, and literal angle brackets have shell redirection meanings. |

`API_KEY` does not need to be defined or exported in the current shell. Even if it is exported, `envget API_KEY` reads the assignment in the selected file. Exporting a variable makes its value available to child processes; it does not make `$API_KEY` expand to the name `API_KEY`.

Neither `envget` nor `envkey` exports a retrieved secret into the calling shell. This reader prints a value or passes it to `jss add`; the writer writes an assignment to a file.

If a shell variable intentionally contains a **name**, quoted expansion is appropriate:

```bash
env_var_name='API_KEY'
jss_destination_secret_name='MY_SERVICE_API_KEY'
envget "$env_var_name" "$jss_destination_secret_name"
```

Here the two shell variables hold the two names. The secret's actual value still comes from the env file.

### Direction of the two helpers

| Helper | First name | Second name | Where the actual value comes from |
| --- | --- | --- | --- |
| `envkey ENV_VAR_NAME JSS_SOURCE_SECRET_NAME` | Destination variable name in the env file. | Existing source secret name to retrieve from `jss`. | `jss JSS_SOURCE_SECRET_NAME`. |
| `envget ENV_VAR_NAME` | Source variable name in the env file. | None. | The selected env file; the value is printed. |
| `envget ENV_VAR_NAME JSS_DESTINATION_SECRET_NAME` | Source variable name in the env file. | Destination secret name to add in `jss`. | The selected env file; the value is passed to `jss add`. |

Neither helper has a direct secret-value argument. Use a JSS **source** name for `envkey` and an optional JSS **destination** name for `envget`.

### Options and file paths

| Form | Result |
| --- | --- |
| `envget API_KEY` | Print the value of the variable named `API_KEY` in `.env`. |
| `envget -f .env.local API_KEY` | Read it from `.env.local`. |
| `envget --file .env.backup API_KEY` | Read it from `.env.backup`. |
| `envget --file=.env.local API_KEY` | Equivalent long-option form. |
| `envget -f .env.local API_KEY MY_SERVICE_API_KEY` | Read `API_KEY` and add its value under the destination name `MY_SERVICE_API_KEY` in `jss`. |
| `envget --help` | Show the argument names and their meanings. |

Put options before `ENV_VAR_NAME`. The variable name must be an ASCII identifier: a letter or underscore followed by letters, digits, or underscores. Matching is case-sensitive. The optional JSS destination name must be nonempty; `jss` determines which destination names it accepts.

The default file is `.env` in the **current working directory**. Relative paths are also relative to that directory, not beside `envget.sh`. Any filename is accepted; there is no extension restriction.

Quote paths containing spaces:

```bash
envget -f "/Users/User/Project Secrets/.env.backup" API_KEY
envget -f "/Users/User/Project Secrets/.env.backup" API_KEY MY_SERVICE_API_KEY
```

The optional final argument is always the destination name in `jss`. It is never the env-file path or the secret value.

## 2. Password symbols and the literal file format

Symbols in a stored value are treated as data. Dollar signs, exclamation marks, both quote characters, backticks, backslashes, equals signs, glob characters, brackets, parentheses, semicolons, ampersands, pipes, spaces, and UTF-8 text are preserved. The helper never sources or evaluates the env file.

It reads **everything after the assignment's first `=` literally**, preserving leading and trailing spaces in the value. It accepts optional indentation, `export`, and whitespace before `=`:

```dotenv
PASSWORD=pa$$!word#with=equals
export API_KEY=abc123==
  OTHER_KEY =another-value
EMPTY=
```

This deliberately matches the literal, unquoted format used by the companion `envkey.sh` writer. It is not a general dotenv parser:

| File entry | Literal value returned |
| --- | --- |
| `PASSWORD=abc#def` | `abc#def` |
| `PASSWORD="abc"` | `"abc"`, including both quotation marks |
| `PASSWORD=abc # note` | `abc # note`, including the space and comment-looking text |
| `PASSWORD=${OTHER}` | `${OTHER}` literally |
| `PASSWORD=abc\nxyz` | `abc\nxyz`, with a backslash and the letter `n` |

Do not add surrounding quotes or escape characters solely for this helper: they would become part of the retrieved password. If your application writes quoted, escaped, interpolated, or multiline dotenv values, use that application's parser to decode those values instead of treating them as this literal format.

Each value must fit on one physical line. NUL bytes and binary/multiline secrets are unsupported. CRLF file endings are accepted by removing the final carriage return of each record. A missing final newline is also accepted. An explicitly empty assignment is a valid empty value.

Comment-only lines and similarly named variables are ignored. If the requested key is absent or appears more than once, the helper returns an error before printing a value or calling `jss`, even when duplicate values are identical.

## 3. Independent one-liner

The supplied line is a complete independent command: it defines `envget`, includes a plain-language argument explanation, and immediately reads a named value from `.env`. It needs no installed `envget.sh` file. Paste it at a Bash or zsh prompt, or put it in a Bash or zsh script.

**Before running it, replace the final quoted `'ENV_VAR_NAME'` placeholder with the actual variable name in your env file, such as `'API_KEY'`. Do not put the secret value there.**

The display may wrap it, but the command is one physical line.

```bash
envget() ( set +xu; LC_ALL=C; export LC_ALL; envget_file=.env; while [ "$#" -gt 0 ]; do case "$1" in -f|--file) if [ "$#" -lt 2 ] || [ -z "$2" ]; then printf '%s\n' 'envget: --file requires a nonempty path' >&2; exit 2; fi; envget_file=$2; shift 2; ;; --file=*) envget_file=${1#*=}; if [ -z "$envget_file" ]; then printf '%s\n' 'envget: --file requires a nonempty path' >&2; exit 2; fi; shift; ;; -h|--help) printf '%s\n' 'Usage: envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]' 'ENV_VAR_NAME: variable NAME inside the env file, not its current shell value.' 'JSS_DESTINATION_SECRET_NAME: optional destination secret NAME to add in jss.' 'Both positional arguments are names; do not pass a secret value.' 'The value is read internally from the env file.' 'With ENV_VAR_NAME only, print the value read from that file.' 'With a destination name, call: jss add JSS_DESTINATION_SECRET_NAME VALUE_READ_FROM_FILE' 'Default file: .env in the current working directory.' 'Example: envget API_KEY MY_SERVICE_API_KEY' 'Here API_KEY is the name in .env; MY_SERVICE_API_KEY is the destination name in jss.' 'Use API_KEY literally; $API_KEY expands to its current shell value.' 'Missing or duplicate keys are errors. Values are not evaluated or unquoted.'; exit 0; ;; --) shift; break; ;; -*) printf 'envget: unknown option: %s\n' "$1" >&2; exit 2; ;; *) break; ;; esac; done; if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then printf '%s\n' 'Usage: envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]' 'Both positional arguments are names; the value is read from the env file.' >&2; exit 2; fi; envget_key=$1; case "$envget_key" in ''|[0-9]*|*[^A-Za-z0-9_]*) printf 'envget: invalid variable name: %s\n' "$envget_key" >&2; exit 2; ;; esac; if [ "$#" -eq 2 ] && [ -z "$2" ]; then printf '%s\n' 'envget: JSS_DESTINATION_SECRET_NAME must not be empty' >&2; exit 2; fi; if [ ! -f "$envget_file" ] || [ ! -r "$envget_file" ]; then printf 'envget: cannot read file: %s\n' "$envget_file" >&2; exit 1; fi; if envget_value=$(awk -v envget_key="$envget_key" ' BEGIN { pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envget_key "[[:blank:]]*="; } { sub(/\r$/, ""); if (match($0, pattern)) { count++; value = substr($0, RLENGTH + 1); } } END { if (count == 0) exit 4; if (count > 1) exit 3; printf "%s", value; } ' < "$envget_file"); then :; else envget_rc=$?; case "$envget_rc" in 3) printf 'envget: %s appears more than once in %s\n' "$envget_key" "$envget_file" >&2; exit 3; ;; 4) printf 'envget: %s was not found in %s\n' "$envget_key" "$envget_file" >&2; exit 4; ;; *) printf 'envget: failed to read %s\n' "$envget_file" >&2; exit 1; ;; esac; fi; if [ "$#" -eq 2 ]; then jss add "$2" "$envget_value"; else printf '%s\n' "$envget_value"; fi; ); : 'Replace ENV_VAR_NAME with the variable name in the env file, not its value. An optional second positional argument is JSS_DESTINATION_SECRET_NAME: the destination name to add in jss, not a secret value.'; envget -f .env 'ENV_VAR_NAME'
```

The quoted `: '...'` statement immediately before the final call contains the explanation. It is a harmless shell no-op, compatible with Bash and default interactive zsh. The actual `envget` invocation is last, so its success or failure remains the line's exit status.

Change only that final invocation to select another operation. For example, the end of that same line can be:

```bash
envget -f .env.local 'API_KEY'
```

This reads the value under the **variable name** `API_KEY` and prints it. To read that same variable and add its value under the **JSS destination name** `MY_SERVICE_API_KEY`, use:

```bash
envget -f .env.backup 'API_KEY' 'MY_SERVICE_API_KEY'
```

The quotes make those strings literal arguments; they do not turn the names into secret values. No secret value is supplied in either example.

These are alternatives for the final invocation, not extra setup steps. The complete line already contains the function definition. After running it at an interactive prompt, `envget` remains declared in that shell.

## 4. Complete reusable script: envget.sh

Save the following complete source as `envget.sh`, or use the supplied file. It has two behaviors:

- **Execute it:** perform the requested read/import operation.
- **Source it:** declare `envget` in the current Bash or zsh session without reading any secret or calling `jss`. Loading its text with `eval "$(cat envget.sh)"` or `bash -c`/`zsh -c "$(cat envget.sh)"` also only declares the function and ignores any arguments; run the file itself to execute it.

```bash
#!/usr/bin/env bash
# envget v2: read a literal, single-line value from an env file.
# Execute this file, or source it in Bash 3.2+ / zsh to declare envget.
# Usage: envget [-f FILE] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]
# ENV_VAR_NAME is the variable NAME inside the env file, never its value.
# The optional second argument is the destination secret NAME in jss.
# The value is read internally, then printed or passed to jss add.
# Example: envget API_KEY MY_SERVICE_API_KEY reads API_KEY from .env and
# calls jss add with destination name MY_SERVICE_API_KEY and that read value.

# BEGIN_ENVGET_FUNCTION
envget() (
    # All option and variable changes stay inside this subshell.
    set +xu;
    LC_ALL=C;
    export LC_ALL;
    envget_file=.env;

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -f|--file)
                if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                    printf '%s\n' 'envget: --file requires a nonempty path' >&2;
                    exit 2;
                fi;
                envget_file=$2;
                shift 2;
                ;;
            --file=*)
                envget_file=${1#*=};
                if [ -z "$envget_file" ]; then
                    printf '%s\n' 'envget: --file requires a nonempty path' >&2;
                    exit 2;
                fi;
                shift;
                ;;
            -h|--help)
                # The $ in the help text is literal on purpose: it names the $API_KEY shell-expansion pitfall as text; it must not expand.
                # shellcheck disable=SC2016
                printf '%s\n' 'Usage: envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]' 'ENV_VAR_NAME: variable NAME inside the env file, not its current shell value.' 'JSS_DESTINATION_SECRET_NAME: optional destination secret NAME to add in jss.' 'Both positional arguments are names; do not pass a secret value.' 'The value is read internally from the env file.' 'With ENV_VAR_NAME only, print the value read from that file.' 'With a destination name, call: jss add JSS_DESTINATION_SECRET_NAME VALUE_READ_FROM_FILE' 'Default file: .env in the current working directory.' 'Example: envget API_KEY MY_SERVICE_API_KEY' 'Here API_KEY is the name in .env; MY_SERVICE_API_KEY is the destination name in jss.' 'Use API_KEY literally; $API_KEY expands to its current shell value.' 'Missing or duplicate keys are errors. Values are not evaluated or unquoted.';
                exit 0;
                ;;
            --)
                shift;
                break;
                ;;
            -*)
                printf 'envget: unknown option: %s\n' "$1" >&2;
                exit 2;
                ;;
            *)
                break;
                ;;
        esac;
    done;

    if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
        printf '%s\n' 'Usage: envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]' 'Both positional arguments are names; the value is read from the env file.' >&2;
        exit 2;
    fi;
    # First positional argument: the NAME before = in the env file.
    envget_key=$1;
    case "$envget_key" in
        ''|[0-9]*|*[^A-Za-z0-9_]*)
            printf 'envget: invalid variable name: %s\n' "$envget_key" >&2;
            exit 2;
            ;;
    esac;
    if [ "$#" -eq 2 ] && [ -z "$2" ]; then
        printf '%s\n' 'envget: JSS_DESTINATION_SECRET_NAME must not be empty' >&2;
        exit 2;
    fi;
    if [ ! -f "$envget_file" ] || [ ! -r "$envget_file" ]; then
        printf 'envget: cannot read file: %s\n' "$envget_file" >&2;
        exit 1;
    fi;

    # Only the validated public variable name is an awk argument.
    # The secret is read through stdin and emitted only for one exact match.
    if envget_value=$(awk -v envget_key="$envget_key" '
        BEGIN { pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envget_key "[[:blank:]]*="; }
        { sub(/\r$/, ""); if (match($0, pattern)) { count++; value = substr($0, RLENGTH + 1); } }
        END { if (count == 0) exit 4; if (count > 1) exit 3; printf "%s", value; }
    ' < "$envget_file"); then
        :;
    else
        envget_rc=$?;
        case "$envget_rc" in
            3) printf 'envget: %s appears more than once in %s\n' "$envget_key" "$envget_file" >&2; exit 3; ;;
            4) printf 'envget: %s was not found in %s\n' "$envget_key" "$envget_file" >&2; exit 4; ;;
            *) printf 'envget: failed to read %s\n' "$envget_file" >&2; exit 1; ;;
        esac;
    fi;

    if [ "$#" -eq 2 ]; then
        # $2 is the destination NAME; envget_value is the value read from FILE.
        # Quoting preserves the complete value as one argument to jss.
        jss add "$2" "$envget_value";
    else
        printf '%s\n' "$envget_value";
    fi;
)
# END_ENVGET_FUNCTION

# Sourcing declares the function; executing calls it with the script arguments.
# Use the appropriate source detector for each supported shell.
if [ -n "${ZSH_VERSION-}" ]; then
    case "${ZSH_EVAL_CONTEXT-}" in
        toplevel) envget "$@" ;;
        *) ;;
    esac
elif [ -n "${BASH_VERSION-}" ]; then
    if [ "${BASH_SOURCE[0]-}" = "$0" ]; then
        envget "$@"
    fi
else
    printf '%s\n' 'envget.sh: use Bash or zsh to run or source this file' >&2
    # shellcheck disable=SC2317
    return 2 2>/dev/null || exit 2
fi
```

The shebang selects Bash when the file is executed directly. Sourcing it in zsh uses the shared implementation directly; it does not start a Bash subprocess just to define the function.

## 5. Install the script

From the directory containing the downloaded or saved `envget.sh`:

```bash
mkdir -p "$HOME/.config/env-tools"
cp ./envget.sh "$HOME/.config/env-tools/envget.sh"
chmod 700 "$HOME/.config/env-tools/envget.sh"
```

### Execute it without loading a function

```bash
"$HOME/.config/env-tools/envget.sh" -f .env.local API_KEY
"$HOME/.config/env-tools/envget.sh" -f .env.local API_KEY MY_SERVICE_API_KEY
"$HOME/.config/env-tools/envget.sh" --help
```

To select macOS's system Bash explicitly, you can also run:

```bash
/bin/bash "$HOME/.config/env-tools/envget.sh" -f .env.backup API_KEY
```

Executing the script does not declare a function in the parent terminal session. Use sourcing for that.

### Load the function immediately

This works in both Bash and zsh:

```bash
source "$HOME/.config/env-tools/envget.sh"
```

You can then use:

```bash
envget -f .env.local API_KEY
envget -f .env.local API_KEY MY_SERVICE_API_KEY
envget --help
```

The portable dot spelling also works:

```bash
. "$HOME/.config/env-tools/envget.sh"
```

## 6. Load it automatically when your shell starts

These are shell-startup settings, not machine-boot hooks. No reboot is required. Source the file once to use it now; the startup configuration loads it in future shells.

### zsh: ~/.zshrc

Add this block to `~/.zshrc`:

```bash
if [ -r "$HOME/.config/env-tools/envget.sh" ]; then
    source "$HOME/.config/env-tools/envget.sh"
fi
```

If you have configured `ZDOTDIR`, use `$ZDOTDIR/.zshrc` instead of `~/.zshrc`.

`.zshrc` is the appropriate place for a function you want in every interactive zsh. `.zprofile` is read by login shells only; putting the block there alone does not cover non-login interactive shells. You can use `.zprofile` when you specifically want login-shell-only loading.

### Bash: ~/.bashrc and your login profile

Add the same block to `~/.bashrc`:

```bash
if [ -r "$HOME/.config/env-tools/envget.sh" ]; then
    source "$HOME/.config/env-tools/envget.sh"
fi
```

For interactive login Bash sessions, ensure your existing login profile loads `.bashrc`:

```bash
if [ -r "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi
```

Put that block in the login profile you already use. Bash checks `~/.bash_profile`, `~/.bash_login`, and `~/.profile` in that order and reads the first readable one. Creating a new higher-priority profile can therefore change which existing configuration is loaded.

You do not need `export -f envget`. That is a Bash-specific facility, not a shared Bash/zsh setup mechanism. Sourcing the script is the way to declare this function in either shell.

## 7. Use it inside scripts

Noninteractive scripts should explicitly source the helper or execute its installed path. Do not assume they will load your interactive startup files.

### Bash script

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$HOME/.config/env-tools/envget.sh"
envget -f "/absolute/path/to/.env.local" API_KEY MY_SERVICE_API_KEY
```

### zsh script

```zsh
#!/usr/bin/env zsh
set -euo pipefail

source "$HOME/.config/env-tools/envget.sh"
envget -f "/absolute/path/to/.env.local" API_KEY MY_SERVICE_API_KEY
```

The one-liner from section 3 is also usable directly in either script; it already defines and invokes the function, so that form needs no `source` statement.

The helper changes options and temporary variables inside a subshell, leaving the caller's settings intact. A missing key, duplicate key, read failure, or failed `jss add` returns a nonzero status. A successful read/import returns zero. An intentionally empty value is not treated as a missing key.

## 8. A symbol-heavy test password

In a disposable test directory, create a file using a **quoted heredoc delimiter**:

```bash
cat > envget-demo.env <<'ENVGET_DEMO'
PASSWORD=pa$$!'"`\*?[]{}();&|<>#%=+ with spaces
EMPTY=
ENVGET_DEMO
```

The quoted delimiter keeps the shell from expanding the test content while creating the file. Then read it:

```bash
envget -f envget-demo.env PASSWORD
```

The output is exactly:

```text
pa$$!'"`\*?[]{}();&|<>#%=+ with spaces
```

The helper adds one output newline for display; that newline is not part of the stored password. For importing a value into `jss`, the helper passes the value directly as one argument without adding that newline.

## 9. jss behavior and exit statuses

The import form uses the interface you supplied. The destination name is the optional second positional argument; `VALUE_READ_FROM_FILE` is filled in internally, not supplied as an argument to `envget`:

```text
jss add JSS_DESTINATION_SECRET_NAME VALUE_READ_FROM_FILE
```

The value is quoted when passed to `jss`, preserving it as exactly one argument. Shell tracing is disabled before handling it. The helper does not print the value itself in import mode, although output from `jss` is passed through.

For portable standalone execution, make `jss` available as a command in `PATH`. When the helper is sourced, an already defined shell function named `jss` can also be used. Do not rely on alias expansion as a cross-shell interface.

The supplied `jss add NAME VALUE` interface puts the secret in the external process's command-line arguments. Disabling tracing does not hide those arguments from process-inspection mechanisms. If `jss` supports a documented stdin-based input mode, that would require adapting this call to its actual syntax.

Existing destination names follow `jss add`'s own rules. This reader does not invent an overwrite flag or bypass a `jss` confirmation. The `--force` option from the earlier `envkey` writer is not an option of this `envget` reader.

| Status | Meaning |
| --- | --- |
| `0` | Successful read, successful `jss add`, or help. |
| `1` | Input file cannot be read or a read/processing error occurred. |
| `2` | Invalid arguments, option, variable name, or empty JSS destination name. |
| `3` | More than one active assignment for the requested key. |
| `4` | Requested key was not found. |
| `jss`'s status | After a successful read, import mode returns the status from `jss add`. |

`envget` never edits the input env file.

## 10. Verification and optional test runner

The exact delivered v2 script and generated one-liner were tested on Linux with actual GNU Bash 3.2.0, GNU Bash 5.2.37, and zsh 5.9. The final run passed **531 checks with zero failures**: 58 cases across three invocation forms, plus three usage checks, for each of three shells.

Checks include symbol-heavy and Unicode values, whitespace, empty values, exact names, duplicate refusal, CRLF, missing final newlines, custom paths, strict scripts, source-versus-execute behavior, error propagation, and exact name/value arguments passed to a mock `jss`. New v2 checks verify explicit help text, reading by name despite a different exported shell value, JSS destination-name semantics, the documented dynamic-name examples, and the complete annotated one-liner in interactive shells. The zsh check explicitly leaves `INTERACTIVE_COMMENTS` disabled and enables history expansion.

The helper's input behavior is unchanged: the first argument is a variable name and the optional second argument is a JSS destination name. The v2 changes make those meanings explicit in the script, help, one-liner, guide, and test runner.

Native macOS execution was not available for these checks. The implementation uses shared Bash/zsh syntax and standard `awk` operations, with no GNU-only command-line options.

The optional `test_envget.py` requires Python 3.7 or later and uses only the standard library and dummy secrets. It does not call your real `jss`. Keep it beside `envget.sh` and `envget-one-liner.md`, then run:

```bash
python3 test_envget.py
```

To select particular shells:

```bash
python3 test_envget.py --shell /bin/bash --shell /bin/zsh
```

Python is needed only for this optional test runner, not for `envget` itself.

## References

- [Bash startup files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files)
- [zsh startup files](https://zsh.sourceforge.io/Doc/Release/Files.html)
- [Bash here-document quoting](https://www.gnu.org/software/bash/manual/html_node/Redirections.html)
- [python-dotenv's description of dotenv file syntax](https://github.com/theskumar/python-dotenv/blob/main/README.md#file-format)
