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
  set +xu
  LC_ALL=C
  export LC_ALL
  envget_file=.env

  while [ "$#" -gt 0 ]; do
    case "$1" in
    -f | --file)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        printf '%s\n' 'envget: --file requires a nonempty path' >&2
        exit 2
      fi
      envget_file=$2
      shift 2
      ;;
    --file=*)
      envget_file=${1#*=}
      if [ -z "$envget_file" ]; then
        printf '%s\n' 'envget: --file requires a nonempty path' >&2
        exit 2
      fi
      shift
      ;;
    -h | --help)
      # The $ in the help text is literal on purpose: it names the $API_KEY shell-expansion pitfall as text; it must not expand.
      # shellcheck disable=SC2016
      printf '%s\n' 'Usage: envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]' 'ENV_VAR_NAME: variable NAME inside the env file, not its current shell value.' 'JSS_DESTINATION_SECRET_NAME: optional destination secret NAME to add in jss.' 'Both positional arguments are names; do not pass a secret value.' 'The value is read internally from the env file.' 'With ENV_VAR_NAME only, print the value read from that file.' 'With a destination name, call: jss add JSS_DESTINATION_SECRET_NAME VALUE_READ_FROM_FILE' 'Default file: .env in the current working directory.' 'Example: envget API_KEY MY_SERVICE_API_KEY' 'Here API_KEY is the name in .env; MY_SERVICE_API_KEY is the destination name in jss.' 'Use API_KEY literally; $API_KEY expands to its current shell value.' 'Missing or duplicate keys are errors. Values are not evaluated or unquoted.'
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      printf 'envget: unknown option: %s\n' "$1" >&2
      exit 2
      ;;
    *)
      break
      ;;
    esac
  done

  if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    printf '%s\n' 'Usage: envget [-f FILE | --file FILE] [--] ENV_VAR_NAME [JSS_DESTINATION_SECRET_NAME]' 'Both positional arguments are names; the value is read from the env file.' >&2
    exit 2
  fi
  # First positional argument: the NAME before = in the env file.
  envget_key=$1
  case "$envget_key" in
  '' | [0-9]* | *[^A-Za-z0-9_]*)
    printf 'envget: invalid variable name: %s\n' "$envget_key" >&2
    exit 2
    ;;
  esac
  if [ "$#" -eq 2 ] && [ -z "$2" ]; then
    printf '%s\n' 'envget: JSS_DESTINATION_SECRET_NAME must not be empty' >&2
    exit 2
  fi
  if [ ! -f "$envget_file" ] || [ ! -r "$envget_file" ]; then
    printf 'envget: cannot read file: %s\n' "$envget_file" >&2
    exit 1
  fi

  # Only the validated public variable name is an awk argument.
  # The secret is read through stdin and emitted only for one exact match.
  if envget_value=$(awk -v envget_key="$envget_key" '
        BEGIN { pattern = "^[[:blank:]]*(export[[:blank:]]+)?" envget_key "[[:blank:]]*="; }
        { sub(/\r$/, ""); if (match($0, pattern)) { count++; value = substr($0, RLENGTH + 1); } }
        END { if (count == 0) exit 4; if (count > 1) exit 3; printf "%s", value; }
    ' <"$envget_file"); then
    :
  else
    envget_rc=$?
    case "$envget_rc" in
    3)
      printf 'envget: %s appears more than once in %s\n' "$envget_key" "$envget_file" >&2
      exit 3
      ;;
    4)
      printf 'envget: %s was not found in %s\n' "$envget_key" "$envget_file" >&2
      exit 4
      ;;
    *)
      printf 'envget: failed to read %s\n' "$envget_file" >&2
      exit 1
      ;;
    esac
  fi

  if [ "$#" -eq 2 ]; then
    # $2 is the destination NAME; envget_value is the value read from FILE.
    # Quoting preserves the complete value as one argument to jss.
    jss add "$2" "$envget_value"
  else
    printf '%s\n' "$envget_value"
  fi
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
