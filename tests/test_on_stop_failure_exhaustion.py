"""End-to-end: the StopFailure hook logs a window-exhaustion snapshot (TRDD-EDSFEQ5C).

Proves the ADD-ON never displaces the hook's ONE hard contract: the critical
`rate-limited.flag` is written, AND — best-effort, strictly after it — a window-exhaustion
event capturing the 5h/7d token sums is appended for empirical cap discovery.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-stop-failure.py"

assert _HOOK.is_file(), f"hook not found at {_HOOK}"


def _run(project: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)  # its scripts/ holds the lib package
    return subprocess.run([sys.executable, str(_HOOK)], env=env,
                          capture_output=True, text=True, timeout=60)


def test_flag_written_and_exhaustion_logged(tmp_path: Path) -> None:
    state = tmp_path / ".janitor" / "state"
    state.mkdir(parents=True)
    now = int(time.time())
    (state / "token-meter.jsonl").write_text(
        "\n".join(
            json.dumps({"ts": now - 100, "output": 5000, "input": 0,
                        "cache_read": 0, "cache_creation": 0})
            for _ in range(3)
        ) + "\n",
        encoding="utf-8",
    )

    r = _run(tmp_path)
    assert r.returncode == 0
    # the ONE hard contract: the resume-cue flag is written
    assert (state / "rate-limited.flag").exists()
    # AND the best-effort exhaustion snapshot was appended
    ev = state / "window-exhaustion.jsonl"
    assert ev.exists()
    events = [json.loads(ln) for ln in ev.read_text().splitlines() if ln.strip()]
    assert len(events) == 1
    assert events[0]["roll_5h"] == 15000  # 3 records × 5000 weighted, all within the 5h window
    assert events[0]["n"] == 3


def test_flag_written_even_without_meter_log(tmp_path: Path) -> None:
    """No token-meter.jsonl → the exhaustion snapshot is skipped, but the critical flag
    is STILL written (the add-on can never break the hard contract)."""
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / ".janitor" / "state" / "rate-limited.flag").exists()


def _run_with_payload(project: Path, payload: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    return subprocess.run([sys.executable, str(_HOOK)], env=env, input=payload,
                          capture_output=True, text=True, timeout=60)


def test_typed_record_uses_the_measured_payload_fields(tmp_path: Path) -> None:
    """The router reads the MEASURED CC 2.1.233 fields (`error`, `last_assistant_message`
    — captured live 2026-08-15, NOT the docs' error_type/error_message) into a typed
    stop-failure-events.jsonl record, while the flag contract stays untouched."""
    state = tmp_path / ".janitor" / "state"
    state.mkdir(parents=True)
    r = _run_with_payload(tmp_path, json.dumps(
        {"hook_event_name": "StopFailure", "error": "rate_limit",
         "last_assistant_message": "You have hit the Fable weekly limit."}))
    assert r.returncode == 0
    assert (state / "rate-limited.flag").exists()
    events = [json.loads(ln) for ln in (state / "stop-failure-events.jsonl").read_text().splitlines() if ln.strip()]
    assert events and events[-1]["error"] == "rate_limit"
    assert "Fable" in events[-1]["msg"]


def test_billing_error_raises_a_high_finding(tmp_path: Path) -> None:
    """billing_error is neither a window nor a token: no reset or rotation fixes it, so the
    router must page the human via a HIGH findings-ledger entry — silence here would leave
    the resume loop retrying a turn that can never succeed without human action."""
    state = tmp_path / ".janitor" / "state"
    state.mkdir(parents=True)
    r = _run_with_payload(tmp_path, json.dumps({"error": "billing_error", "last_assistant_message": "x"}))
    assert r.returncode == 0
    assert (state / "rate-limited.flag").exists()
    ledger = state / "findings-ledger.ndjsonl"
    assert ledger.exists(), "billing_error must land in the findings ledger"
    assert "STOP-FAILURE-BILLING" in ledger.read_text()


def test_malformed_payload_degrades_to_the_pre_payload_behavior(tmp_path: Path) -> None:
    """Garbage on stdin must not block, crash, or displace the flag — the record then
    carries error `unknown` (the tolerant-parse contract)."""
    state = tmp_path / ".janitor" / "state"
    state.mkdir(parents=True)
    r = _run_with_payload(tmp_path, "this is not json {{{")
    assert r.returncode == 0
    assert (state / "rate-limited.flag").exists()
    events = [json.loads(ln) for ln in (state / "stop-failure-events.jsonl").read_text().splitlines() if ln.strip()]
    assert events and events[-1]["error"] == "unknown"
