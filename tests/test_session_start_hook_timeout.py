"""The on-session-start.py SessionStart hook must have a timeout of at least 30 s."""

import json
import re
from pathlib import Path

HOOKS_JSON = Path(__file__).resolve().parent.parent / "hooks" / "hooks.json"


def test_on_session_start_timeout_at_least_30s() -> None:
    """on-session-start.py's SessionStart timeout is >= 30 s (TRDD-KVUVV9D2)."""
    # On 2026-10-05 a loaded host took 5.5-6.7 s to start the SessionStart hooks; at the
    # old 5 s limit Claude Code killed on-session-start.py before it stamped
    # clear-observed.ts, so the post-clear resume flag was never armed. 30 s is about 4x
    # the worst case seen.
    data = json.loads(HOOKS_JSON.read_text())
    entries = [
        h
        for group in data["hooks"]["SessionStart"]
        for h in group["hooks"]
        if re.search(r"on-session-start\.py\b", h["command"])
    ]
    assert len(entries) == 1
    assert entries[0]["timeout"] >= 30
