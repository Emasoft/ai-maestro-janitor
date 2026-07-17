"""Tests for settings_ensurer.ensure_recommended_settings — the two merge modes + safety.

The ensurer keeps recommended Claude Code settings in the user-global ~/.claude/settings.json:
Group A (8 env keys) ADD-IF-MISSING into the `env` block; Group B (askUserQuestionTimeout) ENFORCE
at the top level (set-if-missing-or-different). It runs per-session (SessionStart hook), so it must
be idempotent, atomic, and NEVER clobber a config it cannot parse.

Isolation is load-bearing (memory lesson janitor-keepalive-test-isolation-fsevents): BOTH the
settings path (HOME-derived) AND the flock (global-state-derived) are redirected to tmp dirs, so
the REAL ~/.claude/settings.json and the REAL global-state lock are never touched. The settings
path is resolved at CALL time, so `monkeypatch.setenv("HOME")` after import redirects it — proving
there is no frozen `Path.home()` constant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import global_state as gs  # noqa: E402
import settings_ensurer as se  # noqa: E402


def _isolate(monkeypatch, tmp_path) -> Path:
    """Redirect HOME (settings path) AND JANITOR_GLOBAL_STATE_DIR (the flock) to tmp dirs so the
    real user config and real global-state lock are never touched. Returns the settings.json path."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_ENSURE_SETTINGS_ENABLED", raising=False)
    return home / ".claude" / "settings.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _no_tmp_residue(path: Path) -> bool:
    return not list(path.parent.glob(f"{path.name}.tmp.*"))


def test_adds_all_env_keys_to_empty_file(monkeypatch, tmp_path):
    """Group A: an empty (no-env) settings.json gains all 8 recommended env keys with their values."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text("{}", encoding="utf-8")
    changed = se.ensure_recommended_settings()
    assert sorted(changed["env_added"]) == sorted(se.ENV_ADD_IF_MISSING)
    env = _read(sp)["env"]
    assert env == se.ENV_ADD_IF_MISSING
    assert _no_tmp_residue(sp)


def test_group_a_never_overwrites_existing_env_value(monkeypatch, tmp_path):
    """Group A skips a key already present in the env block, KEEPING the user's value verbatim."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text(json.dumps({"env": {"ENABLE_TOOL_SEARCH": "true"}}), encoding="utf-8")
    changed = se.ensure_recommended_settings()
    env = _read(sp)["env"]
    assert env["ENABLE_TOOL_SEARCH"] == "true"  # untouched — the whole point
    assert "ENABLE_TOOL_SEARCH" not in changed["env_added"]
    assert "ENABLE_BACKGROUND_TASKS" in changed["env_added"]  # the others still added


def test_group_b_enforce_adds_when_missing(monkeypatch, tmp_path):
    """Group B: a missing askUserQuestionTimeout is set to the enforced value."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text("{}", encoding="utf-8")
    changed = se.ensure_recommended_settings()
    assert "askUserQuestionTimeout" in changed["top_level_set"]
    assert _read(sp)["askUserQuestionTimeout"] == se.TOP_LEVEL_ENFORCE["askUserQuestionTimeout"]


def test_group_b_enforce_overwrites_when_different(monkeypatch, tmp_path):
    """Group B ENFORCE: a DIFFERENT askUserQuestionTimeout is OVERWRITTEN (unlike Group A).

    Pre-seed a value guaranteed to differ from whatever the enforced value is, so this test does
    not silently no-op if the enforced constant ever equals the seed.
    """
    sp = _isolate(monkeypatch, tmp_path)
    seed = "5m" if se.TOP_LEVEL_ENFORCE["askUserQuestionTimeout"] != "5m" else "never"
    sp.write_text(json.dumps({"askUserQuestionTimeout": seed}), encoding="utf-8")
    changed = se.ensure_recommended_settings()
    assert "askUserQuestionTimeout" in changed["top_level_set"]
    assert _read(sp)["askUserQuestionTimeout"] == se.TOP_LEVEL_ENFORCE["askUserQuestionTimeout"]


def test_group_b_enforce_noop_when_equal(monkeypatch, tmp_path):
    """Group B: an already-equal askUserQuestionTimeout is not reported changed."""
    sp = _isolate(monkeypatch, tmp_path)
    full_env = dict(se.ENV_ADD_IF_MISSING)
    sp.write_text(json.dumps({"env": full_env, **se.TOP_LEVEL_ENFORCE}), encoding="utf-8")
    changed = se.ensure_recommended_settings()
    assert changed == {"env_added": [], "top_level_set": []}


def test_all_satisfied_does_not_write(monkeypatch, tmp_path):
    """When nothing is missing/different, the file is not rewritten (bytes unchanged, no residue)."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text(json.dumps({"env": dict(se.ENV_ADD_IF_MISSING), **se.TOP_LEVEL_ENFORCE}), encoding="utf-8")
    before = sp.read_bytes()
    changed = se.ensure_recommended_settings()
    assert changed == {"env_added": [], "top_level_set": []}
    assert sp.read_bytes() == before  # no write at all
    assert _no_tmp_residue(sp)


def test_malformed_json_is_left_untouched(monkeypatch, tmp_path):
    """A malformed settings.json is NEVER clobbered — bytes unchanged, empty summary returned."""
    sp = _isolate(monkeypatch, tmp_path)
    garbage = '{"env": {"A": 1  BROKEN not json'
    sp.write_text(garbage, encoding="utf-8")
    changed = se.ensure_recommended_settings()
    assert changed == {"env_added": [], "top_level_set": []}
    assert sp.read_text(encoding="utf-8") == garbage  # untouched
    assert _no_tmp_residue(sp)


def test_env_present_but_not_object_is_left_untouched(monkeypatch, tmp_path):
    """If `env` exists but is not an object, merging would replace it — so we abort, not clobber."""
    sp = _isolate(monkeypatch, tmp_path)
    payload = json.dumps({"env": "not-an-object"})
    sp.write_text(payload, encoding="utf-8")
    changed = se.ensure_recommended_settings()
    assert changed == {"env_added": [], "top_level_set": []}
    assert sp.read_text(encoding="utf-8") == payload  # untouched


def test_missing_file_is_created(monkeypatch, tmp_path):
    """A missing settings.json is created with the env block + the enforced key."""
    sp = _isolate(monkeypatch, tmp_path)
    assert not sp.exists()
    changed = se.ensure_recommended_settings()
    assert changed["env_added"] and changed["top_level_set"]
    data = _read(sp)
    assert data["env"] == se.ENV_ADD_IF_MISSING
    assert data["askUserQuestionTimeout"] == se.TOP_LEVEL_ENFORCE["askUserQuestionTimeout"]


def test_preserves_other_top_level_keys(monkeypatch, tmp_path):
    """Merging touches only env + the enforced key; every other top-level key survives verbatim."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text(
        json.dumps({"enabledPlugins": ["x@mkt"], "hooks": {"Stop": []}, "env": {"KEEP": "1"}}),
        encoding="utf-8",
    )
    se.ensure_recommended_settings()
    data = _read(sp)
    assert data["enabledPlugins"] == ["x@mkt"]
    assert data["hooks"] == {"Stop": []}
    assert data["env"]["KEEP"] == "1"  # pre-existing env key preserved
    assert data["env"]["ENABLE_BACKGROUND_TASKS"] == "1"  # ours added alongside


def test_opt_out_disables_everything(monkeypatch, tmp_path):
    """With the opt-out env set false, nothing is read or written."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_ENSURE_SETTINGS_ENABLED", "false")
    changed = se.ensure_recommended_settings()
    assert changed == {"env_added": [], "top_level_set": []}
    assert sp.read_text(encoding="utf-8") == "{}"  # untouched


def test_held_lock_makes_the_ensurer_skip(monkeypatch, tmp_path):
    """When another session holds the settings-ensurer lock, this one SKIPS (no write)."""
    sp = _isolate(monkeypatch, tmp_path)
    sp.write_text("{}", encoding="utf-8")
    fd = gs.acquire_settings_ensurer_lock()
    assert fd is not None
    try:
        changed = se.ensure_recommended_settings()
        assert changed == {"env_added": [], "top_level_set": []}
        assert sp.read_text(encoding="utf-8") == "{}"  # the holder is applying it; we skip
    finally:
        gs.release_settings_ensurer_lock(fd)


# ---- supersecure verified write: swap ONLY after proving only-intended-edits ----------


def test_verify_invariants_accepts_intended_edits():
    """The verifier passes a result that differs from the original by ONLY the intended edits."""
    original = {"a": 1, "env": {"KEEP": "x"}}
    result = {
        "a": 1,
        "env": {"KEEP": "x", "ENABLE_BACKGROUND_TASKS": "1"},
        "askUserQuestionTimeout": se.TOP_LEVEL_ENFORCE["askUserQuestionTimeout"],
    }
    ok, reason = se._verify_invariants(original, result, ["ENABLE_BACKGROUND_TASKS"], ["askUserQuestionTimeout"])
    assert ok, reason


def test_verify_invariants_rejects_unrelated_top_level_change():
    """An unrelated top-level value changing is a corruption the verifier must reject."""
    ok, _ = se._verify_invariants({"a": 1, "env": {}}, {"a": 999, "env": {"ENABLE_BACKGROUND_TASKS": "1"}}, ["ENABLE_BACKGROUND_TASKS"], [])
    assert not ok


def test_verify_invariants_rejects_removed_key():
    """Dropping a pre-existing key is rejected — the write must preserve everything else."""
    ok, _ = se._verify_invariants({"a": 1, "keepme": 2, "env": {}}, {"a": 1, "env": {}}, [], [])
    assert not ok


def test_verify_invariants_rejects_existing_env_value_change():
    """Overwriting a pre-existing env value (Group A never does this) is rejected."""
    ok, _ = se._verify_invariants({"env": {"KEEP": "old"}}, {"env": {"KEEP": "TAMPERED", "ENABLE_BACKGROUND_TASKS": "1"}}, ["ENABLE_BACKGROUND_TASKS"], [])
    assert not ok


def test_verify_invariants_rejects_unexpected_new_key():
    """A new top-level key that is neither `env` nor an enforced key is rejected."""
    ok, _ = se._verify_invariants({"env": {}}, {"env": {}, "surprise": "!"}, [], [])
    assert not ok


def test_verified_write_swaps_on_valid_result(monkeypatch, tmp_path):
    """The happy path: a valid result is written and swapped in; no temp residue."""
    sp = _isolate(monkeypatch, tmp_path)
    original = {"enabledPlugins": ["x"], "env": {"KEEP": "1"}}
    sp.write_text(json.dumps(original), encoding="utf-8")
    result = {"enabledPlugins": ["x"], "env": {"KEEP": "1", "ENABLE_BACKGROUND_TASKS": "1"}}
    assert se._verified_atomic_write(sp, original, result, ["ENABLE_BACKGROUND_TASKS"], []) is True
    assert _read(sp) == result
    assert _no_tmp_residue(sp)


def test_verified_write_refuses_and_preserves_on_corruption(monkeypatch, tmp_path):
    """If the result altered an UNRELATED value, the write refuses to swap and the LIVE FILE is
    left exactly as it was — the core supersecure guarantee."""
    sp = _isolate(monkeypatch, tmp_path)
    original = {"enabledPlugins": ["x"], "env": {"KEEP": "1"}}
    sp.write_text(json.dumps(original), encoding="utf-8")
    before = sp.read_bytes()
    tampered = {"enabledPlugins": ["TAMPERED"], "env": {"KEEP": "1", "ENABLE_BACKGROUND_TASKS": "1"}}
    assert se._verified_atomic_write(sp, original, tampered, ["ENABLE_BACKGROUND_TASKS"], []) is False
    assert sp.read_bytes() == before  # untouched — never swapped
    assert _no_tmp_residue(sp)


def test_path_resolved_at_call_time_honors_injected_home(monkeypatch, tmp_path):
    """Isolation proof: the settings path follows the injected HOME (no frozen Path.home() constant),
    and an explicit home= writes there — never the real ~/.claude/settings.json."""
    _isolate(monkeypatch, tmp_path)
    # Explicit home= overrides even the env HOME, and resolves at call time.
    other = tmp_path / "explicit-home"
    (other / ".claude").mkdir(parents=True, exist_ok=True)
    assert se._settings_path(home=other) == other / ".claude" / "settings.json"
    se.ensure_recommended_settings(home=other)
    assert (other / ".claude" / "settings.json").exists()
    # The env-HOME path was NOT written when an explicit home was given.
    assert not (Path(str(tmp_path / "home")) / ".claude" / "settings.json").exists()
