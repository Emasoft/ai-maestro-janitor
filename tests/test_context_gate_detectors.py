"""Phase 2 of TRDD-db169d9e — the TRDD-framework detectors self-deactivate
outside ai-maestro.

The `project_is_ai_maestro()` gate is wired into trdd-drift / trdd-reminder /
report-to-trdd-drift main(): they stay silent (no stdout) when the project is
NOT an ai-maestro-plugins member, even with a stale TRDD / orphan decision
report present that WOULD otherwise fire. The positive controls prove the
fixture genuinely fires when the gate is satisfied (`JANITOR_FORCE_AI_MAESTRO=1`),
so the silence isn't trivial.

Each detector is run as a SUBPROCESS (a fresh process — no shared lru-cache /
in-process capsys fragility), with `CLAUDE_PROJECT_DIR` at a temp project and the
gate forced via `JANITOR_FORCE_AI_MAESTRO`. This mirrors test_trdd_detectors.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_DETECTORS = Path(__file__).resolve().parent.parent / "scripts" / "detectors"


def _run(detector: str, project: Path, force: str) -> str:
    # Fresh env: only PATH (so the detector can find `git`) + the project dir +
    # the forced gate + an empty plugins root (members → hardcoded fleet; the
    # force flag makes membership moot anyway). No CLAUDE_PLUGIN_OPTION_* leaks in.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_FORCE_AI_MAESTRO": force,
        "JANITOR_PLUGINS_ROOT": str(project / "_noplugins"),
    }
    proc = subprocess.run(
        [sys.executable, str(_DETECTORS / f"{detector}.py")],
        capture_output=True, text=True, env=env, timeout=60,
    )
    return proc.stdout


def _stale_trdd(project: Path) -> None:
    tasks = project / "design" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    f = tasks / "TRDD-20260101_000000+0200-abcd1234-gate-test.md"
    f.write_text(
        "---\ntrdd-id: abcd1234-0000-0000-0000-000000000000\ntitle: gate test\n"
        "column: dev\ncreated: 2026-01-01T00:00:00+0200\nupdated: 2026-01-01T00:00:00+0200\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    old = time.time() - 60 * 86400          # 60 days old → past the 14d staleness floor
    os.utime(f, (old, old))


def test_trdd_drift_gates_off_outside_ai_maestro(tmp_path):
    project = tmp_path / "vanilla"
    project.mkdir()
    _stale_trdd(project)
    assert _run("trdd-drift", project, "0").strip() == ""        # gate OFF → silent
    assert "abcd1234" in _run("trdd-drift", project, "1")         # gate ON → the stale TRDD fires


def test_trdd_reminder_gates_off_outside_ai_maestro(tmp_path):
    project = tmp_path / "vanilla"
    project.mkdir()
    _stale_trdd(project)
    assert _run("trdd-reminder", project, "0").strip() == ""     # gate OFF → silent
    assert _run("trdd-reminder", project, "1").strip() != ""     # gate ON → reminder fires


def test_report_to_trdd_drift_gates_off_outside_ai_maestro(tmp_path):
    # A decision report under reports/ + a TRDD dir — the shape that WOULD nag.
    project = tmp_path / "vanilla"
    (project / "design" / "tasks").mkdir(parents=True)
    reports = project / "reports" / "audit"
    reports.mkdir(parents=True)
    (reports / "20260101_000000+0200-decision.md").write_text(
        "# Decision: pick stack X\n\nWe decided to adopt X.\n", encoding="utf-8"
    )
    assert _run("report-to-trdd-drift", project, "0").strip() == ""   # gate OFF → silent
