"""Guard against a repeat of the 3.4.14 incident (TRDD-MYQGMAQZ, 2026-09-04).

CI's Lint job ran `ruff check scripts/ tests/` and `uvx --with pyright pyright`,
but `publish.py`'s `stage_lint` gate ran `ruff check scripts/` only, with no
pyright at all. Nothing detected the gate being a strict subset of CI, so
release 3.4.14 was tagged, published, and installed while GitHub CI rejected
the same commit for 7 pyright errors. These tests parse both files and assert
the gate's tool set (and ruff path scope) is never narrower than CI's.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YAML = ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH_PY = ROOT / "scripts" / "publish.py"

# Prefixes that name a tool invoked via a uv/uvx package runner — the pattern
# both ruff and pyright are actually run through in ci.yml's Lint job. A bare
# command (e.g. `shellcheck ...`) is a different lint layer (publish.py Gate
# 2f, not stage_lint) and is intentionally out of scope for this comparison.
_UV_PREFIXES = (("uvx",), ("uv", "run"), ("uv", "tool", "run"))


def _tool_from_tokens(tokens: list[str]) -> str | None:
    """Return the tool name a shell `run:`/argv token list invokes, or None."""
    for prefix in _UV_PREFIXES:
        if tuple(tokens[: len(prefix)]) == prefix:
            rest = tokens[len(prefix) :]
            i = 0
            while i < len(rest) and rest[i].startswith("-"):
                # `--with <pkg>` takes one value; skip flag + its argument.
                i += 2 if rest[i] == "--with" else 1
            return rest[i] if i < len(rest) else None
    return None


def _paths_after(tokens: list[str], tool: str, subcommand: str) -> set[str]:
    """Return the non-flag path arguments following `<tool> <subcommand>`."""
    try:
        start = tokens.index(tool) + 1
    except ValueError:
        return set()
    if start >= len(tokens) or tokens[start] != subcommand:
        return set()
    return {t for t in tokens[start + 1 :] if not t.startswith("-")}


def _lint_job_run_strings() -> list[str]:
    workflow = yaml.safe_load(CI_YAML.read_text())
    for job in workflow["jobs"].values():
        run_strings = [s["run"] for s in job.get("steps", []) if "run" in s]
        if any("ruff check" in r and "pyright" in " ".join(run_strings) for r in run_strings):
            return run_strings
    raise AssertionError("no job in ci.yml runs both ruff and pyright")


def _ci_tools() -> set[str]:
    tools = set()
    for run_str in _lint_job_run_strings():
        tool = _tool_from_tokens(run_str.split())
        if tool:
            tools.add(tool)
    return tools


def _ci_ruff_paths() -> set[str]:
    paths: set[str] = set()
    for run_str in _lint_job_run_strings():
        tokens = run_str.split()
        if _tool_from_tokens(tokens) == "ruff":
            paths |= _paths_after(tokens, "ruff", "check")
    return paths


def _stage_lint_argv_calls() -> list[list[str]]:
    """Every string-literal argv list passed to a `run(...)`/`subprocess.run(...)` call inside stage_lint."""
    tree = ast.parse(PUBLISH_PY.read_text())
    stage_lint = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "stage_lint"
    )
    argv_lists = []
    for node in ast.walk(stage_lint):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        if name != "run" or not node.args or not isinstance(node.args[0], ast.List):
            continue
        elts = node.args[0].elts
        if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts):
            argv_lists.append([e.value for e in elts])  # type: ignore[union-attr]
    return argv_lists


def _gate_tools() -> set[str]:
    return {t for argv in _stage_lint_argv_calls() if (t := _tool_from_tokens(argv))}


def _gate_ruff_paths() -> set[str]:
    paths: set[str] = set()
    for argv in _stage_lint_argv_calls():
        if _tool_from_tokens(argv) == "ruff":
            paths |= _paths_after(argv, "ruff", "check")
    return paths


def test_every_linter_in_cis_lint_job_also_runs_in_the_publish_gate() -> None:
    """Any uvx/uv-run tool CI's Lint job invokes must also run in stage_lint, or a 3.4.14-style gate/CI split can recur."""
    ci_tools = _ci_tools()
    gate_tools = _gate_tools()
    missing = ci_tools - gate_tools
    assert not missing, (
        f"CI's Lint job runs {sorted(missing)} but publish.py's stage_lint does not "
        f"(TRDD-MYQGMAQZ) — ci_tools={sorted(ci_tools)} gate_tools={sorted(gate_tools)}"
    )


def test_the_gates_ruff_scope_matches_cis() -> None:
    """stage_lint must ruff-check at least every path CI's Lint job ruff-checks."""
    ci_paths = _ci_ruff_paths()
    gate_paths = _gate_ruff_paths()
    missing = ci_paths - gate_paths
    assert not missing, f"CI ruff-checks {sorted(missing)} but stage_lint does not: gate_paths={sorted(gate_paths)}"
