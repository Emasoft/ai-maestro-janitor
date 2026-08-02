"""Tests for the event-driven scope-drift fast path (TRDD-MN7ZU3RY).

Three hooks under test, all as REAL subprocess runs (no mocks):
- on-config-change.py     — ConfigChange ⇒ mark the config detectors DUE (unlink stamps)
- on-file-changed.py      — FileChanged ⇒ mark the mapped detectors DUE + observed stamp
- on-session-start-watchpaths.py — declare hookSpecificOutput.watchPaths (absolute) + stamp

The contract pinned here (advisor verdict 2026-08-02):
- mark-due = bare unlink of `last-run-<detector>.ts` (a missing stamp is DUE per
  dispatch's `_detector_is_due`); NO lock (dispatch's loop takes none — a lock would
  serialize nothing and "skip when busy" would drop the event).
- zero stdout from the event hooks; the watchpaths hook emits EXACTLY one JSON object
  (its plain-text stdout would be context-injected) or NOTHING on error.
- always exit 0 — an event hook must never break the session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOKS = _PROJECT_ROOT / "scripts" / "hooks"


def _run(hook: str, tmp: Path, *, stdin: str) -> tuple[subprocess.CompletedProcess, Path]:
    proj = tmp / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp / "home"),
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    (tmp / "home").mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(_HOOKS / hook)],
        input=stdin, capture_output=True, text=True, env=env, timeout=30,
    )
    return proc, state_dir


def _seed_stamps(state_dir: Path, names: list[str]) -> None:
    for n in names:
        (state_dir / f"last-run-{n}.ts").write_text("1700000000")


ALL = [
    "settings-scope-drift", "mcp-config-drift",
    "tracked-ignored", "project-memory-tracked",
]


# ---------- ConfigChange ----------

def test_config_change_marks_config_detectors_due_only(tmp_path: Path) -> None:
    """Both config detectors' stamps vanish (⇒ due next fire); the file-watch
    detectors' stamps are untouched; zero stdout; exit 0."""
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    _seed_stamps(state_dir, ALL)
    proc, _ = _run(
        "on-config-change.py", tmp_path,
        stdin=json.dumps({"hook_event_name": "ConfigChange", "source": "project_settings"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", "event hooks are side-effect only — no stdout, ever"
    assert not (state_dir / "last-run-settings-scope-drift.ts").exists()
    assert not (state_dir / "last-run-mcp-config-drift.ts").exists()
    assert (state_dir / "last-run-tracked-ignored.ts").exists(), "unrelated stamp touched"
    assert (state_dir / "last-run-project-memory-tracked.ts").exists()


def test_config_change_garbage_stdin_exits_zero(tmp_path: Path) -> None:
    proc, state_dir = _run("on-config-change.py", tmp_path, stdin="\x00{{{not json")
    assert proc.returncode == 0, proc.stderr
    # Payload is not load-bearing: the marks still land (any source ⇒ same mapping).
    assert not (state_dir / "last-run-settings-scope-drift.ts").exists()


# ---------- FileChanged ----------

def test_file_changed_gitignore_marks_its_detectors_and_stamps_observed(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    _seed_stamps(state_dir, ALL)
    proc, _ = _run(
        "on-file-changed.py", tmp_path,
        stdin=json.dumps({"hook_event_name": "FileChanged",
                          "file_path": str(proj / ".gitignore"), "event": "change"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert not (state_dir / "last-run-tracked-ignored.ts").exists()
    assert not (state_dir / "last-run-project-memory-tracked.ts").exists()
    assert (state_dir / "last-run-settings-scope-drift.ts").exists(), "unrelated stamp touched"
    assert (state_dir / "watch-paths-observed.ts").is_file(), (
        "every delivered event must stamp observed.ts — the proof-of-armed half"
    )


def test_file_changed_mcp_json_marks_mcp_drift(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    _seed_stamps(state_dir, ALL)
    proc, _ = _run(
        "on-file-changed.py", tmp_path,
        stdin=json.dumps({"file_path": str(proj / ".mcp.json"), "event": "add"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert not (state_dir / "last-run-mcp-config-drift.ts").exists()
    assert (state_dir / "last-run-tracked-ignored.ts").exists()


def test_file_changed_unmapped_file_only_stamps_observed(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    _seed_stamps(state_dir, ALL)
    proc, _ = _run(
        "on-file-changed.py", tmp_path,
        stdin=json.dumps({"file_path": str(proj / "README.md"), "event": "change"}),
    )
    assert proc.returncode == 0, proc.stderr
    for n in ALL:
        assert (state_dir / f"last-run-{n}.ts").exists(), f"{n} stamp must survive"
    assert (state_dir / "watch-paths-observed.ts").is_file()


# ---------- SessionStart watchPaths declaration ----------

def test_watchpaths_emits_exactly_one_json_object_with_absolute_paths(tmp_path: Path) -> None:
    """The stdout must be machine-parseable JSON carrying hookSpecificOutput.watchPaths
    (the placement verified in the 2.1.220 binary — a top-level key is silently ignored),
    every path ABSOLUTE, and the declaration stamped to watch-paths-declared.json."""
    proc, state_dir = _run("on-session-start-watchpaths.py", tmp_path, stdin="{}")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)  # exactly one object — anything else raises here
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    paths = hso["watchPaths"]
    assert paths and all(Path(p).is_absolute() for p in paths), (
        "the binary's reader wants ABSOLUTE paths"
    )
    assert any(p.endswith(".gitignore") for p in paths)
    assert any(p.endswith(".mcp.json") for p in paths)
    declared = json.loads((state_dir / "watch-paths-declared.json").read_text())
    assert declared["paths"] == paths and declared["ts"] > 0


def test_watchpaths_prints_nothing_on_error(tmp_path: Path) -> None:
    """On any failure the hook must print NOTHING — non-JSON stdout from a SessionStart
    hook is injected as context (the K1RJUYGK budget it must never touch)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    # No CLAUDE_PROJECT_DIR and cwd pointing at an unwritable root exercises the
    # fail path deterministically enough: state_dir() resolution still succeeds in
    # most environments, so force the failure by making the state dir a FILE.
    (proj / ".janitor").write_text("not a dir")
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    proc = subprocess.run(
        [sys.executable, str(_HOOKS / "on-session-start-watchpaths.py")],
        input="{}", capture_output=True, text=True, env=env, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", "error path must emit zero stdout (it would be context)"
