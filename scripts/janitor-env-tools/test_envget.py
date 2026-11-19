#!/usr/bin/env python3
"""Test envget v2 with synthetic data and a mock jss; no real secrets are used.

Arguments to envget are names: ENV_VAR_NAME and an optional destination name
in jss. Values come from the env file, not from a positional argument or an
exported shell variable. Tests include these name/value distinctions.

Run ``python3 test_envget.py`` to test Bash and zsh found on PATH, or select
interpreters with repeatable ``--shell /path/to/shell`` arguments.  Test files
are created in a temporary directory below the current working directory.
Only Python's standard library is required.
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
SCRIPT = PACKAGE_DIR / "envget.sh"
ONE_LINER = PACKAGE_DIR / "envget-one-liner.md"
CONTINUED = b"ENVGET_TEST_SCRIPT_CONTINUED"
MODES = ("execute", "source", "one-liner")


@dataclass
class Case:
    name: str
    args: tuple
    files: dict = field(default_factory=dict)
    directories: tuple = ()
    expected_status: int = 0
    expected_stdout: bytes = b""
    stdout_contains: bytes = b""
    expected_jss: object = None
    jss_status: int = 0
    awk_status: object = None
    environment: dict = field(default_factory=dict)


def fixture(value, key="PASSWORD", ending="\n"):
    return (key + "=" + value + ending).encode("utf-8")


def cases():
    symbols = "dummy_!@#$%^&*()[]{}<>?;:'\"\\`~|/=-_+,."
    syntax = "dummy_$(touch ENVGET_SHOULD_NOT_EXIST)`touch ENVGET_SHOULD_NOT_EXIST_EITHER`$HOME${USER}"
    whitespace = "  dummy leading spaces and trailing tabs \t\t "
    unicode_value = "dummy_密碼_κωδικός_пароль_é_🔑"
    destination = "service name / staging 'quoted' $name !"
    result = [
        Case("default-file", ("PASSWORD",), {".env": fixture("dummy_plain")}, expected_stdout=b"dummy_plain\n"),
        Case("symbol-password", ("PASSWORD",), {".env": fixture(symbols)}, expected_stdout=(symbols + "\n").encode()),
        Case("literal-shell-syntax", ("PASSWORD",), {".env": fixture(syntax)}, expected_stdout=(syntax + "\n").encode()),
        Case("literal-whitespace", ("PASSWORD",), {".env": fixture(whitespace)}, expected_stdout=(whitespace + "\n").encode()),
        Case("unicode-password", ("PASSWORD",), {".env": fixture(unicode_value)}, expected_stdout=(unicode_value + "\n").encode()),
        Case("leading-dash-value", ("PASSWORD",), {".env": fixture("--dummy=-n=-e==")}, expected_stdout=b"--dummy=-n=-e==\n"),
        Case("leading-equals-value", ("PASSWORD",), {".env": fixture("===dummy==")}, expected_stdout=b"===dummy==\n"),
        Case("short-file-option", ("-f", ".env.local", "PASSWORD"), {".env.local": fixture("dummy_local")}, expected_stdout=b"dummy_local\n"),
        Case("long-file-option", ("--file", ".env.backup", "PASSWORD"), {".env.backup": fixture("dummy_backup")}, expected_stdout=b"dummy_backup\n"),
        Case("equals-file-option", ("--file=.env.local", "PASSWORD"), {".env.local": fixture("dummy_equal_option")}, expected_stdout=b"dummy_equal_option\n"),
        Case("path-with-spaces", ("-f", "configuration dir/.env backup", "PASSWORD"), {"configuration dir/.env backup": fixture("dummy_spaced_path")}, expected_stdout=b"dummy_spaced_path\n"),
        Case("absolute-path", ("--file={WORK}/configuration dir/.env.local", "PASSWORD"), {"configuration dir/.env.local": fixture("dummy_absolute_path")}, expected_stdout=b"dummy_absolute_path\n"),
        Case("leading-dash-path", ("-f", "--settings.env", "PASSWORD"), {"--settings.env": fixture("dummy_dash_path")}, expected_stdout=b"dummy_dash_path\n"),
        Case("assignment-like-filename", ("-f", "filename=value", "PASSWORD"), {"filename=value": fixture("dummy_assignment_path")}, expected_stdout=b"dummy_assignment_path\n"),
        Case("quoted-filename", ("-f", "folder name/odd '$name.env", "PASSWORD"), {"folder name/odd '$name.env": fixture("dummy_quoted_path")}, expected_stdout=b"dummy_quoted_path\n"),
        Case("option-terminator", ("--", "PASSWORD"), {".env": fixture("dummy_terminator")}, expected_stdout=b"dummy_terminator\n"),
        Case("export-and-spacing", ("PASSWORD",), {".env": b"OTHER=keep\n \texport\tPASSWORD \t=dummy_exported\n"}, expected_stdout=b"dummy_exported\n"),
        Case("exact-key-and-case", ("PASSWORD",), {".env": b"# PASSWORD=comment\nPASSWORD_SUFFIX=wrong\nPREFIX_PASSWORD=wrong\npassword=wrong\nOTHER=PASSWORD=wrong\nPASSWORD=dummy_exact\n"}, expected_stdout=b"dummy_exact\n"),
        Case("wrong-case-is-missing", ("PASSWORD",), {".env": b"password=dummy_lowercase\n"}, expected_status=4),
        Case("empty-value", ("PASSWORD",), {".env": b"PASSWORD=\n"}, expected_stdout=b"\n"),
        Case("crlf", ("PASSWORD",), {".env": b"OTHER=keep\r\nPASSWORD=dummy_crlf\r\n"}, expected_stdout=b"dummy_crlf\n"),
        Case("no-final-newline", ("PASSWORD",), {".env": b"PASSWORD=dummy_eof"}, expected_stdout=b"dummy_eof\n"),
        Case("literal-quotes-and-comment", ("PASSWORD",), {".env": b"PASSWORD=\"dummy quoted\" # literal comment\n"}, expected_stdout=b"\"dummy quoted\" # literal comment\n"),
        Case("missing-file", ("PASSWORD",), expected_status=1),
        Case("directory-is-not-file", ("PASSWORD",), directories=(".env",), expected_status=1),
        Case("missing-key", ("PASSWORD",), {".env": b"OTHER=keep\nPASSWORD\n"}, expected_status=4),
        Case("duplicate-identical", ("PASSWORD",), {".env": b"PASSWORD=dummy_same\nPASSWORD=dummy_same\n"}, expected_status=3),
        Case("duplicate-different", ("PASSWORD",), {".env": b"PASSWORD=dummy_first\nexport PASSWORD =dummy_second\n"}, expected_status=3),
        Case("invalid-key-dot", ("PASSWORD.NAME",), {".env": fixture("dummy")}, expected_status=2),
        Case("invalid-key-digit", ("1PASSWORD",), {".env": fixture("dummy")}, expected_status=2),
        Case("invalid-key-empty", ("",), {".env": fixture("dummy")}, expected_status=2),
        Case("invalid-key-regex", ("PASSWORD.*",), {".env": fixture("dummy")}, expected_status=2),
        Case("invalid-key-unicode", ("密碼",), {".env": fixture("dummy")}, expected_status=2),
        Case("unknown-option", ("--wrong", "PASSWORD"), {".env": fixture("dummy")}, expected_status=2),
        Case("missing-file-option-argument", ("-f",), expected_status=2),
        Case("empty-file-option-argument", ("--file", "", "PASSWORD"), expected_status=2),
        Case("empty-equals-file-option", ("--file=", "PASSWORD"), expected_status=2),
        Case("missing-positional-key", (), expected_status=2),
        Case("excess-positionals", ("PASSWORD", "SECRET_NAME", "extra"), {".env": fixture("dummy")}, expected_status=2),
        Case("empty-jss-name", ("PASSWORD", ""), {".env": fixture("dummy")}, expected_status=2),
        Case("help", ("--help",), stdout_contains=b"Usage: envget"),
        Case("short-help", ("-h",), stdout_contains=b"Usage: envget"),
        Case("jss-symbol-password", ("PASSWORD", destination), {".env": fixture(symbols)}, expected_jss=["add", destination, symbols]),
        Case("jss-literal-shell-syntax", ("PASSWORD", "SECRET_NAME"), {".env": fixture(syntax)}, expected_jss=["add", "SECRET_NAME", syntax]),
        Case("jss-whitespace", ("PASSWORD", "SECRET_NAME"), {".env": fixture(whitespace)}, expected_jss=["add", "SECRET_NAME", whitespace]),
        Case("jss-unicode", ("PASSWORD", "SECRET_NAME"), {".env": fixture(unicode_value)}, expected_jss=["add", "SECRET_NAME", unicode_value]),
        Case("jss-empty-value", ("PASSWORD", "SECRET_NAME"), {".env": b"PASSWORD=\n"}, expected_jss=["add", "SECRET_NAME", ""]),
        Case("jss-other-file", ("-f", ".env.backup", "PASSWORD", "SECRET_NAME"), {".env.backup": fixture("dummy_backup_import")}, expected_jss=["add", "SECRET_NAME", "dummy_backup_import"]),
        Case("jss-missing-key-no-call", ("PASSWORD", "SECRET_NAME"), {".env": b"OTHER=keep\n"}, expected_status=4),
        Case("jss-duplicate-no-call", ("PASSWORD", "SECRET_NAME"), {".env": b"PASSWORD=dummy_one\nPASSWORD=dummy_two\n"}, expected_status=3),
        Case("jss-failure-status", ("PASSWORD", "SECRET_NAME"), {".env": fixture("dummy_failed_add")}, expected_status=42, expected_jss=["add", "SECRET_NAME", "dummy_failed_add"], jss_status=42),
        Case("awk-failure-no-jss-call", ("PASSWORD", "SECRET_NAME"), {".env": fixture("dummy_awk_failure")}, expected_status=1, awk_status=99),
        Case("help-env-variable-name", ("--help",), stdout_contains=b"ENV_VAR_NAME: variable NAME inside the env file"),
        Case("help-jss-destination-name", ("--help",), stdout_contains=b"JSS_DESTINATION_SECRET_NAME: optional destination secret NAME"),
        Case("help-no-secret-value-argument", ("--help",), stdout_contains=b"Both positional arguments are names; do not pass a secret value."),
        Case("literal-name-ignores-exported-value", ("API_KEY",), {".env": fixture("dummy_from_file", key="API_KEY")}, expected_stdout=b"dummy_from_file\n", environment={"API_KEY": "dummy_from_shell"}),
        Case("value-as-name-is-a-different-key", ("dummy_from_shell",), {".env": fixture("dummy_from_file", key="API_KEY")}, expected_status=4),
        Case("jss-destination-name-and-file-value", ("API_KEY", "MY_SERVICE_API_KEY"), {".env": fixture("dummy_from_file", key="API_KEY")}, expected_jss=["add", "MY_SERVICE_API_KEY", "dummy_from_file"], environment={"API_KEY": "dummy_from_shell"}),
    ]
    return result


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


def write_mock(bin_dir):
    helper = bin_dir / "fake_jss.py"
    helper.write_text(
        '#!/usr/bin/env python3\n'
        'import json\nimport os\nfrom pathlib import Path\nimport sys\n'
        'Path(os.environ["ENVGET_TEST_RECORD"]).write_text(json.dumps(sys.argv[1:], ensure_ascii=False), encoding="utf-8")\n'
        'sys.exit(int(os.environ.get("ENVGET_TEST_JSS_STATUS", "0")))\n',
        encoding="utf-8",
    )
    mock = bin_dir / "jss"
    mock.write_text('#!/bin/sh\nexec "$ENVGET_TEST_PYTHON" "$ENVGET_TEST_JSS_HELPER" "$@"\n', encoding="utf-8")
    mock.chmod(0o755)
    return helper


def shell_flags(is_zsh):
    if is_zsh:
        return ["-f", "-e", "-u", "-o", "pipefail"]
    return ["--noprofile", "--norc", "-e", "-u", "-o", "pipefail"]


def snapshot(path):
    details = path.stat()
    return path.read_bytes(), stat.S_IMODE(details.st_mode), details.st_mtime_ns


def run_case(shell, is_zsh, mode, case, work, bin_dir, helper, line_prefix):
    for name, content in case.files.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    for name in case.directories:
        (work / name).mkdir(parents=True, exist_ok=True)
    originals = {name: snapshot(work / name) for name in case.files}
    args = [arg.replace("{WORK}", str(work)) for arg in case.args]
    record = work / "jss-arguments.json"
    env = clean_environment()
    env.update(case.environment)
    env.update({
        "PATH": str(bin_dir) + os.pathsep + env.get("PATH", os.defpath),
        "ENVGET_TEST_PYTHON": sys.executable,
        "ENVGET_TEST_JSS_HELPER": str(helper),
        "ENVGET_TEST_RECORD": str(record),
        "ENVGET_TEST_JSS_STATUS": str(case.jss_status),
    })
    if case.awk_status is not None:
        failure_bin = work / "failure-bin"
        failure_bin.mkdir()
        fake_awk = failure_bin / "awk"
        fake_awk.write_text("#!/bin/sh\nexit " + str(case.awk_status) + "\n", encoding="utf-8")
        fake_awk.chmod(0o755)
        env["PATH"] = str(failure_bin) + os.pathsep + env["PATH"]
    flags = shell_flags(is_zsh)
    if mode == "execute":
        command = [str(shell)] + flags + [str(SCRIPT)] + args
    elif mode == "source":
        code = 'set -x; . "$1"; shift; envget "$@"; set +x; printf "%s\\n" ENVGET_TEST_SCRIPT_CONTINUED >&2'
        command = [str(shell)] + flags + ["-c", code, "envget-test", str(SCRIPT)] + args
    else:
        # Replace only the final example invocation; the function is unchanged.
        invocation = "envget" + (" " + " ".join(shlex.quote(arg) for arg in args) if args else "")
        code = "set -x; " + line_prefix + "; " + invocation + '\nset +x; printf "%s\\n" ENVGET_TEST_SCRIPT_CONTINUED >&2\n'
        generated = work / "one-liner-test.sh"
        generated.write_text(code, encoding="utf-8")
        command = [str(shell)] + flags + [str(generated)]
    result = subprocess.run(command, cwd=work, env=env, input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    if result.returncode != case.expected_status:
        raise AssertionError("expected exit {0}, got {1}; stderr={2!r}".format(case.expected_status, result.returncode, result.stderr[-1200:]))
    if case.stdout_contains:
        if case.stdout_contains not in result.stdout:
            raise AssertionError("expected stdout to contain {0!r}, got {1!r}".format(case.stdout_contains, result.stdout))
    elif result.stdout != case.expected_stdout:
        raise AssertionError("stdout mismatch: expected {0!r}, got {1!r}".format(case.expected_stdout, result.stdout))
    if mode != "execute" and ((CONTINUED in result.stderr) != (case.expected_status == 0)):
        raise AssertionError("strict-mode continuation did not match the command's success or failure")
    if case.expected_jss is None:
        if record.exists():
            raise AssertionError("jss was called unexpectedly")
    else:
        if not record.exists():
            raise AssertionError("jss was not called")
        received = json.loads(record.read_text(encoding="utf-8"))
        if received != case.expected_jss:
            raise AssertionError("jss argument mismatch: expected {0!r}, got {1!r}".format(case.expected_jss, received))
        if len(received) != 3:
            raise AssertionError("jss must receive exactly three arguments: add, name, value")
    for name, before in originals.items():
        if snapshot(work / name) != before:
            raise AssertionError("input file changed: " + name)
    if list(work.glob("ENVGET_SHOULD_NOT_EXIST*")):
        raise AssertionError("text from the password was executed as shell syntax")
    if case.name in ("symbol-password", "jss-symbol-password"):
        secret = case.files[".env"].split(b"=", 1)[1].rstrip(b"\n")
        if secret in result.stderr:
            raise AssertionError("shell tracing exposed the password")


def run_usage_check(shell, is_zsh, name, work, bin_dir, helper, one_liner):
    """Exercise the literal placeholder line and documented name variables."""
    original = b"ENV_VAR_NAME=dummy_placeholder_value\nAPI_KEY=dummy_file_value\n"
    env_file = work / ".env"
    env_file.write_bytes(original)
    record = work / "jss-arguments.json"
    env = clean_environment()
    env.update({
        "PATH": str(bin_dir) + os.pathsep + env.get("PATH", os.defpath),
        "ENVGET_TEST_PYTHON": sys.executable,
        "ENVGET_TEST_JSS_HELPER": str(helper),
        "ENVGET_TEST_RECORD": str(record),
        "ENVGET_TEST_JSS_STATUS": "0",
        "API_KEY": "dummy_wrong_shell_value",
    })
    if name == "interactive-full-one-liner":
        # zsh starts with INTERACTIVE_COMMENTS unset. The complete line must
        # work without enabling it, including its explanatory no-op text.
        history = "unsetopt INTERACTIVE_COMMENTS; setopt BANG_HIST" if is_zsh else "set -H"
        code = history + "\n" + one_liner + 'printf "ENVGET_INTERACTIVE_DONE\\n"\nexit\n'
        flags = ["-f", "-i"] if is_zsh else ["--noprofile", "--norc", "-i"]
        command = [str(shell)] + flags
        input_bytes = code.encode("utf-8")
        expected_stdout = b"dummy_placeholder_value\nENVGET_INTERACTIVE_DONE\n"
        expected_jss = None
    else:
        code = '. "$1"; env_var_name=API_KEY; jss_destination_secret_name=MY_SERVICE_API_KEY; '
        if name == "eval-source-and-read":
            # eval of the file text must only declare envget (bash -u: no BASH_SOURCE; zsh: eval context).
            code = 'eval "$(cat "$1")"; envget API_KEY'
            expected_stdout = b"dummy_file_value\n"
            expected_jss = None
        elif name == "dynamic-variable-name":
            code += 'envget "$env_var_name"'
            expected_stdout = b"dummy_file_value\n"
            expected_jss = None
        else:
            code += 'envget "$env_var_name" "$jss_destination_secret_name"'
            expected_stdout = b""
            expected_jss = ["add", "MY_SERVICE_API_KEY", "dummy_file_value"]
        command = [str(shell)] + shell_flags(is_zsh) + ["-c", code, "envget-usage-test", str(SCRIPT)]
        input_bytes = b""
    result = subprocess.run(command, cwd=work, env=env, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    if result.returncode != 0 or result.stdout != expected_stdout:
        raise AssertionError("usage example failed: status={0}, stdout={1!r}, stderr={2!r}".format(result.returncode, result.stdout, result.stderr[-1200:]))
    actual_jss = json.loads(record.read_text(encoding="utf-8")) if record.exists() else None
    if actual_jss != expected_jss:
        raise AssertionError("usage example called jss with wrong name/value: " + repr(actual_jss))
    if env_file.read_bytes() != original:
        raise AssertionError("usage example changed its input file")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shell", action="append", metavar="PATH", help="Bash or zsh executable; repeat to test several versions")
    parser.add_argument("--verbose", action="store_true", help="print every successful case")
    options = parser.parse_args()
    if not SCRIPT.is_file() or not ONE_LINER.is_file():
        parser.error("Keep test_envget.py beside envget.sh and envget-one-liner.md.")
    one_liner = ONE_LINER.read_text(encoding="utf-8")
    if len(one_liner.splitlines()) != 1:
        parser.error("envget-one-liner.md must contain exactly one physical line.")
    line_prefix, separator, invocation = one_liner.rstrip("\n").rpartition("; envget ")
    if not separator or not invocation:
        parser.error("Cannot locate the one-liner's final envget invocation.")
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
    usage_checks = ("interactive-full-one-liner", "eval-source-and-read", "dynamic-variable-name", "dynamic-source-and-destination-names")
    checks = 0
    failures = []
    try:
        with tempfile.TemporaryDirectory(prefix="envget-tests-", dir=Path.cwd()) as temporary:
            base = Path(temporary)
            bin_dir = base / "mock-bin"
            bin_dir.mkdir()
            helper = write_mock(bin_dir)
            for shell_index, (shell, label, is_zsh) in enumerate(resolved):
                shell_failures = 0
                for case_index, case in enumerate(matrix):
                    for mode in MODES:
                        work = base / ("shell-{0}-case-{1}-{2}".format(shell_index, case_index, mode))
                        work.mkdir()
                        checks += 1
                        name = "{0}: {1}: {2}".format(label, mode, case.name)
                        try:
                            run_case(shell, is_zsh, mode, case, work, bin_dir, helper, line_prefix)
                        except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as error:
                            shell_failures += 1
                            failures.append(name)
                            print("FAIL: " + name + "\n  " + str(error), file=sys.stderr)
                        else:
                            if options.verbose:
                                print("PASS: " + name)
                for usage_name in usage_checks:
                    work = base / ("shell-{0}-{1}".format(shell_index, usage_name))
                    work.mkdir()
                    checks += 1
                    name = label + ": " + usage_name
                    try:
                        run_usage_check(shell, is_zsh, usage_name, work, bin_dir, helper, one_liner)
                    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as error:
                        shell_failures += 1
                        failures.append(name)
                        print("FAIL: " + name + "\n  " + str(error), file=sys.stderr)
                    else:
                        if options.verbose:
                            print("PASS: " + name)
                per_shell = len(matrix) * len(MODES) + len(usage_checks)
                print("{0}: {1}; {2} cases x {3} forms + {4} usage checks = {5} checks; {6} failures".format("PASS" if not shell_failures else "FAIL", label, len(matrix), len(MODES), len(usage_checks), per_shell, shell_failures), flush=True)
    except OSError as error:
        print("Cannot create or use the temporary test directory below the current directory: " + str(error), file=sys.stderr)
        return 1
    print("Total: {0} checks across {1} shell(s); {2} failures. Only synthetic passwords and a mock jss were used.".format(checks, len(resolved), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
