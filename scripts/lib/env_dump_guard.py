"""Layer 1 of issue #354: does a shell command print a process environment where an agent can read or store it?

check_environment_dump() returns a reason to deny, or None. A dump is let through only when the next stage of
its own pipeline reduces it to a count or to variable names, so that no value can reach a file or the
conversation (the conversation is itself stored in a transcript on disk and sent to the model). It parses
words, not meaning: an alias, a variable that holds a command name, a wrapper with options or its own sub-command
(`sudo -u root env`, `timeout 5 env`, `time -p env`, `nice env`, `xargs env`, `uv run env`), `docker exec ... env`,
`launchctl` and a program that prints its own environment (`perl -e 'print %ENV'`, `ruby`, `jq -n env`, `awk` with
ENVIRON) are out of reach. The sweep
(scripts/detectors/env-secret-on-disk.py) catches what passes this guard.

Pure functions, stdlib only, no I/O: the Bash hook imports this module, so it must never block on anything.
"""
from __future__ import annotations

import os.path
import re
import shlex

import secret_names

_MAX_DEPTH = 4  # nesting of bash -c / eval / $(...) / here-documents that is followed
_WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "builtin", "noglob"}
# Words that open a command position in a compound command: `{ env; }`, `if x; then env; fi`, `! env`.
_KEYWORDS = {"{", "!", "if", "then", "else", "elif", "while", "until", "do"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_INTERPRETER_PREFIXES = ("python", "node", "deno", "bun")
_PS_VALUE_LETTERS = set("opOutUgG")  # ps option letters whose value is the next word
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=.*", re.S)
_SHELL_COMMAND_OPTION = re.compile(r"-[A-Za-z]*c[A-Za-z]*")  # -c, -lc, -ec: the next word is a command string
# Any /proc/<anything>/environ: `$$`, `$!`, `*`, `task/1/`, `./` and a `$SUBST` placeholder are all a process environment.
_PROC_ENVIRON = re.compile(r"/proc/(?:[^/\s]*/+)*environ\b")
_WHOLE_ENV_IN_CODE = re.compile(
    r"\bos\.environb?\b(?!\s*(?:\[|\.get\(|\.pop\(|\.setdefault\())|\bprocess\.env\b(?!\s*[.\[])"
)
# `<<` or `<<-` with a delimiter word (quoted or not), never the here-string `<<<`.
_HEREDOC_OPERATOR = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(?:'([^']+)'|\"([^\"]+)\"|\\?(\w+))")
_NOWHERE = {"/dev/null"}  # a redirect target that is no file: `> 2` writes a file named 2, `>&2` is the conversation


def _split_substitutions(text: str) -> tuple[str, list[str]]:
    """The text with every command substitution replaced by `$SUBST`, and the body of each one.

    Bodies come from `$(...)` (parentheses balanced, so `$(cat <(env))` is one body) and from backticks, in the
    shell word context where they run: not inside single quotes, not after a backslash. Scanning the whole text, not
    the words of a stage, is what catches a substitution in a here-string, in an assignment-only stage and in the
    middle of a path such as `/proc/$(pidof node)/environ`. An unbalanced body runs to the end of the text."""
    out: list[str] = []
    bodies: list[str] = []
    i, n = 0, len(text)
    single = double = False
    while i < n:
        ch = text[i]
        if single:
            single = ch != "'"
        elif ch == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        elif ch == "'" and not double:
            single = True
        elif ch == "\"":
            double = not double
        elif text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += (text[j] == "(") - (text[j] == ")")
                j += 1
            bodies.append(text[i + 2 : j - 1 if depth == 0 else j])
            out.append("$SUBST")
            i = j
            continue
        elif ch == "`":
            j = text.find("`", i + 1)
            j = n if j == -1 else j
            bodies.append(text[i + 1 : j])
            out.append("$SUBST")
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), bodies


def _is_interpreter(name: str) -> bool:
    return name.startswith(_INTERPRETER_PREFIXES)


def _strip_prefix(argv: list[str]) -> list[str]:
    while argv:
        if argv[0] == "function":  # `function f { env; }`: the name is not a command, the brace opens the body
            argv = argv[2:]
        elif argv[0] in _WRAPPERS or argv[0] in _KEYWORDS or _ASSIGNMENT.fullmatch(argv[0]):
            argv = argv[1:]
        else:
            break
    return argv


def _ps_shows_environment(args: list[str]) -> bool:
    """BSD keyword e (no dash) or option -E. Dashed -e only means every process."""
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        dashed = arg.startswith("-")
        letters = arg.lstrip("-")
        if not letters.isalpha():  # a pid, a format list
            continue
        if (dashed and "E" in letters) or (not dashed and "e" in letters):
            return True
        skip = letters[-1] in _PS_VALUE_LETTERS
    return False


def _simple_command_dumps(argv: list[str]) -> str | None:
    argv = _strip_prefix(argv)
    if not argv:
        return None
    cmd, args = os.path.basename(argv[0]), argv[1:]
    if cmd == "env":
        i = 0
        while i < len(args):  # step over env's own options and NAME=value words
            if args[i] in ("-u", "-S", "-P", "-C"):
                i += 2
            elif args[i].startswith("-") or "=" in args[i]:
                i += 1
            else:
                return _simple_command_dumps(args[i:])  # env runs a command: judge that command
        return None if "-i" in args else "env with no command prints the whole environment"
    if cmd == "printenv":
        names = [a for a in args if not a.startswith("-")]
        if not names:
            return "printenv with no name prints the whole environment"
        secret = [n for n in names if secret_names.is_secret_env_name(n)]
        return f"printenv prints the value of {secret[0]}" if secret else None
    if cmd == "ps" and _ps_shows_environment(args):
        return "ps with the keyword e or the option -E prints the environment of other processes"
    if cmd in ("export", "declare", "typeset") and all(a.startswith("-") for a in args):
        if not any("f" in a.lower() for a in args):
            return f"{cmd} with no name prints every variable it covers"
    if cmd == "set" and not args:
        return "set with no argument prints every shell variable"
    if cmd == "pm2" and args[:1] == ["env"]:
        return "pm2 env prints the environment of a managed process"
    if any(_PROC_ENVIRON.search(a) for a in args):
        return "the command reads /proc/<pid>/environ"
    if _is_interpreter(cmd) and _WHOLE_ENV_IN_CODE.search(" ".join(args)):
        return "an inline script reads the whole environment mapping"
    return None


def _cut_keeps_names(args: list[str]) -> bool:
    """cut -d= -f1 (any order, joined or separate): keeps what is in front of the first equals sign."""
    if "--complement" in args:  # keeps every field EXCEPT the first: the values
        return False
    delimiter = fields = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-d" and i + 1 < len(args):
            delimiter, i = args[i + 1], i + 1
        elif arg.startswith("-d") and len(arg) > 2:
            delimiter = arg[2:]
        elif arg == "-f" and i + 1 < len(args):
            fields, i = args[i + 1], i + 1
        elif arg.startswith("-f") and len(arg) > 2:
            fields = arg[2:]
        elif arg.startswith("--fields="):
            fields = arg[len("--fields="):]
        elif arg.startswith("--delimiter="):
            delimiter = arg[len("--delimiter="):]
        i += 1
    return delimiter == "=" and fields == "1"


def _only_counts_or_names(argv: list[str]) -> bool:
    argv = _strip_prefix(argv)
    if not argv:
        return False
    cmd, args = os.path.basename(argv[0]), argv[1:]
    if cmd == "wc":
        return True
    if cmd == "grep":  # -c prints a count, -q prints nothing
        return any(a in ("--count", "--quiet", "--silent") or re.fullmatch(r"-[A-Za-z]*[cq][A-Za-z]*", a) for a in args)
    if cmd == "cut":
        return _cut_keeps_names(args)
    return False


def _split_heredocs(command: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """The command with every here-document body removed, and each body as (header line, body, expands).

    `expands` is True when the delimiter is unquoted: the shell then runs $(...) inside the body."""
    lines = command.split("\n")
    kept: list[str] = []
    found: list[tuple[str, str, bool]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for match in _HEREDOC_OPERATOR.finditer(line):
            delimiter = match.group(1) or match.group(2) or match.group(3)
            quoted = match.group(3) is None or "\\" in match.group(0)
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != delimiter:
                body.append(lines[i])
                i += 1
            i += 1  # the delimiter line itself
            found.append((line, "\n".join(body), not quoted))
    return "\n".join(kept), found


def _parse(text: str) -> list[list[dict]] | None:
    """Pipelines of stages; each stage is {argv, to_file, herestring}. None when the quotes do not balance."""
    lexer = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None  # unbalanced quotes: not this guard's call
    pipelines: list[list[dict]] = [[{"argv": [], "to_file": False, "herestring": None}]]
    i = 0
    while i < len(tokens):
        tok, stage = tokens[i], pipelines[-1][-1]
        if tok in ("|", "|&"):
            pipelines[-1].append({"argv": [], "to_file": False, "herestring": None})
        elif tok in (">", ">>", ">|", "&>", "&>>", ">&"):
            if stage["argv"] and stage["argv"][-1] in ("1", "2"):
                stage["argv"].pop()  # a file descriptor in front of the redirect
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            if target not in _NOWHERE and not (tok == ">&" and target == "1"):  # `2>&1` joins the pipe: not a file
                stage["to_file"] = True  # also true for 2>file: a false deny, never a false allow
            i += 1
        elif tok == "<<<":
            stage["herestring"] = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 1
        elif tok in ("<", "<<"):
            pass  # the source word that follows stays in argv, so /proc/<pid>/environ is seen
        elif set(tok) <= set(";&|()<>"):
            pipelines.append([{"argv": [], "to_file": False, "herestring": None}])
        else:
            stage["argv"].append(tok)
        i += 1
    return pipelines


def _nested_commands(argv: list[str], herestring: str | None) -> list[str]:
    """Command strings that this stage hands to a shell."""
    name = os.path.basename(argv[0])
    nested: list[str] = []
    if name in _SHELLS:
        for index, word in enumerate(argv[1:], start=1):
            if _SHELL_COMMAND_OPTION.fullmatch(word):
                nested += argv[index + 1 : index + 2]
                break
        if herestring:
            nested.append(herestring)
    elif name == "eval":
        nested.append(" ".join(argv[1:]))
    return nested


def check_environment_dump(command: str, _depth: int = 0) -> str | None:
    """A reason to deny `command`, or None. See the module docstring for what it cannot see."""
    if _depth > _MAX_DEPTH:
        return f"commands nested more than {_MAX_DEPTH} levels deep cannot be checked, and a dump can hide in them"  # fail closed: five `bash -c` levels used to be waved through
    text, heredocs = _split_heredocs(command)
    for header, body, expands in heredocs:
        header_pipelines = _parse(header) or []
        heads = {
            os.path.basename(argv[0])
            for pipeline in header_pipelines
            for stage in pipeline
            if (argv := _strip_prefix(stage["argv"]))
        }
        if heads & _SHELLS:  # the body is a script
            reason = check_environment_dump(body, _depth + 1)
            if reason:
                return reason
        if any(_is_interpreter(h) for h in heads) and _WHOLE_ENV_IN_CODE.search(body):
            return "an inline script reads the whole environment mapping"
        if expands:  # an unquoted delimiter: the shell runs $(...) inside the body
            bodies = _split_substitutions(body)[1]
            for inner in bodies:
                reason = check_environment_dump(inner, _depth + 1)
                if reason:
                    return reason
    text, bodies = _split_substitutions(text)
    for inner in bodies:  # every $(...) and backtick of the command itself, wherever it stands
        reason = check_environment_dump(inner, _depth + 1)
        if reason:
            return reason
    pipelines = _parse(text)
    if pipelines is None:
        return None
    for pipeline in pipelines:
        for n, stage in enumerate(pipeline):
            argv = _strip_prefix(stage["argv"])
            if not argv:
                continue
            for inner in _nested_commands(argv, stage["herestring"]):
                reason = check_environment_dump(inner, _depth + 1)
                if reason:
                    return reason
            if _is_interpreter(os.path.basename(argv[0])) and stage["herestring"] and _WHOLE_ENV_IN_CODE.search(stage["herestring"]):
                return "an inline script reads the whole environment mapping"
            reason = _simple_command_dumps(argv)
            if not reason:
                continue
            if stage["to_file"]:
                return reason + ", and the command stores it in a file"
            following = pipeline[n + 1]["argv"] if n + 1 < len(pipeline) else []
            if not _only_counts_or_names(following):
                return reason + ", and nothing reduces it to a count or to names"
    return None
