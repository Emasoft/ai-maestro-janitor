"""Phase 2 of TRDD-db169d9e — the TRDD-framework detectors self-deactivate
outside ai-maestro.

Verifies the `project_is_ai_maestro()` gate is wired into the three
TRDD-framework detectors (trdd-drift, trdd-reminder, report-to-trdd-drift):
they stay silent (return 0, no stdout) when the project is NOT an
ai-maestro-plugins member, even with a stale TRDD present that WOULD otherwise
fire — and the positive controls prove the fixture genuinely fires when the
gate is satisfied, so the silence isn't trivial.

Detectors are loaded by path (their filenames are hyphenated) and run
in-process; CLAUDE_PROJECT_DIR + JANITOR_FORCE_AI_MAESTRO are toggled to flip
the gate, with the state caches cleared each time.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTORS = _PROJECT_ROOT / "scripts" / "detectors"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def _load(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(modname, _DETECTORS / filename)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reset() -> None:
    state.project_root.cache_clear()
    state.project_is_ai_maestro.cache_clear()
    state.ai_maestro_marketplace_members.cache_clear()


def _stale_trdd(project: Path) -> Path:
    tasks = project / "design" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    f = tasks / "TRDD-20260101_000000+0200-abcd1234-gate-test.md"
    f.write_text(
        "---\n"
        "trdd-id: abcd1234-0000-0000-0000-000000000000\n"
        "title: gate test\n"
        "column: dev\n"
        "created: 2026-01-01T00:00:00+0200\n"
        "updated: 2026-01-01T00:00:00+0200\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    old = time.time() - 60 * 86400          # 60 days old → past the 14d staleness floor
    os.utime(f, (old, old))
    return f


def _isolate(monkeypatch, project: Path, tmp_path: Path) -> None:
    empty_root = tmp_path / "plugins"
    (empty_root / "marketplaces").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(empty_root))
    monkeypatch.delenv("JANITOR_FORCE_AI_MAESTRO", raising=False)
    _reset()


def _run(mod, monkeypatch, capsys, force: str) -> tuple[int, str]:
    monkeypatch.setenv("JANITOR_FORCE_AI_MAESTRO", force)
    _reset()
    rc = mod.main()
    return rc, capsys.readouterr().out


def test_trdd_drift_gates_off_outside_ai_maestro(monkeypatch, tmp_path, capsys):
    project = tmp_path / "vanilla"
    project.mkdir()
    _stale_trdd(project)
    _isolate(monkeypatch, project, tmp_path)
    mod = _load("trdd-drift.py", "trdd_drift_gate")

    rc_off, out_off = _run(mod, monkeypatch, capsys, "0")
    assert rc_off == 0 and out_off.strip() == ""          # gate OFF → silent

    rc_on, out_on = _run(mod, monkeypatch, capsys, "1")
    assert rc_on == 0 and "abcd1234" in out_on            # gate ON → the stale TRDD fires


def test_trdd_reminder_gates_off_outside_ai_maestro(monkeypatch, tmp_path, capsys):
    project = tmp_path / "vanilla"
    project.mkdir()
    _stale_trdd(project)
    _isolate(monkeypatch, project, tmp_path)
    mod = _load("trdd-reminder.py", "trdd_reminder_gate")

    rc_off, out_off = _run(mod, monkeypatch, capsys, "0")
    assert rc_off == 0 and out_off.strip() == ""          # gate OFF → silent

    rc_on, out_on = _run(mod, monkeypatch, capsys, "1")
    assert rc_on == 0 and out_on.strip() != ""            # gate ON → reminder fires


def test_report_to_trdd_drift_gates_off_outside_ai_maestro(monkeypatch, tmp_path, capsys):
    # A decision report under reports/ + a TRDD dir — the shape that WOULD nag.
    project = tmp_path / "vanilla"
    (project / "design" / "tasks").mkdir(parents=True)
    reports = project / "reports" / "audit"
    reports.mkdir(parents=True)
    (reports / "20260101_000000+0200-decision.md").write_text(
        "# Decision: pick stack X\n\nWe decided to adopt X.\n", encoding="utf-8"
    )
    _isolate(monkeypatch, project, tmp_path)
    mod = _load("report-to-trdd-drift.py", "report_to_trdd_gate")

    rc_off, out_off = _run(mod, monkeypatch, capsys, "0")
    assert rc_off == 0 and out_off.strip() == ""          # gate OFF → silent
