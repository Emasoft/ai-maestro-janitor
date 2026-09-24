"""on-prompt-submit.py's cron-marker fast path (report:
reports/hook-timeout/20260924_175736+0200-startup-timing.md, proposal 3).

A cron/heartbeat fire is the overwhelming majority of this hook's invocations — every armed
session's heartbeat prompt hits it — and the hook's genuine-prompt-only work (`state.
bump_user_presence`, `user_intent.record_intent_from_prompt`) buys a cron fire nothing. Importing
`state` at MODULE TOP paid ~50-60ms of import time on every single heartbeat, on every armed
session, purely additive to the CPU-contention bursts the report measured. This pins that `state`
is imported LAZILY — never at module load, only once `main()` has already decided the prompt is
NOT a cron marker.
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = _ROOT / "scripts" / "hooks" / "on-prompt-submit.py"
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def _load_hook_tracking_imports(calls: list[str]) -> Any:
    """Load a FRESH copy of the hyphenated hook module (mirrors
    tests/test_wikimem_lint_hook.py's `_import_hook` idiom), while recording every module name
    passed to the REAL `importlib.import_module` — including any import the module performs at
    its own TOP LEVEL, during `exec_module` itself, before any test code gets to call `main()`.

    A fresh spec name per call (`uuid4`) avoids a stale `sys.modules` entry masking a second
    load in the same test session.
    """
    real_import = importlib.import_module

    def _tracking(name: str, *a: Any, **kw: Any) -> Any:
        calls.append(name)
        return real_import(name, *a, **kw)

    importlib.import_module = _tracking  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(f"on_prompt_submit_hook_{uuid.uuid4().hex}", _HOOK_PATH)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        importlib.import_module = real_import  # type: ignore[assignment]


def _call_main(hook: Any, monkeypatch: pytest.MonkeyPatch, prompt: str, calls: list[str]) -> int:
    """Run `hook.main()` against `prompt`, recording every module name it requests via
    `importlib.import_module` (the hook's own lazy-import mechanism) into `calls`."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
    real_import = hook.importlib.import_module

    def _tracking(name: str, *a: Any, **kw: Any) -> Any:
        calls.append(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(hook.importlib, "import_module", _tracking)
    return hook.main()


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated HOME + project dir, so a genuine-prompt run's real `state.bump_user_presence()`
    write never touches this machine's actual breadcrumb."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def test_module_load_imports_no_state_module(isolated_env: Path) -> None:
    """FAILS on HEAD: `state = importlib.import_module("state")` sat at module top, so merely
    LOADING the hook — before any prompt is even read — already paid the import, regardless of
    whether the fire turns out to be a cron marker. After the fix, loading the module must import
    nothing beyond its own module-top dependencies (json/sys/importlib/pathlib)."""
    import_time_calls: list[str] = []
    _load_hook_tracking_imports(import_time_calls)
    assert "state" not in import_time_calls, (
        f"loading the module must not import state; imported at load time: {import_time_calls}"
    )


def test_cron_marker_prompt_imports_no_state_module(monkeypatch: pytest.MonkeyPatch, isolated_env: Path) -> None:
    """A cron-marker prompt must never cause `state` to be imported, at load time OR during
    `main()` — it is a no-op fire and the import buys it nothing (see module docstring)."""
    import_time_calls: list[str] = []
    hook = _load_hook_tracking_imports(import_time_calls)
    main_time_calls: list[str] = []
    rc = _call_main(hook, monkeypatch, "[janitor-heartbeat]\nrun the beat", main_time_calls)
    assert rc == 0
    all_calls = import_time_calls + main_time_calls
    assert "state" not in all_calls, f"a cron-marker prompt must not import state; imported {all_calls}"


def test_genuine_prompt_still_imports_state_and_bumps_presence(
    monkeypatch: pytest.MonkeyPatch, isolated_env: Path
) -> None:
    """The deferral must not break the real behavior: a genuine (non-cron) prompt still imports
    `state` (during `main()`, not at load time) and still writes the presence breadcrumb —
    laziness must not become a silent no-op."""
    import_time_calls: list[str] = []
    hook = _load_hook_tracking_imports(import_time_calls)
    assert "state" not in import_time_calls
    main_time_calls: list[str] = []
    rc = _call_main(hook, monkeypatch, "please fix the flaky test", main_time_calls)
    assert rc == 0
    assert "state" in main_time_calls, f"a genuine prompt must still import state; imported {main_time_calls}"
    # `bump_user_presence` resolves the breadcrumb from `Path.home()`, which `isolated_env`
    # redirected to `tmp_path/home` via HOME — so a real write here proves the deferred import
    # didn't turn into a silent no-op, without touching the real machine's breadcrumb.
    breadcrumb = isolated_env / "home" / ".aimaestro" / "state" / "user-presence.json"
    assert breadcrumb.is_file(), "genuine-prompt path must still write the presence breadcrumb"
