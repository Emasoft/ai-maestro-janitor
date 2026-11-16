"""End-to-end tests of the env-secret-on-disk detector (janitor issue #354, layer 3).

The detector is run as a real program in a throwaway git project, with a secret generated at test time passed as
an environment variable. The assertions are on what it prints, writes and proposes: the variable NAME and the
path are reported, the value never appears in any output, log, state file or proposal.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _ROOT / "scripts" / "detectors" / "env-secret-on-disk.py"
_NAME = "FAKE_API_TOKEN_0000"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    for folder in ("reports_dev", "design/proposals", "design/tasks"):
        (project / folder).mkdir(parents=True)
    (project / ".gitignore").write_text("reports_dev/\n.janitor/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, env={**os.environ, "HOME": str(tmp_path / "home")})
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
    assert json.loads(cursor.read_text())["flagged"] == [str(target)]
    target.write_text("cleaned\n")
    _run(tmp_path, project, value)
    assert json.loads(cursor.read_text())["flagged"] == []
    proposal = next((project / "design" / "proposals").glob("*"))
    assert "column: refused" in proposal.read_text()


def test_a_file_the_sweep_cannot_read_is_counted_and_holds_the_cursor(tmp_path: Path) -> None:
    """An unreadable file is named in a coverage line, and the cursor does not move past it."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    older = project / "reports_dev" / "a-older.txt"
    locked = project / "reports_dev" / "b-locked.txt"
    older.write_text("nothing\n")
    locked.write_text("nothing\n")
    os.utime(older, (1000.0, 1000.0))
    os.utime(locked, (2000.0, 2000.0))
    locked.chmod(0)
    try:
        out = _run(tmp_path, project, value)
    finally:
        locked.chmod(0o600)
    assert "sweep coverage" in out.stdout and "1 unreadable" in out.stdout
    cursor = json.loads((project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").read_text())
    assert cursor["cursor"] == [1000.0, str(older)]
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


def test_a_git_that_cannot_list_untracked_files_is_said_and_holds_the_cursor(tmp_path: Path) -> None:
    """A failed `git ls-files` used to look like "no untracked files" and the cursor moved past a leaking file that
    was never read; now it is counted in the coverage line, and a project that has no git at all still advances."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    (project / "reports_dev" / "a.txt").write_text("clean\n")
    shutil.rmtree(project / ".git")  # in-process: the suite sandbox denies spawning a real rm, and none is needed
    (project / ".git").write_text("gitdir: /nonexistent\n")
    out = _run(tmp_path, project, value)
    assert "untracked files were not listed" in out.stdout
    assert _cursor(project)["cursor"] == [0.0, ""]
    plain = tmp_path / "plain"
    (plain / "reports_dev").mkdir(parents=True)
    (plain / "reports_dev" / "a.txt").write_text("clean\n")
    assert "untracked files were not listed" not in _run(tmp_path, plain, value).stdout
    assert _cursor(plain)["cursor"][0] > 0



def test_a_git_that_keeps_failing_stops_holding_the_cursor_and_the_retry_count_is_cleared_when_it_works(tmp_path: Path) -> None:
    """After MAX_FAIL_RETRIES failed passes the cursor moves on (git failing for good must not stall the sweep), the
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
        assert state["retries"] == {"git ls-files": expected} and state["cursor"] == [0.0, ""]
    _run(tmp_path, project, value)  # the fourth failure: retries exhausted, the cursor is released
    assert _cursor(project)["cursor"][0] > 0
    (project / ".git").unlink()
    git_dir.rename(project / ".git")
    _run(tmp_path, project, value)
    assert "git ls-files" not in _cursor(project)["retries"]


def test_more_leaking_files_than_the_cap_are_all_reported_over_the_passes(tmp_path: Path) -> None:
    """Hit files were raised in path order but the cursor moves in modification order: with names ascending and
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
    real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
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


def test_a_cut_listing_keeps_the_cursor_retries_and_findings_and_says_so_once_a_day(tmp_path: Path) -> None:
    """With the listing forced over its budget the pass reads nothing, keeps cursor, retries and findings, and says so once."""
    runner = (
        "import runpy, sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "import env_secrets\n"
        "original = env_secrets.sweep\n"
        "env_secrets.sweep = lambda *a, **k: original(*a, **{**k, \"listing_budget_s\": -1.0})\n"
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
        "cursor": [5.0, "x"], "retries": {"/nonexistent/held": 2}, "flagged": [str(planted)], "trash": {"positions": {}, "done": []},
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
    assert state["cursor"] == [5.0, "x"] and state["retries"]["/nonexistent/held"] == 2 and str(planted) in state["flagged"]
    second = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert second.returncode == 0, second.stderr
    if time.strftime("%Y-%m-%d") == day:
        assert "the listing of the agent folders took over" not in second.stdout
    assert _cursor(project)["cursor"] == [5.0, "x"]
