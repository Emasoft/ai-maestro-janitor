"""Python-language-specific attack-surface patterns.

Wave 17 impl-aa — distillation of 8 proposals from
``distill3-g-python-specific`` into deterministic regex rules.

The distill report proposed AST-based detectors for shapes that the
janitor's current detector stack does NOT cover: the Python-runtime
side of the import system (``__import__`` / ``importlib`` with non-
literal arguments), site-packages persistence vectors (``.pth`` files,
``sitecustomize.py`` / ``usercustomize.py``), ``sys.path`` tainting,
two-file lazy-dropper ``__init__.py`` chains, reflection-based exec
(``inspect.getsource``+``exec``, ``types.ModuleType``+``exec``), and
import-time decorator-argument side effects.

This module encodes the same shapes as **pure regex** for the
heartbeat detectors that prefer the lightweight one-pass scanner
shape over an AST walk. The regex rules accept a small precision
trade-off (slightly higher FP rate vs an AST walk that can reason
about scopes) in exchange for being trivially composable with the
other ``scripts/lib/*_patterns.py`` modules.

Architecture mirrors ``scripts/lib/agent_config_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — single finding record.

Pure-stdlib (``re``, ``NamedTuple``) so the module loads in every
PEP 723 script block without third-party deps.

Severity mapping from the distill-3-g report's MAJOR/CRITICAL onto
the janitor's canonical four-tier scale:

  CRITICAL (report) → CRITICAL (rule)
  MAJOR    (report) → HIGH (rule)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/agent_config_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE.

    Python identifiers and keywords are case-sensitive — so the
    regexes here do NOT use IGNORECASE (unlike the prose/config-file
    scanners). This is the right choice for source code: ``Import``
    is NOT the same as ``import`` in Python parsing.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Proposal 1: __import__ with non-literal first arg -----------------


# ``__import__`` is a builtin whose first positional argument must be
# the module name string. A literal string (``__import__("subprocess")``)
# is the legitimate shape used by every documented framework. A
# non-literal first argument — variable, attribute access, function
# call (``__import__(base64.b64decode(...))``), or string-concat —
# is the canonical obfuscation shape used in PyPI dropper packages.
#
# Pattern strategy: match ``__import__(`` followed by anything that
# is NOT a quote-opener (no ``'`` or ``"`` immediately inside the
# parens, modulo leading whitespace). The negative lookahead rejects
# the literal-string shape and lets every "computed name" shape fire.
# Trailing ``\s*\)`` requirement avoids triggering on unfinished
# half-typed sources.
_DUNDER_IMPORT_NONLITERAL = _re(
    r"\b__import__\s*\(\s*"
    r"(?!['\"])"                 # NOT a quote — i.e. not a string literal
    r"(?![\)\n])"                # NOT a closing paren (bare ``__import__()``)
    r"[^\)\n]{1,200}\)"
)


# ---- Proposal 2: importlib.import_module / spec_from_file_location -----


# ``importlib.import_module(NAME)`` and
# ``importlib.util.spec_from_file_location(NAME, PATH)`` are the
# documented modern way to load code dynamically. As with
# ``__import__``, the legitimate shape passes a string literal; a
# non-literal name OR a non-literal path is the smell.
#
# The shape ``importlib.import_module(VAR)`` is caught by branch (A)
# below. The shape ``importlib.util.spec_from_file_location("name",
# downloaded_path)`` keeps a literal first arg but the file PATH
# itself comes from untrusted bytes — branch (B) catches that.
#
# We DON'T require a co-located exfil-cluster import (the distill
# report suggests this as an FP-reduction layer) — the caller does
# the cluster check upstream. Here we just catch the shape.
_IMPORTLIB_DYNAMIC_NONLITERAL = _re(
    # Branch A: import_module / spec_from_file_location / SourceFileLoader
    # with a non-literal FIRST positional arg.
    r"\bimportlib(?:\.util|\.machinery)?\."
    r"(?:import_module|spec_from_file_location|SourceFileLoader)"
    r"\s*\(\s*"
    r"(?!['\"])"                 # NOT a string literal
    r"(?![\)\n])"                # NOT empty
    r"[A-Za-z_][\w.\[\]\(\)\"' ]{0,200}"
    r"(?:,|\))"
    # Branch B: spec_from_file_location / SourceFileLoader where the
    # SECOND positional arg (the file path) is a non-literal — variable
    # name or function-call return.
    r"|\bimportlib(?:\.util|\.machinery)?\."
    r"(?:spec_from_file_location|SourceFileLoader)"
    r"\s*\(\s*"
    r"['\"][^'\"\n]+['\"]"       # First arg IS a literal (module name)
    r"\s*,\s*"
    r"(?!['\"])"                 # Second arg is NOT a literal — taint
    r"(?![\)\n])"
    r"[A-Za-z_][\w.\[\]\(\) ]{0,200}\)"
)


# ---- Proposal 3: .pth files with `import` line -------------------------


# ``.pth`` files inside ``site-packages/`` are auto-evaluated by
# ``site.py`` at every Python interpreter startup. Lines starting
# with ``import`` (optionally followed by whitespace/tab) are
# documented Python behaviour — the line is exec'd verbatim. ZERO
# legit ``.pth`` files use this. The shape is the textbook silent-
# persistence vector.
#
# Pattern tolerates zero-width unicode prefixes so the attacker
# can't bypass with invisible-character homoglyphs. ``^`` is line-
# anchored under MULTILINE.
_PTH_IMPORT_LINE = _re(
    r"^[\s​‌‍﻿]*import[\s\t​‌‍﻿]+"
)


# ---- Proposal 4: sitecustomize.py / usercustomize.py presence ----------


# ``sitecustomize`` / ``usercustomize`` are auto-imported by
# ``site.py`` on every Python startup if they're findable on
# ``sys.path``. The PRESENCE of either filename in a repo is itself
# the smell — these files are essentially never legitimately
# committed to a project repository. The distill report proposes
# AST-walking the body to triage exfil-cluster vs benign env tweaks;
# here we use a regex on a marker line that, in practice, every
# auto-startup customise file contains: an ``import`` statement
# combined with a top-level ``subprocess`` / ``socket`` / ``ctypes``
# / ``urllib`` / ``requests`` / ``httpx`` / ``ftplib`` / ``telnetlib``
# reference within the same file. The CALLER routes only files whose
# basename is ``sitecustomize.py`` or ``usercustomize.py`` through
# this rule; we just fire on the dangerous content.
_SITECUSTOMIZE_DANGEROUS_BODY = _re(
    r"^[ \t]*(?:from|import)\s+"
    r"(?P<mod>subprocess|socket|ctypes|urllib|requests|httpx|ftplib|"
    r"telnetlib|paramiko|os)\b"
    r"|^[ \t]*(?:eval|exec|compile)\s*\("
)


# ---- Proposal 5: sys.path.insert / append with tainted / writable path -


# ``sys.path.insert(0, X)`` and ``sys.path.append(X)`` where ``X`` is:
#   * a path lexically containing ``..`` (parent-traversal escape), or
#   * a path starting with ``/tmp/``, ``/var/tmp/``, or ``/dev/shm/``
#     (writable-by-any-uid staging directories), or
#   * a function-call value (taint shape — return of
#     ``urllib.request.urlretrieve``, ``requests.get(...)``, etc.), or
#   * ``os.environ[...]`` / ``os.getenv(...)`` (env-controlled).
#
# Legit shapes — ``sys.path.insert(0, str(Path(__file__).parent / "lib"))``
# — pass either a literal relative path or a ``Path(__file__)``-derived
# string. Those don't match the alternatives below.
_SYS_PATH_TAINTED = _re(
    r"\bsys\.path\.(?:insert|append)\s*\(\s*"
    r"(?:0\s*,\s*)?"                                # `insert(0, …)` skips the index
    # Branch A: string literal containing `..` or writable-prefix paths
    r"(?:"
    r"['\"][^'\"\n]*\.\.[^'\"\n]*['\"]"             # `'../foo'` or `"../bar"`
    r"|['\"]/(?:tmp|var/tmp|dev/shm)/[^'\"\n]*['\"]"
    # Branch B: os.environ / os.getenv as the path arg
    r"|os\.environ\s*\[[^\]\n]+\]"
    r"|os\.getenv\s*\("
    # Branch C: urllib / requests / subprocess return-value as path arg
    r"|(?:urllib\.request\.urlretrieve|requests\.get|requests\.post"
    r"|httpx\.get|subprocess\.(?:check_output|run|Popen))\s*\("
    r")"
)


# ---- Proposal 6: __init__.py lazy-dropper chain ------------------------


# A cross-file proposal: ``__init__.py`` contains ``from . import X``
# and ``X.py`` body contains a top-level ``subprocess.Popen``. Pure
# regex can't walk two files, but it CAN flag the suspicious
# single-file shape: a tiny ``__init__.py``-style module body whose
# whole content is a single ``from . import …`` (lazy-loader shape)
# AND the file is named ``__init__.py`` AND the line text contains
# the kebab to identify the import. The caller routes only
# ``__init__.py`` files to this scanner; the regex fires on the
# single ``from . import`` line as a marker, and the caller is
# expected to cross-reference the sibling module body.
#
# We deliberately keep the regex permissive — the rule fires on any
# top-level ``from . import X`` statement in an ``__init__.py`` that
# otherwise has minimal content. The single-rule shape gives the
# detector a way to enumerate candidate children for further audit
# without baking the cross-file walk into the regex itself.
_INIT_PY_LAZY_RELATIVE_IMPORT = _re(
    r"^[ \t]*from\s+\.\s+import\s+(?P<child>[A-Za-z_][A-Za-z0-9_]*)"
)


# ---- Proposal 7: reflection-based exec (getsource + exec, ModuleType) --


# Two shape families combined into one regex:
#
# Shape A — ``inspect.getsource(...)`` anywhere in the file AND ``exec(``
#           anywhere in the file. We can't tie them to a specific variable
#           name without an AST walk, but the co-occurrence of the two
#           in any non-trivial file is itself the smell — legitimate
#           uses of ``inspect.getsource`` are for documentation tools
#           that never call ``exec``.
#
# Shape B — ``types.ModuleType(`` AND ``exec(`` in the same file.
#           Same co-occurrence signal: legitimate uses of ModuleType
#           (e.g. dynamic plugin loaders) generally avoid ``exec`` —
#           they use ``exec_module`` from importlib.machinery.
#
# Single regex pattern: we use a forward-reference trick — match the
# first signal anywhere, then require the second signal anywhere
# later in the string. ``re.DOTALL`` would let ``.`` cross newlines;
# we use ``[\s\S]`` instead to keep MULTILINE behaviour intact.
_REFLECTION_EXEC_COOCCURRENCE = _re(
    # First marker
    r"(?:\binspect\.getsource\s*\(|\btypes\.ModuleType\s*\()"
    r"[\s\S]{0,8000}?"
    # Second marker (within same 8KB window)
    r"\bexec\s*\("
)


# ---- Proposal 8: decorator-argument import-time side effect ------------


# A decorator factory ``@foo(args)`` evaluates ``foo(args)`` at import
# time — every expression inside the parens runs before any user
# code calls the decorated function. The smell: a decorator whose
# arguments contain a ``subprocess.run`` / ``subprocess.Popen`` /
# ``os.system`` / ``requests.{get,post}`` / ``httpx.{get,post}`` /
# ``urllib.request.urlopen`` / ``socket.socket`` call. Legit shape:
# the decorator factory takes literal / constant arguments.
#
# Pattern: ``@`` at start of line, optional dotted name, ``(``, then
# anywhere inside the parens (no newline escape, single-line
# decorators only) one of the dropper-shape calls.
_DECORATOR_DROPPER_ARG = _re(
    r"^[ \t]*@[A-Za-z_][\w.]*\s*\(\s*"
    r"[^)\n]{0,400}?"
    r"\b(?:subprocess\.(?:run|Popen|check_output|call)"
    r"|os\.(?:system|popen|exec[lv]?p?e?)"
    r"|socket\.(?:socket|create_connection)"
    r"|requests\.(?:get|post|put|delete)"
    r"|httpx\.(?:get|post)"
    r"|urllib\.request\.urlopen)"
    r"\s*\("
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="py-dunder-import-nonliteral",
        name="__import__ called with non-literal module name",
        severity="HIGH",
        description=(
            "`__import__(X)` where X is NOT a string literal — variable, "
            "attribute access, function-call return, or base64-decoded "
            "bytes. The canonical Python-runtime obfuscation shape that "
            "evades static-only `setup.py` scanners by deferring the "
            "module name until runtime. Disclosed in "
            "claude_security_sentinel + sentinel-main."
        ),
        pattern=_DUNDER_IMPORT_NONLITERAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="py-importlib-dynamic-load-nonliteral",
        name="importlib dynamic load with non-literal first arg",
        severity="HIGH",
        description=(
            "`importlib.import_module(X)` / "
            "`importlib.util.spec_from_file_location(X, ...)` / "
            "`importlib.machinery.SourceFileLoader(X, ...)` where X is "
            "NOT a string literal. The modern `__import__` equivalent; "
            "any deterministic check on `__import__` MUST also cover "
            "the importlib family or attackers trivially refactor."
        ),
        pattern=_IMPORTLIB_DYNAMIC_NONLITERAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="py-pth-file-import-line",
        name=".pth file contains import-line (site.py auto-exec)",
        severity="CRITICAL",
        description=(
            "A `.pth` file's body contains a line whose first non-"
            "whitespace token is `import`. Python's `site.py` documents "
            "this exact shape: lines starting `import ` (or `import\\t`) "
            "are exec'd verbatim on every interpreter startup. ZERO "
            "legitimate `.pth` files use this. Caller must route only "
            "`*.pth` files to this rule. Highest-value gap in the "
            "Python runtime detector stack."
        ),
        pattern=_PTH_IMPORT_LINE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="py-sitecustomize-dangerous-body",
        name="sitecustomize/usercustomize body imports exfil module or exec",
        severity="HIGH",
        description=(
            "Body of a file named `sitecustomize.py` / `usercustomize.py` "
            "imports an exfil-cluster module (subprocess / socket / "
            "ctypes / urllib / requests / httpx / ftplib / telnetlib / "
            "paramiko / os) or calls eval/exec/compile. Python auto-"
            "imports both files at startup from sys.path. Caller must "
            "route only those two basenames to this rule."
        ),
        pattern=_SITECUSTOMIZE_DANGEROUS_BODY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="py-sys-path-insert-from-network",
        name="sys.path.insert/append from tainted or writable path",
        severity="CRITICAL",
        description=(
            "`sys.path.insert` / `sys.path.append` with an argument that "
            "is a parent-traversal path (`..`), a world-writable staging "
            "directory (`/tmp/`, `/var/tmp/`, `/dev/shm/`), an env-var "
            "read (`os.environ[...]` / `os.getenv(...)`), or a network/"
            "subprocess return value. Path-hijack pivot used in disclosed "
            "Python supply-chain incidents."
        ),
        pattern=_SYS_PATH_TAINTED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="py-init-py-lazy-relative-import",
        name="__init__.py contains lazy `from . import X` candidate",
        severity="LOW",
        description=(
            "An `__init__.py` file contains a top-level `from . import X` "
            "statement. This is the marker side of the two-file lazy-"
            "dropper chain: caller must cross-reference the sibling "
            "`X.py` body for top-level subprocess.Popen / network / "
            "exec-shape calls. By itself this is LOW severity (legit "
            "Python package layout pattern); paired with a dropper-shape "
            "child it escalates."
        ),
        pattern=_INIT_PY_LAZY_RELATIVE_IMPORT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="py-reflection-exec-getsource-modtype",
        name="inspect.getsource or types.ModuleType co-located with exec",
        severity="HIGH",
        description=(
            "File contains `inspect.getsource(...)` OR `types.ModuleType("
            "...)` AND a subsequent `exec(...)` call within an 8KB window. "
            "Two AST-level signatures of anti-static-analysis tricks: "
            "(A) decompile-self-then-exec for source mutation, (B) "
            "dynamic-module fabrication that bypasses `sys.modules` "
            "import hooks. Neither has a legit use in production code."
        ),
        pattern=_REFLECTION_EXEC_COOCCURRENCE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="py-decorator-import-time-side-effect",
        name="Decorator factory argument runs subprocess/network at import",
        severity="HIGH",
        description=(
            "A decorator factory `@foo(args)` whose argument expression "
            "contains a `subprocess.run` / `subprocess.Popen` / "
            "`os.system` / `requests.get` / `httpx.post` / `socket.socket` "
            "/ `urllib.request.urlopen` call. The argument evaluates at "
            "import time — every dropper-shape call runs the moment the "
            "module is imported, even if the decorated function is "
            "never called."
        ),
        pattern=_DECORATOR_DROPPER_ARG,
        owasp_asi="ASI-06",
    ),
)


# ---- The composed scanner ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Unlike ``agent_config_patterns.scan_text`` this scanner does not
    differentiate prose vs source — every rule here targets a specific
    Python source-file shape and the caller routes the right file at
    the right rule (e.g. ``.pth`` files only to the pth-import-line
    rule, ``__init__.py`` only to the lazy-relative-import rule,
    ``sitecustomize.py`` / ``usercustomize.py`` only to the
    sitecustomize-dangerous-body rule). We keep the single-entry
    signature for parity with the reference module so heartbeat
    detectors can call either uniformly.

    Findings are deduped by ``(rule_id, line, col)`` — a single line
    that triggers two rules emits two findings, but the same rule
    firing twice on the same line emits one.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
