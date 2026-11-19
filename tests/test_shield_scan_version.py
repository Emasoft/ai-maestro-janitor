"""Real-bun tests of the scan plugin_version: SHIELD_SCAN_VERSION, when set, replaces the plugin.json version.

No mock: every test runs `scripts/shield_scan/scan.ts` under real bun on a plain folder in tmp_path. A vendored byte-identical copy of scan.ts has no .claude-plugin/plugin.json, so the variable is how it names its version.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import transcript_redact as tr
from _shield_redact_box import TOKEN, Box

# The suite denies every real binary by default (tests/sandbox_guard.py); these tests run the REAL bun and the REAL git, so they opt in.
pytestmark = pytest.mark.real_subprocess("bun", "git")

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCAN = PLUGIN_ROOT / "scripts" / "shield_scan" / "scan.ts"
# WHY the name has no SECRET in it: the CPV skillaudit rule CRED_ENV_READ matches process.env.[A-Z_]*SECRET and blocked the publish gate on the former name.
VERSION_ENV = "SHIELD_SCAN_VERSION"
TIMEOUT_S = 180.0


def _scan(tmp_path: Path, version: str | None) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run scan.ts over a one-file folder with SHIELD_SCAN_VERSION set to version (unset when None); return the process and the findings file."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "clean.txt").write_text("nothing\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "out.jsonl"
    env = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"), GIT_CONFIG_NOSYSTEM="1")
    env.pop(VERSION_ENV, None)
    if version is not None:
        env[VERSION_ENV] = version
    done = subprocess.run([tr.resolve_bun(), str(SCAN), "--jobs", "2", "--out", str(out), str(root)], capture_output=True, text=True, timeout=TIMEOUT_S, env=env, check=False)
    return done, out


def _summary(out: Path) -> dict[str, Any]:
    """The last record of the findings file, which is the summary."""
    summary: dict[str, Any] = json.loads(out.read_text(encoding="utf-8").splitlines()[-1])
    assert summary["type"] == "summary"
    return summary


def test_scan_version_env_value_is_the_reported_plugin_version(tmp_path: Path) -> None:
    """With SHIELD_SCAN_VERSION set to 9.9.9-test, the summary reports plugin_version 9.9.9-test and the scan exits 0."""
    done, out = _scan(tmp_path, "9.9.9-test")
    assert done.returncode == 0, done.stderr
    assert _summary(out)["plugin_version"] == "9.9.9-test"


@pytest.mark.parametrize(
    "version",
    ["", "a b", "a\tb", "a\x07b", "v" * 65, "a\N{NO-BREAK SPACE}b", "a\x85b"],
    ids=["empty", "space", "tab", "bel-control", "65-chars", "nbsp", "c1-nel"],
)
def test_malformed_scan_version_env_value_exits_2_with_the_fixed_error(tmp_path: Path, version: str) -> None:
    """A malformed SHIELD_SCAN_VERSION (empty, whitespace, a control character, or over 64 characters) exits 2 with the fixed error and writes no findings file."""
    done, out = _scan(tmp_path, version)
    assert done.returncode == 2
    assert "SHIELD_SCAN_VERSION is set but empty or malformed" in done.stderr
    assert not out.exists()


def test_scan_version_env_value_of_exactly_64_characters_is_accepted(tmp_path: Path) -> None:
    """A SHIELD_SCAN_VERSION of exactly 64 characters is accepted: the scan exits 0 and the summary reports it as plugin_version."""
    value = "v" * 64
    done, out = _scan(tmp_path, value)
    assert done.returncode == 0, done.stderr
    assert _summary(out)["plugin_version"] == value


def test_unset_scan_version_env_reports_the_plugin_json_version(tmp_path: Path) -> None:
    """With SHIELD_SCAN_VERSION unset, the summary reports the version in .claude-plugin/plugin.json."""
    done, out = _scan(tmp_path, None)
    assert done.returncode == 0, done.stderr
    manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert _summary(out)["plugin_version"] == manifest["version"]


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def test_malformed_scan_version_with_redact_exits_2_before_any_file_or_vault_is_touched(box: Box) -> None:
    """A malformed SHIELD_SCAN_VERSION with --redact exits 2 before any file is read: the file bytes are unchanged and no vault.db is created."""
    original = f"k = {TOKEN}\n".encode()
    target = box.put(box.root / "a.txt", original)
    result = box.run(env_extra={VERSION_ENV: "a b"})
    assert result.code == 2
    assert "SHIELD_SCAN_VERSION is set but empty or malformed" in result.stderr
    assert target.read_bytes() == original
    assert not (box.vault_dir / "vault.db").exists()
    assert TOKEN not in result.streams()
