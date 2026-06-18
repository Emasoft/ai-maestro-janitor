"""Tests for the global wikimem-editor settings store + scheduler stamps + the CLI
(TRDD-c1397102).

Real fixtures, no mocks: the settings store is redirected to a tmp dir via
JANITOR_MEMORY_SETTINGS_DIR and the machine-wide stamps via
JANITOR_GLOBAL_STATE_DIR, so the real plugin-DATA dir is never touched. Covers the
acceptance: set/get/default-revert/disabled round-trips, fail-fast validation, the
per-day → interval derivation, the due/mark_ran cadence, per-root stamp
independence (no starvation), global-stamp sharing (two sessions → one fire), and
the CLI's get/set/revert/error paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_settings as ms  # noqa: E402
import memory_settings_cli as cli  # noqa: E402

_NOW = 1_000_000_000  # a fixed epoch so tests never depend on the wall clock


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("JANITOR_MEMORY_SETTINGS_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))


# ---- settings store --------------------------------------------------------

def test_defaults_on_fresh_store():
    """A store that was never written returns the documented defaults."""
    assert ms.get("consolidation_per_day") == 2.5
    assert ms.get("split_per_day") == 4.5
    assert ms.get("split_max_bytes") == 12000
    assert ms.get("conflict_per_day") == 0.5
    assert ms.get("edit_project_scope") is False


def test_set_and_get_roundtrip():
    """set_value persists; a subsequent get reflects it."""
    assert ms.set_value("consolidation_per_day", "3") == 3.0
    assert ms.get("consolidation_per_day") == 3.0


def test_set_none_reverts_to_default():
    """set_value(key, None) reverts that key to its default."""
    ms.set_value("split_per_day", "9")
    assert ms.set_value("split_per_day", None) == 4.5
    assert ms.get("split_per_day") == 4.5


def test_set_zero_is_allowed_and_disables():
    """A 0 rate is valid (it disables the pass) — not rejected."""
    assert ms.set_value("conflict_per_day", "0") == 0.0
    assert ms.interval_s("conflict_per_day") == float("inf")


def test_set_rejects_negative_rate():
    """A negative rate is fail-fast rejected, not silently clamped."""
    with pytest.raises(ValueError):
        ms.set_value("consolidation_per_day", "-1")


def test_set_rejects_nonnumeric_rate():
    """A non-numeric rate raises."""
    with pytest.raises(ValueError):
        ms.set_value("consolidation_per_day", "soon")


def test_maxsize_must_be_positive_int():
    """split_max_bytes accepts a positive int and rejects 0 / negatives."""
    assert ms.set_value("split_max_bytes", "8000") == 8000
    with pytest.raises(ValueError):
        ms.set_value("split_max_bytes", "0")


def test_bool_setting_parses_friendly_spellings():
    """edit_project_scope parses on/off-style values; garbage raises."""
    assert ms.set_value("edit_project_scope", "on") is True
    assert ms.set_value("edit_project_scope", "off") is False
    with pytest.raises(ValueError):
        ms.set_value("edit_project_scope", "maybe")


def test_unknown_key_raises():
    """An unknown setting key is rejected on both get and set."""
    with pytest.raises(ValueError):
        ms.get("nope_per_day")
    with pytest.raises(ValueError):
        ms.set_value("nope_per_day", "1")


def test_load_is_resilient_to_a_corrupt_store():
    """A corrupt store file degrades to defaults, never crashes."""
    ms.settings_dir().mkdir(parents=True, exist_ok=True)
    (ms.settings_dir() / "memory-settings.json").write_text("{not json", encoding="utf-8")
    assert ms.get("consolidation_per_day") == 2.5


# ---- interval derivation ---------------------------------------------------

def test_interval_s_from_rate():
    """interval_s = 86400 / per-day; default 2.5/day -> 34560s."""
    assert ms.interval_s("consolidation_per_day") == 86400 / 2.5
    ms.set_value("consolidation_per_day", "0")
    assert ms.interval_s("consolidation_per_day") == float("inf")


def test_interval_s_for_intervention_maps_to_its_key():
    """interval_s_for('split') reads split_per_day."""
    ms.set_value("split_per_day", "6")
    assert ms.interval_s_for("split") == 86400 / 6


# ---- scheduler stamps ------------------------------------------------------

def test_due_then_not_due_after_mark_ran():
    """A never-run intervention is due; mark_ran makes it not-due immediately."""
    root = "/some/scope/root"
    assert ms.is_due("consolidate", "USER", root, _NOW) is True
    ms.mark_ran("consolidate", "USER", root, _NOW)
    assert ms.is_due("consolidate", "USER", root, _NOW) is False


def test_due_again_after_interval_elapses():
    """Once a full cadence interval passes, the intervention is due again."""
    root = "/some/scope/root"
    ms.mark_ran("consolidate", "USER", root, _NOW)
    # default 2.5/day -> 34560s interval; advance beyond it
    assert ms.is_due("consolidate", "USER", root, _NOW + 40000) is True


def test_disabled_intervention_is_never_due():
    """A 0 rate means the intervention never fires, even with an ancient stamp."""
    ms.set_value("conflict_per_day", "0")
    assert ms.is_due("conflict", "USER", "/r", _NOW + 10_000_000) is False


def test_stamps_are_per_root_independent():
    """Marking root A run does NOT make root B not-due (no starvation across roots)."""
    ms.mark_ran("split", "LOCAL", "/root/a", _NOW)
    assert ms.is_due("split", "LOCAL", "/root/a", _NOW) is False
    assert ms.is_due("split", "LOCAL", "/root/b", _NOW) is True


def test_stamp_is_shared_machine_wide():
    """The stamp lives under the global-state dir, so a second 'session' sees the
    same global last-run (two sessions don't double-fire one global intervention)."""
    root = "/some/scope/root"
    ms.mark_ran("conflict", "USER", root, _NOW)
    assert ms.read_last_run("conflict", "USER", root) == _NOW


# ---- the CLI ---------------------------------------------------------------

def test_cli_get_shows_cadence(capsys, monkeypatch):
    """`get` prints the rate + derived interval."""
    monkeypatch.setattr(sys, "argv", ["x", "get", "consolidation_per_day"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "consolidation_per_day = 2.5/day" in out


def test_cli_set_then_persists(capsys, monkeypatch):
    """`set <key> <value>` persists and confirms."""
    monkeypatch.setattr(sys, "argv", ["x", "set", "split_per_day", "6"])
    assert cli.main() == 0
    assert "split_per_day = 6/day" in capsys.readouterr().out
    assert ms.get("split_per_day") == 6.0


def test_cli_bare_set_reverts(capsys, monkeypatch):
    """`set <key>` with no value reverts to default and says so."""
    ms.set_value("conflict_per_day", "3")
    monkeypatch.setattr(sys, "argv", ["x", "set", "conflict_per_day"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "reverted to default" in out
    assert ms.get("conflict_per_day") == 0.5


def test_cli_bad_value_exits_nonzero(capsys, monkeypatch):
    """A bad value exits non-zero with an error, never silently."""
    monkeypatch.setattr(sys, "argv", ["x", "set", "consolidation_per_day", "-2"])
    assert cli.main() == 2
    assert "error:" in capsys.readouterr().err
