"""Tests for the repo-trust-score detector.

The detector at scripts/detectors/repo-trust-score.py audits the
current project tree for the dropper pattern shared by the two
malicious repos found in the github-monitoring study (snakebite,
Pipeline-Sentinel). Score threshold = 8.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "repo-trust-score.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    project_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_REPO_TRUST_SCORE_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def _seed_legitimate_project(project_dir: Path) -> None:
    """Make a normal-looking project: README + LICENSE + tests + source."""
    (project_dir / "README.md").write_text(
        "# my-tool\n\nSmall CLI utility for X.\n", encoding="utf-8",
    )
    (project_dir / "LICENSE").write_text("MIT", encoding="utf-8")
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "src" / "main.py").write_text(
        "def main():\n    print('hi')\n" * 20, encoding="utf-8",
    )
    (project_dir / "tests").mkdir(exist_ok=True)
    (project_dir / "tests" / "test_main.py").write_text(
        "def test_main(): pass\n", encoding="utf-8",
    )
    (project_dir / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (project_dir / ".github" / "workflows" / "ci.yml").write_text(
        "name: ci\non: [push]\njobs: {}\n", encoding="utf-8",
    )


def _seed_dropper(project_dir: Path) -> None:
    """Match the snakebite / Pipeline-Sentinel shape: heavy README with a
    download funnel + suspicious binaries in image/ + no tests/CI/LICENSE."""
    (project_dir / "image").mkdir(exist_ok=True)
    # Five suspicious binaries — matches the Pipeline-Sentinel inventory.
    (project_dir / "image" / "Software-2.9.zip").write_bytes(b"PK\x03\x04" + b"X" * 1000)
    (project_dir / "image" / "Launcher.cmd").write_text("echo evil", encoding="utf-8")
    (project_dir / "image" / "Application.bat").write_text("echo evil", encoding="utf-8")
    (project_dir / "image" / "loader.exe").write_bytes(b"MZ" + b"\x00" * 100)
    (project_dir / "image" / "lua51.dll").write_bytes(b"MZ" + b"\x00" * 100)
    # README aggressively funnels to the binary; SEO-stuffed.
    readme = (
        "# AwesomeTool — the Pipeline Sentinel CI/CD Failure Analysis tool\n\n"
        + ("AwesomeTool is the AwesomeTool you need. AwesomeTool, the only AwesomeTool. "
           "AwesomeTool helps AwesomeTool fans AwesomeTool faster than any AwesomeTool. "
           "Download AwesomeTool. AwesomeTool everywhere.\n\n") * 5
        + "For Windows users, download the latest from image/Software-2.9.zip\n\n"
        + "Click here to launch: image/Launcher.cmd\n\n"
        + "See image/loader.exe to run.\n\n"
        + ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
           "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
           "veniam quis nostrud exercitation ullamco laboris.\n") * 30
    )
    (project_dir / "README.md").write_text(readme, encoding="utf-8")
    # Tiny camouflage Python — looks like the repo has source but it's a noop.
    (project_dir / "main.py").write_text("# decorative\n", encoding="utf-8")


# ---------- Silent on legitimate projects --------------------------------


def test_silent_on_legitimate_project(tmp_path: Path) -> None:
    _seed_legitimate_project(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_on_empty_project(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_with_one_binary_in_examples_dir(tmp_path: Path) -> None:
    """A single .zip in examples/ does NOT trip the detector on its
    own — legitimate repos sometimes ship sample data."""
    _seed_legitimate_project(tmp_path)
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "sample.zip").write_bytes(b"PK\x03\x04xxx")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Fires on the dropper pattern --------------------------------


def test_fires_on_dropper_pattern(tmp_path: Path) -> None:
    _seed_dropper(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[repo-trust-score]" in r.stdout
    assert "dropper-shape" in r.stdout
    # The Pipeline-Sentinel-style inventory should produce ≥ 8 score.
    assert "trust-deficit score" in r.stdout


def test_fires_when_readme_funnels_to_binary(tmp_path: Path) -> None:
    """A README that points at a local .exe is the canonical
    rogue-distribution shape."""
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "loader.exe").write_bytes(b"MZ" + b"\x00" * 100)
    (tmp_path / "image" / "Application.bat").write_text("echo x", encoding="utf-8")
    (tmp_path / "image" / "Launcher.cmd").write_text("echo x", encoding="utf-8")
    (tmp_path / "image" / "data.zip").write_bytes(b"PK\x03\x04" + b"x" * 50)
    (tmp_path / "README.md").write_text(
        "# Awesome\n\nFor Windows users: download from image/loader.exe\n"
        "Click here to extract: image/data.zip\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[repo-trust-score]" in r.stdout
    assert "download-funnel" in r.stdout


def test_fires_on_seo_keyword_stuffing(tmp_path: Path) -> None:
    """Repeated keyword stuffing + a couple of binaries crosses threshold."""
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "Software.zip").write_bytes(b"PK\x03\x04xx")
    (tmp_path / "image" / "Launcher.cmd").write_text("x", encoding="utf-8")
    (tmp_path / "image" / "Application.bat").write_text("x", encoding="utf-8")
    (tmp_path / "image" / "loader.exe").write_bytes(b"MZ" + b"\x00" * 50)
    (tmp_path / "README.md").write_text(
        "# X\n\n" + (
            "AwesomeProduct AwesomeProduct AwesomeProduct AwesomeProduct "
            "AwesomeProduct AwesomeProduct AwesomeProduct AwesomeProduct "
            "AwesomeProduct AwesomeProduct rocks for AwesomeProduct fans.\n"
        ),
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[repo-trust-score]" in r.stdout


# ---------- Heartbeat hygiene -------------------------------------------


def test_silent_on_second_run_when_nothing_changed(tmp_path: Path) -> None:
    _seed_dropper(tmp_path)
    first = _run(tmp_path)
    assert "[repo-trust-score]" in first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stdout == ""


# ---------- Self-scan guard ---------------------------------------------


def test_self_scan_guard_silences_detector(tmp_path: Path) -> None:
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.1"}),
        encoding="utf-8",
    )
    _seed_dropper(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Feature flag ------------------------------------------------


def test_disabled_by_env_flag(tmp_path: Path) -> None:
    _seed_dropper(tmp_path)
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_REPO_TRUST_SCORE_ENABLED": "0"},
    )
    assert r.returncode == 0
    assert r.stdout == ""
