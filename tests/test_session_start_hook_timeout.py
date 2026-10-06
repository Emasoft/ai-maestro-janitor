"""The SessionStart hooks must each have a timeout of at least 30 s."""

import json
import re
from pathlib import Path

import pytest

HOOKS_JSON = Path(__file__).resolve().parent.parent / "hooks" / "hooks.json"


@pytest.mark.parametrize(
    "name",
    [
        "on-session-start.py",
        "on-session-start-trdd-state.py",
        "on-session-start-watchpaths.py",
    ],
)
def test_session_start_hook_timeout_at_least_30s(name: str) -> None:
    """Each listed SessionStart hook has exactly one entry with timeout >= 30 s (TRDD-9438CGJZ)."""
    # On 2026-10-05 a loaded host made every SessionStart hook take 5.5-6.7 s and Claude Code
    # killed on-session-start.py (clear stamp lost, TRDD-KVUVV9D2), on-session-start-trdd-state.py
    # (STATE blocks not injected on resume) and on-session-start-watchpaths.py at the old 5 s limit.
    # Measured warm cost is 0.04-0.16 s each (reports/continuity-build/
    # 20261006_185535+0200-sessionstart-hook-cost.md), so 30 s is headroom for load, not work.
    data = json.loads(HOOKS_JSON.read_text())
    entries = [
        h
        for group in data["hooks"]["SessionStart"]
        for h in group["hooks"]
        if re.search(rf"{re.escape(name)}\b", h["command"])
    ]
    assert len(entries) == 1
    assert entries[0]["timeout"] >= 30
