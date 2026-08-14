"""Drift guard: every READ-ONLY `git` subprocess invocation under `scripts/` must be
protected from taking `.git/index.lock` (janitor#245).

THE INCIDENT THIS EXISTS FOR (measured, not theorized — see the atom
`ATOM-ZSY4-JI84` and `scripts/lib/git_utils.py::_git`'s docstring for the
120-iteration measurement): `git status` and `git diff` WRITE
`.git/index.lock` for an OPTIONAL stat-cache write-back even though they only
READ history, and they fail SOFT (exit 0, no visible symptom) when denied it.
A concurrent WRITER (`git add`/`git commit` — e.g. `publish.py`'s own release
commit) fails HARD on the same lock instead. So a background reader — a
janitor heartbeat detector, a hook, a stray `git status` — can silently kill
whatever else is touching the repo while reporting success itself.

The fix (`GIT_OPTIONAL_LOCKS=0` on the child env) was applied PER CALL SITE
across ~20 files before this test existed, with nothing keeping a NEW git call
site honest. This is that guard: it walks every `.py` under `scripts/`,
extracts every `["git", ...]` invocation via `ast` (never hand-typed, never a
grep that could miss a reformatted call), classifies each as WRITE (exempt —
it legitimately needs the lock and must not be muted) or READ-ONLY (must be
provably protected), and fails loudly, naming file:line, on any read-only
invocation this test cannot prove is protected.

WHAT COUNTS AS "PROTECTED" (mirrors the patterns already live in the tree):
  1. `state.run_subprocess(...)` — unconditionally injects
     `GIT_OPTIONAL_LOCKS=0` for every child it spawns (state.py), git or not.
  2. `git_utils.run_git_readonly(...)` / the module-private `git_utils._git(...)`
     — the shared read-only git helper this same TRDD adds.
  3. A call to a LOCALLY-DEFINED wrapper function (e.g. `_run`, `_out`, a
     file's own `run()`) whose OWN function body mentions
     `GIT_OPTIONAL_LOCKS` — every call to that wrapper is protected
     regardless of what the call site itself passes, because the wrapper
     injects the env unconditionally (the `_run`-in-`fleet_status.py` /
     `_git`-in-`git_utils.py` pattern).
  4. A direct `subprocess.run`/`check_call`/`check_output`/`Popen` (or a
     local `run()` passthrough, e.g. `publish.py`) call that passes an
     explicit `env=` keyword whose value either (a) is itself a call to one
     of the wrapper functions from (3), or (b) is a plain variable, in which
     case the ENCLOSING function's source must mention `GIT_OPTIONAL_LOCKS`
     (the `git_env = dict(os.environ); git_env["GIT_OPTIONAL_LOCKS"] = "0"`
     inline pattern used throughout the detectors).
  5. A file that sets `os.environ["GIT_OPTIONAL_LOCKS"]` at MODULE scope
     (outside every function) — protects every call in that file
     unconditionally, process-wide (the `trdd-state-reconciliation.py`
     pattern).

WHAT IS EXEMPT (never needs protection — the lock is legitimately theirs, or
irrelevant): any invocation whose git VERB is one of
`add/commit/push/mv/rm/checkout/reset/clean/tag` (per this TRDD's own scope),
plus `git config <key> <value>` (a WRITE to `.git/config`, never the index —
only `git config --get ...` is treated as a read needing protection).

A finding here means: someone added a new `["git", ...]` invocation without
carrying the fix forward. Fix it the same way every sibling call site was
fixed — pass `env=` from a protected wrapper, or route through
`state.run_subprocess` / `git_utils.run_git_readonly`.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_ROOT = _PROJECT_ROOT / "scripts"

# Verbs that legitimately need `.git/index.lock` (or, for `tag`, are exempted
# wholesale per this TRDD's explicit scope — a `git tag --sort=...` LIST is
# harmless to leave unprotected too, since listing tags never touches the
# index either).
_WRITE_VERBS = frozenset(
    {"add", "commit", "push", "mv", "rm", "checkout", "reset", "clean", "tag"}
)

# Callees that are ALWAYS protected, however they were reached, because the
# callee itself unconditionally injects GIT_OPTIONAL_LOCKS=0.
_ALWAYS_PROTECTED_CALLEES = frozenset(
    {
        "state.run_subprocess",
        "git_utils.run_git_readonly",
        "git_utils._git",
        "run_git_readonly",  # imported directly (`from git_utils import run_git_readonly`)
    }
)


def _iter_scanned_files() -> list[Path]:
    """Every `.py` under `scripts/` this guard is responsible for."""
    return sorted(_SCRIPTS_ROOT.rglob("*.py"))


def _callee_name(func_node: ast.expr) -> str:
    try:
        return ast.unparse(func_node)
    except Exception:  # noqa: BLE001 - malformed/unparseable expr, treat as unknown
        return ""


def _compute_wrapper_names(tree: ast.Module, source: str) -> set[str]:
    """Every locally-defined function whose OWN body EITHER mentions
    GIT_OPTIONAL_LOCKS directly, OR calls `state.run_subprocess` — the second
    arm covers the `_out`/`_out_any`-in-identify_environment.py shape: a
    thin wrapper that forwards to `state.run_subprocess` (which is
    unconditionally protected — see `_ALWAYS_PROTECTED_CALLEES`) without
    repeating the literal env-building code itself. A call to either shape of
    wrapper is protected regardless of what the call site passes (rule 3)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(source, node) or ""
            if "GIT_OPTIONAL_LOCKS" in seg or "run_subprocess(" in seg:
                names.add(node.name)
    return names


def _has_module_level_lock_env(tree: ast.Module, source: str) -> bool:
    """True iff a TOP-LEVEL (outside every function/class) statement mentions
    GIT_OPTIONAL_LOCKS — protects the whole file unconditionally (rule 5)."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        seg = ast.get_source_segment(source, node) or ""
        if "GIT_OPTIONAL_LOCKS" in seg:
            return True
    return False


class _GitCallVisitor(ast.NodeVisitor):
    """Walk a module's AST, collecting one finding per unprotected read-only
    `["git", ...]` invocation. Tracks the enclosing FunctionDef so rule 4's
    "enclosing function mentions GIT_OPTIONAL_LOCKS" check has a scope to
    search — a bare `ast.walk` gives no parent, so this needs a real visitor.
    """

    def __init__(self, source: str, rel_path: str, wrapper_names: set[str]) -> None:
        self.source = source
        self.rel_path = rel_path
        self.wrapper_names = wrapper_names
        self.func_stack: list[ast.AST] = []
        self.findings: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.func_stack.append(node)
        self.generic_visit(node)
        self.func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _enclosing_source(self) -> str:
        if not self.func_stack:
            return self.source
        seg = ast.get_source_segment(self.source, self.func_stack[-1])
        return seg or self.source

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self._check_git_call(node)
        self.generic_visit(node)

    def _check_git_call(self, node: ast.Call) -> None:
        if not node.args:
            return
        first = node.args[0]
        if not isinstance(first, (ast.List, ast.Tuple)) or not first.elts:
            return
        head = first.elts[0]
        if not (isinstance(head, ast.Constant) and head.value == "git"):
            return  # not a `["git", ...]` argv — a data tuple/table entry, etc.

        verb = None
        if len(first.elts) > 1 and isinstance(first.elts[1], ast.Constant):
            verb = first.elts[1].value

        if verb in _WRITE_VERBS:
            return  # legitimately needs the lock (or is exempted wholesale)

        if verb == "config":
            third = first.elts[2] if len(first.elts) > 2 else None
            is_read = isinstance(third, ast.Constant) and third.value == "--get"
            if not is_read:
                return  # a config SET — never touches .git/index

        if self._is_protected(node):
            return

        self.findings.append(
            f"{self.rel_path}:{node.lineno}: unprotected read-only git call "
            f"(verb={verb!r}, callee={_callee_name(node.func)!r})"
        )

    def _is_protected(self, node: ast.Call) -> bool:
        callee = _callee_name(node.func)
        if callee in _ALWAYS_PROTECTED_CALLEES:
            return True
        base = callee.rsplit(".", 1)[-1] if callee else ""
        if base in self.wrapper_names:
            return True

        env_kw = next((kw for kw in node.keywords if kw.arg == "env"), None)
        if env_kw is None:
            return False
        if isinstance(env_kw.value, ast.Constant) and env_kw.value.value is None:
            return False  # `env=None` is explicitly "no override" — not protected

        if isinstance(env_kw.value, ast.Call):
            inner = _callee_name(env_kw.value.func).rsplit(".", 1)[-1]
            if inner in self.wrapper_names:
                return True

        # Fallback for `env=<a plain Name>`: the enclosing function EITHER
        # (a) builds that variable inline (`git_env["GIT_OPTIONAL_LOCKS"] =
        # "0"`) a few lines above the call — the pattern used throughout
        # state.py / the detectors — OR (b) assigns it from a call to a
        # wrapper function DEFINED IN A DIFFERENT function than the call
        # site (`git_env = _git_env()` in `main()`, `_git_env` defined at
        # module scope — nested-git-safety.py's shape: one wrapper call
        # builds the env once, then several sibling calls in the SAME
        # function reuse the variable). Both are scoped to the ENCLOSING
        # function's own source (never the whole file) so an unrelated
        # function's mention can't launder a different, actually-unprotected
        # call site.
        enclosing = self._enclosing_source()
        if "GIT_OPTIONAL_LOCKS" in enclosing:
            return True
        return any(f"{name}(" in enclosing for name in self.wrapper_names)


def _scan_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # not this guard's job to catch syntax errors

    if _has_module_level_lock_env(tree, source):
        return []  # rule 5 — whole file protected process-wide

    rel_path = str(path.relative_to(_PROJECT_ROOT))
    wrapper_names = _compute_wrapper_names(tree, source)
    visitor = _GitCallVisitor(source, rel_path, wrapper_names)
    visitor.visit(tree)
    return visitor.findings


def _scan_all() -> list[str]:
    findings: list[str] = []
    for path in _iter_scanned_files():
        findings.extend(_scan_file(path))
    return findings


def test_every_readonly_git_invocation_under_scripts_is_protected():
    """Drift guard: a new `["git", ...]` call under scripts/ that is not a
    WRITE verb must carry GIT_OPTIONAL_LOCKS=0 through one of the sanctioned
    channels, or this fails naming the exact file:line (janitor#245)."""
    findings = _scan_all()
    assert not findings, (
        "unprotected read-only git invocation(s) found — each can take "
        ".git/index.lock and kill a concurrent WRITE (janitor#245); protect "
        "via env=<GIT_OPTIONAL_LOCKS=0 dict>, state.run_subprocess, or "
        "git_utils.run_git_readonly:\n" + "\n".join(findings)
    )


def test_the_scanner_actually_detects_an_unprotected_call():
    """Self-check the guard is not a silent no-op: feed it source containing
    a genuinely unprotected `git status` call and confirm it fires."""
    source = (
        "import subprocess\n\n"
        "def read_status(root):\n"
        "    return subprocess.run(['git', 'status', '--porcelain'], cwd=root)\n"
    )
    tree = ast.parse(source)
    assert not _has_module_level_lock_env(tree, source)
    wrapper_names = _compute_wrapper_names(tree, source)
    visitor = _GitCallVisitor(source, "fake.py", wrapper_names)
    visitor.visit(tree)
    assert visitor.findings, "the scanner must flag an unprotected git status call"


def test_the_scanner_accepts_every_sanctioned_protection_pattern():
    """Self-check the guard does not FALSE-POSITIVE on any of the five
    sanctioned protection patterns it documents above."""
    cases = {
        "state.run_subprocess": (
            "import state\n\n"
            "def f(root):\n"
            "    return state.run_subprocess(['git', 'status', '--porcelain'], cwd=root)\n"
        ),
        "git_utils.run_git_readonly": (
            "import git_utils\n\n"
            "def f(root):\n"
            "    return git_utils.run_git_readonly(['git', 'status', '--porcelain'], cwd=root)\n"
        ),
        "local wrapper (_run pattern)": (
            "import os, subprocess\n\n"
            "def _run(cmd, cwd=None):\n"
            "    env = dict(os.environ)\n"
            "    env['GIT_OPTIONAL_LOCKS'] = '0'\n"
            "    return subprocess.run(cmd, cwd=cwd, env=env)\n\n"
            "def f(root):\n"
            "    return _run(['git', 'status', '--porcelain'], cwd=root)\n"
        ),
        "inline env= kwarg (state.py pattern)": (
            "import os, subprocess\n\n"
            "def f(root):\n"
            "    git_env = dict(os.environ)\n"
            "    git_env['GIT_OPTIONAL_LOCKS'] = '0'\n"
            "    return subprocess.run(['git', 'status', '--porcelain'], cwd=root, env=git_env)\n"
        ),
        "module-level os.environ mutation": (
            "import os, subprocess\n"
            "os.environ['GIT_OPTIONAL_LOCKS'] = '0'\n\n"
            "def f(root):\n"
            "    return subprocess.run(['git', 'status', '--porcelain'], cwd=root)\n"
        ),
    }
    for label, source in cases.items():
        tree = ast.parse(source)
        if _has_module_level_lock_env(tree, source):
            findings: list[str] = []
        else:
            wrapper_names = _compute_wrapper_names(tree, source)
            visitor = _GitCallVisitor(source, "fake.py", wrapper_names)
            visitor.visit(tree)
            findings = visitor.findings
        assert not findings, f"{label}: false positive — {findings}"


def test_the_scanner_exempts_write_verbs_and_config_set():
    """Self-check the guard never demands protection for a WRITE invocation
    (it legitimately needs the lock) or a `git config <key> <value>` set
    (never touches .git/index)."""
    source = (
        "import subprocess\n\n"
        "def f(root):\n"
        "    subprocess.run(['git', 'add', '--', 'f'], cwd=root)\n"
        "    subprocess.run(['git', 'commit', '-m', 'x'], cwd=root)\n"
        "    subprocess.run(['git', 'push', 'origin', 'main'], cwd=root)\n"
        "    subprocess.run(['git', 'tag', '-a', 'v1'], cwd=root)\n"
        "    subprocess.run(['git', 'tag', '--sort=-creatordate'], cwd=root)\n"
        "    subprocess.run(['git', 'config', 'core.hooksPath', 'git-hooks'], cwd=root)\n"
    )
    tree = ast.parse(source)
    assert not _has_module_level_lock_env(tree, source)
    wrapper_names = _compute_wrapper_names(tree, source)
    visitor = _GitCallVisitor(source, "fake.py", wrapper_names)
    visitor.visit(tree)
    assert not visitor.findings, f"write verbs / config-set must be exempt: {visitor.findings}"


def test_the_scanner_still_flags_git_config_get():
    """`git config --get ...` IS a read and must still require protection —
    only the config SET form (any other third token) is exempt."""
    source = (
        "import subprocess\n\n"
        "def f(root):\n"
        "    return subprocess.run(['git', 'config', '--get', 'remote.origin.url'], cwd=root)\n"
    )
    tree = ast.parse(source)
    assert not _has_module_level_lock_env(tree, source)
    wrapper_names = _compute_wrapper_names(tree, source)
    visitor = _GitCallVisitor(source, "fake.py", wrapper_names)
    visitor.visit(tree)
    assert visitor.findings, "git config --get is a read and must require protection"


_TESTS_ROOT = _PROJECT_ROOT / "tests"


def _literal_return_members(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The string members of `func_node`'s `Literal[...]` (or
    `typing.Literal[...]`) return annotation, in source order — `[]` if the
    function has no such annotation (or the annotation isn't a `Literal`)."""
    ann = func_node.returns
    if ann is None or not isinstance(ann, ast.Subscript):
        return []
    base_name = _callee_name(ann.value).rsplit(".", 1)[-1]
    if base_name != "Literal":
        return []
    sl = ann.slice
    if isinstance(sl, ast.Index):  # pragma: no cover - py<3.9 AST shape
        sl = sl.value  # type: ignore[attr-defined]
    elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
    return [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _iter_literal_return_functions() -> dict[str, list[str]]:
    """Every `scripts/` function with a `Literal[...]` return annotation,
    mapped to `"rel/path.py::func_name" -> [members...]`."""
    out: dict[str, list[str]] = {}
    for path in _iter_scanned_files():
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        rel_path = str(path.relative_to(_PROJECT_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            members = _literal_return_members(node)
            if members:
                out[f"{rel_path}::{node.name}"] = members
    return out


def _missing_literal_assertions(tests_source: str, members: list[str]) -> list[str]:
    """Which of `members` never appears as an asserted expected value
    (`== "member"` / `== 'member'`) anywhere in the concatenated tests
    source — i.e. a refusal reason no test can actually reach."""
    missing = []
    for member in members:
        if f'== "{member}"' not in tests_source and f"== '{member}'" not in tests_source:
            missing.append(member)
    return missing


def test_every_literal_return_member_is_asserted_by_some_test():
    """Drift guard (TRDD-W0XT5B3B): every `Literal[...]`-returning guard
    function under `scripts/` must have EVERY member of its Literal asserted
    as an expected value somewhere under `tests/` — a refusal path with no
    test asserting its outcome is mechanically indistinguishable from a
    guard that never refuses (the janitor#245 lesson, generalised)."""
    tests_source = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in sorted(_TESTS_ROOT.glob("*.py"))
    )
    findings = []
    for qualified_name, members in _iter_literal_return_functions().items():
        missing = _missing_literal_assertions(tests_source, members)
        if missing:
            findings.append(f"{qualified_name}: unasserted Literal member(s) {missing!r}")
    assert not findings, (
        "Literal-returning guard function(s) with an unreachable-by-test "
        "refusal path — add an `== \"<member>\"` assertion for each:\n"
        + "\n".join(findings)
    )


def test_the_literal_reachability_scanner_actually_detects_a_gap():
    """Self-check the meta-test is not a silent no-op: a Literal member with
    no asserting `==` anywhere in the (fake) tests corpus must be flagged."""
    missing = _missing_literal_assertions(
        tests_source='assert outcome == "absent"\nassert outcome == "held"\n',
        members=["absent", "held", "no-probe"],
    )
    assert missing == ["no-probe"], "the scanner must flag the unasserted member"


def test_the_literal_reachability_scanner_accepts_full_coverage():
    """Self-check the meta-test does not false-positive when every member of
    a Literal return type has a matching `==` assertion somewhere."""
    missing = _missing_literal_assertions(
        tests_source="assert outcome == 'absent'\nassert outcome == \"held\"\n",
        members=["absent", "held"],
    )
    assert missing == [], f"full coverage must not be flagged: {missing}"


def test_the_literal_extractor_reads_a_real_literal_return_annotation():
    """Self-check `_literal_return_members` correctly extracts a multi-member
    `Literal[...]` return annotation from real source (not just documents its
    intent) — and returns `[]` for an ordinary `-> str` function."""
    source = (
        "from typing import Literal\n\n"
        "def guard() -> Literal['a', 'b', 'c']:\n"
        "    return 'a'\n\n"
        "def not_a_guard() -> str:\n"
        "    return 'x'\n"
    )
    tree = ast.parse(source)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert _literal_return_members(funcs["guard"]) == ["a", "b", "c"]
    assert _literal_return_members(funcs["not_a_guard"]) == []


def test_clear_stale_index_lock_has_a_production_caller():
    """`git_utils.clear_stale_index_lock` (the janitor#245 RECOVERY half) must be reachable from
    at least one `scripts/` file other than its own definition — otherwise the safe removal it
    implements never actually runs, and an orphaned `.git/index.lock` stalls an unattended run
    forever. This is the guard that would have caught it existing as dead code."""
    callers: list[str] = []
    for path in _SCRIPTS_ROOT.rglob("*.py"):
        if path.name == "git_utils.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "clear_stale_index_lock" in text:
            callers.append(str(path.relative_to(_PROJECT_ROOT)))
    assert callers, "clear_stale_index_lock has no production caller under scripts/ — dead code"
