"""scripts/daemon.py::task_marketplace_refresh — TRDD-5EHBPH6G acceptance boxes 2+3.

Real code throughout: a real `claude` stand-in executable on PATH (never a mocked
subprocess), real `gs.marketplace_lock()`, real `state.atomic_write` I/O against an
isolated `JANITOR_GLOBAL_STATE_DIR`. Only the installed-plugins lookup and the
per-marketplace timeout are pointed at test fixtures (`_plugins_cache_root`,
`CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S`) — the planner itself is
never mocked, it runs for real against a real `installed_plugins.json` on disk.

`last-run.ts`'s unconditional-stamp-even-on-failure semantics are intentionally
left as-is here (TRDD-FFXGPZEI, backburner — separate, wider-blast-radius change);
these tests only cover the per-item timeout/skip behavior and the "a run where
every marketplace failed is itself a FAILED task" bookkeeping.
"""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))
daemon = importlib.import_module("daemon")

# Marketplace this fake claude sleeps past the per-item timeout for.
_SLOW_MARKET = "slow-mkt"
_FAIL_MARKET = "fail-mkt"

_FAKE_CLAUDE = """#!{python}
import sys, time
# argv: claude plugin marketplace update <name>
name = sys.argv[-1]
if name == {slow!r}:
    time.sleep(3)
elif name == {fail!r}:
    sys.exit(1)
sys.exit(0)
""".format(python=sys.executable, slow=_SLOW_MARKET, fail=_FAIL_MARKET)


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    """Isolated global-state dir + a fake `claude` prepended onto PATH.

    Returns (cache_parent_dir, captured_log_lines) — captured_log_lines is filled
    live by monkeypatching state.log_line, which is more robust than reading
    daemon.log off disk (that path is only wired up by the daemon's own main(),
    not by a bare call to task_marketplace_refresh() in-process).
    """
    gsd = tmp_path / "global-state"
    gsd.mkdir()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_bin = bin_dir / "claude"
    claude_bin.write_text(_FAKE_CLAUDE, encoding="utf-8")
    claude_bin.chmod(claude_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    # installed_plugins.json backing a controllable set of marketplaces —
    # `_plugins_cache_root()` returns `<dir>/cache`; the reader looks at its parent.
    cache_parent = tmp_path / "plugins-config"
    cache_parent.mkdir()
    monkeypatch.setattr(daemon, "_plugins_cache_root", lambda: cache_parent / "cache")

    lines: list[str] = []
    real_log_line = daemon.state.log_line

    def _capture(component, msg):
        lines.append(msg)
        return real_log_line(component, msg)

    monkeypatch.setattr(daemon.state, "log_line", _capture)
    return cache_parent, lines


def _write_installed(cache_parent_dir: Path, market_names: list[str]) -> None:
    plugins = {f"plugin-{i}@{m}": [{"scope": "user"}] for i, m in enumerate(market_names)}
    (cache_parent_dir / "installed_plugins.json").write_text(
        json.dumps({"plugins": plugins}), encoding="utf-8"
    )


@pytest.mark.no_timeout_scale
def test_per_item_timeout_skips_and_run_still_succeeds(
    isolated: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """acceptance box 2: a per-item timeout skips ONLY that entry — the run does not
    raise, and the OK marketplace is still counted refreshed.

    Marked `no_timeout_scale`: the suite-wide `Popen.communicate` timeout scaling
    (tests/conftest.py, x10) would otherwise turn this test's real 1s per-item
    budget into 10s — the exact thing this test asserts DIDN'T fire."""
    cache_parent, lines = isolated
    _write_installed(cache_parent, ["ok-mkt", _SLOW_MARKET])
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S", "1")

    daemon.task_marketplace_refresh()  # must not raise

    joined = "\n".join(lines)
    assert f"{_SLOW_MARKET} timed out after 1s — skipped" in joined
    assert "refreshed 1/2 marketplaces" in joined


def test_all_items_failing_is_a_failed_run(
    isolated: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """acceptance box 3: a run where EVERY marketplace fails counts as a FAILED
    task run — exercised through the real `Task.run()` bookkeeping (the
    consecutive-failure streak advances), not by hand-calling internals."""
    cache_parent, _ = isolated
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S", "5")
    _write_installed(cache_parent, [_FAIL_MARKET])

    task = daemon.Task("marketplace-refresh", 3600, daemon.task_marketplace_refresh, background=False)
    assert task._failcount() == 0
    task.run()

    assert task._failcount() == 1, "a run where every marketplace failed must count as FAILED"


@pytest.mark.no_timeout_scale
def test_run_budget_stops_starting_new_items_and_does_not_fail(
    isolated: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Follow-up (5EHBPH6G): N items x per-item timeout with no overall run budget
    can exceed `_WORKLOAD_TIMEOUT_SEC` and get SIGKILLed by the outer watchdog
    again. A tiny `_WORKLOAD_TIMEOUT_SEC` here forces the deadline to already be
    exhausted before the loop starts, so every item is skipped and logged — and
    that must NOT count as a failed run (nothing was attempted)."""
    cache_parent, lines = isolated
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S", "1")
    monkeypatch.setattr(daemon, "_WORKLOAD_TIMEOUT_SEC", 1)
    _write_installed(cache_parent, ["ok-mkt-1", "ok-mkt-2"])

    task = daemon.Task("marketplace-refresh", 3600, daemon.task_marketplace_refresh, background=False)
    task.run()

    assert task._failcount() == 0, "an all-skipped run (nothing attempted) must not count as FAILED"
    joined = "\n".join(lines)
    assert "budget exhausted after 0/2 — 2 skipped" in joined


def test_a_partial_success_is_not_a_failed_run(
    isolated: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fix's stated contract: the run fails ONLY when every item failed — one
    success out of two is a successful task run, not a failure."""
    cache_parent, _ = isolated
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S", "5")
    _write_installed(cache_parent, ["ok-mkt", _FAIL_MARKET])

    task = daemon.Task("marketplace-refresh", 3600, daemon.task_marketplace_refresh, background=False)
    task.run()

    assert task._failcount() == 0, "a partial success must not count as a FAILED run"
