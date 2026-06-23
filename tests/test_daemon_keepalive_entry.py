"""Inertness contract for the L0 OS-keepalive entry (TRDD-71ABD7V7).

The launchd/systemd target is re-scanned by CPV's persistence discriminator (its
C2/C3 gates) and must be provably CLEAN + NON-EXPLOITABLE: no dynamic load/exec, no
input-listen RCE surface. These tests are a janitor-owned, STRICTER-than-CPV proof
(an AST whitelist, so the docstring's mentions of the forbidden constructs do not
count) that the shipped entry stays inert — if it ever grows a dangerous call, the
build fails here long before the CPV gate does.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENTRY_PATH = Path(__file__).resolve().parents[1] / "scripts" / "daemon_keepalive_entry.py"
SRC = ENTRY_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

# Only these three modules may be imported — this alone bars subprocess / socket /
# importlib / ctypes etc. from ever being used in the launched file.
ALLOWED_IMPORTS = {"os", "sys", "daemon"}

# Call targets (a bare name or the final attribute) that signal dynamic code
# execution or an RCE surface — the exact shapes CPV's C3 (_non_exploitable)
# rejects, plus a defensive superset.
FORBIDDEN_CALL_NAMES = {
    "eval", "exec", "compile", "__import__", "import_module", "open", "input",
    "system", "popen", "spawn", "fork",
    "execv", "execve", "execvp", "execvpe", "execl", "execlp", "execle",
    "Popen", "run", "call", "check_output", "check_call", "getoutput",
    "socket", "create_connection", "bind", "listen", "connect", "recvfrom",
    "load", "loads", "run_path", "load_module", "exec_module",
}


def _called_name(node: ast.Call) -> str:
    """Return the bare name or final attribute of a call's target (e.g. os.system -> 'system')."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def test_entry_has_python3_shebang() -> None:
    """The entry begins with a python3 shebang so launchd/systemd can exec it directly."""
    assert SRC.splitlines()[0] == "#!/usr/bin/env python3"


def test_entry_imports_only_os_sys_daemon() -> None:
    """The launched file imports ONLY os, sys, daemon — barring subprocess/socket/importlib outright."""
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A bare `from __future__ import …` is allowed; any other from-import is not.
            if node.module != "__future__":
                imported.add((node.module or "").split(".")[0])
    assert imported <= ALLOWED_IMPORTS, f"unexpected imports: {imported - ALLOWED_IMPORTS}"


def test_entry_has_no_dynamic_exec_or_rce_calls() -> None:
    """No call in the entry is a dynamic-exec / RCE sink (CPV C3 non-exploitable, proven via AST)."""
    offenders = sorted(
        {name for node in ast.walk(TREE) if isinstance(node, ast.Call)
         if (name := _called_name(node)) in FORBIDDEN_CALL_NAMES}
    )
    assert not offenders, f"forbidden call(s) present: {offenders}"


def test_entry_opens_no_listen_socket_surface() -> None:
    """The entry has no server/listen construct (a boot daemon opening a port is an RCE surface)."""
    # With imports restricted to os/sys/daemon there is no transport module to listen on;
    # assert positively that none of the listen/bind/serve attribute names appear in the AST.
    listen_attrs = {"listen", "bind", "createServer", "start_server", "serve_forever", "recvfrom"}
    found = {
        node.attr for node in ast.walk(TREE)
        if isinstance(node, ast.Attribute) and node.attr in listen_attrs
    }
    assert not found, f"listen/serve surface present: {sorted(found)}"


def test_entry_launches_daemon_in_keepalive_mode() -> None:
    """The entry injects --keepalive and runs daemon.main() (the intended OS-keepalive behavior)."""
    has_keepalive_flag = any(
        isinstance(node, ast.Constant) and node.value == "--keepalive"
        for node in ast.walk(TREE)
    )
    calls_daemon_main = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "main"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "daemon"
        for node in ast.walk(TREE)
    )
    assert has_keepalive_flag, "entry must inject the --keepalive flag"
    assert calls_daemon_main, "entry must call daemon.main()"


def test_entry_discovers_its_dir_from___file__() -> None:
    """The entry resolves its own dir from __file__ (verbatim-copyable: no path is baked in / templated)."""
    uses_file = any(
        isinstance(node, ast.Name) and node.id == "__file__" for node in ast.walk(TREE)
    )
    # No string-formatting of a path: no f-strings, no %-format, no .format()/.replace().
    no_fstring = not any(isinstance(node, ast.JoinedStr) for node in ast.walk(TREE))
    no_str_templating = not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"format", "replace"}
        for node in ast.walk(TREE)
    )
    assert uses_file, "entry must autodiscover its directory from __file__"
    assert no_fstring and no_str_templating, "entry must not template any path (verbatim-copyable)"
