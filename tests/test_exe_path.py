"""Tests for scripts/lib/exe_path.exe: it resolves a bare name the way subprocess would, under the given env's PATH or os.environ's (TRDD-SWQXCIOS)."""

from __future__ import annotations

from pathlib import Path

import pytest
from exe_path import exe


def test_exe_finds_stub_on_env_path(tmp_path: Path) -> None:
    """exe resolves a tool on the PATH given in env to its full path."""
    stub = tmp_path / "fake-tool-xyz"
    stub.write_text("#!/bin/sh\n", encoding="utf-8")
    stub.chmod(0o755)
    assert exe("fake-tool-xyz", {"PATH": str(tmp_path)}) == str(tmp_path / "fake-tool-xyz")


def test_exe_returns_bare_name_when_tool_missing(tmp_path: Path) -> None:
    """exe returns the bare name when no PATH entry holds the tool."""
    assert exe("no-such-tool-xyz-123", {"PATH": str(tmp_path)}) == "no-such-tool-xyz-123"


def test_exe_uses_os_environ_path_when_env_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With env=None, exe resolves under os.environ's PATH: a stub on a PATH set only in os.environ is found."""
    stub = tmp_path / "fake-tool-env-none"
    stub.write_text("#!/bin/sh\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert exe("fake-tool-env-none") == str(stub)
