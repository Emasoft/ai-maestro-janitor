"""S2 guard (TRDD-A8DRPZFM, fseventsd plan): no NEW module-level frozen home paths.

A module-level constant built from ``Path.home()`` / ``os.path.expanduser`` is captured at
IMPORT time, so a test (or any embedder) that redirects ``HOME``/``JANITOR_*`` env AFTER
the import still resolves the REAL machine tree through it. Exactly that shape
(``launchd_keepalive._DATA_DIR`` reached via a restage helper) let the test suite corrupt
the real keepalive closure and drive the 39 GB fseventsd runaway (TRDD-ZNN0UK5K).

This guard AST-scans every ``scripts/**/*.py`` module (no imports — zero side effects) and
asserts the set of module-level home-capturing assignments EQUALS the reviewed allowlist.
Equality, not subset: removing an offender without pruning the allowlist fails too, so the
list can't rot. Adding a new frozen-home constant fails this test until it is either
rewritten as a call-time resolver (the required fix) or consciously allowlisted here with
a WHY a reviewer can veto.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

# Every entry is "<path relative to scripts/>:<constant name>", verified individually.
# The WHY must make clear the constant cannot pollute isolated tests via WRITES.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Read-only scan-skip prefixes; never used to write. Frozen-at-import only means a
        # HOME-redirected process still skips the REAL uv cache — harmless for isolation.
        "detectors/binary-magic-scanner.py:_SKIP_ABS_PREFIXES",
        # The dispatcher stub is a standalone zero-dep script exec'd fresh on every cron
        # fire (never imported long-lived), so import-time capture IS call-time here.
        "dispatcher-stub.py:PLUGIN_CACHE_ROOT",
        "dispatcher-stub.py:PLUGIN_DATA_ROOT",
        # The TRDD-named legit fallback: data_dir() re-resolves at CALL time and honors
        # JANITOR_DATA_DIR; the frozen constant is only its no-env default.
        "lib/launchd_keepalive.py:_DATA_DIR",
        # Read-only source for restage COPIES (reads the real plugin cache, never writes
        # to it); all write destinations go through call-time data_dir().
        "lib/launchd_keepalive.py:_CACHE_PARENT",
        # Same wrapped-fallback pattern: _data_dir() honors JANITOR_DATA_DIR at call time.
        "lib/version_update_lib.py:_FIXED_DATA_DIR",
    }
)


def _captures_home(node: ast.AST) -> bool:
    """True iff the expression tree contains Path.home() / *.expanduser(...) capture."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute) and func.attr in ("home", "expanduser"):
            return True
        if isinstance(func, ast.Name) and func.id == "expanduser":
            return True
    return False


def _module_level_offenders(py: Path) -> list[str]:
    tree = ast.parse(py.read_text(encoding="utf-8"))
    rel = py.relative_to(SCRIPTS)
    found: list[str] = []
    for stmt in tree.body:  # module level ONLY — function bodies are call-time by nature
        targets: list[str] = []
        value: ast.AST | None = None
        if isinstance(stmt, ast.Assign):
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            targets = [stmt.target.id]
            value = stmt.value
        if value is not None and targets and _captures_home(value):
            found.extend(f"{rel}:{name}" for name in targets)
    return found


def test_guard_detects_a_reintroduced_frozen_home_writer(tmp_path: Path) -> None:
    """PROOF the S2 guard FIRES (TRDD-A8DRPZFM derived task): a synthetic module that
    reintroduces the exact fseventsd-incident shape (module-level Path.home() constant)
    must be flagged. Runs on a tmp tree so the proof is durable instead of a throwaway
    branch."""
    bad = tmp_path / "bad_module.py"
    bad.write_text(
        "from pathlib import Path\n_STATE_DIR = Path.home() / '.claude' / 'x'\n",
        encoding="utf-8",
    )
    tree = ast.parse(bad.read_text(encoding="utf-8"))
    hits = [
        t.id
        for stmt in tree.body
        if isinstance(stmt, ast.Assign) and _captures_home(stmt.value)
        for t in stmt.targets
        if isinstance(t, ast.Name)
    ]
    assert hits == ["_STATE_DIR"], "the S2 scan must flag the frozen-home constant"


def test_s1b_manifest_detects_added_changed_and_removed_files(tmp_path: Path) -> None:
    """PROOF the S1b write-guard FIRES: the conftest manifest diff must see an added,
    a changed, and a removed guarded file — while ignoring an excluded churn file."""
    # tests/ is not a package — pytest imports conftest.py as the top-level `conftest`.
    from conftest import _manifest

    root = tmp_path / "real-state"
    root.mkdir()
    (root / "state.json").write_text("{}", encoding="utf-8")
    (root / "gone.flag").write_text("x", encoding="utf-8")
    (root / "daemon.heartbeat.ts").write_text("1", encoding="utf-8")  # excluded churn
    rotator = root / "oauth-rotator"
    rotator.mkdir()
    (rotator / "state.json").write_text("{}", encoding="utf-8")  # excluded subtree
    before = _manifest(root)

    (root / "state.json").write_text('{"mutated": true}', encoding="utf-8")  # changed
    (root / "gone.flag").unlink()  # removed
    (root / "new-file.json").write_text("{}", encoding="utf-8")  # added
    (root / "daemon.heartbeat.ts").write_text("2", encoding="utf-8")  # churn — ignored
    (rotator / "state.json").write_text('{"tick": 1}', encoding="utf-8")  # daemon-owned — ignored
    after = _manifest(root)

    changed = {rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel)}
    assert changed == {"state.json", "gone.flag", "new-file.json"}
    assert "daemon.heartbeat.ts" not in before and "daemon.heartbeat.ts" not in after
    assert not any("oauth-rotator" in rel for rel in set(before) | set(after))


def test_no_new_module_level_frozen_home_paths() -> None:
    """Module-level home captures in scripts/** must exactly match the reviewed allowlist."""
    offenders: set[str] = set()
    for py in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        offenders.update(_module_level_offenders(py))

    new = offenders - ALLOWLIST
    stale = ALLOWLIST - offenders
    assert not new, (
        "NEW module-level frozen-home constant(s) — import-time capture escapes test/env "
        "isolation (the fseventsd-runaway class, TRDD-ZNN0UK5K). Rewrite each as a "
        f"call-time resolver, or allowlist it with a reviewed WHY: {sorted(new)}"
    )
    assert not stale, (
        "Allowlist entries no longer present in the code — prune them so the allowlist "
        f"can't rot: {sorted(stale)}"
    )
