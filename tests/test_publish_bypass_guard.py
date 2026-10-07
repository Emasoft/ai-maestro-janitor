"""publish.py step 0 (bypass guard) must exempt only CPV's renamed integrity variable.

CPV renamed CPV_SKIP_GITHUB_INTEGRITY to PLUGIN_SKIP_GITHUB_INTEGRITY. The guard
refused the new name, leaving only the name CPV is dropping. These tests run the
real guard against the real process environment (monkeypatch.setenv), no mocks.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_bypass_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every host skip/no-verify variable so the host cannot change the result."""
    for name in list(os.environ):
        if name.startswith(("PLUGIN_SKIP_", "CPV_SKIP_", "SKIP_")) or name == "NO_VERIFY":
            monkeypatch.delenv(name)


def test_new_integrity_variable_is_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLUGIN_SKIP_GITHUB_INTEGRITY=1 passes the guard."""
    monkeypatch.setenv("PLUGIN_SKIP_GITHUB_INTEGRITY", "1")
    publish.stage_bypass_guard()


def test_legacy_integrity_variable_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """CPV_SKIP_GITHUB_INTEGRITY=1 is refused with SystemExit."""
    monkeypatch.setenv("CPV_SKIP_GITHUB_INTEGRITY", "1")
    with pytest.raises(SystemExit):
        publish.stage_bypass_guard()


def test_exemption_does_not_widen(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLUGIN_SKIP_FOO=1 is still refused with SystemExit."""
    monkeypatch.setenv("PLUGIN_SKIP_FOO", "1")
    with pytest.raises(SystemExit):
        publish.stage_bypass_guard()


def test_no_bypass_variable_passes() -> None:
    """With no bypass variable set the guard returns normally."""
    publish.stage_bypass_guard()
