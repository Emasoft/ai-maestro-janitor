"""Test for `token_report.py --weekly-summary` (TRDD-NEVQOHGS boxes 2+3).

Real subprocess, isolated CLAUDE_PROJECT_DIR — no mocks: writes fake
`.janitor/state/token-meter.jsonl` lines and reads the printed total back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "token_report.py"

assert _SCRIPT.is_file(), f"script not found at {_SCRIPT}"


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_log(proj: Path, records: list[dict]) -> None:
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-meter.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def _write_kind_log(proj: Path, records: list[dict]) -> None:
    """The TRDD-NEVQOHGS box-3 sidecar the report joins on `id` == the main log's `ts`
    (kept SEPARATE from token-meter.jsonl -- its schema is pinned, TRDD-ZCODD6YS)."""
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-meter-kind.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_weekly_summary_sums_two_fake_week_old_lines(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(time.time())
    _write_log(
        proj,
        [
            {"ts": now - 1000, "input": 100, "output": 50, "heartbeat": True},
            {"ts": now - 2000, "input": 30, "output": 20, "heartbeat": True},
        ],
    )
    r = _run({"CLAUDE_PROJECT_DIR": str(proj)}, "--weekly-summary", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["weekly_total_tokens"] == 200


def test_weekly_summary_names_top_kinds(tmp_path: Path) -> None:
    """Each fire gets its own `ts` (real fires never share a second) and a sidecar
    `token-meter-kind.jsonl` line joining that `ts` to its kind -- the report must
    read BOTH files and rank by the join, not by any key on the main record."""
    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(time.time())
    _write_log(
        proj,
        [
            {"ts": now, "input": 100, "output": 100, "heartbeat": True},
            {"ts": now - 10, "input": 5, "output": 5, "heartbeat": True},
            {"ts": now - 20, "input": 1, "output": 1, "heartbeat": True},
        ],
    )
    _write_kind_log(
        proj,
        [
            {"id": now, "kind": "memory-consolidate"},
            {"id": now - 10, "kind": "resume"},
            {"id": now - 20, "kind": "plain-quiet"},
        ],
    )
    r = _run({"CLAUDE_PROJECT_DIR": str(proj)}, "--weekly-summary", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["top_kinds"][0] == ["memory-consolidate", 200]


def test_weekly_summary_missing_sidecar_is_all_unknown(tmp_path: Path) -> None:
    """No `token-meter-kind.jsonl` at all -- every fire buckets "unknown" instead of
    the report crashing on a missing file."""
    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(time.time())
    _write_log(proj, [{"ts": now, "input": 10, "output": 10, "heartbeat": True}])
    r = _run({"CLAUDE_PROJECT_DIR": str(proj)}, "--weekly-summary", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["top_kinds"] == [["unknown", 20]]


def test_weekly_summary_no_log_prints_zero(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run({"CLAUDE_PROJECT_DIR": str(proj)}, "--weekly-summary")
    assert r.returncode == 0, r.stderr
    assert "7d total: 0 tokens" in r.stdout


def test_weekly_summary_excludes_interactive_turns(tmp_path: Path) -> None:
    """Review fix (2026-09-17): this report is 'the janitor's own' cost -- a user's own
    interactive coding turn must not inflate it, same rule `heartbeat_cost_7d` enforces."""
    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(time.time())
    _write_log(
        proj,
        [
            {"ts": now, "input": 10, "output": 10, "heartbeat": True},
            {"ts": now, "input": 10_000, "output": 10_000, "heartbeat": False},
        ],
    )
    r = _run({"CLAUDE_PROJECT_DIR": str(proj)}, "--weekly-summary", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["weekly_total_tokens"] == 20
