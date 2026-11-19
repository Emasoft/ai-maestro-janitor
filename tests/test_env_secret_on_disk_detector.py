"""End-to-end tests of the env-secret-on-disk detector (janitor issue #354, layer 3).

The detector is run as a real program in a throwaway git project, with a secret generated at test time passed as
an environment variable. The assertions are on what it prints, writes and proposes: the variable NAME and the
path are reported, the value never appears in any output, log, state file or proposal.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _ROOT / "scripts" / "detectors" / "env-secret-on-disk.py"
_NAME = "FAKE_API_TOKEN_0000"

sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
import env_secrets  # noqa: E402
from exe_path import exe  # noqa: E402


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    for folder in ("reports_dev", "design/proposals", "design/tasks"):
        (project / folder).mkdir(parents=True)
    (project / ".gitignore").write_text("reports_dev/\n.janitor/\n")
    subprocess.run([exe("git"), "init", "-q"], cwd=project, check=True, env={**os.environ, "HOME": str(tmp_path / "home")})
    return project


def _run(tmp_path: Path, project: Path, value: str) -> subprocess.CompletedProcess[str]:
    """One detector pass with a minimal environment: the planted secret and nothing else that could be a needle."""
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"),
        _NAME: value,
    }
    return subprocess.run([sys.executable, str(_DETECTOR), "--one-shot"], env=env, capture_output=True, text=True, timeout=120, check=False)


def _files_holding(tmp_path: Path, value: str, except_names: set[str]) -> list[str]:
    needle = value.encode()
    return [str(p) for p in tmp_path.rglob("*") if p.is_file() and ".git" not in p.parts and p.name not in except_names and needle in p.read_bytes()]


def test_planted_value_is_reported_by_name_once_and_never_printed_or_stored(tmp_path: Path) -> None:
    """Two files carry the value (one in plain form, one URL-quoted): both are reported by NAME, the second pass is silent,
    and the value appears in no output, log, state file or proposal."""
    value = secrets.token_urlsafe(36) + "+/="
    project = _project(tmp_path)
    (project / "reports_dev" / "dump.txt").write_text(f"PATH=/x HOME=/x SHELL=/x USER=u TERM=x {_NAME}={value} rest\n")
    (project / "notes.txt").write_text("quoted: " + urllib.parse.quote(value, safe="") + "\n")
    first = _run(tmp_path, project, value)
    assert first.returncode == 0, first.stderr
    assert value not in first.stdout and value not in first.stderr
    assert first.stdout.count("CRED-002") == 2 and f"value of {_NAME}" in first.stdout
    assert "reports_dev/dump.txt, line 1 (untracked and ignored)" in first.stdout
    assert "notes.txt, line 1 (untracked)" in first.stdout
    assert "Rotating the secret is YOUR decision" in first.stdout
    assert _run(tmp_path, project, value).stdout == ""
    assert _files_holding(tmp_path, value, {"dump.txt", "notes.txt"}) == []
    assert (project / "reports_dev" / "dump.txt").read_text().count(value) == 1  # report-only: nothing was rewritten


def test_a_cleaned_file_withdraws_its_finding(tmp_path: Path) -> None:
    """After the value is removed from a flagged file the next pass clears the finding and stops tracking the file."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {value}\n")
    assert "CRED-002" in _run(tmp_path, project, value).stdout
    cursor = project / ".janitor" / "state" / "env-secret-on-disk.cursor.json"
    assert list(json.loads(cursor.read_text())["flagged"]) == [str(target)]  # TRDD-ZFD3KBM3: an object path -> fingerprints, no longer a list of paths
    target.write_text("cleaned\n")
    _run(tmp_path, project, value)
    assert json.loads(cursor.read_text())["flagged"] == {}
    proposal = next((project / "design" / "proposals").glob("*"))
    assert "column: refused" in proposal.read_text()


def test_a_file_the_sweep_cannot_read_is_counted_and_holds_the_covered_range(tmp_path: Path) -> None:
    """An unreadable file is named in a coverage line, and the covered range does not move past it (lo stays above it)."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    older = project / "reports_dev" / "a-older.txt"
    locked = project / "reports_dev" / "b-locked.txt"
    older.write_text("nothing\n")
    locked.write_text("nothing\n")
    os.utime(older, (1000.0, 1000.0))
    os.utime(locked, (2000.0, 2000.0))
    locked.chmod(0)
    before = time.time()
    try:
        out = _run(tmp_path, project, value)
    finally:
        locked.chmod(0o600)
        after = time.time()
    assert "sweep coverage" in out.stdout and "1 unreadable" in out.stdout
    cursor = json.loads((project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").read_text())
    # Both edges start at the live edge (no saved range). The locked file (2000) is the top backlog hold, so lo cannot move down
    # over it, and the older file (1000) read behind it stays unclaimed. Both edges are exactly the live edge: the wall clock at the
    # start of the sweep minus LIVE_EDGE_MARGIN_S, bounded here by two clock reads around the run (lo at 1000 would fail this).
    assert cursor["covered"][0] == cursor["covered"][1]
    assert before - 2.0 <= cursor["covered"][0][0] <= after - 2.0  # 2.0 = env_secrets.LIVE_EDGE_MARGIN_S
    assert cursor["retries"] == {str(locked): 1}


def test_a_dump_shaped_file_is_reported_without_a_value_to_match(tmp_path: Path) -> None:
    """A file that looks like a dump of some other environment is reported by the names it holds, as report-only."""
    project = _project(tmp_path)
    entries = [f"{k}=/x" for k in ("PATH", "HOME", "SHELL", "USER", "LOGNAME", "TERM")] + [f"OTHER_API_KEY={secrets.token_urlsafe(40)}"]
    (project / "reports_dev" / "dump.txt").write_text("\n".join(entries) + "\n")
    out = _run(tmp_path, project, secrets.token_urlsafe(36))
    assert "has the shape of an environment dump" in out.stdout and "OTHER_API_KEY" in out.stdout
    assert "CRED-002" not in out.stdout and "Report-only" in out.stdout



# Review leads of 2026-11-15 (outside-model review of the code drop; each failure below was reproduced first).
def _cursor(project: Path) -> dict:
    return json.loads((project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").read_text())


def test_a_git_that_cannot_list_untracked_files_is_said_and_holds_the_covered_range(tmp_path: Path) -> None:
    """A failed `git ls-files` used to look like "no untracked files" and the covered range moved past a leaking file that
    was never read; now it is counted in the coverage line, and a project that has no git at all still advances."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / "reports_dev" / "a.txt").write_text("clean\n")
    shutil.rmtree(project / ".git")  # in-process: the suite sandbox denies spawning a real rm, and none is needed
    (project / ".git").write_text("gitdir: /nonexistent\n")
    out = _run(tmp_path, project, value)
    assert "untracked files were not listed" in out.stdout
    assert _cursor(project)["covered"] is None
    plain = tmp_path / "plain"
    (plain / "reports_dev").mkdir(parents=True)
    (plain / "reports_dev" / "a.txt").write_text("clean\n")
    assert "untracked files were not listed" not in _run(tmp_path, plain, value).stdout
    assert _cursor(plain)["covered"][1][0] > 0



def test_a_git_that_keeps_failing_stops_holding_the_covered_range_and_the_retry_count_is_cleared_when_it_works(tmp_path: Path) -> None:
    """After MAX_FAIL_RETRIES failed passes the covered range moves on (git failing for good must not stall the sweep), the
    count rides in the cursor file across passes, and a pass where git works clears it."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / "reports_dev" / "a.txt").write_text("clean\n")
    git_dir = tmp_path / "git.bak"
    (project / ".git").rename(git_dir)
    (project / ".git").write_text("gitdir: /nonexistent\n")
    for expected in (1, 2, 3):
        _run(tmp_path, project, value)
        state = _cursor(project)
        assert state["retries"] == {"git ls-files": expected} and state["covered"] is None
    _run(tmp_path, project, value)  # the fourth failure: retries exhausted, the covered range is released
    assert _cursor(project)["covered"][1][0] > 0
    (project / ".git").unlink()
    git_dir.rename(project / ".git")
    _run(tmp_path, project, value)
    assert "git ls-files" not in _cursor(project)["retries"]


def test_more_leaking_files_than_the_cap_are_all_reported_over_the_passes(tmp_path: Path) -> None:
    """Hit files were raised in path order but the covered range moves in modification order: with names ascending and
    times descending the same five were raised every pass and the other four never."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    for i in range(9):
        target = project / "reports_dev" / f"f{i}.txt"
        target.write_text(f"leak {value}\n")
        os.utime(target, (5000.0 - i, 5000.0 - i))
    raised = 0
    for _ in range(4):
        raised += _run(tmp_path, project, value).stdout.count("CRED-002")
    assert raised == 9


def test_files_over_the_cap_cost_no_git_calls(tmp_path: Path) -> None:
    """Each leaking file used to cost three git processes, the ones over the per-fire cap included."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    for i in range(9):
        (project / "reports_dev" / f"f{i}.txt").write_text(f"leak {value}\n")
    shim = tmp_path / "shim"
    shim.mkdir()
    calls = tmp_path / "git-calls.log"
    real = subprocess.run([exe("which"), "git"], capture_output=True, text=True, check=True).stdout.strip()
    (shim / "git").write_text(f'#!/bin/sh\necho "$@" >> {calls}\nexec {real} "$@"\n')
    (shim / "git").chmod(0o755)
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": f"{shim}:{os.environ.get('PATH', '')}", "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"), _NAME: value,
    }
    subprocess.run([sys.executable, str(_DETECTOR), "--one-shot"], env=env, capture_output=True, text=True, timeout=120, check=True)
    status_calls = [c for c in calls.read_text().splitlines() if "check-ignore" in c or "error-unmatch" in c]
    assert len(status_calls) <= 5 * 2


def test_many_dump_shaped_files_print_a_few_lines_and_a_count(tmp_path: Path) -> None:
    """Forty dump-shaped files printed forty lines into a heartbeat that the model reads."""
    project = _project(tmp_path)
    for i in range(12):
        entries = [f"{k}=/x" for k in ("PATH", "HOME", "SHELL", "USER", "LOGNAME", "TERM")] + [f"OTHER_API_KEY={secrets.token_urlsafe(40)}"]
        (project / "reports_dev" / f"d{i}.txt").write_text("\n".join(entries) + "\n")
    lines = _run(tmp_path, project, secrets.token_urlsafe(36)).stdout.splitlines()
    assert len(lines) <= 6 and any("more dump-shaped" in line for line in lines)


def test_a_file_named_after_the_value_is_reported_by_folder_and_the_value_is_stored_nowhere(tmp_path: Path) -> None:
    """The cursor file, the log and the finding all carry paths: a name that holds the value must not reach them."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / "reports_dev" / f"cache-{value}.json").write_text("{}\n")
    out = _run(tmp_path, project, value)
    assert value not in out.stdout and value not in out.stderr
    assert "CRED-002" in out.stdout and f"value of {_NAME}" in out.stdout and "reports_dev" in out.stdout
    assert _files_holding(tmp_path, value, set()) == []


def test_a_cut_listing_keeps_the_covered_range_retries_and_findings_and_says_so_once_a_day(tmp_path: Path) -> None:
    """With the listing forced over its budget the pass reads nothing, keeps both edges of the covered range, retries and findings, and says so once."""
    runner = (
        "import runpy, sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "import env_secrets\n"
        "original = env_secrets.sweep\n"
        # TRDD-ZANQ1QW0: a clock moving 12.3 s per read makes the cut elapsed exactly 12.3, so the pass line's listing figure is told from listing_s (0.0 on a cut).
        "import itertools\n"
        "ticks = itertools.count(1)\n"
        "env_secrets.sweep = lambda *a, **k: original(*a, **{**k, \"listing_budget_s\": -1.0, \"clock\": lambda: next(ticks) * 12.3})\n"
        "detector = sys.argv[1]\n"
        "sys.argv = [detector, \"--one-shot\"]\n"
        "runpy.run_path(detector, run_name=\"__main__\")\n"
    )
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    planted = project / "reports_dev" / "dump.txt"
    planted.write_text(f"leak {value}\n")
    state_dir = project / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "env-secret-on-disk.cursor.json").write_text(json.dumps({
        "covered": [[5.0, "x"], [9.0, "y"]], "retries": {"/nonexistent/held": 2}, "flagged": [str(planted)], "trash": {"positions": {}, "done": []},
    }))
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"), _NAME: value,
    }
    argv = [sys.executable, "-c", runner, str(_DETECTOR), str(_DETECTOR.parent.parent / "lib")]
    day = time.strftime("%Y-%m-%d")  # the detector keys the line on the local date: a pass pair straddling midnight proves nothing
    first = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert first.returncode == 0, first.stderr
    assert first.stdout.count("the listing of the agent folders took over") == 1 and "URGENT" not in first.stdout
    state = _cursor(project)
    assert state["covered"] == [[5.0, "x"], [9.0, "y"]] and state["retries"]["/nonexistent/held"] == 2 and str(planted) in state["flagged"]
    assert "the covered range did not move" in first.stdout
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text()
    assert "listing cut after" in log and "covered range kept" in log
    assert "listing cut after 12 s" in log and "; seconds: listing 12.3, fresh 0.0, backlog 0.0, trash " in log  # the cut elapsed, not listing_s (0.0 on a cut)
    second = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert second.returncode == 0, second.stderr
    if time.strftime("%Y-%m-%d") == day:
        assert "the listing of the agent folders took over" not in second.stdout
    assert _cursor(project)["covered"] == [[5.0, "x"], [9.0, "y"]]



def test_an_old_state_file_keeps_flagged_and_drops_the_cursor(tmp_path: Path) -> None:
    """A state file from before the covered range ("cursor", no "covered") starts newest first: flagged is kept and handled, the cursor is dropped."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {value}\n")
    assert "CRED-002" in _run(tmp_path, project, value).stdout
    target.write_text("cleaned\n")
    state_file = project / ".janitor" / "state" / "env-secret-on-disk.cursor.json"
    state_file.write_text(json.dumps({
        "cursor": [5.0, "x"], "retries": {}, "flagged": [str(target)], "trash": {"positions": {}, "done": []},
    }))
    assert _run(tmp_path, project, value).returncode == 0
    state = _cursor(project)
    assert "cursor" not in state
    assert len(state["covered"]) == 2 and all(len(edge) == 2 for edge in state["covered"])
    # TRDD-ZFD3KBM3 rule change (was: withdrawn, == []): an old bare-path entry cannot name the secret behind its finding, so a clean read by a pass that
    # cannot know which secret to look for proves nothing. The entry is kept, rewritten in the object shape with the sentinel "unknown" as its secret.
    assert state["flagged"] == {str(target): ["unknown"]}


# TRDD-XNZFKX0L: a finding is withdrawn only for a file that was READ and scanned this pass. Each test below flags a file with a first
# pass, then makes the file unreadable in a different way and runs a second pass that must reach the file. The second pass is forced
# to read it by the state file, not by luck: the file gets an mtime of 100.0 and the saved covered range is [[1.0, ""], [1.0, ""]],
# so its key (100.0, path) lies ABOVE hi: it is in the FRESH tier (the backlog is keys below lo), which reads it. (An mtime of now + 10 would
# also force a read, but it sits above the live edge for only about 12 s, so the test would depend on wall-clock timing.)
_PATCHED_RUNNER = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "import env_secrets\n"
    "env_secrets.MAX_FILE_BYTES = int(sys.argv[3])\n"
    "detector = sys.argv[1]\n"
    "sys.argv = [detector, \"--one-shot\"]\n"
    "runpy.run_path(detector, run_name=\"__main__\")\n"
)


def _flag_then_force_a_reread(tmp_path: Path, project: Path, value: str, retries: int | None = None, body: str | None = None) -> Path:
    """First pass flags reports_dev/dump.txt; then the state is rewritten so the next pass must read the file again, with `retries`
    failed reads already saved against it when given. `body` replaces the default one-line content (the value must stay in it)."""
    target = project / "reports_dev" / "dump.txt"
    target.write_text(body if body is not None else f"leak {value}\n")
    assert "CRED-002" in _run(tmp_path, project, value).stdout
    state = _cursor(project)
    assert list(state["flagged"]) == [str(target)]  # TRDD-ZFD3KBM3: "flagged" is an object path -> fingerprints now, no longer a list of paths
    os.utime(target, (100.0, 100.0))
    state["covered"] = [[1.0, ""], [1.0, ""]]
    if retries is not None:
        state["retries"] = {str(target): retries}
    (project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").write_text(json.dumps(state))
    return target


def _second_run(tmp_path: Path, project: Path, value: str | None, max_file_bytes: int | None = None) -> subprocess.CompletedProcess[str]:
    """A pass with the secret optionally absent from the environment and MAX_FILE_BYTES optionally lowered (through runpy, so the
    detector sees the patched module)."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project), "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate")}
    if value is not None:
        env[_NAME] = value
    argv = [sys.executable, str(_DETECTOR), "--one-shot"]
    if max_file_bytes is not None:
        argv = [sys.executable, "-c", _PATCHED_RUNNER, str(_DETECTOR), str(_DETECTOR.parent.parent / "lib"), str(max_file_bytes)]
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return done


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0 file")
def test_a_flagged_file_whose_read_fails_keeps_its_finding(tmp_path: Path) -> None:
    """A flagged file the next pass could not read was not rescanned, so it stays in flagged (it used to be withdrawn)."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = _flag_then_force_a_reread(tmp_path, project, value)
    target.chmod(0)
    try:
        out = _second_run(tmp_path, project, value)
    finally:
        target.chmod(0o600)
    assert "1 unreadable" in out.stdout  # the read was attempted and failed: the test reached the file
    state = _cursor(project)
    assert str(target) in state["flagged"] and state["retries"] == {str(target): 1}


def test_a_flagged_file_over_the_read_limit_keeps_its_finding(tmp_path: Path) -> None:
    """A flagged file larger than MAX_FILE_BYTES is counted, not read, so it stays in flagged (it used to be withdrawn)."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = _flag_then_force_a_reread(tmp_path, project, value)
    _second_run(tmp_path, project, value, max_file_bytes=len(target.read_bytes()) - 1)
    # Every file of the project is over the lowered limit, so the count says nothing about this one: the log names the paths not read.
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text().splitlines()
    # The first pass also logs, so assert on the coverage line of the second one, which names the paths not read.
    assert any("not fully covered" in line and str(target) in line for line in log)  # this file was reached and skipped as too big
    assert str(target) in _cursor(project)["flagged"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0 file")
def test_a_flagged_file_given_up_keeps_its_finding(tmp_path: Path) -> None:
    """A flagged file whose reads already failed MAX_FAIL_RETRIES times is given up on: the sweep still tries it, the read fails again, and
    the file counts as done (processed) all the same. It was not scanned, so it stays in flagged."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = _flag_then_force_a_reread(tmp_path, project, value, retries=env_secrets.MAX_FAIL_RETRIES)
    target.chmod(0)
    try:
        out = _second_run(tmp_path, project, value)
    finally:
        target.chmod(0o600)
    assert "1 unreadable" in out.stdout  # the read was attempted and failed again; give_up made _read_one return True, so the key is in processed, not failed
    state = _cursor(project)
    # Only the give-up branch drops the retries entry (retries are rebuilt from the failed keys); a plain failed read counts it up,
    # as the failed-read test above sees ({target: 1}). Without this the test could not tell a give-up from an ordinary failure.
    assert str(target) not in state["retries"]
    assert str(target) in state["flagged"]


# TRDD-ZANQ1QW0 increment 5, the hard read bound at the detector level. Two things are patched inside the detector process through runpy: CHUNK_BYTES (small, so the
# flagged file spans many chunks; _read_one passes CHUNK_BYTES at call time, which is what lets this reach scan_file) and env_secrets.sweep, wrapped to inject a
# stepping clock and a hard deadline (sweep binds clock=time.monotonic as a default argument, so patching time.monotonic would not reach it). The detector is not changed
# for the test: it only passes MAIN_HARD_DEADLINE_S, which the wrapper overrides. The deadline is read into a variable first, because sys.argv is rewritten before the run.
_CUT_RUNNER = (
    "import itertools, runpy, sys\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "import env_secrets\n"
    "env_secrets.CHUNK_BYTES = int(sys.argv[3])\n"
    "deadline = float(sys.argv[4])\n"
    "original = env_secrets.sweep\n"
    "ticks = itertools.count()\n"
    "env_secrets.sweep = lambda *a, **k: original(*a, **{**k, \"clock\": lambda: float(next(ticks)), \"hard_deadline_s\": deadline})\n"
    "detector = sys.argv[1]\n"
    "sys.argv = [detector, \"--one-shot\"]\n"
    "runpy.run_path(detector, run_name=\"__main__\")\n"
)


def _cut_pass(tmp_path: Path, project: Path, value: str, also: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """One detector pass through _CUT_RUNNER. The clock steps 1.0 per read: the deadline of 40 passes inside the 200 chunks of the flagged file (the listing,
    a few reads, comes first), after its first chunk."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project), "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"), _NAME: value, **(also or {})}
    argv = [sys.executable, "-c", _CUT_RUNNER, str(_DETECTOR), str(_DETECTOR.parent.parent / "lib"), "64", "40"]
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return done


def test_a_flagged_file_cut_by_the_hard_read_bound_keeps_its_finding_and_is_held(tmp_path: Path) -> None:
    """A flagged file whose read the hard bound stops part-way was not fully scanned: it keeps its finding, stays held (retry counted, covered range in front of it), and is named in the log, not on stdout."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    # 200 chunks of 64 bytes of padding, the value only at the END: the cut falls long before it, so the pass finds no hit in the file, and the finding stays only
    # because the file was not fully scanned (a pass that wrongly counted it as read would withdraw it).
    target = _flag_then_force_a_reread(tmp_path, project, value, body="x" * (64 * 200) + f"\nleak {value}\n")
    done = _cut_pass(tmp_path, project, value)
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text().splitlines()
    cut_lines = [line for line in log if "cut by the hard read bound, read again next pass" in line]
    assert len(cut_lines) == 1 and str(target) in cut_lines[0]  # the cut happened, and it was this file: asserted before the finding
    assert any("pass: " in line and "; cut by the hard read bound: 1;" in line for line in log)
    assert "cut by the hard read bound" not in done.stdout
    state = _cursor(project)
    assert str(target) in state["flagged"]
    assert state["retries"] == {str(target): 1} and state["covered"] == [[1.0, ""], [1.0, ""]]  # held like a failed read


def test_a_given_up_file_that_is_cut_is_counted_and_covered_but_not_listed_as_read_again(tmp_path: Path) -> None:
    """A file already given up on (MAX_FAIL_RETRIES failed reads saved) is opened and cut once more: it is done (the covered range moves past it, its retry entry is
    dropped) and it is counted in the pass line and named in the "not fully covered" line, but it is NOT in the "read again next pass" line: a given-up file is not read
    again (it is inside the covered range, like a given-up failed read), so listing it as read again would be false. Its finding stays, and the next pass does not
    open it until the file changes."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = _flag_then_force_a_reread(tmp_path, project, value, retries=env_secrets.MAX_FAIL_RETRIES, body="x" * (64 * 200) + f"\nleak {value}\n")
    log_file = project / ".janitor" / "logs" / "env-secret-on-disk.log"
    give_up_pass = _cut_pass(tmp_path, project, value)
    # The give-up pass also reaches the stdout coverage line (parity with a given-up unreadable file), with the count, and the log names the file.
    # "On every try" in that text means the MAX_FAIL_RETRIES tries before give-up, not later passes: the file is not read again after the give-up pass.
    assert any("not fully covered" in line and str(target) in line for line in log_file.read_text().splitlines())
    assert "1 cut by the hard read bound on every try and left unread" in give_up_pass.stdout
    cut_lines = [line for line in log_file.read_text().splitlines() if "cut by the hard read bound, read again next pass" in line]
    # The pass line counts exactly one cut (the target), so with it given up no "read again next pass" line may exist at all, not even an empty one.
    assert cut_lines == []
    assert any("pass: " in line and "; cut by the hard read bound: 1;" in line for line in log_file.read_text().splitlines())
    state = _cursor(project)
    assert str(target) not in state["retries"] and state["covered"][1] == [100.0, str(target)]  # given up: done, no longer held
    assert str(target) in state["flagged"]
    _cut_pass(tmp_path, project, value)  # second pass: the target is inside the covered range, so it is not opened again
    # Another file (the proposal the first pass wrote) may be cut by this tiny clock; the given-up target must still not be in a "read again next pass" line.
    assert not any("cut by the hard read bound, read again next pass" in line and str(target) in line for line in log_file.read_text().splitlines())
    assert str(target) in _cursor(project)["flagged"]


def test_a_pass_with_no_secret_in_the_environment_withdraws_nothing(tmp_path: Path) -> None:
    """With no secret-named variable in the environment the exact matcher is off and nothing is scanned for a value: no finding is withdrawn."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = _flag_then_force_a_reread(tmp_path, project, value)
    target.write_text("cleaned\n")
    os.utime(target, (100.0, 100.0))  # the rewrite moved the mtime: put it back below the live edge, above hi
    _second_run(tmp_path, project, None)
    assert str(target) in _cursor(project)["flagged"]


def test_the_pass_line_reports_the_seconds_of_each_phase(tmp_path: Path) -> None:
    """The detector log line that carries the pass segment ends with the per-phase seconds and a total, in the expected format (TRDD-ZANQ1QW0)."""
    project = _project(tmp_path)
    (project / "notes.txt").write_text("nothing to find\n")
    result = _run(tmp_path, project, secrets.token_urlsafe(36))
    assert result.returncode == 0, result.stderr
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text()
    lines = [line for line in log.splitlines() if "pass: " in line]
    assert len(lines) == 1 and "; seconds: listing " in lines[0] and "total " in lines[0]
    # One decimal of a real clock: a fast pass prints 0.0, so only the format is asserted, not a positive value (the sweep tests pin the values).
    assert re.search(r"; seconds: listing \d+\.\d, fresh \d+\.\d, backlog \d+\.\d, trash \d+\.\d, total \d+\.\d$", lines[0])


def test_the_pass_line_prints_the_sweep_phase_seconds_when_the_listing_was_not_cut(tmp_path: Path) -> None:
    """On a complete listing the pass line prints listing_s, fresh_s and backlog_s of the sweep report, not the cut elapsed (TRDD-ZANQ1QW0)."""
    runner = (
        "import runpy, sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "import env_secrets\n"
        "original = env_secrets.sweep\n"
        "def patched(*a, **k):\n"
        "    report = original(*a, **k)\n"
        "    report.listing_s, report.fresh_s, report.backlog_s = 4.2, 1.1, 2.3\n"
        "    return report\n"
        "env_secrets.sweep = patched\n"
        "detector = sys.argv[1]\n"
        "sys.argv = [detector, \"--one-shot\"]\n"
        "runpy.run_path(detector, run_name=\"__main__\")\n"
    )
    project = _project(tmp_path)
    (project / "notes.txt").write_text("nothing to find\n")
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"), _NAME: secrets.token_urlsafe(36),
    }
    result = subprocess.run([sys.executable, "-c", runner, str(_DETECTOR), str(_DETECTOR.parent.parent / "lib")], env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text()
    assert "listing cut after" not in log and "; seconds: listing 4.2, fresh 1.1, backlog 2.3, trash " in log


def test_a_second_pass_while_one_holds_the_lock_changes_nothing(tmp_path: Path) -> None:
    """A pass that finds the project lock held prints nothing, leaves the state file byte-identical and logs that it was skipped (TRDD-ZANQ1QW0)."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / "notes.txt").write_text("nothing to find\n")
    assert _run(tmp_path, project, value).returncode == 0
    state_dir = project / ".janitor" / "state"
    cursor = state_dir / "env-secret-on-disk.cursor.json"
    before = cursor.read_bytes()
    # A file that an unlocked pass WOULD report and record in the state file.
    (project / "reports_dev" / "dump.txt").write_text(f"leak {value}\n")
    lock_fd = os.open(state_dir / "env-secret-on-disk.lock", os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        second = _run(tmp_path, project, value)
    finally:
        os.close(lock_fd)  # closing the descriptor releases the lock
    assert second.returncode == 0, second.stderr
    assert second.stdout == ""
    assert cursor.read_bytes() == before
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text()
    assert "another pass of this project holds the lock: this pass was skipped" in log


# TRDD-ZFD3KBM3: a finding is withdrawn only by a pass that held the same secret as the finding (the matcher is built from the environment of the process
# running the pass, so a pass of another session, or one run after a rotation, reads the file clean without having looked for the secret). "flagged" maps each
# path to the sorted fingerprints of its secrets (the sentinel "unknown" for a finding of an old state file, whose secret is not known). The second pass is forced to read the file the
# same way as _flag_then_force_a_reread: mtime 100.0 lies above hi of the saved covered range [[1.0, ""], [1.0, ""]], so the file is in the fresh tier.
_NAME_B = "FAKE_API_TOKEN_0001"


def _run_env(tmp_path: Path, project: Path, held: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """One detector pass whose environment holds exactly the secrets of `held` (name -> value) and nothing else that could be a needle."""
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project), "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"), **held}
    done = subprocess.run([sys.executable, str(_DETECTOR), "--one-shot"], env=env, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return done


def _fp(tmp_path: Path, value: str) -> str:
    """The fingerprint the detector records for `value`: the salt is the one the first pass wrote to the global state directory."""
    salt_file = next((tmp_path / "gstate").rglob("env-secret-fingerprint.salt"))
    return env_secrets.fingerprint(value, bytes.fromhex(salt_file.read_text().strip()))


def _force_reread(project: Path, target: Path, flagged: object = None) -> None:
    """Make the next pass read `target` again (mtime 100.0 above hi of the saved range), optionally rewriting the saved "flagged" value (an old-shape list)."""
    os.utime(target, (100.0, 100.0))
    state = _cursor(project)
    state["covered"] = [[1.0, ""], [1.0, ""]]
    if flagged is not None:
        state["flagged"] = flagged
    (project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").write_text(json.dumps(state))


def _issue_refused(project: Path) -> bool:
    """Whether the one CRED-002 proposal of the project was withdrawn (clear_issue marks it column: refused)."""
    proposals = list((project / "design" / "proposals").glob("*"))
    assert len(proposals) == 1
    return "column: refused" in proposals[0].read_text()


def test_a_finding_of_secret_a_stays_after_a_clean_pass_that_holds_only_secret_b(tmp_path: Path) -> None:
    """The file is cleaned, but the second pass has only secret B in its environment: it read the file clean without looking for A, so the finding stays."""
    a, b = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    assert _cursor(project)["flagged"] == {str(target): [_fp(tmp_path, a)]}
    target.write_text("cleaned\n")
    _force_reread(project, target)
    _run_env(tmp_path, project, {_NAME_B: b})
    assert _cursor(project)["flagged"] == {str(target): [_fp(tmp_path, a)]}
    assert not _issue_refused(project)


def test_a_finding_of_secret_a_is_withdrawn_by_a_clean_pass_that_holds_a_and_b(tmp_path: Path) -> None:
    """The same clean file read by a pass that holds A (and B) proves A is gone: the finding is withdrawn and the issue cleared."""
    a, b = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    target.write_text("cleaned\n")
    _force_reread(project, target)
    _run_env(tmp_path, project, {_NAME: a, _NAME_B: b})
    assert _cursor(project)["flagged"] == {}
    assert _issue_refused(project)


def test_a_clean_pass_drops_only_the_fingerprints_of_the_secrets_it_holds(tmp_path: Path) -> None:
    """A file flagged for A and B, cleaned, read by a pass that holds only A: the entry keeps B (that pass could not look for it) and the issue stays."""
    a, b = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {a} and {b}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a, _NAME_B: b}).stdout
    assert _cursor(project)["flagged"] == {str(target): sorted([_fp(tmp_path, a), _fp(tmp_path, b)])}
    target.write_text("cleaned\n")
    _force_reread(project, target)
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {str(target): [_fp(tmp_path, b)]}
    assert not _issue_refused(project)


def test_an_old_bare_path_entry_is_never_withdrawn_by_a_clean_read(tmp_path: Path) -> None:
    """An old state file lists bare paths, which cannot name the secret behind a finding: each loads as the sentinel "unknown", a clean read keeps it even by a pass that holds a secret, and a hit adds its fingerprint beside it, so the unknown secret is not forgotten."""
    a = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    target.write_text("cleaned\n")
    _force_reread(project, target, flagged=[str(target)])
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {str(target): ["unknown"]}
    assert not _issue_refused(project)
    # The unknown secret is not forgotten when a hit adds a fingerprint: the file gets a hit for A, is cleaned again, and a pass that holds A reads it clean.
    target.write_text(f"leak {a}\n")
    _force_reread(project, target)
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {str(target): sorted(["unknown", _fp(tmp_path, a)])}
    target.write_text("cleaned\n")
    _force_reread(project, target)
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {str(target): ["unknown"]}
    assert not _issue_refused(project)


def test_a_flagged_file_deleted_with_no_trash_copy_is_withdrawn(tmp_path: Path) -> None:
    """A flagged file that is gone (os.lstat says so, whatever the listing says) and has no copy in the trash holds no value any more: the finding is withdrawn."""
    a = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    target.unlink()
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {}
    assert _issue_refused(project)


def test_a_flagged_file_moved_to_the_trash_keeps_its_finding_until_the_copy_is_gone(tmp_path: Path) -> None:
    """safe-delete moves the file to .trashcan/<batch>/<relative path>, the value is still on disk and the trash tier reads an unsettled batch only later: the finding stays while a copy exists and closes when it is gone."""
    a = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / ".gitignore").write_text("reports_dev/\n.janitor/\n.trashcan/\n")  # the copy is then reached by the trash tier only, which skips an unsettled batch
    target = project / "reports_dev" / "dump.txt"
    target.write_text(f"leak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    batch = project / ".trashcan" / time.strftime("%Y%m%d_%H%M%S%z")
    (batch / "reports_dev").mkdir(parents=True)
    os.replace(target, batch / "reports_dev" / "dump.txt")
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {str(target): [_fp(tmp_path, a)]}
    assert not _issue_refused(project)
    shutil.rmtree(batch)
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {}
    assert _issue_refused(project)


def test_a_file_cut_by_the_hard_bound_gains_the_fingerprint_of_a_new_secret_and_keeps_the_recorded_one(tmp_path: Path) -> None:
    """A flagged file the hard read bound cuts was not fully scanned: the hit for secret B before the cut is added, and the recorded fingerprint of A is kept (the unread rest may still hold A)."""
    a, b = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    project = _project(tmp_path)
    target = project / "reports_dev" / "dump.txt"
    # B first (inside the first 64-byte chunk, before the cut), then 200 chunks of padding, then A at the END: pass 1 holds only A and reads the whole file.
    target.write_text(f"{b}\n" + "x" * (64 * 200) + f"\nleak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    _force_reread(project, target)
    _cut_pass(tmp_path, project, a, also={_NAME_B: b})
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text().splitlines()
    assert any("cut by the hard read bound, read again next pass" in line and str(target) in line for line in log)  # the file was cut: a precondition of this test
    assert _cursor(project)["flagged"] == {str(target): sorted([_fp(tmp_path, a), _fp(tmp_path, b)])}


def test_a_flagged_file_in_a_folder_named_with_leading_dots_is_inside_the_project_and_its_trash_copy_is_looked_up(tmp_path: Path) -> None:
    """A project folder named "..cache" is inside the project (its relative path starts with two dots but is not "../"): the file moved to the trash keeps its finding."""
    a = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / ".gitignore").write_text("reports_dev/\n.janitor/\n.trashcan/\n")
    target = project / "..cache" / "dump.txt"
    target.parent.mkdir()
    target.write_text(f"leak {a}\n")
    assert "CRED-002" in _run_env(tmp_path, project, {_NAME: a}).stdout
    assert list(_cursor(project)["flagged"]) == [str(target)]
    batch = project / ".trashcan" / time.strftime("%Y%m%d_%H%M%S%z")
    (batch / "..cache").mkdir(parents=True)
    os.replace(target, batch / "..cache" / "dump.txt")
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {str(target): [_fp(tmp_path, a)]}
    assert not _issue_refused(project)


def test_a_flagged_path_outside_the_project_that_is_gone_is_withdrawn_without_a_trash_lookup(tmp_path: Path) -> None:
    """A path outside the project can have no copy under the project's .trashcan: once it is gone its finding closes."""
    a = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    # without the outside-project branch the lookup would join "../outside/gone.txt" under the trash child "outside" and find this file, so the finding would wrongly stay
    (project / ".trashcan" / "outside").mkdir(parents=True)
    (project / ".trashcan" / "outside" / "gone.txt").write_text("x\n")
    (project / "notes.txt").write_text("nothing\n")
    assert _run_env(tmp_path, project, {_NAME: a}).returncode == 0
    outside = tmp_path / "outside" / "gone.txt"  # never created
    state = _cursor(project)
    state["flagged"] = {str(outside): ["aaaaaaaaaaaa"]}
    (project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").write_text(json.dumps(state))
    _run_env(tmp_path, project, {_NAME: a})
    assert _cursor(project)["flagged"] == {}
