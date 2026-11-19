#!/usr/bin/env python3
"""Test envkey v2 with synthetic values and a mock jss; no real secrets are used.

Run ``python3 test_envkey.py`` to test Bash and zsh found on PATH, or choose
interpreters with repeatable ``--shell /path/to/shell`` arguments. Test files
are created in a temporary directory below the current working directory.
Only Python's standard library is required (Python 3.7 or later).

The envkey interface takes ENV_VAR_NAME and JSS_SOURCE_SECRET_NAME, both names.
The retrieved secret VALUE is supplied by the mock jss, not by either argument.
"""

import argparse
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SCRIPT = PACKAGE_DIR / "envkey.sh"
ONE_LINER = PACKAGE_DIR / "envkey-one-liner.md"
CONTINUED = b"ENVKEY_TEST_SCRIPT_CONTINUED"
MODES = ("execute", "source", "one-liner")
DEFAULT_ARGS = ("PASSWORD", "SECRET_NAME")
DEFAULT_VALUE = b"dummy_secret\n"


@dataclass
class Case:
    name: str
    args: tuple = DEFAULT_ARGS
    files: dict = field(default_factory=dict)
    directories: tuple = ()
    symlinks: dict = field(default_factory=dict)
    target: str = ".env"
    expected_writes: dict = field(default_factory=dict)
    expected_status: int = 0
    stdout_contains: bytes = b""
    expected_jss: object = None
    jss_output: bytes = DEFAULT_VALUE
    jss_status: int = 0
    tool_failure: object = None


def writing(name, args=DEFAULT_ARGS, files=None, target=".env",
            result=b"PASSWORD=dummy_secret\n", value=DEFAULT_VALUE,
            jss_name="SECRET_NAME"):
    return Case(name, args, files or {}, target=target,
                expected_writes={target: result},
                expected_jss=[jss_name], jss_output=value)


def cases():
    symbols = "dummy_!@#$%^&*()[]{}<>?;:'\"\\`~|/=-_+,."
    syntax = "dummy_$(touch ENVKEY_SHOULD_NOT_EXIST)`touch ENVKEY_SHOULD_NOT_EXIST_EITHER`$HOME${USER}"
    whitespace = "  dummy leading spaces and trailing tabs \t\t "
    unicode_value = "dummy_密碼_κωδικός_пароль_é_🔑"
    source_name = "service name / staging 'quoted' $name !"
    duplicate = b"FIRST=keep\n \texport\tPASSWORD \t=old1\nMIDDLE=keep\nPASSWORD=old2\nLAST=keep\n"
    duplicate_result = b"FIRST=keep\n \texport\tPASSWORD \t=dummy_secret\nMIDDLE=keep\nLAST=keep\n"
    matrix = [
        writing("create-default-file"),
        writing("append-existing-file", files={".env": b"OTHER=keep\n"}, result=b"OTHER=keep\nPASSWORD=dummy_secret\n"),
        writing("empty-existing-file", files={".env": b""}),
        writing("append-after-blank-line", files={".env": b"OTHER=keep\n\n"}, result=b"OTHER=keep\n\nPASSWORD=dummy_secret\n"),
        writing("symbol-password", result=("PASSWORD=" + symbols + "\n").encode(), value=(symbols + "\n").encode()),
        writing("literal-shell-syntax", result=("PASSWORD=" + syntax + "\n").encode(), value=(syntax + "\n").encode()),
        writing("literal-whitespace", result=("PASSWORD=" + whitespace + "\n").encode(), value=(whitespace + "\n").encode()),
        writing("unicode-password", result=("PASSWORD=" + unicode_value + "\n").encode(), value=(unicode_value + "\n").encode()),
        writing("leading-dash-value", result=b"PASSWORD=--dummy=-n=-e==\n", value=b"--dummy=-n=-e==\n"),
        writing("leading-equals-value", result=b"PASSWORD====dummy==\n", value=b"===dummy==\n"),
        writing("literal-quotes-and-comment", result=b"PASSWORD=\"dummy quoted\" # literal comment\n", value=b"\"dummy quoted\" # literal comment\n"),
        writing("literal-backslash-escapes", result=b"PASSWORD=dummy\\n\\r\\t\\123\\x41\\\\\n", value=b"dummy\\n\\r\\t\\123\\x41\\\\\n"),
        writing("empty-value", result=b"PASSWORD=\n", value=b""),
        writing("newline-only-output-is-empty", result=b"PASSWORD=\n", value=b"\n\n"),
        writing("multiple-trailing-newlines-trimmed", value=b"dummy_secret\n\n\n"),
        writing("jss-no-final-newline", value=b"dummy_secret"),
        writing("short-file-option", ("-f", ".env.local", "PASSWORD", "SECRET_NAME"), target=".env.local"),
        writing("long-file-option", ("--file", ".env.backup", "PASSWORD", "SECRET_NAME"), target=".env.backup"),
        writing("equals-file-option", ("--file=.env.local", "PASSWORD", "SECRET_NAME"), target=".env.local"),
        writing("path-with-spaces", ("-f", "configuration dir/.env backup", "PASSWORD", "SECRET_NAME"), files={"configuration dir/keep.txt": b"unchanged\n"}, target="configuration dir/.env backup"),
        writing("absolute-path", ("--file={WORK}/configuration dir/.env.local", "PASSWORD", "SECRET_NAME"), files={"configuration dir/keep.txt": b"unchanged\n"}, target="configuration dir/.env.local"),
        writing("leading-dash-path", ("-f", "--settings.env", "PASSWORD", "SECRET_NAME"), target="--settings.env"),
        writing("assignment-like-filename", ("-f", "filename=value", "PASSWORD", "SECRET_NAME"), target="filename=value"),
        writing("quoted-filename", ("-f", "folder name/odd '$name.env", "PASSWORD", "SECRET_NAME"), files={"folder name/keep.txt": b"unchanged\n"}, target="folder name/odd '$name.env"),
        writing("option-terminator", ("--", "PASSWORD", "SECRET_NAME")),
        writing("jss-name-symbols", ("PASSWORD", source_name), jss_name=source_name),
        writing("jss-name-leading-dash", ("PASSWORD", "--vault-name"), jss_name="--vault-name"),
        writing("underscore-key", ("_PASSWORD_2", "SECRET_NAME"), result=b"_PASSWORD_2=dummy_secret\n"),
        writing("exact-key-and-case", files={".env": b"# PASSWORD=comment\nPASSWORD_SUFFIX=keep\nPREFIX_PASSWORD=keep\npassword=keep\nOTHER=PASSWORD=keep\nPASSWORD\n"}, result=b"# PASSWORD=comment\nPASSWORD_SUFFIX=keep\nPREFIX_PASSWORD=keep\npassword=keep\nOTHER=PASSWORD=keep\nPASSWORD\nPASSWORD=dummy_secret\n"),
        Case("skip-identical-value", files={".env": b"PASSWORD=dummy_secret\n"}, jss_status=42),
        Case("skip-different-value", files={".env": b"PASSWORD=old\n"}, jss_status=42),
        Case("skip-empty-value", files={".env": b"PASSWORD=\n"}),
        Case("skip-export-and-spacing", files={".env": b"OTHER=keep\n \texport\tPASSWORD \t=old\n"}),
        Case("skip-duplicate-identical", files={".env": b"PASSWORD=old\nPASSWORD=old\n"}),
        Case("skip-duplicate-different", files={".env": duplicate}),
        Case("skip-no-final-newline", files={".env": b"PASSWORD=old"}),
        Case("skip-crlf", files={".env": b"OTHER=keep\r\nPASSWORD=old\r\n"}),
        writing("force-front", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"PASSWORD=old\n"}),
        writing("force-trailing", ("PASSWORD", "SECRET_NAME", "--force"), files={".env": b"PASSWORD=old\n"}),
        writing("force-new-key", ("--force", "PASSWORD", "SECRET_NAME")),
        writing("force-coalesces-duplicates", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": duplicate}, result=duplicate_result),
        writing("force-keeps-unrelated-duplicates", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"OTHER=first\nPASSWORD=old\nOTHER=second\npassword=lower\n"}, result=b"OTHER=first\nPASSWORD=dummy_secret\nOTHER=second\npassword=lower\n"),
        writing("force-other-file", ("--file", ".env.backup", "--force", "PASSWORD", "SECRET_NAME"), files={".env": b"UNCHANGED=yes\n", ".env.backup": b"export PASSWORD =old\n"}, target=".env.backup", result=b"export PASSWORD =dummy_secret\n"),
        writing("force-before-file-option", ("--force", "--file=.env.local", "PASSWORD", "SECRET_NAME"), files={".env.local": b"PASSWORD=old\n"}, target=".env.local"),
        writing("force-and-terminator", ("--force", "--", "PASSWORD", "SECRET_NAME"), files={".env": b"PASSWORD=old\n"}),
        writing("append-crlf", files={".env": b"OTHER=keep\r\n"}, result=b"OTHER=keep\r\nPASSWORD=dummy_secret\r\n"),
        writing("force-crlf", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"OTHER=keep\r\nPASSWORD=old\r\nLAST=keep\r\n"}, result=b"OTHER=keep\r\nPASSWORD=dummy_secret\r\nLAST=keep\r\n"),
        writing("force-mixed-line-endings", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"FIRST=keep\nPASSWORD=old\r\nLAST=keep\n"}, result=b"FIRST=keep\nPASSWORD=dummy_secret\r\nLAST=keep\n"),
        writing("append-follows-last-line-ending", files={".env": b"FIRST=keep\r\nLAST=keep\n"}, result=b"FIRST=keep\r\nLAST=keep\nPASSWORD=dummy_secret\n"),
        writing("append-no-final-newline", files={".env": b"OTHER=keep"}, result=b"OTHER=keep\nPASSWORD=dummy_secret\n"),
        writing("force-no-final-newline", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"PASSWORD=old"}),
        Case("directory-is-not-file", directories=(".env",), expected_status=1),
        Case("symlink-is-rejected", files={"target.env": b"OTHER=keep\n"}, symlinks={".env": "target.env"}, expected_status=1),
        Case("dangling-symlink-is-rejected", symlinks={".env": "missing.env"}, expected_status=1),
        Case("missing-parent-directory", ("-f", "missing/subdir/.env", "PASSWORD", "SECRET_NAME"), target="missing/subdir/.env", expected_status=1, expected_jss=["SECRET_NAME"]),
        Case("invalid-key-dot", ("PASSWORD.NAME", "SECRET_NAME"), expected_status=2),
        Case("invalid-key-digit", ("1PASSWORD", "SECRET_NAME"), expected_status=2),
        Case("invalid-key-empty", ("", "SECRET_NAME"), expected_status=2),
        Case("invalid-key-regex", ("PASSWORD.*", "SECRET_NAME"), expected_status=2),
        Case("invalid-key-unicode", ("密碼", "SECRET_NAME"), expected_status=2),
        Case("invalid-key-space", ("PASS WORD", "SECRET_NAME"), expected_status=2),
        Case("unknown-option", ("--wrong", "PASSWORD", "SECRET_NAME"), expected_status=2),
        Case("missing-file-option-argument", ("-f",), expected_status=2),
        Case("empty-file-option-argument", ("--file", "", "PASSWORD", "SECRET_NAME"), expected_status=2),
        Case("empty-equals-file-option", ("--file=", "PASSWORD", "SECRET_NAME"), expected_status=2),
        Case("no-positionals", (), expected_status=2),
        Case("missing-jss-name", ("PASSWORD",), expected_status=2),
        Case("empty-jss-name", ("PASSWORD", ""), expected_status=2),
        Case("excess-positionals", ("PASSWORD", "SECRET_NAME", "extra"), expected_status=2),
        Case("file-option-after-positionals", ("PASSWORD", "SECRET_NAME", "-f", ".env.local"), expected_status=2),
        Case("help", ("--help",), stdout_contains=b"Usage: envkey"),
        Case("short-help", ("-h",), stdout_contains=b"Usage: envkey"),
        Case("jss-failure-new-file", expected_status=42, expected_jss=["SECRET_NAME"], jss_status=42),
        Case("jss-failure-existing-file", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"PASSWORD=old\n"}, expected_status=42, expected_jss=["SECRET_NAME"], jss_status=42),
        Case("jss-failure-with-partial-output", files={".env": b"OTHER=keep\n"}, expected_status=42, expected_jss=["SECRET_NAME"], jss_status=42, jss_output=b"dummy_partial\n"),
        Case("jss-embedded-lf", files={".env": b"OTHER=keep\n"}, expected_status=3, expected_jss=["SECRET_NAME"], jss_output=b"dummy_first\ndummy_second\n"),
        Case("jss-leading-lf", expected_status=3, expected_jss=["SECRET_NAME"], jss_output=b"\ndummy_second\n"),
        Case("jss-carriage-return", files={".env": b"OTHER=keep\n"}, expected_status=3, expected_jss=["SECRET_NAME"], jss_output=b"dummy_first\rdummy_second\n"),
        Case("jss-crlf-output", expected_status=3, expected_jss=["SECRET_NAME"], jss_output=b"dummy_secret\r\n"),
        Case("force-rejects-multiline", ("--force", "PASSWORD", "SECRET_NAME"), files={".env": b"PASSWORD=old\n"}, expected_status=3, expected_jss=["SECRET_NAME"], jss_output=b"dummy_first\ndummy_second\n"),
        Case("awk-precheck-failure", files={".env": b"OTHER=keep\n"}, expected_status=1, tool_failure=("awk", 1, 99)),
        Case("awk-precheck-failure-existing-key", files={".env": b"PASSWORD=old\n"}, expected_status=1, tool_failure=("awk", 1, 99)),
        Case("awk-rewrite-failure", files={".env": b"OTHER=keep\n"}, expected_status=1, expected_jss=["SECRET_NAME"], tool_failure=("awk", 2, 99)),
        Case("awk-rewrite-failure-new-file", expected_status=1, expected_jss=["SECRET_NAME"], tool_failure=("awk", 2, 5)),
        Case("mktemp-failure", files={".env": b"OTHER=keep\n"}, expected_status=1, expected_jss=["SECRET_NAME"], tool_failure=("mktemp", 1, 99)),
        Case("chmod-failure", files={".env": b"OTHER=keep\n"}, expected_status=1, expected_jss=["SECRET_NAME"], tool_failure=("chmod", 1, 99)),
        Case("mv-failure", files={".env": b"OTHER=keep\n"}, expected_status=1, expected_jss=["SECRET_NAME"], tool_failure=("mv", 1, 99)),
        Case("skip-does-not-create-temp", files={".env": b"PASSWORD=old\n"}, jss_status=42, tool_failure=("mktemp", 1, 99)),
    ]
    return matrix


def clean_environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith("BASH_FUNC_")}
    for key in ("BASH_ENV", "ENV", "BASH_XTRACEFD", "CDPATH", "SHELLOPTS", "BASHOPTS"):
        env.pop(key, None)
    env["PS4"] = "+ "
    env["HISTFILE"] = os.devnull
    return env


def resolve_shell(requested):
    candidate = str(Path(requested).expanduser())
    resolved = shutil.which(candidate)
    if resolved is None:
        raise ValueError("Shell not found or not executable: " + requested)
    shell = Path(resolved).resolve()
    probe = subprocess.run(
        [str(shell), "-c", 'if [ -n "${BASH_VERSION-}" ]; then printf "bash %s" "$BASH_VERSION"; elif [ -n "${ZSH_VERSION-}" ]; then printf "zsh %s" "$ZSH_VERSION"; else exit 2; fi'],
        env=clean_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )
    if probe.returncode != 0:
        raise ValueError("Only Bash and zsh are supported: " + requested)
    label = probe.stdout.decode("utf-8", "replace")
    return shell, label, label.startswith("zsh ")


def write_mocks(bin_dir):
    helper = bin_dir / "mock_tools.py"
    helper.write_text(
        '#!/usr/bin/env python3\n'
        'import json\nimport os\nfrom pathlib import Path\nimport sys\n'
        'tool = sys.argv[1]\n'
        'args = sys.argv[2:]\n'
        'record = Path(os.environ["ENVKEY_TEST_TOOL_LOG"])\n'
        'with record.open("a", encoding="utf-8") as stream:\n'
        '    stream.write(json.dumps([tool, args], ensure_ascii=False) + "\\n")\n'
        'if tool == "jss":\n'
        '    sys.stdout.buffer.write(Path(os.environ["ENVKEY_TEST_VALUE_FILE"]).read_bytes())\n'
        '    sys.exit(int(os.environ.get("ENVKEY_TEST_JSS_STATUS", "0")))\n'
        'failure = json.loads(os.environ["ENVKEY_TEST_TOOL_FAILURE"])\n'
        'if failure and tool == failure[0]:\n'
        '    calls = [json.loads(line)[0] for line in record.read_text(encoding="utf-8").splitlines()]\n'
        '    if calls.count(tool) == failure[1]:\n'
        '        if tool == "awk":\n'
        '            sys.stdout.buffer.write(b"deliberate partial output\\n")\n'
        '        sys.exit(failure[2])\n'
        'real = json.loads(os.environ["ENVKEY_TEST_REAL_TOOLS"])[tool]\n'
        'os.execv(real, [real] + args)\n',
        encoding="utf-8",
    )
    real_tools = {}
    for name in ("awk", "mktemp", "chmod", "mv"):
        resolved = shutil.which(name)
        if resolved is None:
            raise ValueError("Required command not found: " + name)
        real_tools[name] = os.path.abspath(resolved)  # no symlink resolution: busybox applets dispatch on argv[0]
    for name in ("jss", "awk", "mktemp", "chmod", "mv"):
        wrapper = bin_dir / name
        wrapper.write_text(
            '#!/bin/sh\nexec "$ENVKEY_TEST_PYTHON" "$ENVKEY_TEST_HELPER" '
            + shlex.quote(name) + ' "$@"\n', encoding="utf-8",
        )
        wrapper.chmod(0o755)
    return helper, real_tools


def shell_flags(is_zsh):
    if is_zsh:
        return ["-f", "-e", "-u", "-o", "pipefail"]
    return ["--noprofile", "--norc", "-e", "-u", "-o", "pipefail"]


def snapshot(path):
    details = path.stat()
    return path.read_bytes(), stat.S_IMODE(details.st_mode), details.st_mtime_ns


def test_environment(work, bin_dir, helper, real_tools, case):
    value_file = work / "synthetic-jss-output.bin"
    value_file.write_bytes(case.jss_output)
    env = clean_environment()
    env.update({
        "PATH": str(bin_dir) + os.pathsep + env.get("PATH", os.defpath),
        "ENVKEY_TEST_PYTHON": sys.executable,
        "ENVKEY_TEST_HELPER": str(helper),
        "ENVKEY_TEST_VALUE_FILE": str(value_file),
        "ENVKEY_TEST_TOOL_LOG": str(work / "tool-calls.jsonl"),
        "ENVKEY_TEST_JSS_STATUS": str(case.jss_status),
        "ENVKEY_TEST_TOOL_FAILURE": json.dumps(case.tool_failure),
        "ENVKEY_TEST_REAL_TOOLS": json.dumps(real_tools),
    })
    return env


def read_log(work):
    record = work / "tool-calls.jsonl"
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]


def run_case(shell, is_zsh, mode, case, work, bin_dir, helper, real_tools, line_prefix):
    for name, content in case.files.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    for name in case.directories:
        (work / name).mkdir(parents=True, exist_ok=True)
    for name, destination in case.symlinks.items():
        (work / name).symlink_to(destination)
    originals = {name: snapshot(work / name) for name in case.files}
    args = [arg.replace("{WORK}", str(work)) for arg in case.args]
    env = test_environment(work, bin_dir, helper, real_tools, case)
    flags = shell_flags(is_zsh)
    if mode == "execute":
        command = [str(shell)] + flags + [str(SCRIPT)] + args
    elif mode == "source":
        code = 'set -x; . "$1"; shift; envkey "$@"; set +x; printf "%s\\n" ENVKEY_TEST_SCRIPT_CONTINUED >&2'
        command = [str(shell)] + flags + ["-c", code, "envkey-test", str(SCRIPT)] + args
    else:
        # Replace only the final example invocation; keep the function intact.
        invocation = "envkey" + (" " + " ".join(shlex.quote(arg) for arg in args) if args else "")
        code = "set -x; " + line_prefix + "; " + invocation + '\nset +x; printf "%s\\n" ENVKEY_TEST_SCRIPT_CONTINUED >&2\n'
        generated = work / "one-liner-test.sh"
        generated.write_text(code, encoding="utf-8")
        command = [str(shell)] + flags + [str(generated)]
    result = subprocess.run(command, cwd=work, env=env, input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    if result.returncode != case.expected_status:
        raise AssertionError("expected exit {0}, got {1}; stderr={2!r}".format(case.expected_status, result.returncode, result.stderr[-1200:]))
    if case.stdout_contains:
        if case.stdout_contains not in result.stdout:
            raise AssertionError("expected stdout to contain {0!r}, got {1!r}".format(case.stdout_contains, result.stdout))
    elif result.stdout != b"":
        raise AssertionError("unexpected stdout: {0!r}".format(result.stdout))
    if case.name in ("help", "short-help"):
        for explanation in (
            b"ENV_VAR_NAME JSS_SOURCE_SECRET_NAME",
            b"Both positional arguments are names; neither is the secret value.",
            b"destination variable name in the env file",
            b"name of an existing secret in jss",
            b"does not export the value into the calling shell",
        ):
            if explanation not in result.stdout:
                raise AssertionError("help omitted the name/value clarification: " + repr(explanation))
    if mode != "execute" and ((CONTINUED in result.stderr) != (case.expected_status == 0)):
        raise AssertionError("strict-mode continuation did not match success or failure")
    calls = read_log(work)
    jss_calls = [args for tool, args in calls if tool == "jss"]
    expected_calls = [] if case.expected_jss is None else [case.expected_jss]
    if jss_calls != expected_calls:
        raise AssertionError("jss calls differ: expected {0!r}, got {1!r}".format(expected_calls, jss_calls))
    for tool, arguments in calls:
        if tool == "awk":
            secret = case.jss_output.rstrip(b"\n")
            if secret and any(secret in item.encode("utf-8") for item in arguments):
                raise AssertionError("the secret appeared in an awk process argument")
    for name, before in originals.items():
        if name not in case.expected_writes and snapshot(work / name) != before:
            raise AssertionError("an unchanged file changed in bytes, permissions, or mtime: " + name)
    for name, content in case.expected_writes.items():
        path = work / name
        if not path.is_file() or path.is_symlink():
            raise AssertionError("expected regular output file: " + name)
        actual, mode_bits, unused_mtime = snapshot(path)
        if actual != content:
            raise AssertionError("file bytes differ for {0}: expected {1!r}, got {2!r}".format(name, content, actual))
        if mode_bits != 0o600:
            raise AssertionError("written file mode should be 0600, got {0:o}: {1}".format(mode_bits, name))
    for name, destination in case.symlinks.items():
        path = work / name
        if not path.is_symlink() or os.readlink(str(path)) != destination:
            raise AssertionError("the symlink was changed: " + name)
    target = work / case.target
    if case.target not in case.files and case.target not in case.expected_writes and case.target not in case.symlinks and case.target not in case.directories:
        if target.exists() or target.is_symlink():
            raise AssertionError("an error unexpectedly created the target: " + case.target)
    leftovers = list(work.rglob("*.envkey.*"))
    if leftovers:
        raise AssertionError("temporary files were not cleaned up: " + repr(leftovers))
    if list(work.glob("ENVKEY_SHOULD_NOT_EXIST*")):
        raise AssertionError("text from the password was executed as shell syntax")
    secret = case.jss_output.rstrip(b"\n")
    if secret and (secret in result.stdout or secret in result.stderr):
        raise AssertionError("output or shell tracing exposed the synthetic secret")
    if case.name.startswith("skip-") and any(tool in ("jss", "mktemp", "chmod", "mv") for tool, arguments in calls):
        raise AssertionError("the default existing-key path performed retrieval or a write operation")


def run_startup_check(shell, is_zsh, name, work, bin_dir, helper, real_tools, line_prefix):
    case = Case(name)
    env = test_environment(work, bin_dir, helper, real_tools, case)
    if name == "eval-source-only":
        # eval of the file text has no BASH_SOURCE (bash -u) and a zsh context ending in eval, not file:
        # both must only declare envkey, never run it.
        code = 'eval "$(cat "$1")"; type envkey > /dev/null; printf "SOURCE_ONLY_OK\\n"'
    elif name == "source-only":
        code = '. "$1"; type envkey > /dev/null; printf "SOURCE_ONLY_OK\\n"'
    elif name == "source-in-function":
        code = 'loader() { . "$1"; }; loader "$1"; type envkey > /dev/null; printf "SOURCE_ONLY_OK\\n"'
    elif name == "dynamic-names-and-no-export":
        code = (
            '. "$1"; API_KEY=existing_shell_value; export API_KEY; '
            "env_var_name='API_KEY'; jss_source_secret_name='MY_SERVICE_API_KEY'; "
            'envkey "$env_var_name" "$jss_source_secret_name"; '
            '[ "$API_KEY" = existing_shell_value ]; printf "DYNAMIC_NAMES_OK\\n"'
        )
        result = subprocess.run([str(shell)] + shell_flags(is_zsh) + ["-c", code, "envkey-names-test", str(SCRIPT)], cwd=work, env=env, input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if result.returncode != 0 or result.stdout != b"DYNAMIC_NAMES_OK\n" or result.stderr:
            raise AssertionError("dynamic name arguments or caller-value preservation failed: " + repr(result.stderr))
        if (work / ".env").read_bytes() != b"API_KEY=dummy_secret\n":
            raise AssertionError("the name-holder variables did not select the intended env-file name")
        if [args for tool, args in read_log(work) if tool == "jss"] != [["MY_SERVICE_API_KEY"]]:
            raise AssertionError("the JSS source-name holder was not passed as one name")
        return
    else:
        # Run the entire delivered line, including its shell-neutral explanation.
        # Default interactive zsh does not assume INTERACTIVE_COMMENTS is enabled.
        history = "setopt BANG_HIST" if is_zsh else "set -H"
        code = history + '\n' + ONE_LINER.read_text(encoding="utf-8") + 'printf "INTERACTIVE_OK\\n"\nexit\n'
        flags = ["-f", "-i"] if is_zsh else ["--noprofile", "--norc", "-i"]
        result = subprocess.run([str(shell)] + flags, cwd=work, env=env, input=code.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if result.returncode != 0 or b"INTERACTIVE_OK" not in result.stdout:
            raise AssertionError("interactive one-liner failed: " + repr(result.stderr[-1200:]))
        if (work / ".env").read_bytes() != b"ENV_VAR_NAME=dummy_secret\n":
            raise AssertionError("interactive one-liner produced incorrect file bytes")
        if [args for tool, args in read_log(work) if tool == "jss"] != [["JSS_SOURCE_SECRET_NAME"]]:
            raise AssertionError("interactive one-liner did not retrieve the expected name")
        return
    result = subprocess.run([str(shell)] + shell_flags(is_zsh) + ["-c", code, "envkey-source-test", str(SCRIPT)], cwd=work, env=env, input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    if result.returncode != 0 or result.stdout != b"SOURCE_ONLY_OK\n" or result.stderr:
        raise AssertionError("sourcing should only declare envkey: stdout={0!r}; stderr={1!r}".format(result.stdout, result.stderr))
    if read_log(work) or (work / ".env").exists():
        raise AssertionError("sourcing alone called an external tool or wrote a file")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shell", action="append", metavar="PATH", help="Bash or zsh executable; repeat to test several versions")
    parser.add_argument("--verbose", action="store_true", help="print every successful check")
    options = parser.parse_args()
    if not SCRIPT.is_file() or not ONE_LINER.is_file():
        parser.error("Keep test_envkey.py beside envkey.sh and envkey-one-liner.md.")
    one_liner = ONE_LINER.read_text(encoding="utf-8")
    if len(one_liner.splitlines()) != 1:
        parser.error("envkey-one-liner.md must contain exactly one physical line.")
    line_prefix, separator, invocation = one_liner.rstrip("\n").rpartition("; envkey ")
    if not separator or not invocation:
        parser.error("Cannot locate the one-liner's final envkey invocation.")
    if invocation != "-f .env 'ENV_VAR_NAME' 'JSS_SOURCE_SECRET_NAME'":
        parser.error("The final example must explicitly use the two NAME placeholders.")
    if ": 'Replace both quoted placeholders with names:" not in line_prefix:
        parser.error("The independent one-liner must contain its name/value explanation.")
    requested = options.shell or [name for name in ("bash", "zsh") if shutil.which(name)]
    if not requested:
        parser.error("No Bash or zsh interpreter found; specify --shell PATH.")
    resolved = []
    seen = set()
    try:
        for name in requested:
            item = resolve_shell(name)
            if item[0] not in seen:
                resolved.append(item)
                seen.add(item[0])
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    matrix = cases()
    startup_checks = ("source-only", "eval-source-only", "source-in-function", "dynamic-names-and-no-export", "interactive-one-liner")
    checks = 0
    failures = []
    try:
        with tempfile.TemporaryDirectory(prefix="envkey-tests-", dir=Path.cwd()) as temporary:
            base = Path(temporary)
            bin_dir = base / "mock-bin"
            bin_dir.mkdir()
            helper, real_tools = write_mocks(bin_dir)
            for shell_index, (shell, label, is_zsh) in enumerate(resolved):
                shell_failures = 0
                for case_index, case in enumerate(matrix):
                    for mode in MODES:
                        work = base / ("shell-{0}-case-{1}-{2}".format(shell_index, case_index, mode))
                        work.mkdir()
                        checks += 1
                        name = "{0}: {1}: {2}".format(label, mode, case.name)
                        try:
                            run_case(shell, is_zsh, mode, case, work, bin_dir, helper, real_tools, line_prefix)
                        except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as error:
                            shell_failures += 1
                            failures.append(name)
                            print("FAIL: " + name + "\n  " + str(error), file=sys.stderr)
                        else:
                            if options.verbose:
                                print("PASS: " + name)
                for startup_name in startup_checks:
                    work = base / ("shell-{0}-{1}".format(shell_index, startup_name))
                    work.mkdir()
                    checks += 1
                    name = label + ": " + startup_name
                    try:
                        run_startup_check(shell, is_zsh, startup_name, work, bin_dir, helper, real_tools, line_prefix)
                    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as error:
                        shell_failures += 1
                        failures.append(name)
                        print("FAIL: " + name + "\n  " + str(error), file=sys.stderr)
                    else:
                        if options.verbose:
                            print("PASS: " + name)
                per_shell = len(matrix) * len(MODES) + len(startup_checks)
                print("{0}: {1}; {2} cases x {3} forms + {4} startup checks = {5} checks; {6} failures".format("PASS" if not shell_failures else "FAIL", label, len(matrix), len(MODES), len(startup_checks), per_shell, shell_failures), flush=True)
    except (OSError, ValueError) as error:
        print("Cannot prepare or use the temporary test directory below the current directory: " + str(error), file=sys.stderr)
        return 1
    print("Total: {0} checks across {1} shell(s); {2} failures. Only synthetic values and a mock jss were used.".format(checks, len(resolved), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
