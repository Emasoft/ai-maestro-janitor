"""Tests for the screenshot-purge detector.

The detector lives at scripts/detectors/screenshot-purge.py. Tests run it
as a subprocess (the real invocation surface — matches how dispatch.py
spawns it), with CLAUDE_PROJECT_DIR pointed at a tmp_path. That sidesteps
state.py's lru_cache and guarantees zero cross-test contamination.

Fixtures use `os.utime` to set mtime explicitly rather than `touch -d`
or sleeping — synthetic mtimes make age boundaries deterministic and
keep the suite under a second total.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

# Resolve the detector once at module level. tests/ is a sibling of scripts/.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "screenshot-purge.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_screenshot(dir_: Path, name: str, age_hours: float, size_bytes: int = 16) -> Path:
    """Create a screenshot file with a precise age (in hours).

    Size is in bytes — non-zero so low-disk freed-bytes math is testable.
    """
    p = dir_ / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size_bytes)
    when = time.time() - (age_hours * 3600)
    os.utime(p, (when, when))
    return p


def _run_detector(
    project_dir: Path,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the detector as a subprocess with the given project dir.

    Returns the CompletedProcess so tests can inspect stdout, stderr, exit code.
    """
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    # Disable any global janitor state side effects that aren't relevant.
    env.pop("CLAUDE_PLUGIN_OPTION_SCREENSHOT_PURGE_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _list_dir(dir_: Path) -> set[str]:
    """Return a set of file/dir names directly under `dir_`."""
    if not dir_.is_dir():
        return set()
    return {p.name for p in dir_.iterdir()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Build a minimal fake project layout: <tmp>/reports/screenshots/."""
    shots = tmp_path / "reports" / "screenshots"
    shots.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def shots_dir(project_root: Path) -> Path:
    return project_root / "reports" / "screenshots"


# ---------------------------------------------------------------------------
# Tests: age-based purge
# ---------------------------------------------------------------------------

def test_age_purge_removes_files_above_threshold(project_root: Path, shots_dir: Path) -> None:
    """Files older than 72h (default) are removed."""
    _make_screenshot(shots_dir, "old.png", age_hours=80)
    _make_screenshot(shots_dir, "ancient.jpg", age_hours=200)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    assert _list_dir(shots_dir) == set()
    assert "removed 2 screenshot(s)" in result.stdout
    assert "older than 72h" in result.stdout


def test_age_purge_keeps_files_below_threshold(project_root: Path, shots_dir: Path) -> None:
    """Files younger than 72h survive."""
    _make_screenshot(shots_dir, "fresh.png", age_hours=1)
    _make_screenshot(shots_dir, "recent.webp", age_hours=24)
    _make_screenshot(shots_dir, "borderline.jpg", age_hours=71)  # under 72h

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    assert _list_dir(shots_dir) == {"fresh.png", "recent.webp", "borderline.jpg"}
    assert result.stdout == ""  # silent — nothing purged


def test_age_purge_exact_boundary(project_root: Path, shots_dir: Path) -> None:
    """A file exactly at the threshold is purged (>= cutoff).

    Detector logic: `if age < threshold_sec: continue` — so age == threshold
    means PURGE. Document the contract.
    """
    _make_screenshot(shots_dir, "exactly72h.png", age_hours=72.001)
    _make_screenshot(shots_dir, "just-under.png", age_hours=71.999)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    assert _list_dir(shots_dir) == {"just-under.png"}
    assert "removed 1 screenshot(s)" in result.stdout


def test_custom_max_age_hours(project_root: Path, shots_dir: Path) -> None:
    """The CLAUDE_PLUGIN_OPTION_SCREENSHOT_MAX_AGE_HOURS env var overrides default."""
    _make_screenshot(shots_dir, "old.png", age_hours=25)  # >24h
    _make_screenshot(shots_dir, "young.png", age_hours=23)  # <24h

    result = _run_detector(
        project_root,
        env_overrides={"CLAUDE_PLUGIN_OPTION_SCREENSHOT_MAX_AGE_HOURS": "24"},
    )
    assert result.returncode == 0, result.stderr

    assert _list_dir(shots_dir) == {"young.png"}
    assert "older than 24h" in result.stdout


# ---------------------------------------------------------------------------
# Tests: marker preservation
# ---------------------------------------------------------------------------

def test_markers_never_deleted(project_root: Path, shots_dir: Path) -> None:
    """.gitkeep, README.txt, README.md are explicit-keep — never removed even when ancient."""
    _make_screenshot(shots_dir, ".gitkeep", age_hours=10_000)  # very old
    _make_screenshot(shots_dir, "README.txt", age_hours=10_000)
    _make_screenshot(shots_dir, "README.md", age_hours=10_000)
    _make_screenshot(shots_dir, "real.png", age_hours=200)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    survivors = _list_dir(shots_dir)
    assert ".gitkeep" in survivors
    assert "README.txt" in survivors
    assert "README.md" in survivors
    assert "real.png" not in survivors  # this one DID get purged


def test_non_image_extensions_ignored(project_root: Path, shots_dir: Path) -> None:
    """Files outside the screenshot extension set are never touched, even when ancient."""
    _make_screenshot(shots_dir, "metadata.json", age_hours=500)
    _make_screenshot(shots_dir, "log.txt", age_hours=500)
    _make_screenshot(shots_dir, "test.html", age_hours=500)
    _make_screenshot(shots_dir, "real.png", age_hours=500)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    survivors = _list_dir(shots_dir)
    assert survivors == {"metadata.json", "log.txt", "test.html"}
    # ^ real.png purged; others preserved
    assert "real.png" not in survivors


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "webp", "gif"])
def test_all_screenshot_extensions_recognized(
    project_root: Path,
    shots_dir: Path,
    ext: str,
) -> None:
    """Every documented extension is purgeable."""
    _make_screenshot(shots_dir, f"old.{ext}", age_hours=100)
    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr
    assert _list_dir(shots_dir) == set()


def test_extension_case_insensitive(project_root: Path, shots_dir: Path) -> None:
    """Upper/Title case extensions are treated identically to lower case."""
    _make_screenshot(shots_dir, "shot1.PNG", age_hours=100)
    _make_screenshot(shots_dir, "shot2.Jpg", age_hours=100)
    _make_screenshot(shots_dir, "shot3.JPEG", age_hours=100)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    assert _list_dir(shots_dir) == set()


# ---------------------------------------------------------------------------
# Tests: symlinks
# ---------------------------------------------------------------------------

def test_symlinks_never_followed_or_deleted(
    project_root: Path,
    shots_dir: Path,
    tmp_path: Path,
) -> None:
    """Symlinks to old files are skipped; the target is also untouched."""
    target = tmp_path / "elsewhere.png"
    target.write_bytes(b"target")
    old_mtime = time.time() - 500 * 3600
    os.utime(target, (old_mtime, old_mtime))

    link = shots_dir / "symlink.png"
    link.symlink_to(target)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    # The symlink survives.
    assert link.is_symlink()
    # The target outside the project survives.
    assert target.is_file()


# ---------------------------------------------------------------------------
# Tests: recursive subdir traversal
# ---------------------------------------------------------------------------

def test_recursive_subdir_traversal(project_root: Path, shots_dir: Path) -> None:
    """Screenshots inside subdirectories are also purged."""
    subdir = shots_dir / "feature-x"
    _make_screenshot(subdir, "old.png", age_hours=100)
    _make_screenshot(subdir, "young.png", age_hours=1)
    _make_screenshot(shots_dir, "toplevel-old.png", age_hours=100)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr

    # Subdir's old file purged, young one survives. Top-level old file purged.
    # Subdir itself persists (we never rmdir).
    assert subdir.is_dir()
    assert (subdir / "young.png").is_file()
    assert not (subdir / "old.png").exists()
    assert not (shots_dir / "toplevel-old.png").exists()


# ---------------------------------------------------------------------------
# Tests: no-op cases
# ---------------------------------------------------------------------------

def test_missing_screenshots_dir_is_silent_noop(project_root: Path) -> None:
    """When reports/screenshots/ does not exist at all, exit 0 silently."""
    shutil.rmtree(project_root / "reports" / "screenshots")
    assert not (project_root / "reports" / "screenshots").exists()

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_empty_screenshots_dir_is_silent_noop(project_root: Path) -> None:
    """Empty dir: no-op, exit 0, silent. The project_root fixture creates an
    empty reports/screenshots/ — no further setup needed."""
    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_only_young_files_silent_noop(project_root: Path, shots_dir: Path) -> None:
    """A dir full of young files produces no output."""
    for i in range(5):
        _make_screenshot(shots_dir, f"shot-{i}.png", age_hours=1)

    result = _run_detector(project_root)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert len(_list_dir(shots_dir)) == 5


# ---------------------------------------------------------------------------
# Tests: enabled flag
# ---------------------------------------------------------------------------

def test_disabled_flag_skips_all_work(project_root: Path, shots_dir: Path) -> None:
    """When SCREENSHOT_PURGE_ENABLED=false, even ancient files are kept."""
    _make_screenshot(shots_dir, "ancient.png", age_hours=10_000)

    result = _run_detector(
        project_root,
        env_overrides={"CLAUDE_PLUGIN_OPTION_SCREENSHOT_PURGE_ENABLED": "false"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (shots_dir / "ancient.png").is_file()


@pytest.mark.parametrize("falsy_value", ["false", "False", "0", "no", "off"])
def test_disabled_accepts_falsy_strings(
    project_root: Path,
    shots_dir: Path,
    falsy_value: str,
) -> None:
    """state.is_truthy_env should accept conventional falsy values.

    Note: empty string is intentionally NOT in this list — per
    state.is_truthy_env, empty/unset env vars fall back to the function's
    `default` (True for this detector). That's the right behavior: a
    user clearing the var should not silently disable purging.
    """
    _make_screenshot(shots_dir, "ancient.png", age_hours=10_000)

    result = _run_detector(
        project_root,
        env_overrides={"CLAUDE_PLUGIN_OPTION_SCREENSHOT_PURGE_ENABLED": falsy_value},
    )
    assert result.returncode == 0, result.stderr
    assert (shots_dir / "ancient.png").is_file()


def test_empty_string_env_treated_as_default_enabled(
    project_root: Path,
    shots_dir: Path,
) -> None:
    """An empty SCREENSHOT_PURGE_ENABLED env var falls through to default=True
    — i.e. purging still happens. This is the documented contract of
    state.is_truthy_env."""
    _make_screenshot(shots_dir, "ancient.png", age_hours=10_000)

    result = _run_detector(
        project_root,
        env_overrides={"CLAUDE_PLUGIN_OPTION_SCREENSHOT_PURGE_ENABLED": ""},
    )
    assert result.returncode == 0, result.stderr
    assert not (shots_dir / "ancient.png").exists(), (
        "empty env var should NOT disable purging"
    )


# ---------------------------------------------------------------------------
# Tests: low-disk override (oldest-first ordering)
# ---------------------------------------------------------------------------

def test_lowdisk_purges_oldest_first(project_root: Path, shots_dir: Path) -> None:
    """When free disk is below min, delete oldest first.

    We force low-disk mode by setting min_free_gb to absurdly high, so the
    threshold is impossible to satisfy and every file gets deleted in
    oldest-first order.
    """
    # All within the 72h cap so age-purge does not fire — only low-disk runs.
    _make_screenshot(shots_dir, "oldest.png",   age_hours=50)
    _make_screenshot(shots_dir, "middle.png",   age_hours=20)
    _make_screenshot(shots_dir, "youngest.png", age_hours=1)

    result = _run_detector(
        project_root,
        env_overrides={
            "CLAUDE_PLUGIN_OPTION_SCREENSHOT_LOWDISK_MIN_FREE_GB": "999999",
            "CLAUDE_PLUGIN_OPTION_SCREENSHOT_LOWDISK_TARGET_FREE_GB": "1000000",
        },
    )
    assert result.returncode == 0, result.stderr

    # All files removed; low-disk loop ran until the dir was empty.
    assert _list_dir(shots_dir) == set()
    assert "LOW DISK" in result.stdout

    # The log must record deletions in oldest-first order.
    log_path = project_root / ".janitor" / "logs" / "screenshot-purge.log"
    assert log_path.is_file()
    log_text = log_path.read_text()
    pos_oldest = log_text.find("oldest.png")
    pos_middle = log_text.find("middle.png")
    pos_youngest = log_text.find("youngest.png")
    assert 0 <= pos_oldest < pos_middle < pos_youngest, (
        f"oldest-first ordering broken in log:\n{log_text}"
    )


def test_lowdisk_disabled_when_min_is_zero(project_root: Path, shots_dir: Path) -> None:
    """When min_free_gb=0 AND nothing is age-expired, no purge runs.

    The free-space probe will return > 0 GiB on any real filesystem, so
    `free_before >= lowdisk_min_bytes (== 0)` triggers the early exit
    from the low-disk loop. This is the documented "set to 0 to disable
    low-disk override" behavior.
    """
    _make_screenshot(shots_dir, "young.png", age_hours=1)

    result = _run_detector(
        project_root,
        env_overrides={"CLAUDE_PLUGIN_OPTION_SCREENSHOT_LOWDISK_MIN_FREE_GB": "0"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (shots_dir / "young.png").is_file()


def test_lowdisk_hysteresis_forced_gap(project_root: Path, shots_dir: Path) -> None:
    """target ≤ min is corrected at runtime to min+1, preventing infinite loop.

    We set both to the same absurdly high value; the detector must still
    terminate cleanly. Without the runtime gap, the loop would never make
    progress (free < target after every iteration).
    """
    _make_screenshot(shots_dir, "shot.png", age_hours=1)

    result = _run_detector(
        project_root,
        env_overrides={
            "CLAUDE_PLUGIN_OPTION_SCREENSHOT_LOWDISK_MIN_FREE_GB": "999999",
            "CLAUDE_PLUGIN_OPTION_SCREENSHOT_LOWDISK_TARGET_FREE_GB": "999999",
        },
    )
    # The point is termination — not whether the file is gone.
    # If the hysteresis fix is missing, this test would hang and time out
    # via the 30s subprocess timeout.
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------

def test_running_twice_is_idempotent(project_root: Path, shots_dir: Path) -> None:
    """A second consecutive run on a clean state produces no output and no errors."""
    _make_screenshot(shots_dir, "old.png", age_hours=100)
    _make_screenshot(shots_dir, "young.png", age_hours=1)

    result1 = _run_detector(project_root)
    assert result1.returncode == 0
    assert "removed 1 screenshot(s)" in result1.stdout

    result2 = _run_detector(project_root)
    assert result2.returncode == 0
    assert result2.stdout == ""  # nothing left to do

    assert _list_dir(shots_dir) == {"young.png"}


# ---------------------------------------------------------------------------
# Tests: log file management
# ---------------------------------------------------------------------------

def test_log_file_created_on_first_purge(project_root: Path, shots_dir: Path) -> None:
    """The detector creates .janitor/logs/screenshot-purge.log on first deletion."""
    _make_screenshot(shots_dir, "old.png", age_hours=100)

    result = _run_detector(project_root)
    assert result.returncode == 0

    log_path = project_root / ".janitor" / "logs" / "screenshot-purge.log"
    assert log_path.is_file()
    log_text = log_path.read_text()
    assert "age-purged" in log_text
    assert "old.png" in log_text
