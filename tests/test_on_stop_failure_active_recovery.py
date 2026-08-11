"""Regression tests for the ACTIVE 429 RECOVERY block in on-stop-failure.py (TRDD-G4BCRUP7 R9).

On a turn-ending API error the hook now, best-effort and STRICTLY AFTER its critical
`rate-limited.flag` write, fires a DETACHED `rotator.py auto` so the session rotates to a
fresh account instead of waiting for the usage window to reset. It is gated on the rotator
opt-in flag at `<janitor-DATA>/oauth-rotator/opt-in.flag`, derived from
`global_state.global_state_dir().parent / "oauth-rotator" / "opt-in.flag"`.

The whole block is wrapped in `except Exception: pass` (deliberately — it must never break
the hook's one hard contract), which means a broken import would silently and permanently
disable this recovery while every other test kept passing. `test_import_actually_resolves`
exists specifically to catch that failure mode directly, not as a side effect of the other
cases passing.
"""

from __future__ import annotations

import importlib.util as _u
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "on-stop-failure.py"

assert _HOOK_PATH.is_file(), f"hook not found at {_HOOK_PATH}"


def _purge_lib_modules() -> None:
    """Drop `lib` AND every `lib.*` submodule from sys.modules.

    `lib.state` exposes `project_root()`/`state_dir()` as `@lru_cache(maxsize=...)`
    (module-lifetime caches, by design — a real hook invocation is a fresh `uv run
    --script` process). Popping only the top-level `"lib"`/`"state"` names (as the
    other in-process hook tests do) leaves the ALREADY-IMPORTED `lib.state`
    submodule cached in sys.modules; `from lib import state` then reuses that
    stale submodule object — with its stale lru_cache — across tests in this
    file, silently binding a later test's hook run to an EARLIER test's
    `CLAUDE_PROJECT_DIR`. Dropping every `lib.*` entry forces a genuinely fresh
    submodule (and cache) per test, matching a real subprocess invocation."""
    for name in list(sys.modules):
        if name == "lib" or name.startswith("lib."):
            sys.modules.pop(name, None)


def _load_hook() -> Any:
    """Load the hook module fresh (spec_from_file_location — mirrors the other in-process
    hook tests, e.g. test_session_start_rearm_guard.py) so each test gets an isolated copy."""
    spec = _u.spec_from_file_location(
        "janitor_on_stop_failure_under_test",
        str(_HOOK_PATH),
    )
    assert spec is not None and spec.loader is not None
    hook = _u.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _run_hook(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Path]:
    """Set up full env isolation (project dir, plugin root, global-state dir) and run
    main(). Returns (hook module, project dir) so callers can assert on state."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))

    _purge_lib_modules()

    hook = _load_hook()
    rc = hook.main()
    assert rc == 0
    return hook, project


def test_critical_flag_written_without_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The hook's ONE hard contract must survive regardless of the new recovery block: with
    the rotator opt-in flag ABSENT, rate-limited.flag + rate-limited-since.ts are still
    written and the hook still exits 0."""
    _hook, project = _run_hook(monkeypatch, tmp_path)
    state = project / ".janitor" / "state"
    assert (state / "rate-limited.flag").exists()
    assert (state / "rate-limited-since.ts").exists()


def test_no_rotator_spawn_when_gate_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Opt-in flag ABSENT ⇒ no rotator subprocess is spawned."""
    calls: list[list[str]] = []
    real_popen = __import__("subprocess").Popen

    def _spy_popen(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        return real_popen(["true"] if sys.platform != "win32" else ["cmd", "/c", "exit", "0"])

    monkeypatch.setattr("subprocess.Popen", _spy_popen)
    _run_hook(monkeypatch, tmp_path)

    rotator_calls = [c for c in calls if any("rotator.py" in str(a) for a in c)]
    assert rotator_calls == []


def test_rotator_spawn_when_gate_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Opt-in flag PRESENT ⇒ the rotator IS invoked (captured via a spy on subprocess.Popen
    so no real rotation runs in this test)."""
    gstate = tmp_path / "gstate"
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gstate))
    # opt_in path == global_state_dir().parent / "oauth-rotator" / "opt-in.flag" —
    # note it's a SIBLING of the global-state dir, not inside it.
    opt_in = gstate.parent / "oauth-rotator" / "opt-in.flag"
    opt_in.parent.mkdir(parents=True, exist_ok=True)
    opt_in.touch()

    calls: list[list[str]] = []

    class _FakeProc:
        pass

    def _spy_popen(argv: list[str], **kwargs: Any) -> Any:
        calls.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr("subprocess.Popen", _spy_popen)
    _run_hook(monkeypatch, tmp_path)

    rotator_calls = [c for c in calls if any("rotator.py" in str(a) for a in c)]
    assert len(rotator_calls) == 1
    assert rotator_calls[0][-1] == "auto"


def test_import_actually_resolves() -> None:
    """THE MOST IMPORTANT CASE. The recovery block is wrapped in `except Exception: pass`,
    so a broken `from lib import global_state` would silently and PERMANENTLY disable the
    whole recovery while every other test in this file still passed (the gate-open test
    would just see zero calls and nobody would notice why). This test bypasses the swallow
    entirely and asserts the import chain the hook depends on actually works, exactly as
    the hook sets up sys.path: scripts/ first (for `lib` as a package), then scripts/lib/
    (because global_state.py does a BARE `import state`, which only resolves once
    scripts/lib is on the path too — see on-stop-failure.py's own comment on this)."""
    _purge_lib_modules()
    saved_path = list(sys.path)
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
        sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
        from lib import global_state as gs  # noqa: E402

        assert callable(gs.global_state_dir)
        # Prove it's not just importable but actually callable end-to-end.
        result = gs.global_state_dir()
        assert isinstance(result, Path)
    finally:
        sys.path[:] = saved_path
        _purge_lib_modules()


def test_exits_zero_when_rotator_script_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Opt-in flag present but rotator.py absent (e.g. a stripped-down plugin root) ⇒ the
    hook still exits 0 and the critical flag is still written."""
    fake_root = tmp_path / "fake_plugin_root"
    (fake_root / "scripts").mkdir(parents=True)
    # Copy only what main() strictly needs: scripts/lib as a real package (symlink keeps
    # this test independent of the janitor's own file layout drifting).
    import os

    os.symlink(_PROJECT_ROOT / "scripts" / "lib", fake_root / "scripts" / "lib")
    os.symlink(_PROJECT_ROOT / "scripts" / "hooks", fake_root / "scripts" / "hooks")
    # oauth_rotator dir deliberately NOT created -> rotator.py does not exist.

    project = tmp_path / "project"
    project.mkdir()
    gstate = tmp_path / "gstate"
    opt_in = gstate.parent / "oauth-rotator" / "opt-in.flag"
    opt_in.parent.mkdir(parents=True, exist_ok=True)
    opt_in.touch()

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(fake_root))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gstate))

    _purge_lib_modules()

    hook = _load_hook()
    rc = hook.main()
    assert rc == 0
    assert (project / ".janitor" / "state" / "rate-limited.flag").exists()
