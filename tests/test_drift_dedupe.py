"""Cross-fire drift-line dedupe (TRDD-7ZMQSXO6, acceptance criterion c).

A detector re-measuring the SAME condition on the next fire ("~390min" becomes
"~371min") must not repeat itself verbatim. Reuses `dedupe.emit_once`, the same
permanent per-detector dedup primitive already used elsewhere in dispatch.py, keyed
on a NORMALIZED form of the line: only elapsed-time tokens are blanked, never a
count or an id, so a genuinely different finding still prints. A suppressed repeat
is never silently lost — the seen-file records it, and a one-line summary prints
whenever the suppressed count increased since the previous fire.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def env_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Point project/global state + HOME at tmp dirs; reload dispatch + state so
    `state.state_dir()`'s `lru_cache` picks up the isolated paths (mirrors the
    identically-named fixture in tests/test_dispatch_phases.py)."""
    project = tmp_path / "project"
    project.mkdir()
    global_dir = tmp_path / "janitor-global-state"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "janitor-control"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))

    for mod in ("dispatch", "global_state", "state"):
        if mod in sys.modules:
            del sys.modules[mod]

    return {"project": project, "global_dir": global_dir}


def _import_dispatch():
    """Import scripts/dispatch.py without running main() (mirrors test_dispatch_phases.py)."""
    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_under_test_drift_dedupe",
        str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_second_fire_drops_the_repeat_third_fire_is_silent_again(env_isolation: dict) -> None:
    """Three fires, same underlying finding re-measured each time (elapsed minutes
    change): fire 1 prints it plain, fire 2 suppresses it AND prints the summary
    (count went 0 -> 1), fire 3 suppresses it again with NO summary (count held
    steady at 1 -- the reader already knows)."""
    dispatch = _import_dispatch()
    fire1 = dispatch._dedupe_drift_text("stale-task", "[stale-task] idle for ~390min\n")
    assert fire1 == "[stale-task] idle for ~390min\n"

    fire2 = dispatch._dedupe_drift_text("stale-task", "[stale-task] idle for ~371min\n")
    assert "[stale-task] idle for" not in fire2
    assert fire2 == "(1 drift line(s) unchanged since the last fire were not repeated)\n"

    fire3 = dispatch._dedupe_drift_text("stale-task", "[stale-task] idle for ~355min\n")
    assert fire3 == ""


def test_a_leading_space_before_the_tilde_still_normalizes(env_isolation: dict) -> None:
    """`\\b~?\\d+min\\b` would silently exempt ' ~390min' (a `\\b` right before `~`
    never fires after a space) -- the fix moves the `\\b` to sit before the digits,
    after the optional `~`, so a leading space does not escape normalization."""
    dispatch = _import_dispatch()
    a = dispatch._drift_dedupe_key("reminder: idle  ~390min")
    b = dispatch._drift_dedupe_key("reminder: idle  ~371min")
    assert a == b


def test_a_line_differing_only_in_a_plain_count_still_prints(env_isolation: dict) -> None:
    """A count is information, not noise -- "8 uncommitted" and "9 uncommitted" are
    two different findings and must never collapse into one."""
    dispatch = _import_dispatch()
    fire1 = dispatch._dedupe_drift_text("dirty-tree", "[dirty-tree] 8 uncommitted files\n")
    fire2 = dispatch._dedupe_drift_text("dirty-tree", "[dirty-tree] 9 uncommitted files\n")
    assert fire1 == "[dirty-tree] 8 uncommitted files\n"
    assert fire2 == "[dirty-tree] 9 uncommitted files\n"


def test_a_hex_dispatch_id_ending_in_digit_d_stays_intact(env_isolation: dict) -> None:
    """A dispatch/commit id such as `...-c0274e7d` must never be mistaken for a
    "NNNd" elapsed-days token -- there is no word boundary before the '7' (it is
    preceded by the word character 'e'), so the days pattern cannot match inside it."""
    dispatch = _import_dispatch()
    key = dispatch._drift_dedupe_key("MEMPASS-EXPIRED dispatch-id=abc-c0274e7d age=120")
    assert "c0274e7d" in key
    assert "age=#" in key


def test_bare_marker_lines_are_never_suppressed(env_isolation: dict) -> None:
    """Action markers are the authorization channel, not a drift finding -- they must
    survive every repeat, unconditionally."""
    dispatch = _import_dispatch()
    for _ in range(3):
        out = dispatch._dedupe_drift_text("ticket-dispatch", "[janitor-ticket]\n")
        assert out == "[janitor-ticket]\n"
