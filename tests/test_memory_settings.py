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

import json
import math
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
    """A store that was never written returns the documented defaults — the seven
    per-day editorial rates are 1 (autonomous curation ON by default but capped at
    1/day, owner directive 2026-08-11 superseding the 2026-06-30 all-OFF default)."""
    assert ms.get("consolidation_per_day") == 1
    assert ms.get("split_per_day") == 1
    assert ms.get("split_max_bytes") == 36000
    assert ms.get("conflict_per_day") == 1
    # Flipped True by owner directive 2026-08-27: librarians must reach PROJECT scope too. The old
    # False meant 100% of PROJECT-scope recall-surface defects were unreachable by ANY chore — the
    # gate's "PROJECT memory is unpushable outside publish.py" rationale is still true and simply
    # never implied the pages should go unmaintained; librarian commits ride the next publish.
    assert ms.get("edit_project_scope") is True


def test_set_and_get_roundtrip():
    """set_value persists; a subsequent get reflects it."""
    assert ms.set_value("consolidation_per_day", "3") == 3.0
    assert ms.get("consolidation_per_day") == 3.0


def test_set_none_reverts_to_default():
    """set_value(key, None) reverts that key to its default."""
    ms.set_value("split_per_day", "9")
    assert ms.set_value("split_per_day", None) == 1
    assert ms.get("split_per_day") == 1


def test_per_day_rate_above_86400_never_crashes_is_due():
    """M-5 (wikimem audit 2026-07-07): a per-day rate > 86400 (interval < 1 s)
    is accepted by validation, so is_due must not die on `% int(interval)` —
    pre-fix int(0.5) == 0 raised `integer modulo by zero` on EVERY is_due."""
    ms.set_value("harvest_per_day", "100000")
    assert isinstance(ms.is_due("harvest", "LOCAL", "/tmp/root", _NOW), bool)
    assert ms.interval_s("harvest_per_day") < 1


def test_wrong_typed_stored_value_degrades_to_default():
    """M-6 (wikimem audit 2026-07-07): a hand-edited store with a wrong-TYPED
    value must degrade to the default like a corrupt FILE does — pre-fix
    interval_s raised ValueError, crashing the scheduler's is_due and the txn
    CLI's _split_max_bytes."""
    ms.settings_dir().mkdir(parents=True, exist_ok=True)
    ms._settings_path().write_text(
        json.dumps({"harvest_per_day": "banana", "split_max_bytes": "not-an-int",
                    "split_per_day": 2}),
        encoding="utf-8",
    )
    assert ms.get("harvest_per_day") == 1          # corrupt → default
    assert ms.get("split_max_bytes") == 36000      # corrupt → default
    assert ms.get("split_per_day") == 2.0          # the valid key still applies
    assert ms.interval_s("harvest_per_day") == 86400.0  # default is now 1/day, not disabled
    assert isinstance(ms.is_due("harvest", "LOCAL", "/tmp/root", _NOW), bool)  # never raises


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
    assert ms.get("consolidation_per_day") == 1


# ---- deviation-only persistence (TRDD-378c85da) ----------------------------
# The store must persist ONLY keys that deviate from the current DEFAULTS, never
# the whole dict. The old wholesale write froze EVERY key (incl. ones left at
# default), so a later default change was masked by the stale captured value —
# the bug that defeated the split_max_bytes 12k->36k raise.

def _stored() -> dict:
    """The raw persisted settings dict (what landed on disk), or {} if absent."""
    path = ms.settings_dir() / "memory-settings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_set_persists_only_the_deviation():
    """A non-default set writes ONLY that key — not the whole dict."""
    ms.set_value("split_per_day", "9")
    assert _stored() == {"split_per_day": 9.0}


def test_set_to_default_persists_no_deviation():
    """Setting a key to its CURRENT default freezes nothing in — the file holds no
    deviation (an empty object), so the default still flows from DEFAULTS."""
    ms.set_value("split_max_bytes", str(ms.DEFAULTS["split_max_bytes"]))
    assert _stored() == {}
    assert ms.get("split_max_bytes") == ms.DEFAULTS["split_max_bytes"]


def test_multiple_deviations_accumulate():
    """Independent non-default sets accumulate; an unrelated set keeps prior ones."""
    ms.set_value("split_per_day", "9")
    ms.set_value("conflict_per_day", "3")
    assert _stored() == {"split_per_day": 9.0, "conflict_per_day": 3.0}


def test_revert_drops_the_key_from_the_file():
    """Reverting a key to its default removes it from the persisted file."""
    ms.set_value("split_per_day", "9")
    assert "split_per_day" in _stored()
    ms.set_value("split_per_day", None)  # revert to default
    assert "split_per_day" not in _stored()
    assert ms.get("split_per_day") == ms.DEFAULTS["split_per_day"]


def test_default_change_flows_through_untouched_key(monkeypatch):
    """THE REGRESSION (split_max_bytes 12k->36k): tuning ONE key must not freeze the
    OTHERS at their default, so a LATER default change flows through instead of being
    masked by a stale captured value."""
    ms.set_value("conflict_per_day", "3")            # a real deviation -> file is written
    assert "split_max_bytes" not in _stored()        # untouched key is NOT frozen in
    # Simulate a later default RAISE; the untouched key must follow it, not a stale capture.
    monkeypatch.setitem(ms.DEFAULTS, "split_max_bytes", 99000)
    assert ms.get("split_max_bytes") == 99000


# ---- interval derivation ---------------------------------------------------

def test_interval_s_from_rate():
    """interval_s = 86400 / per-day (e.g. 2.5/day -> 34560s); a 0 rate -> inf (disabled)."""
    ms.set_value("consolidation_per_day", "2.5")  # enable (raised above the 1/day default)
    assert ms.interval_s("consolidation_per_day") == 86400 / 2.5
    ms.set_value("consolidation_per_day", "0")
    assert ms.interval_s("consolidation_per_day") == float("inf")


def test_interval_s_for_intervention_maps_to_its_key():
    """interval_s_for('split') reads split_per_day."""
    ms.set_value("split_per_day", "6")
    assert ms.interval_s_for("split") == 86400 / 6


# ---- scheduler stamps ------------------------------------------------------

def test_due_then_not_due_after_mark_ran():
    """A never-run (enabled) intervention is due; mark_ran makes it not-due immediately."""
    ms.set_value("consolidation_per_day", "2.5")  # enable (raised above the 1/day default)
    root = "/some/scope/root"
    assert ms.is_due("consolidate", "USER", root, _NOW) is True
    ms.mark_ran("consolidate", "USER", root, _NOW)
    assert ms.is_due("consolidate", "USER", root, _NOW) is False


def test_due_again_after_interval_elapses():
    """Once a full cadence interval passes, the (enabled) intervention is due again."""
    ms.set_value("consolidation_per_day", "2.5")  # enable (raised above the 1/day default)
    root = "/some/scope/root"
    ms.mark_ran("consolidate", "USER", root, _NOW)
    # 2.5/day -> 34560s interval; advance beyond it
    assert ms.is_due("consolidate", "USER", root, _NOW + 40000) is True


def test_disabled_intervention_is_never_due():
    """A 0 rate means the intervention never fires, even with an ancient stamp."""
    ms.set_value("conflict_per_day", "0")
    assert ms.is_due("conflict", "USER", "/r", _NOW + 10_000_000) is False


def test_stamps_are_per_root_independent():
    """Marking root A run does NOT make root B not-due (no starvation across roots)."""
    ms.set_value("split_per_day", "4.5")  # enable (raised above the 1/day default)
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
    """`get` prints the rate + derived interval for an enabled pass."""
    ms.set_value("consolidation_per_day", "2.5")  # enable (raised above the 1/day default)
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
    assert ms.get("conflict_per_day") == 1


def test_cli_bad_value_exits_nonzero(capsys, monkeypatch):
    """A bad value exits non-zero with an error, never silently."""
    monkeypatch.setattr(sys, "argv", ["x", "set", "consolidation_per_day", "-2"])
    assert cli.main() == 2
    assert "error:" in capsys.readouterr().err


# ---- per-project phase staggering (TRDD-3f7b6807) --------------------------

def _next_boundary(phase: float, last: float, iv: float) -> float:
    """First phase-aligned boundary k*iv+phase strictly greater than `last`."""
    k = math.floor((last - phase) / iv) + 1
    b = k * iv + phase
    while b <= last:
        k += 1
        b = k * iv + phase
    return b


def test_stagger_enabled_default_on_and_toggles():
    """stagger_enabled defaults True and parses on/off like every bool setting."""
    assert ms.get("stagger_enabled") is True
    assert ms.set_value("stagger_enabled", "off") is False
    assert ms.get("stagger_enabled") is False
    assert ms.set_value("stagger_enabled", "on") is True


def test_phase_offset_in_range_stable_and_per_root():
    """Phase is in [0, interval), stable for one root, and DIFFERENT across roots —
    the staggering: two projects land on different time-of-day slots."""
    ms.set_value("harvest_per_day", "1")  # explicit — matches the 1/day default
    iv = ms.interval_s_for("harvest")  # 86400 (1/day)
    pa = ms._phase_offset("harvest", "LOCAL", "/proj/alpha", iv)
    pb = ms._phase_offset("harvest", "LOCAL", "/proj/beta", iv)
    assert 0.0 <= pa < iv and 0.0 <= pb < iv
    assert ms._phase_offset("harvest", "LOCAL", "/proj/alpha", iv) == pa  # stable
    assert pa != pb  # two projects -> different slots


def test_stagger_two_roots_due_at_different_times():
    """With the SAME last_run, two projects come due at DIFFERENT `now` — the core
    rate-limit-smoothing property: at the earlier project's slot, the later one is
    NOT yet due."""
    ms.set_value("harvest_per_day", "1")  # explicit — matches the 1/day default
    iv = ms.interval_s_for("harvest")
    t0 = _NOW
    ms.mark_ran("harvest", "LOCAL", "/proj/alpha", t0)
    ms.mark_ran("harvest", "LOCAL", "/proj/beta", t0)
    nb_a = _next_boundary(ms._phase_offset("harvest", "LOCAL", "/proj/alpha", iv), t0, iv)
    nb_b = _next_boundary(ms._phase_offset("harvest", "LOCAL", "/proj/beta", iv), t0, iv)
    assert nb_a != nb_b  # staggered next-due moments
    if nb_a < nb_b:
        earlier, later, now = "/proj/alpha", "/proj/beta", int(nb_a)
    else:
        earlier, later, now = "/proj/beta", "/proj/alpha", int(nb_b)
    assert ms.is_due("harvest", "LOCAL", earlier, now) is True
    assert ms.is_due("harvest", "LOCAL", later, now) is False  # its slot is later


def test_stagger_off_restores_plain_interval():
    """With stagger disabled, is_due is the plain now-last_run>=interval cadence."""
    ms.set_value("stagger_enabled", "off")
    ms.set_value("consolidation_per_day", "2.5")  # enable (raised above the 1/day default)
    root, iv = "/proj/x", ms.interval_s_for("consolidate")
    ms.mark_ran("consolidate", "USER", root, _NOW)
    assert ms.is_due("consolidate", "USER", root, _NOW + int(iv) - 5) is False
    assert ms.is_due("consolidate", "USER", root, _NOW + int(iv) + 5) is True


def test_stagger_first_run_fires_promptly():
    """A never-run (enabled) intervention (last_run=0) is due immediately even with
    staggering on — day-1 is serialized by the flock, not by withholding the first run."""
    ms.set_value("harvest_per_day", "1")  # explicit — matches the 1/day default
    assert ms.is_due("harvest", "LOCAL", "/proj/fresh", _NOW) is True


def test_stagger_fires_once_per_interval_at_the_slot():
    """After a run at its slot, not due until the NEXT phase boundary; due again
    exactly there (one fire per interval)."""
    ms.set_value("harvest_per_day", "1")  # explicit — matches the 1/day default
    iv = ms.interval_s_for("harvest")
    root = "/proj/cadence"
    phase = ms._phase_offset("harvest", "LOCAL", root, iv)
    b0 = _next_boundary(phase, _NOW, iv)
    ms.mark_ran("harvest", "LOCAL", root, int(b0))
    assert ms.is_due("harvest", "LOCAL", root, int(b0) + 100) is False  # same period
    b1 = _next_boundary(phase, b0, iv)
    assert ms.is_due("harvest", "LOCAL", root, int(b1)) is True  # next slot


def test_stagger_disabled_rate_never_due():
    """A 0 rate is never due even with staggering on."""
    ms.set_value("harvest_per_day", "0")
    assert ms.is_due("harvest", "LOCAL", "/proj/x", _NOW + 10_000_000) is False


# --------------------------------------------------------------------------- #
# harvest watermark store (TRDD-ab232dbd — idempotent coexistence mirror)
# --------------------------------------------------------------------------- #

def test_harvest_watermark_empty_by_default():
    """A scope with no watermark yet → empty map, nothing mirrored."""
    assert ms.harvest_watermark_read("LOCAL", "/proj/wm") == {}
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/wm", "note.md", "anytext") is False


def test_harvest_watermark_marks_and_recognises_by_content_hash():
    """After marking a note mirrored, the SAME content is recognised; CHANGED content
    is NOT (so an edited buffer note re-mirrors, never goes stale)."""
    ms.harvest_mark_mirrored("LOCAL", "/proj/wm", "note.md", "original body")
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/wm", "note.md", "original body") is True
    # An edit to the buffer note changes the hash → NOT mirrored → harvest re-mirrors it.
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/wm", "note.md", "EDITED body") is False


def test_harvest_watermark_is_per_scope_and_per_root():
    """The watermark is keyed by (scope, root) — a mark in one does not leak to another."""
    ms.harvest_mark_mirrored("LOCAL", "/proj/a", "note.md", "body")
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/a", "note.md", "body") is True
    assert ms.harvest_note_is_mirrored("USER", "/proj/a", "note.md", "body") is False
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/b", "note.md", "body") is False


def test_harvest_watermark_accumulates_multiple_notes():
    """Marking several notes accumulates them all in the one per-scope map."""
    ms.harvest_mark_mirrored("LOCAL", "/proj/m", "a.md", "ba")
    ms.harvest_mark_mirrored("LOCAL", "/proj/m", "b.md", "bb")
    wm = ms.harvest_watermark_read("LOCAL", "/proj/m")
    assert set(wm) == {"a.md", "b.md"}
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/m", "a.md", "ba") is True
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/m", "b.md", "bb") is True


def test_harvest_watermark_survives_corrupt_file(tmp_path, monkeypatch):
    """A corrupt watermark JSON degrades to empty (re-mirror), never crashes harvest."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    p = ms.harvest_watermark_path("LOCAL", "/proj/corrupt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", encoding="utf-8")
    assert ms.harvest_watermark_read("LOCAL", "/proj/corrupt") == {}
    assert ms.harvest_note_is_mirrored("LOCAL", "/proj/corrupt", "n.md", "x") is False


# ── is-due / mark-ran CLI verbs (issue #68 P1, TRDD-UENXDA8P) ────────────────────────────


def test_cli_is_due_then_mark_ran_roundtrip(capsys, monkeypatch, tmp_path):
    """The agent-shell cadence gate: `is-due` exits 0 (due) for an enabled fresh pass;
    `mark-ran` stamps it; `is-due` then exits 1 with `not-due` — no lib import needed."""
    ms.set_value("harvest_per_day", "4")
    root = tmp_path / "memroot"
    root.mkdir()
    due_argv = ["x", "is-due", "harvest", "LOCAL", "--root", str(root), "--now", str(_NOW)]
    monkeypatch.setattr(sys, "argv", due_argv)
    assert cli.main() == 0
    assert capsys.readouterr().out.strip() == "due"

    monkeypatch.setattr(
        sys, "argv", ["x", "mark-ran", "harvest", "LOCAL", "--root", str(root), "--now", str(_NOW)]
    )
    assert cli.main() == 0
    capsys.readouterr()

    monkeypatch.setattr(sys, "argv", due_argv)
    assert cli.main() == 1
    assert capsys.readouterr().out.strip() == "not-due"


def test_cli_is_due_disabled_pass_not_due(capsys, monkeypatch, tmp_path):
    """A pass explicitly disabled (rate 0) is never due — exit 1."""
    ms.set_value("conflict_per_day", "0")
    monkeypatch.setattr(
        sys, "argv", ["x", "is-due", "conflict", "LOCAL", "--root", str(tmp_path), "--now", str(_NOW)]
    )
    assert cli.main() == 1
    assert capsys.readouterr().out.strip() == "not-due"


def test_cli_is_due_unknown_intervention_errors(capsys, monkeypatch, tmp_path):
    """An unknown intervention fails fast with exit 2 — never a silent not-due."""
    monkeypatch.setattr(
        sys, "argv", ["x", "is-due", "nonsense", "LOCAL", "--root", str(tmp_path), "--now", str(_NOW)]
    )
    assert cli.main() == 2
    assert "unknown intervention" in capsys.readouterr().err


def test_cli_scope_label_is_case_insensitive(capsys, monkeypatch, tmp_path):
    """`local` and `LOCAL` hit the SAME stamp — the CLI normalizes to the scheduler's
    UPPERCASE labels, else agent-typed lowercase would fork the cadence."""
    ms.set_value("repair_per_day", "2")
    root = tmp_path / "m"
    root.mkdir()
    monkeypatch.setattr(
        sys, "argv", ["x", "mark-ran", "repair", "local", "--root", str(root), "--now", str(_NOW)]
    )
    assert cli.main() == 0
    capsys.readouterr()
    monkeypatch.setattr(
        sys, "argv", ["x", "is-due", "repair", "LOCAL", "--root", str(root), "--now", str(_NOW)]
    )
    assert cli.main() == 1  # the lowercase mark-ran satisfied the UPPERCASE is-due
    assert capsys.readouterr().out.strip() == "not-due"
