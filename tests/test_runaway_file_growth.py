"""The runaway-file-growth detector (TRDD-XM3FPJC0).

It exists because a 231 MB debug log grew for ELEVEN DAYS with nothing reporting it — the janitor's
purge detectors are age-based sweeps of dirs it OWNS, and nothing watched the size of a file
written by someone else. These pin the four properties that make it useful rather than noisy:
it names a balloon once, it stays quiet while that balloon is static, it speaks again when the
balloon doubles, and it NEVER touches the file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

_spec = importlib.util.spec_from_file_location(
    "runaway_file_growth", _REPO / "scripts" / "detectors" / "runaway-file-growth.py"
)
assert _spec and _spec.loader
rfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rfg)

_MB = 1024 * 1024


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"\0" * size)
    return path


# --- the re-alert policy (pure) ---------------------------------------------------


def test_a_first_sighting_is_always_reported() -> None:
    """A balloon nobody has named yet must be named."""
    assert rfg.worth_reporting(300 * _MB, None, factor=2.0) is True


def test_an_unchanged_file_is_not_reported_again() -> None:
    """An hourly detector that repeats the same line forever teaches the reader to skip it."""
    assert rfg.worth_reporting(300 * _MB, 300 * _MB, factor=2.0) is False


def test_a_file_that_doubles_is_reported_again() -> None:
    """Still growing is new information, so it earns a second line."""
    assert rfg.worth_reporting(600 * _MB, 300 * _MB, factor=2.0) is True


def test_modest_growth_stays_quiet() -> None:
    """Below the factor it is the same finding, not a new one."""
    assert rfg.worth_reporting(310 * _MB, 300 * _MB, factor=2.0) is False


def test_a_shrunk_file_goes_quiet_rather_than_re_reporting() -> None:
    """A balloon a human just truncated must stop shouting — that is the fix working."""
    assert rfg.worth_reporting(1024, 300 * _MB, factor=2.0) is False


# --- scanning -----------------------------------------------------------------------


def test_only_files_at_or_above_the_threshold_are_found(tmp_path) -> None:
    """A healthy small log must never appear; the threshold is the whole filter."""
    _write(tmp_path / "small.log", 1024)
    big = _write(tmp_path / "big.log", 2 * _MB)
    found = rfg.scan_roots([str(tmp_path)], threshold=_MB)
    assert list(found) == [str(big.resolve())]


def test_the_same_inode_via_two_roots_is_reported_once(tmp_path) -> None:
    """On macOS /tmp IS /private/tmp — a naive scan reports one balloon as two runaways."""
    real = tmp_path / "real"
    big = _write(real / "big.log", 2 * _MB)
    link = tmp_path / "alias"
    link.symlink_to(real, target_is_directory=True)
    found = rfg.scan_roots([str(real), str(link)], threshold=_MB)
    assert list(found) == [str(big.resolve())]


def test_a_missing_root_is_a_silent_noop(tmp_path) -> None:
    """A tidiness advisory must never break a heartbeat over an absent directory."""
    assert rfg.scan_roots([str(tmp_path / "nope")], threshold=_MB) == {}


def test_a_zero_threshold_disables_the_scan(tmp_path) -> None:
    """The documented off switch must actually switch it off."""
    _write(tmp_path / "big.log", 2 * _MB)
    assert rfg.scan_roots([str(tmp_path)], threshold=0) == {}


def test_a_symlinked_file_is_not_followed(tmp_path) -> None:
    """Following file symlinks would report one file under every alias pointing at it."""
    big = _write(tmp_path / "big.log", 2 * _MB)
    (tmp_path / "alias.log").symlink_to(big)
    found = rfg.scan_roots([str(tmp_path)], threshold=_MB)
    assert list(found) == [str(big.resolve())]


def test_the_detector_never_modifies_what_it_finds(tmp_path) -> None:
    """REPORT-ONLY is the design: these files belong to other tools and to the user."""
    big = _write(tmp_path / "big.log", 2 * _MB)
    before = (big.stat().st_size, big.stat().st_mtime)
    rfg.scan_roots([str(tmp_path)], threshold=_MB)
    assert big.is_file()
    assert (big.stat().st_size, big.stat().st_mtime) == before


# --- knobs --------------------------------------------------------------------------


def test_roots_are_colon_separated(monkeypatch) -> None:
    """Operators configure extra scan roots without editing the detector."""
    monkeypatch.setenv(rfg.ROOTS_ENV, "/a/b: /c/d :")
    assert rfg.roots() == ["/a/b", "/c/d"]


def test_an_unset_roots_knob_uses_the_documented_default(monkeypatch) -> None:
    """The measured balloon lived in /tmp/claude, so that is what ships on by default."""
    monkeypatch.delenv(rfg.ROOTS_ENV, raising=False)
    assert rfg.roots() == ["/tmp/claude"]


def test_a_malformed_growth_factor_falls_back_instead_of_disabling(monkeypatch) -> None:
    """A typo in a knob must not silently turn a repeating guard into a one-shot."""
    monkeypatch.setenv(rfg.GROWTH_FACTOR_ENV, "not-a-number")
    assert rfg.growth_factor() == rfg.DEFAULT_GROWTH_FACTOR
    monkeypatch.setenv(rfg.GROWTH_FACTOR_ENV, "0.5")
    assert rfg.growth_factor() == rfg.DEFAULT_GROWTH_FACTOR


def test_the_detector_is_registered_in_the_dispatcher() -> None:
    """An unregistered detector never runs — the gap would silently persist."""
    dispatch_src = (_REPO / "scripts" / "dispatch.py").read_text(encoding="utf-8")
    assert '("runaway-file-growth", 3600,' in dispatch_src
    assert '"runaway-file-growth",' in dispatch_src
