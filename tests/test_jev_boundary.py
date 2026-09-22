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

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHEBANG_DIRS = (_REPO_ROOT / "scripts", _REPO_ROOT / "scripts" / "detectors", _REPO_ROOT / "scripts" / "hooks")

# Explicit non-shebang modules that are imported in-process by other scripts/tests and must
# therefore stay import-light too (they don't live under a _SHEBANG_DIRS top level).
_FORBIDDEN_MODULE_FILES = (
    "scripts/lib/external_clear.py",
    "scripts/lib/cold_cache_compact.py",
    "scripts/lib/jev_compaction_lane.py",
    "scripts/summarize_previous_session.py",
    "scripts/external_handoff_clear.py",
    "scripts/dispatch.py",
    "scripts/daemon.py",
)

# The ONE allowed exception: jev_compact.py is deliberately its own separate PEP-723 process
# (see module docstring) and is the only thing that imports jevctx/jev_compaction in-process.
_ALLOWED_EXCEPTION = "scripts/jev_compact.py"

# The two allowed importers of llm_ext_summary (TRDD-RAEGS1D5 card 3 C2): the manual lane's
# own composer -- the ONE entry that actually matters today, since compose_agent_handoff.py
# has a shebang and lives directly under scripts/, so the _SHEBANG_DIRS glob below scans it
# and would flag `import llm_ext_summary as les` without this exemption (verified) -- and the
# module itself, listed for defense-in-depth even though scripts/lib/ is not currently a scan
# root (neither _SHEBANG_DIRS nor _FORBIDDEN_MODULE_FILES reaches it), so this second entry is
# a no-op guard against a future rescoping, not something exercised by this test today.
_LLM_EXT_SUMMARY_ALLOWED = (
    "scripts/compose_agent_handoff.py",
    "scripts/lib/llm_ext_summary.py",
)


def _imports(module_text: str, name: str) -> bool:
    """A real top-level import of `name`, not a mention in a comment/string, and not a
    DIFFERENT module that merely starts with `name` (TRDD-RAEGS1D5 card 3 C2: adding the
    legitimate `jev_compaction_lane` module made a bare substring check on `"jev_compaction"`
    false-positive on it -- `name in stripped` matches inside `jev_compaction_lane` too).

    Only lines that START with `import`/`from` count -- a match inside a comment
    (e.g. "# do NOT import jevctx here") or a docstring must not false-positive. `name` must
    then be followed by a non-identifier character (`.`, whitespace, or end of string) so a
    same-prefixed sibling module never counts as importing `name` itself.
    """
    boundary = re.compile(rf"\b{re.escape(name)}(?![A-Za-z0-9_])")
    for line in module_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and boundary.search(stripped):
            return True
    return False


def _has_shebang(path: Path) -> bool:
    with path.open(encoding="utf-8") as fh:
        return fh.readline().startswith("#!")



def test_no_hook_or_named_lib_script_imports_jevctx_or_httpx() -> None:
    """Hook/detector/daemon/dispatch scripts run stdlib-only under `uv run --script` (or
    in-process, for the explicit lib modules) -- an in-process `import jevctx`/`import httpx`
    would kill them at import time since neither is declared in their own PEP-723 header.
    `jev_compact.py` is the sole, deliberate exception (its own separate process boundary).

    Also bans `llm_ext_summary` from the same automatic-lane file set (TRDD-RAEGS1D5 card 3
    C2): that module is the MANUAL summarizer's own copy, and the automatic lane must never
    import it -- `scripts/compose_agent_handoff.py` (the manual lane's composer) and
    `scripts/lib/llm_ext_summary.py` itself are the only allowed importers.
    """
    candidates: list[Path] = []
    for d in _SHEBANG_DIRS:
        for p in sorted(d.glob("*.py")):
            if _has_shebang(p) and p.relative_to(_REPO_ROOT).as_posix() != _ALLOWED_EXCEPTION:
                candidates.append(p)
    assert candidates, f"expected shebang scripts under {_SHEBANG_DIRS}"
    for rel in _FORBIDDEN_MODULE_FILES:
        path = _REPO_ROOT / rel
        assert path.is_file(), f"expected {path} to exist"
        candidates.append(path)

    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in candidates
        if _imports(p.read_text(), "jevctx")
        or _imports(p.read_text(), "httpx")
        or _imports(p.read_text(), "jev_compaction")
        or (
            _imports(p.read_text(), "llm_ext_summary")
            and p.relative_to(_REPO_ROOT).as_posix() not in _LLM_EXT_SUMMARY_ALLOWED
        )
    ]
    assert offenders == [], (
        f"scripts importing jevctx/httpx/jev_compaction/llm_ext_summary in-process: {offenders}"
    )
