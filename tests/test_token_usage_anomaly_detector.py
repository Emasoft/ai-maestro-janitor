"""End-to-end tests for the token-usage-anomaly heartbeat detector (TRDD-EDSFEQ5C).

Runs the real detector as a subprocess against a fixture `token-meter.jsonl` under a
throwaway CLAUDE_PROJECT_DIR. Verifies: it alarms on a genuine outlier, stays silent on
a normal log, is disable-able, dedupes per bucket, and never crashes on a missing log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "token-usage-anomaly.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

_ENABLED = "CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_ENABLED"
# a fixed base epoch far in the past, so every fixture bucket is "complete" (older than now)
_BASE = 1_700_000_000


def _write_log(project: Path, bucket_values: list[int]) -> None:
    state = project / ".janitor" / "state"
    state.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, v in enumerate(bucket_values):
        lines.append(json.dumps({"ts": _BASE + i * 300, "output": v, "input": 0,
                                 "cache_read": 0, "cache_creation": 0}))
    (state / "token-meter.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(project: Path, *, enabled: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env.pop(_ENABLED, None)
    if not enabled:
        env[_ENABLED] = "false"
    return subprocess.run([sys.executable, str(_DETECTOR)], env=env,
                          capture_output=True, text=True, timeout=60)


def test_alarms_on_outlier(tmp_path: Path) -> None:
    _write_log(tmp_path, [100] * 12 + [100_000])  # flat history + a huge newest bucket
    out = _run(tmp_path).stdout
    assert "[token-anomaly]" in out
    assert "100000" in out


def test_silent_on_normal_log(tmp_path: Path) -> None:
    _write_log(tmp_path, [90, 110, 95, 105, 100, 120, 88, 112, 99, 101, 97, 103, 130])
    assert _run(tmp_path).stdout.strip() == ""


def test_silent_when_disabled(tmp_path: Path) -> None:
    _write_log(tmp_path, [100] * 12 + [100_000])
    assert _run(tmp_path, enabled=False).stdout.strip() == ""


def test_dedupes_per_bucket(tmp_path: Path) -> None:
    _write_log(tmp_path, [100] * 12 + [100_000])
    assert "[token-anomaly]" in _run(tmp_path).stdout  # first fire alarms
    assert _run(tmp_path).stdout.strip() == ""          # second fire: same bucket → silent


def test_no_log_is_silent(tmp_path: Path) -> None:
    assert _run(tmp_path).stdout.strip() == ""          # no token-meter.jsonl → silent, no crash


def test_too_little_history_silent(tmp_path: Path) -> None:
    _write_log(tmp_path, [100, 100_000])                # < 9 buckets → no baseline → silent
    assert _run(tmp_path).stdout.strip() == ""
