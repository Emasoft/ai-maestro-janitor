"""Jev/httpx must never reach a hook or another in-process script's import (TRDD-541CBN36 card 2).

Hook scripts under `scripts/hooks/` are stdlib-only PEP-723 -- Claude Code invokes them via
`uv run --script`, and any of them importing `jevctx`/`httpx` in-process would try to resolve
those dependencies (not declared in a hook's own `# dependencies = [...]` header) at import
time and kill the hook before it runs a single line (see the wikimem page
`janitor-hooks-two-import-conventions`). The same holds for a handful of scripts/lib modules
that other tests exercise in-process and must stay import-light. `jev_compact.py` is deliberately
its OWN separate PEP-723 process for exactly this reason -- `arm_prepare.py` only ever reaches
it via `subprocess.run`, never `import jevctx`.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOKS_DIR = _REPO_ROOT / "scripts" / "hooks"

_FORBIDDEN_MODULE_FILES = (
    "scripts/lib/external_clear.py",
    "scripts/summarize_previous_session.py",
    "scripts/external_handoff_clear.py",
    "scripts/dispatch.py",
    "scripts/daemon.py",
)


def _imports(module_text: str, name: str) -> bool:
    """A real top-level import of `name`, not a mention in a comment/string.

    Only lines that START with `import`/`from` count -- a match inside a comment
    (e.g. "# do NOT import jevctx here") or a docstring must not false-positive.
    """
    for line in module_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and name in stripped:
            return True
    return False


def test_no_hook_or_named_lib_script_imports_jevctx_or_httpx() -> None:
    hook_files = sorted(_HOOKS_DIR.glob("*.py"))
    assert hook_files, f"expected hook scripts under {_HOOKS_DIR}"
    candidates = list(hook_files)
    for rel in _FORBIDDEN_MODULE_FILES:
        path = _REPO_ROOT / rel
        assert path.is_file(), f"expected {path} to exist"
        candidates.append(path)

    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in candidates
        if _imports(p.read_text(), "jevctx") or _imports(p.read_text(), "httpx")
    ]
    assert offenders == [], f"scripts importing jevctx/httpx in-process: {offenders}"
