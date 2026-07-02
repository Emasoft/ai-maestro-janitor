"""Tests for `/janitor-token-report --attribution` (TRDD-OY0W6LX5).

Real I/O, no mocks, NO network: a tmp HOME holds two project transcript dirs with hand-built
`*.jsonl` carrying known recent usage; the script is run via subprocess with HOME +
JANITOR_GLOBAL_STATE_DIR pointed at isolated tmp dirs so it scans the fixtures and writes its
fleet cache in isolation. The rotator/usage path is never touched by --attribution.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "token_report.py"

assert _SCRIPT.is_file(), f"script not found at {_SCRIPT}"


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def _assistant(epoch: int, *, output: int) -> dict:
    """A type:assistant transcript entry with a known output-token cost at `epoch`."""
    return {
        "type": "assistant",
        "timestamp": _iso(epoch),
        "message": {"usage": {"output_tokens": output, "input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "content": []},
    }


def _write_project(home: Path, slug: str, *, output: int, epoch: int) -> None:
    """Create ~/.claude/projects/<slug>/t.jsonl with one recent assistant turn."""
    d = home / ".claude" / "projects" / slug
    d.mkdir(parents=True)
    (d / "t.jsonl").write_text(json.dumps(_assistant(epoch, output=output)) + "\n", encoding="utf-8")


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    full_env.update(env)
    return subprocess.run([sys.executable, str(_SCRIPT), *args], env=full_env, capture_output=True, text=True, timeout=30)


def _seed(tmp_path: Path) -> tuple[Path, Path]:
    """A tmp HOME with a dominant 'proj-alpha' and a small 'proj-beta', both recent. Returns
    (home, global_state_dir)."""
    home = tmp_path / "home"
    recent = int(time.time()) - 1800  # 30 min ago → inside both the 5h and 7d windows
    _write_project(home, "proj-alpha", output=900_000, epoch=recent)
    _write_project(home, "proj-beta", output=100_000, epoch=recent)
    gstate = tmp_path / "gstate"
    gstate.mkdir()
    return home, gstate


def test_attribution_text_names_top_consumer(tmp_path: Path) -> None:
    """The table lists both projects with their 5h share and names proj-alpha (90% share, no
    trailing baseline → passes the spike gate) as the top consumer to advise."""
    home, gstate = _seed(tmp_path)
    r = _run({"HOME": str(home), "JANITOR_GLOBAL_STATE_DIR": str(gstate)}, "--attribution")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "proj-alpha" in out and "proj-beta" in out
    assert "share5h" in out
    assert "top consumer: proj-alpha" in out


def test_attribution_json_composes(tmp_path: Path) -> None:
    """--attribution --json emits the fleet dict + the culprit slug; proj-alpha is the culprit
    and carries the dominant 5h share."""
    home, gstate = _seed(tmp_path)
    r = _run({"HOME": str(home), "JANITOR_GLOBAL_STATE_DIR": str(gstate)}, "--attribution", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["attribution"] is True
    assert data["culprit"] == "proj-alpha"
    projects = data["fleet"]["projects"]
    assert set(projects) == {"proj-alpha", "proj-beta"}
    assert projects["proj-alpha"]["share_5h"] > 0.8


def test_attribution_empty_fleet_is_clean(tmp_path: Path) -> None:
    """No project transcripts anywhere → a clear 'no activity' line, exit 0, no crash."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    gstate = tmp_path / "gstate"
    gstate.mkdir()
    r = _run({"HOME": str(home), "JANITOR_GLOBAL_STATE_DIR": str(gstate)}, "--attribution")
    assert r.returncode == 0, r.stderr
    assert "no per-project transcript activity" in r.stdout
