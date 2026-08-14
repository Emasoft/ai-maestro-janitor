"""The fallback context window must follow CC's 1M hold (CC 2.1.223).

WHY THIS EXISTS. `resolve_context` prefers the statusline snapshot, which carries the real
window — so this fallback only matters when no snapshot is readable. That narrowness is
exactly what makes it dangerous: the failure is SILENT and looks like a healthy session.

CC 2.1.223 made `CLAUDE_CODE_DISABLE_1M_CONTEXT` hold EVERY native-1M model to 200K via
auto-compaction. Assuming 1M while the session is held to 200K under-reports occupancy ~5x
— a 190k session reads as 19% instead of 95% — so `pre-tool-context-usage`'s >=85% guard
never fires and the watchdog is inert while appearing fine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import token_meter as tm  # noqa: E402


@pytest.mark.parametrize(
    ("value", "expected", "why"),
    [
        (None, tm.NATIVE_1M_WINDOW, "unset — the ordinary 1M session"),
        ("1", tm.HELD_200K_WINDOW, "the hold is on"),
        ("true", tm.HELD_200K_WINDOW, "word spelling of on"),
        ("TRUE", tm.HELD_200K_WINDOW, "case-insensitive"),
        ("yes", tm.HELD_200K_WINDOW, "any non-falsy value means on"),
        ("0", tm.NATIVE_1M_WINDOW, "an env var must honor its own off-switch"),
        ("false", tm.NATIVE_1M_WINDOW, "word spelling of off"),
        ("off", tm.NATIVE_1M_WINDOW, "off"),
        ("no", tm.NATIVE_1M_WINDOW, "no"),
        ("", tm.NATIVE_1M_WINDOW, "empty is not 'set'"),
        ("  ", tm.NATIVE_1M_WINDOW, "whitespace-only is not 'set'"),
    ],
)
def test_default_window_follows_the_1m_hold(value, expected, why) -> None:
    """The fallback is 200K exactly when CC is holding the session to 200K."""
    env = {} if value is None else {"CLAUDE_CODE_DISABLE_1M_CONTEXT": value}
    assert tm.default_window(env) == expected, why


def test_the_hold_actually_changes_the_reported_percentage() -> None:
    """The point of the fix, stated as arithmetic rather than as a constant.

    A 190k-token session is at 19% of 1M but 95% of 200K. Under the hold the guard's >=85%
    threshold must be crossed; assuming 1M it is not — which is how a watchdog goes silently
    inert instead of loudly wrong."""
    tokens = 190_000
    unheld = round(100 * tokens / tm.default_window({}))
    held = round(100 * tokens / tm.default_window({"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}))
    assert unheld < 85, f"assuming 1M this reads as {unheld}% — below the guard, so it never fires"
    assert held >= 85, f"under the hold it must read as {held}% and trip the guard"
